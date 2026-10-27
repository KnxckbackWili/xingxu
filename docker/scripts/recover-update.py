#!/usr/bin/env python3
"""Settle an interrupted update after manual recovery and full data verification.

Run as the same host user, HOME and Docker environment as update-runner.py.
First stop that runner and confirm no detached deployment/restore remains.
This command verifies metadata only; it does not restore data or start services.
"""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import uuid


class RecoveryError(ValueError):
    pass


def _identity(value):
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise RecoveryError("恢复任务或更新服务标识无效") from None


def _directory(path):
    if path.is_symlink() or not path.is_dir():
        raise RecoveryError("原更新服务工作目录不存在或不安全")
    return path


def _read(path):
    try:
        if not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > 1024 * 1024:
            raise ValueError
        value = json.loads(path.read_text())
        if not isinstance(value, dict):
            raise ValueError
        return value
    except (OSError, ValueError):
        raise RecoveryError("原更新服务身份或任务记录无法读取") from None


def _write(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".recovery-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def _container_lock(container):
    # This must be byte-for-byte the same key/location as update-runner.py.
    base = Path.home() / ".local/state/agv-update-runner"
    if base.is_symlink():
        raise RecoveryError("更新服务锁目录不安全")
    base.mkdir(parents=True, mode=0o700, exist_ok=True)
    base.chmod(0o700)
    key = hashlib.sha256((os.environ.get("DOCKER_HOST", "default") + ":" + container).encode()).hexdigest()
    fd = os.open(base / (key + ".lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RecoveryError("更新服务仍在管理此容器，请先停止并确认没有残余部署进程") from None
        yield
    finally:
        os.close(fd)


def _docker(container, payload):
    try:
        result = subprocess.run(["docker", "exec", "-i", container, "python", "-m", "app.services.system_update_recovery"],
                                input=json.dumps(payload), text=True, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RecoveryError("容器恢复收尾调用未完成；保持停写，可用相同参数重试") from None
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RecoveryError("容器恢复收尾未返回有效结果；保持停写，可用相同参数重试") from None
    if result.returncode or not isinstance(value, dict) or value.get("ok") is not True:
        # stdout/stderr may contain unrelated startup failures or private paths.
        if isinstance(value, dict) and value.get("error") in {
            "实际运行提交为 unknown 或短提交，无法核验并解除维护",
            "实际运行版本或完整提交与确认值不一致，维护保持",
            "待恢复快照尚未完成，请先完成恢复再进行任务收尾",
        }:
            raise RecoveryError(value["error"])
        raise RecoveryError("容器拒绝恢复收尾，请核对任务身份、完整版本提交与维护状态")
    return value


def recover(container, work_dir, job_id, expected_version, expected_commit, outcome, confirmed, *, docker=None):
    if confirmed is not True:
        raise RecoveryError("请先完成全部人工恢复和数据核验，再添加 --confirm-data-verified")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container):
        raise RecoveryError("容器名称无效")
    _identity(job_id)
    if not isinstance(expected_commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", expected_commit):
        raise RecoveryError("必须提供完整40位提交，不能使用 unknown 或短提交")
    if not isinstance(expected_version, str) or not expected_version or len(expected_version) > 128:
        raise RecoveryError("请提供已核验的运行版本")
    if outcome not in {"failed", "rolled_back", "succeeded"}:
        raise RecoveryError("恢复结果无效")
    work = _directory(Path(work_dir))
    with _container_lock(container):
        runner = _read(work / "runner.json")
        runner_id = runner.get("runner_id")
        _identity(runner_id)
        path = work / "active-job.json"
        journal = _read(path)
        if journal.get("job_id") != job_id:
            raise RecoveryError("宿主任务记录与指定任务不一致，未调用容器")
        payload = {"runner_id": runner_id, "job_id": job_id, "confirm": True,
                   "expected_version": expected_version, "expected_commit": expected_commit.lower(), "outcome": outcome}
        result = (docker or _docker)(container, payload)
        job = result.get("job") if isinstance(result, dict) else None
        if (not isinstance(job, dict) or result.get("ok") is not True or result.get("maintenance_cleared") is not True
                or job.get("id") != job_id or job.get("status") != outcome):
            raise RecoveryError("应用任务收尾结果不匹配，宿主记录未改动")
        # Container settlement is idempotent if this final local write fails.
        _write(path, {**journal, "job_id": job_id, "status": outcome, "terminal": True,
                      "recovered_manually": True, "data_verified_automatically": False})
        return {"ok": True, "job_id": job_id, "outcome": outcome, "data_verified_automatically": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--outcome", required=True, choices=("failed", "rolled_back", "succeeded"))
    parser.add_argument("--confirm-data-verified", action="store_true")
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        recover(args.container, args.work_dir, args.job_id, args.expected_version, args.expected_commit,
                args.outcome, args.confirm_data_verified)
    except RecoveryError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print("人工恢复收尾未完成，宿主记录无法保存；保持停写并使用相同参数重试。", file=sys.stderr)
        return 1
    print("恢复任务和宿主记录已收尾；数据由管理员人工核验，未自动启动任何服务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
