"""Host-only recovery settlement after an operator has verified restored data.

This command verifies running version/commit metadata, not database or file
integrity. It neither installs code nor starts services. There is no HTTP route.
"""

import json
import os
from pathlib import Path
import re
import stat
import sys

# config imports can apply a pending SQLite restore. A metadata-only recovery
# command must reject that situation before importing any application modules.
if __name__ == "__main__":
    _pending = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data")) / "restore-pending.tar.gz"
    if _pending.exists() or _pending.is_symlink():
        print(json.dumps({"error": "待恢复快照尚未完成，请先完成恢复再进行任务收尾"}, ensure_ascii=False))
        raise SystemExit(1)

from app import config
from app.services import system_updates as updates
from app.services.update_source import _SEMVER

OUTCOMES = {"failed", "rolled_back", "succeeded"}
MESSAGES = {
    "failed": "管理员已核验运行环境并结束本次更新，请重新检查更新来源",
    "rolled_back": "管理员已确认恢复原版本和数据，本次更新已结束",
    "succeeded": "管理员已核验目标版本，本次更新已完成",
}


def _marker(path):
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(value.st_mode):
        raise updates.UpdateError("维护标记不是普通文件，拒绝人工恢复收尾", 409)
    return {"device": value.st_dev, "inode": value.st_ino,
            "modified_ns": value.st_mtime_ns, "changed_ns": value.st_ctime_ns,
            "bytes": value.st_size}


def _parameters(request):
    fields = {"runner_id", "job_id", "confirm", "expected_version", "expected_commit", "outcome"}
    if not isinstance(request, dict) or set(request) != fields or request["confirm"] is not True:
        raise updates.UpdateError("必须明确确认已人工恢复并核验全部数据")
    updates._identity(request["runner_id"])
    updates._identity(request["job_id"])
    version, commit = request["expected_version"], request["expected_commit"]
    if not isinstance(version, str) or len(version) > 128 or not _SEMVER.fullmatch(version):
        raise updates.UpdateError("请提供已核验的完整版本号")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise updates.UpdateError("请提供已核验的完整40位提交，不能使用 unknown 或短提交")
    if not isinstance(request["outcome"], str) or request["outcome"] not in OUTCOMES:
        raise updates.UpdateError("人工恢复结果无效")
    return {**request, "expected_commit": commit.lower()}


def _preserve_before(state, request):
    directory = updates._directory() / "recovery-records"
    if directory.is_symlink():
        raise updates.UpdateError("恢复记录目录异常", 503)
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    path = directory / (request["job_id"] + ".json")
    if path.exists() or path.is_symlink():
        record = updates._read(path, {})
        if record.get("job_id") != request["job_id"] or record.get("runner_id") != request["runner_id"]:
            raise updates.UpdateError("已有恢复记录与当前任务不一致", 409)
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise updates.UpdateError("恢复记录权限异常", 503)
        return path.name
    updates._write(path, {"protocol": 1, "job_id": request["job_id"], "runner_id": request["runner_id"],
                          "recorded_at": updates._now(), "before": state,
                          "confirmation": "operator_verified_data",
                          "expected_version": request["expected_version"],
                          "expected_commit": request["expected_commit"], "outcome": request["outcome"]})
    return path.name


def _result(job, *, idempotent):
    return {"ok": True, "job": updates._public_job(job), "idempotent": idempotent,
            "maintenance_cleared": True, "data_verified_automatically": False}


def recover(request):
    """Settle only an attended job, preserving its original state before writes.

    An already matching terminal result is a read-only reconciliation. A retry
    may finish removing the exact original marker if that final unlink failed;
    a newly created maintenance marker is never cleared by an old confirmation.
    """
    request = _parameters(request)
    pending = updates._data_dir() / "restore-pending.tar.gz"
    if pending.exists() or pending.is_symlink():
        raise updates.UpdateError("待恢复快照尚未完成，请先完成恢复再进行任务收尾", 409)
    with updates._locked():
        state = updates._state()
        job = updates._owned(state, request["runner_id"], request["job_id"])
        actual_commit = os.getenv("GIT_SHA", "unknown")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", actual_commit):
            raise updates.UpdateError("实际运行提交为 unknown 或短提交，无法核验并解除维护", 409)
        if config.APP_VERSION != request["expected_version"] or actual_commit.lower() != request["expected_commit"]:
            raise updates.UpdateError("实际运行版本或完整提交与确认值不一致，维护保持", 409)
        outcome = request["outcome"]
        if outcome == "succeeded" and (config.APP_VERSION != job["target_version"]
                                       or actual_commit.lower() != job["target_commit"].lower()):
            raise updates.UpdateError("实际运行版本与更新目标不一致，不能确认更新成功", 409)
        marker_path = updates._data_dir() / "update-maintenance.json"
        marker = _marker(marker_path)
        if job["status"] == outcome:
            if marker is None:
                return _result(job, idempotent=True)
            recovery = job.get("manual_recovery") or {}
            if (recovery.get("outcome") != outcome or recovery.get("version") != request["expected_version"]
                    or recovery.get("commit") != request["expected_commit"] or recovery.get("marker") != marker):
                raise updates.UpdateError("任务已结束，但存在另一维护标记，请先核查维护原因", 409)
            # Only complete the same settlement's failed final filesystem step.
            marker_path.unlink()
            return _result(job, idempotent=True)
        if job["status"] != "needs_attention":
            raise updates.UpdateError("仅等待人工处理的任务可收尾，不能覆盖活动任务或其他最终结果", 409)
        if not updates.is_maintenance():
            raise updates.UpdateError("当前不在更新维护状态，拒绝恢复收尾", 409)
        record = _preserve_before(state, request)
        job.update(status=outcome, phase=outcome, message=MESSAGES[outcome], updated_at=updates._now(),
                   manual_recovery={"outcome": outcome, "version": request["expected_version"],
                                    "commit": request["expected_commit"], "record": record, "marker": marker,
                                    "data_verified_automatically": False})
        job.pop("source", None)
        state["check"] = None
        updates._save(state)
        # Publish the verified terminal state first, then remove only the marker
        # inspected while holding the shared update lock.
        if marker is not None:
            if _marker(marker_path) != marker:
                raise updates.UpdateError("维护标记已变化，维护保持，请重新核查", 409)
            marker_path.unlink()
        return _result(job, idempotent=False)


def main():
    try:
        raw = sys.stdin.buffer.read(16_385)
        if len(raw) > 16_384:
            raise updates.UpdateError("恢复确认参数过大")
        result = recover(json.loads(raw))
        print(json.dumps(result, ensure_ascii=False))
    except updates.UpdateError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"error": "人工恢复收尾未完成，维护记录保持，请检查任务与存储状态"}, ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
