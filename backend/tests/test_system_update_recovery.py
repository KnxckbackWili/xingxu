"""Attended recovery settlement with temporary files and a fake Docker boundary."""

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import uuid

import pytest

from app import config
from app.services import system_update_recovery as recovery
from app.services import system_updates as updates

spec = importlib.util.spec_from_file_location("update_recovery_host", Path(__file__).resolve().parents[2] / "docker/scripts/recover-update.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


@pytest.fixture()
def attended(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "APP_VERSION", "2.3.8")
    monkeypatch.setenv("GIT_SHA", "a" * 40)
    runner, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    now = updates._now()
    job = {"id": job_id, "runner_id": runner, "status": "needs_attention", "phase": "needs_attention",
           "message": "needs operator", "created_at": now, "updated_at": now,
           "target_version": "2.4.0", "target_commit": "b" * 40,
           "source": {"token_encrypted": "test-only-ciphertext"}}
    updates._save({"job": job, "check": {"id": "stale-check"}, "runner": {"id": runner}})
    marker = tmp_path / "update-maintenance.json"
    marker.write_text('{"protocol":1}')
    marker.chmod(0o600)
    request = {"runner_id": runner, "job_id": job_id, "confirm": True, "expected_version": "2.3.8",
               "expected_commit": "a" * 40, "outcome": "rolled_back"}
    return SimpleNamespace(root=tmp_path, marker=marker, request=request, job_id=job_id, runner=runner)


def test_recovery_preserves_original_state_clears_stale_intent_and_removes_marker_last(attended):
    before = updates._state()
    result = recovery.recover(attended.request)
    state = updates._state()
    assert result["ok"] and not result["data_verified_automatically"]
    assert result["job"]["status"] == "rolled_back"
    assert state["check"] is None and "source" not in state["job"]
    assert state["job"]["phase"] == "rolled_back"
    assert not attended.marker.exists() and not updates.is_maintenance()
    record = attended.root / "system-updates/recovery-records" / (attended.job_id + ".json")
    assert json.loads(record.read_text())["before"] == before
    assert record.stat().st_mode & 0o777 == 0o600
    assert record.parent.stat().st_mode & 0o777 == 0o700
    assert "test-only-ciphertext" not in json.dumps(result)


def test_same_result_retry_is_read_only_and_preserves_original_recovery_record(attended, monkeypatch):
    recovery.recover(attended.request)
    state_before = (attended.root / "system-updates/state.json").read_bytes()
    records = list((attended.root / "system-updates/recovery-records").iterdir())
    record_before = records[0].read_bytes()
    monkeypatch.setattr(updates, "_save", lambda value: pytest.fail("idempotent recovery must not write state"))
    assert recovery.recover(attended.request)["idempotent"]
    assert (attended.root / "system-updates/state.json").read_bytes() == state_before
    assert records[0].read_bytes() == record_before


@pytest.mark.parametrize("status", ["queued", "downloading", "building", "backing_up", "installing", "verifying", "succeeded", "failed"])
def test_active_or_conflicting_terminal_job_cannot_be_overridden(attended, status):
    state = updates._state()
    state["job"]["status"] = status
    updates._save(state)
    with pytest.raises(updates.UpdateError):
        recovery.recover(attended.request)
    assert updates._state()["job"]["status"] == status
    assert attended.marker.exists()


@pytest.mark.parametrize("field,value", [
    ("confirm", False), ("confirm", 1), ("runner_id", "00000000-0000-4000-8000-0000000000a1"),
    ("job_id", "00000000-0000-4000-8000-0000000000a2"), ("expected_version", "2.3.7"),
    ("expected_commit", "unknown"), ("expected_commit", "abcdef0"),
    ("expected_commit", "c" * 40), ("outcome", "installing"),
])
def test_identity_confirmation_and_actual_metadata_must_match(attended, field, value):
    with pytest.raises(updates.UpdateError):
        recovery.recover({**attended.request, field: value})
    assert attended.marker.exists()
    assert updates._state()["job"]["status"] == "needs_attention"


def test_unknown_running_commit_cannot_release_maintenance(attended, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "unknown")
    with pytest.raises(updates.UpdateError, match="unknown 或短提交"):
        recovery.recover(attended.request)
    assert attended.marker.exists()


def test_pending_snapshot_is_not_applied_by_metadata_only_cli(tmp_path):
    pending = tmp_path / "restore-pending.tar.gz"
    pending.write_bytes(b"not-a-real-backup-must-not-be-opened")
    result = subprocess.run([sys.executable, "-m", "app.services.system_update_recovery"],
                            input="{}", text=True, capture_output=True,
                            env={**os.environ, "DATA_DIR": str(tmp_path), "DATABASE_URL": "sqlite:///" + str(tmp_path / "isolated.db")},
                            cwd=Path(__file__).resolve().parents[1], timeout=10, check=False)
    assert result.returncode == 1
    assert "待恢复快照尚未完成" in json.loads(result.stdout)["error"]
    assert result.stderr == ""
    assert pending.read_bytes() == b"not-a-real-backup-must-not-be-opened"
    assert not (tmp_path / "isolated.db").exists()


def test_pending_snapshot_cannot_release_maintenance_through_imported_helper(attended):
    (attended.root / "restore-pending.tar.gz").write_bytes(b"pending")
    with pytest.raises(updates.UpdateError, match="待恢复快照"):
        recovery.recover(attended.request)
    assert attended.marker.exists()


def test_success_requires_target_in_addition_to_operator_confirmation(attended, monkeypatch):
    with pytest.raises(updates.UpdateError, match="更新目标"):
        recovery.recover({**attended.request, "outcome": "succeeded"})
    monkeypatch.setattr(config, "APP_VERSION", "2.4.0")
    monkeypatch.setenv("GIT_SHA", "b" * 40)
    result = recovery.recover({**attended.request, "outcome": "succeeded", "expected_version": "2.4.0", "expected_commit": "b" * 40})
    assert result["job"]["status"] == "succeeded"


@pytest.mark.parametrize("kind", ["symlink", "directory"])
def test_nonregular_maintenance_marker_is_never_removed(attended, kind):
    attended.marker.unlink()
    if kind == "symlink":
        attended.marker.symlink_to(attended.root / "unrelated")
    else:
        attended.marker.mkdir()
    with pytest.raises(updates.UpdateError, match="不是普通文件"):
        recovery.recover(attended.request)
    assert attended.marker.is_symlink() or attended.marker.is_dir()
    assert updates._state()["job"]["status"] == "needs_attention"


def test_needs_attention_itself_is_maintenance_without_a_marker(attended):
    attended.marker.unlink()
    assert updates.is_maintenance()
    assert recovery.recover(attended.request)["maintenance_cleared"]
    assert not updates.is_maintenance()


def test_existing_same_terminal_is_only_reconciled_without_mutation(attended, monkeypatch):
    state = updates._state()
    state["job"]["status"] = state["job"]["phase"] = "rolled_back"
    updates._save(state)
    attended.marker.unlink()
    monkeypatch.setattr(updates, "_save", lambda value: pytest.fail("terminal reconciliation must be read only"))
    assert recovery.recover(attended.request)["idempotent"]
    assert not (attended.root / "system-updates/recovery-records").exists()


def test_failed_state_write_preserves_marker_and_original_record_for_retry(attended, monkeypatch):
    save = updates._save
    monkeypatch.setattr(updates, "_save", lambda value: (_ for _ in ()).throw(OSError("test-only failure")))
    with pytest.raises(OSError):
        recovery.recover(attended.request)
    assert attended.marker.exists() and updates._state()["job"]["status"] == "needs_attention"
    record = attended.root / "system-updates/recovery-records" / (attended.job_id + ".json")
    before = record.read_bytes()
    monkeypatch.setattr(updates, "_save", save)
    recovery.recover(attended.request)
    assert record.read_bytes() == before


def test_marker_unlink_failure_stays_closed_and_retry_finishes_only_that_marker(attended, monkeypatch):
    unlink = Path.unlink
    failures = [True]
    def fail_once(path, *args, **kwargs):
        if path == attended.marker and failures:
            failures.pop()
            raise OSError("test-only marker unlink failure")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_once)
    with pytest.raises(OSError):
        recovery.recover(attended.request)
    assert updates._state()["job"]["status"] == "rolled_back"
    assert updates.is_maintenance()
    assert recovery.recover(attended.request)["idempotent"]
    assert not updates.is_maintenance()


def test_old_confirmation_cannot_remove_a_new_maintenance_marker(attended):
    recovery.recover(attended.request)
    attended.marker.write_text('{"different_maintenance":true}')
    with pytest.raises(updates.UpdateError, match="另一维护标记"):
        recovery.recover(attended.request)
    assert attended.marker.exists()


@pytest.fixture()
def host_store(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(host.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("DOCKER_HOST", "unix:///tmp/isolated-test-only-docker.sock")
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    job_id, runner_id = str(uuid.uuid4()), str(uuid.uuid4())
    identity = work / "runner.json"
    identity.write_text(json.dumps({"runner_id": runner_id}))
    identity.chmod(0o600)
    journal = work / "active-job.json"
    journal.write_text(json.dumps({"job_id": job_id, "status": "needs_attention", "terminal": True}))
    journal.chmod(0o600)
    calls = []
    def docker(container, payload):
        calls.append((container, payload))
        return {"ok": True, "maintenance_cleared": True,
                "job": {"id": job_id, "status": "rolled_back"}}
    return SimpleNamespace(home=home, work=work, job_id=job_id, runner_id=runner_id,
                           calls=calls, docker=docker, journal=journal, identity=identity)


def call_host(fixture, **overrides):
    values = {"container": "fixture-app", "work_dir": fixture.work, "job_id": fixture.job_id,
              "expected_version": "2.3.8", "expected_commit": "a" * 40, "outcome": "rolled_back",
              "confirmed": True, "docker": fixture.docker, **overrides}
    return host.recover(**values)


def test_host_syncs_same_job_atomically_and_preserves_runner_identity(host_store):
    before = host_store.identity.read_bytes()
    result = call_host(host_store)
    assert result["ok"] and not result["data_verified_automatically"]
    journal = json.loads(host_store.journal.read_text())
    assert journal["terminal"] is True and journal["status"] == "rolled_back"
    assert host_store.journal.stat().st_mode & 0o777 == 0o600
    assert host_store.identity.read_bytes() == before
    assert host_store.calls[0][1]["runner_id"] == host_store.runner_id
    assert host_store.calls[0][1]["confirm"] is True


@pytest.mark.parametrize("overrides", [{"confirmed": False}, {"job_id": "00000000-0000-4000-8000-0000000000a3"}, {"expected_commit": "unknown"}])
def test_host_rejects_unconfirmed_wrong_journal_or_short_commit_before_docker(host_store, overrides):
    with pytest.raises(host.RecoveryError):
        call_host(host_store, **overrides)
    assert not host_store.calls


def test_host_contends_for_exact_same_container_lock_as_runner(host_store):
    base = host_store.home / ".local/state/agv-update-runner"
    base.mkdir(parents=True)
    key = hashlib.sha256((os.environ["DOCKER_HOST"] + ":fixture-app").encode()).hexdigest()
    with (base / (key + ".lock")).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(host.RecoveryError, match="仍在管理"):
            call_host(host_store)
    assert not host_store.calls


def test_host_rejects_wrong_or_unfinished_backend_response(host_store):
    before = host_store.journal.read_bytes()
    with pytest.raises(host.RecoveryError):
        call_host(host_store, docker=lambda *args: {"ok": True, "maintenance_cleared": False, "job": {"id": host_store.job_id, "status": "rolled_back"}})
    assert host_store.journal.read_bytes() == before


def test_host_local_write_failure_is_safe_to_retry_same_remote_settlement(host_store, monkeypatch):
    write = host._write
    monkeypatch.setattr(host, "_write", lambda *args: (_ for _ in ()).throw(OSError("test-only disk failure")))
    with pytest.raises(OSError):
        call_host(host_store)
    assert json.loads(host_store.journal.read_text())["status"] == "needs_attention"
    monkeypatch.setattr(host, "_write", write)
    call_host(host_store)
    assert len(host_store.calls) == 2 and host_store.calls[0] == host_store.calls[1]
    assert json.loads(host_store.journal.read_text())["terminal"] is True


def test_docker_boundary_uses_only_exec_and_never_echoes_untrusted_errors(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1, stdout='{"error":"TEST_SECRET_NOT_FOR_DISPLAY"}', stderr="TEST_SECRET_NOT_FOR_DISPLAY")
    monkeypatch.setattr(host.subprocess, "run", run)
    with pytest.raises(host.RecoveryError) as error:
        host._docker("fixture-app", {"confirm": True})
    assert "TEST_SECRET_NOT_FOR_DISPLAY" not in str(error.value)
    assert calls[0][0] == ["docker", "exec", "-i", "fixture-app", "python", "-m", "app.services.system_update_recovery"]
