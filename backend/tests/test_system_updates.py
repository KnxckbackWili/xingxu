import json
import os
from pathlib import Path
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import config
from app.services import system_updates as updates
from app.services.system_update_bridge import dispatch


@pytest.fixture(autouse=True)
def isolated_update_store(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "_data_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "APP_VERSION", "2.3.8")
    monkeypatch.setenv("GIT_SHA", "a" * 40)
    monkeypatch.setattr(updates.update_source, "inspect_source", lambda *args: {"commit": "b" * 40, "version": "2.4.0"})


def source_values(**overrides):
    return {"repository_url": "https://git.example.com/team/workbench", "ref": "main",
            "allow_http": False, "revision": 0, "clear_token": False, **overrides}


def connected_runner(identifier):
    """Existing lifecycle tests assume the host has verified their fixture source."""
    result = updates.heartbeat(identifier, 1, trust_protocol=1, trust_configured=True)
    check = updates._state().get("check")
    if check and (check.get("trust") or {}).get("status") == "pending":
        updates.trust_result(identifier, check["id"], "trusted", method="commit")
    return result


def ready():
    updates.save_source(source_values(token="secret-repository-token"))
    checked = updates.check_source(1)
    runner = str(uuid.uuid4())
    connected_runner(runner)
    return checked["check"]["id"], runner


def queued():
    check_id, runner = ready()
    status = updates.request_install(check_id, "admin")
    return status["job"], runner


def test_configuration_encrypts_token_and_never_returns_it():
    result = updates.save_source(source_values(token="secret-repository-token"))
    assert result["source"]["has_token"] is True
    raw = (updates._data_dir() / "system-update-config.json").read_text()
    assert "secret-repository-token" not in raw
    assert "token_encrypted" not in json.dumps(result)
    assert updates._token(updates._source()) == "secret-repository-token"
    assert (updates._data_dir() / "system-update-config.json").stat().st_mode & 0o777 == 0o600


def test_blank_token_keeps_it_clear_is_explicit_and_changed_origin_clears():
    updates.save_source(source_values(token="secret-repository-token"))
    updates.save_source(source_values(revision=1, token=""))
    assert updates._token(updates._source()) == "secret-repository-token"
    updates.save_source(source_values(revision=2, clear_token=True))
    assert updates._token(updates._source()) == ""
    updates.save_source(source_values(revision=3, token="another-private-token"))
    updates.save_source(source_values(revision=4, repository_url="https://different.example/team/workbench"))
    assert updates._token(updates._source()) == ""


def test_failed_config_save_does_not_discard_old_token():
    updates.save_source(source_values(token="secret-repository-token"))
    with pytest.raises(updates.UpdateError, match="已被修改"):
        updates.save_source(source_values(revision=0, clear_token=True))
    assert updates._token(updates._source()) == "secret-repository-token"


def test_slow_check_cannot_publish_old_configuration(monkeypatch):
    updates.save_source(source_values())
    def lookup(*args):
        updates.save_source(source_values(revision=1, ref="stable"))
        return {"commit": "b" * 40, "version": "2.4.0"}
    monkeypatch.setattr(updates.update_source, "inspect_source", lookup)
    with pytest.raises(updates.UpdateError, match="期间配置"):
        updates.check_source(1)
    assert updates.get_status()["check"] is None


def test_install_is_pinned_and_idempotent_across_response_loss():
    check_id, _ = ready()
    first = updates.request_install(check_id, "admin")
    again = updates.request_install(check_id, "admin")
    assert first["job"] == again["job"]
    assert first["job"]["target_commit"] == "b" * 40
    assert "token" not in json.dumps(first["job"])


def test_concurrent_install_creates_only_one_job():
    check_id, _ = ready()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: updates.request_install(check_id, "admin"), range(4)))
    assert len({result["job"]["id"] for result in results}) == 1


def test_install_requires_fresh_check_and_connected_runner():
    updates.save_source(source_values())
    checked = updates.check_source(1)
    with pytest.raises(updates.UpdateError, match="未连接"):
        updates.request_install(checked["check"]["id"], "admin")
    connected_runner(str(uuid.uuid4()))
    state = updates._state()
    state["check"]["checked_at"] = "2000-01-01T00:00:00+00:00"
    updates._save(state)
    with pytest.raises(updates.UpdateError, match="过期"):
        updates.request_install(checked["check"]["id"], "admin")


@pytest.mark.parametrize("target,commit", [("2.3.7", "b" * 40), ("2.3.8", "a" * 40)])
def test_older_version_and_exact_commit_cannot_install(target, commit, monkeypatch):
    monkeypatch.setattr(updates.update_source, "inspect_source", lambda *args: {"commit": commit, "version": target})
    check_id, _ = ready()
    assert updates.get_status()["check"]["update_available"] is False
    with pytest.raises(updates.UpdateError, match="没有可安装"):
        updates.request_install(check_id, "admin")


def test_same_version_new_commit_is_allowed_for_branch_fixes(monkeypatch):
    monkeypatch.setattr(updates.update_source, "inspect_source", lambda *args: {"commit": "b" * 40, "version": "2.3.8"})
    check_id, _ = ready()
    assert updates.request_install(check_id, "admin")["job"]["target_version"] == "2.3.8"


def test_busy_job_blocks_source_changes_and_new_checks():
    queued()
    with pytest.raises(updates.UpdateError, match="不能修改"):
        updates.save_source(source_values(revision=1))
    with pytest.raises(updates.UpdateError, match="不能重新检查"):
        updates.check_source(1)


def test_claim_is_recoverable_after_lost_response_and_wrong_runner_cannot_mutate():
    job, runner = queued()
    assert updates.claim(runner)["job"]["id"] == job["id"]
    assert updates.claim(runner)["job"]["id"] == job["id"]
    updates.report(runner, job["id"], "building")
    assert updates.claim(runner)["job"]["status"] == "building"
    with pytest.raises(updates.UpdateError, match="不属于"):
        updates.report(str(uuid.uuid4()), job["id"], "failed")
    with pytest.raises(updates.UpdateError, match="另一个"):
        connected_runner(str(uuid.uuid4()))


def test_replacement_runner_cannot_take_over_active_job():
    job, runner = queued()
    updates.claim(runner)
    state = updates._state()
    state["runner"]["last_seen"] = "2000-01-01T00:00:00+00:00"
    updates._save(state)
    replacement = str(uuid.uuid4())
    connected_runner(replacement)
    with pytest.raises(updates.UpdateError, match="其他更新服务"):
        updates.claim(replacement)


def test_host_credentials_use_frozen_source_and_legacy_package_protocol_is_disabled(monkeypatch):
    job, runner = queued()
    claimed = updates.claim(runner)['job']
    assert claimed['target_commit'] == 'b' * 40
    assert updates.trust_credentials(runner, job_id=job['id']) == {'token': 'secret-repository-token'}
    calls = []
    monkeypatch.setattr(updates.update_source, 'download_source', lambda *args: calls.append(args))
    with pytest.raises(updates.UpdateError, match='旧版压缩包更新协议已停用'):
        updates.prepare(runner, job['id'])
    assert calls == []


def test_success_requires_running_target_version_and_cannot_overwrite_terminal(monkeypatch):
    job, runner = queued()
    updates.claim(runner)
    updates.report(runner, job["id"], "verifying")
    with pytest.raises(updates.UpdateError, match="实际运行版本"):
        updates.report(runner, job["id"], "succeeded")
    monkeypatch.setattr(config, "APP_VERSION", "2.4.0")
    monkeypatch.setenv("GIT_SHA", "b" * 40)
    assert updates.report(runner, job["id"], "succeeded")["job"]["status"] == "succeeded"
    assert "source" not in updates._state()["job"]
    with pytest.raises(updates.UpdateError, match="已结束"):
        updates.report(runner, job["id"], "failed")


def test_bridge_discards_untrusted_log_message_and_needs_attention_stays_locked():
    job, runner = queued()
    updates.claim(runner)
    result = dispatch({"action": "report", "runner_id": runner, "job_id": job["id"],
                       "status": "needs_attention", "message": "private-password"})
    assert "private-password" not in json.dumps(result)
    assert updates.is_maintenance()
    with pytest.raises(updates.UpdateError):
        updates.save_source(source_values(revision=1))


def test_state_corruption_fails_closed_and_symlink_config_is_rejected(tmp_path):
    updates.get_status()
    (tmp_path / "system-updates/state.json").write_text("broken json")
    assert updates.is_maintenance()
    with pytest.raises(updates.UpdateError, match="无法读取"):
        updates.get_status()
    (tmp_path / "system-updates/state.json").unlink()
    (tmp_path / "system-update-config.json").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(updates.UpdateError, match="无法读取"):
        updates.get_status()


def test_route_rejects_non_admin_even_with_permission_grants(client, pm_headers, admin_headers):
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        user = db.query(User).filter_by(username="pm").one()
        user.permission_overrides = {"system.backups.create": True, "system.updates.manage": True}
        db.commit()
    assert client.get("/api/system/updates", headers=pm_headers).status_code == 403
    assert client.get("/api/system/updates", headers=admin_headers).status_code == 200


def test_route_save_check_install_and_safe_audit(client, admin_headers):
    response = client.put("/api/system/updates/source", headers=admin_headers, json=source_values(token="private-repo-token"))
    assert response.status_code == 200
    assert "private-repo-token" not in response.text
    checked = client.post("/api/system/updates/check", headers=admin_headers, json={"source_revision": 1})
    assert checked.status_code == 200
    connected_runner(str(uuid.uuid4()))
    payload = {"check_id": checked.json()["check"]["id"], "confirm": False}
    assert client.post("/api/system/updates/install", headers=admin_headers, json=payload).status_code == 400
    payload["confirm"] = True
    installed = client.post("/api/system/updates/install", headers=admin_headers, json=payload)
    assert installed.status_code == 202
    from app.db import SessionLocal
    from app.models import ChangeLog
    with SessionLocal() as db:
        rows = db.query(ChangeLog).filter_by(entity_type="system_update").all()
        assert {row.action for row in rows} == {"configure", "check", "request"}
        assert "private-repo-token" not in str([(row.detail, row.new_value) for row in rows])


def test_maintenance_rejects_business_requests_but_keeps_status_and_health(client, admin_headers):
    job, runner = queued()
    updates.claim(runner)
    updates.report(runner, job["id"], "backing_up")
    response = client.get("/api/projects", headers=admin_headers)
    assert response.status_code == 503 and response.json()["maintenance"] is True
    assert client.post("/api/system/backups", headers=admin_headers, json={"label": "manual"}).status_code == 503
    assert client.get("/api/system/updates", headers=admin_headers).status_code == 200
    assert client.get("/api/auth/me", headers=admin_headers).status_code == 200
    assert client.get("/health").status_code == 200


def test_update_source_backup_is_allowed_but_queue_is_not(tmp_path):
    import io
    import tarfile
    from app.services.backup_safety import safe_members
    for name, allowed in [("system-update-config.json", True), ("system-updates/state.json", False)]:
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            member = tarfile.TarInfo(name)
            member.size = 2
            archive.addfile(member, io.BytesIO(b"{}"))
        stream.seek(0)
        with tarfile.open(fileobj=stream) as archive:
            if allowed:
                assert len(safe_members(archive)) == 1
            else:
                with pytest.raises(ValueError):
                    safe_members(archive)


def test_manual_maintenance_marker_blocks_until_removed(tmp_path):
    marker = tmp_path / "update-maintenance.json"
    assert not updates.is_maintenance()
    marker.write_text('{}')
    assert updates.is_maintenance()
    marker.unlink()
    assert not updates.is_maintenance()


def test_restore_preserves_encrypted_source_and_clears_it_for_legacy_snapshot(tmp_path):
    from app.services.restore_bootstrap import _install_snapshot
    live, staged = tmp_path / "live", tmp_path / "staged"
    live.mkdir(); staged.mkdir()
    (live / "system-update-config.json").write_text('{"token_encrypted":"old"}')
    (staged / "system-update-config.json").write_text('{"token_encrypted":"restored"}')
    _install_snapshot(live, staged)
    assert json.loads((live / "system-update-config.json").read_text())["token_encrypted"] == "restored"
    assert (live / "system-update-config.json").stat().st_mode & 0o777 == 0o600
    _install_snapshot(live, staged)
    assert not (live / "system-update-config.json").exists()


def test_scheduler_waits_for_maintenance_before_starting(monkeypatch):
    from app.services import run_scheduler, report_scheduler
    checks = iter([True, True, False])
    starts, sleeps, stops = [], [], []
    class Scheduler:
        def shutdown(self, wait=False):
            stops.append(wait)
    monkeypatch.setattr(updates, "is_maintenance", lambda: next(checks))
    monkeypatch.setattr(report_scheduler, "start_scheduler", lambda: (starts.append(True), Scheduler())[1])
    def sleep(seconds):
        sleeps.append(seconds)
        if seconds == 60:
            raise KeyboardInterrupt()
        assert starts == []
    monkeypatch.setattr(run_scheduler.time, "sleep", sleep)
    run_scheduler.main()
    assert starts == [True] and sleeps == [2, 2, 60] and stops == [False]


@pytest.mark.parametrize("automatic_rollback", [False, True])
def test_restore_invalidates_old_jobs_except_during_automatic_update_rollback(tmp_path, automatic_rollback):
    from app.services.restore_bootstrap import _install_snapshot
    live, staged = tmp_path / "live", tmp_path / "staged"
    live.mkdir(); staged.mkdir()
    (live / "system-updates").mkdir()
    state = live / "system-updates/state.json"
    state.write_text('{"job":{"status":"queued"}}')
    if automatic_rollback:
        (live / "update-maintenance.json").write_text('{}')
    _install_snapshot(live, staged)
    assert state.exists() is automatic_rollback


def test_default_is_preselected_without_network_or_config_write(tmp_path, monkeypatch):
    monkeypatch.setattr(updates.update_source, "inspect_source", lambda *args: pytest.fail("unexpected network check"))
    first, second = updates.get_status(), updates.get_status()
    assert first == second
    assert first["active_source_id"] == "default-gitea"
    assert first["source"] == first["sources"][0]
    assert first["source"]["name"] == "我的 Gitea"
    assert first["source"]["repository_url"] == updates.DEFAULT_REPOSITORY_URL
    assert first["source"]["ref"] == "main"
    assert first["source"]["is_default"] is True
    assert first["source"]["has_token"] is False
    assert first["source"]["revision"] == 0
    assert first["maintenance"] is False
    assert not (tmp_path / "system-update-config.json").exists()


@pytest.mark.parametrize("url", ["https://git.example.com/team/private", updates.DEFAULT_REPOSITORY_URL + ".git/"])
def test_legacy_source_is_preserved_without_read_side_effects(tmp_path, url):
    encrypted = updates._fernet().encrypt(b"legacy-private-token").decode()
    legacy = {**updates.update_source.normalize_source(url), "repository_url": url,
              "revision": 17, "token_encrypted": encrypted}
    path = tmp_path / "system-update-config.json"
    path.write_text(json.dumps(legacy))
    path.chmod(0o600)
    before, before_stat = path.read_bytes(), path.stat()
    status = updates.get_status()
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert status["source"]["repository_url"] == url
    assert status["source"]["ref"] == "main"
    assert status["source"]["revision"] == 17
    assert updates._token(updates._source()) == "legacy-private-token"
    assert len(status["sources"]) == (1 if url.startswith(updates.DEFAULT_REPOSITORY_URL) else 2)
    assert status["active_source_id"] == status["source"]["id"]
    # Selecting another item is the first operation that persists migration;
    # all original fields and encrypted bytes remain in the retained item.
    updated = updates.select_source(updates.DEFAULT_SOURCE_ID, 17)
    assert updated["source"]["revision"] == 18
    migrated = json.loads(path.read_text())
    original = next(item for item in migrated["sources"] if item["id"] == status["source"]["id"])
    assert all(original[key] == legacy[key] for key in ("repository_url", "ref", "allow_http", "token_encrypted"))
    assert migrated["repository_url"] == updated["source"]["repository_url"]
    assert migrated["token_encrypted"] == updates._source()["token_encrypted"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_old_version_flat_save_can_be_read_again(tmp_path):
    updates.add_source(source_values(name="第二来源", token="private-second-token"))
    selected = updates._source()
    legacy = {key: selected[key] for key in ("repository_url", "ref", "allow_http", "revision", "token_encrypted")}
    legacy["revision"] += 1
    (tmp_path / "system-update-config.json").write_text(json.dumps(legacy))
    status = updates.get_status()
    assert status["source"]["repository_url"] == legacy["repository_url"]
    assert status["source"]["revision"] == 2
    assert updates._token(updates._source()) == "private-second-token"


@pytest.mark.parametrize("corruption", ["flat", "active", "duplicate", "missing_default", "schema", "token_type"])
def test_inconsistent_source_lists_fail_closed(tmp_path, corruption):
    updates.add_source(source_values(name="测试来源"))
    path = tmp_path / "system-update-config.json"
    raw = json.loads(path.read_text())
    if corruption == "flat":
        raw["repository_url"] = "https://wrong.example/team/workbench"
    elif corruption == "active":
        raw["active_source_id"] = "missing"
    elif corruption == "duplicate":
        raw["sources"].append(dict(raw["sources"][-1]))
    elif corruption == "missing_default":
        raw["sources"] = raw["sources"][1:]
    elif corruption == "schema":
        raw["schema_version"] = 3
    else:
        raw["sources"][-1]["token_encrypted"] = ["not-a-string"]
    path.write_text(json.dumps(raw))
    with pytest.raises(updates.UpdateError, match="不一致") as error:
        updates.get_status()
    assert error.value.status == 503


def test_sources_keep_independent_tokens_and_edits_only_change_active():
    initial = updates.get_status()["source"]
    updates.save_source({**initial, "token": "private-default-token"})
    added = updates.add_source(source_values(revision=1, name="内部测试", token="private-second-token"))
    second_id = added["active_source_id"]
    assert second_id != updates.DEFAULT_SOURCE_ID
    assert updates._token(updates._source()) == "private-second-token"
    assert all(item["has_token"] for item in added["sources"])
    updated = updates.save_source(source_values(revision=2, name="内部正式", ref="stable"))
    assert updated["source"]["name"] == "内部正式"
    assert updates._token(updates._source()) == "private-second-token"
    selected = updates.select_source(updates.DEFAULT_SOURCE_ID, 3)
    assert selected["source"]["repository_url"] == initial["repository_url"]
    assert selected["source"]["name"] == initial["name"]
    assert updates._token(updates._source()) == "private-default-token"
    updates.select_source(second_id, 4)
    updates.save_source(source_values(revision=5, repository_url="https://other.example/team/workbench"))
    assert updates._token(updates._source()) == ""
    assert updates.get_status()["sources"][0]["has_token"] is True
    public = json.dumps(updates.get_status())
    assert "private-default-token" not in public and "private-second-token" not in public
    assert "token_encrypted" not in public


def test_source_selection_and_deletion_invalidate_checks_and_preserve_default():
    added = updates.add_source(source_values(name="测试来源"))
    source_id = added["active_source_id"]
    checked = updates.check_source(1)
    selected = updates.select_source(updates.DEFAULT_SOURCE_ID, 1)
    assert selected["check"] is None and selected["source"]["revision"] == 2
    with pytest.raises(updates.UpdateError, match="失效"):
        updates.request_install(checked["check"]["id"], "admin")
    updates.select_source(source_id, 2)
    updates.check_source(3)
    removed = updates.delete_source(source_id, 3)
    assert removed["check"] is None
    assert removed["active_source_id"] == updates.DEFAULT_SOURCE_ID
    assert len(removed["sources"]) == 1
    assert removed["source"]["revision"] == 4
    with pytest.raises(updates.UpdateError, match="不能删除"):
        updates.delete_source(updates.DEFAULT_SOURCE_ID, 4)


def test_deleting_inactive_source_preserves_selected_source_and_token():
    first = updates.add_source(source_values(name="第一源"))["active_source_id"]
    second = updates.add_source(source_values(name="第二源", revision=1, ref="stable", token="selected-token"))
    result = updates.delete_source(first, 2)
    assert result["active_source_id"] == second["active_source_id"]
    assert updates._token(updates._source()) == "selected-token"


def test_normalized_duplicates_are_rejected_but_different_refs_are_allowed():
    updates.add_source(source_values(name="第一源"))
    with pytest.raises(updates.UpdateError, match="已存在"):
        updates.add_source(source_values(name="重复源", revision=1,
                                        repository_url="https://GIT.EXAMPLE.COM:443/team/workbench.git/"))
    result = updates.add_source(source_values(name="稳定分支", revision=1, ref="stable"))
    with pytest.raises(updates.UpdateError, match="已存在"):
        updates.save_source(source_values(name="重复编辑", revision=2))
    assert updates.get_status() == result


@pytest.mark.parametrize("name", ["", "   ", "a" * 61, "line\nbreak", "a\u202eb", "a\x7fb"])
def test_invalid_source_names_are_rejected_without_writing(tmp_path, name):
    with pytest.raises(updates.UpdateError, match="名称"):
        updates.add_source(source_values(name=name))
    assert not (tmp_path / "system-update-config.json").exists()


def test_source_count_is_bounded():
    for index in range(updates.MAX_SOURCES - 1):
        updates.add_source(source_values(name=f"来源 {index}", revision=index, ref=f"branch-{index}"))
    with pytest.raises(updates.UpdateError, match="最多"):
        updates.add_source(source_values(name="超出限制", revision=19, ref="overflow"))
    assert len(updates.get_status()["sources"]) == 20


def test_concurrent_source_mutations_commit_exactly_one_revision():
    def add(index):
        try:
            return updates.add_source(source_values(name=f"来源 {index}", ref=f"branch-{index}"))
        except updates.UpdateError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(add, range(4)))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert results.count(409) == 3
    assert updates.get_status()["source"]["revision"] == 1
    assert len(updates.get_status()["sources"]) == 2


def test_stale_select_and_delete_cannot_overwrite_newer_source_config():
    added = updates.add_source(source_values(name="测试来源"))
    source_id = added["active_source_id"]
    with pytest.raises(updates.UpdateError, match="已被修改"):
        updates.select_source(updates.DEFAULT_SOURCE_ID, 0)
    with pytest.raises(updates.UpdateError, match="已被修改"):
        updates.delete_source(source_id, 0)
    assert updates.get_status() == added


def test_slow_check_is_discarded_after_source_switch(monkeypatch):
    updates.add_source(source_values(name="测试来源"))
    def lookup(*args):
        updates.select_source(updates.DEFAULT_SOURCE_ID, 1)
        return {"commit": "b" * 40, "version": "2.4.0"}
    monkeypatch.setattr(updates.update_source, "inspect_source", lookup)
    with pytest.raises(updates.UpdateError, match="期间配置"):
        updates.check_source(1)
    assert updates.get_status()["check"] is None


@pytest.mark.parametrize("blocker", ["queued", "needs_attention", "marker"])
def test_every_source_mutation_and_check_is_locked_during_updates(tmp_path, blocker):
    added = updates.add_source(source_values(name="测试来源"))
    source_id = added["active_source_id"]
    check_id = updates.check_source(1)["check"]["id"]
    runner = str(uuid.uuid4())
    connected_runner(runner)
    if blocker == "marker":
        (tmp_path / "update-maintenance.json").write_text("{}")
    else:
        job = updates.request_install(check_id, "admin")["job"]
        if blocker == "needs_attention":
            updates.claim(runner)
            updates.report(runner, job["id"], "needs_attention")
    before = (tmp_path / "system-update-config.json").read_bytes()
    actions = [lambda: updates.save_source(source_values(revision=1)),
               lambda: updates.add_source(source_values(revision=1, name="另一源", ref="stable")),
               lambda: updates.select_source(updates.DEFAULT_SOURCE_ID, 1),
               lambda: updates.delete_source(source_id, 1),
               lambda: updates.check_source(1)]
    if blocker == "marker":
        actions.append(lambda: updates.request_install(check_id, "admin"))
    for action in actions:
        with pytest.raises(updates.UpdateError) as error:
            action()
        assert error.value.status == 409
    assert (tmp_path / "system-update-config.json").read_bytes() == before
    assert updates.get_status()["maintenance"] is (blocker != "queued")


def test_install_freezes_only_selected_source_and_its_token(monkeypatch):
    default = updates.get_status()["source"]
    updates.save_source({**default, "token": "private-default-token"})
    added = updates.add_source(source_values(revision=1, name="选中来源", token="private-selected-token"))
    check_id = updates.check_source(2)["check"]["id"]
    runner = str(uuid.uuid4())
    connected_runner(runner)
    job = updates.request_install(check_id, "admin")["job"]
    frozen = updates._state()["job"]["source"]
    assert frozen["id"] == added["active_source_id"]
    assert set(frozen) == set(updates._SOURCE_FIELDS) | {"revision"}
    assert updates._token(frozen) == "private-selected-token"
    default_cipher = updates._configuration()["sources"][0]["token_encrypted"]
    assert default_cipher not in json.dumps(updates._state())
    updates.claim(runner)
    assert updates.trust_credentials(runner, job_id=job['id']) == {'token': 'private-selected-token'}
    with pytest.raises(updates.UpdateError, match='旧版压缩包更新协议已停用'):
        updates.prepare(runner, job['id'])


def test_sources_api_is_admin_only_and_audits_without_tokens(client, admin_headers, pm_headers):
    path = "/api/system/updates/sources"
    body = source_values(name="私有更新源", token="private-source-audit-token")
    assert client.post(path, headers=pm_headers, json=body).status_code == 403
    created = client.post(path, headers=admin_headers, json=body)
    assert created.status_code == 201
    source_id = created.json()["active_source_id"]
    assert client.post(f"{path}/{source_id}/select", headers=pm_headers, json={"revision": 1}).status_code == 403
    assert client.delete(f"{path}/{source_id}?revision=1", headers=pm_headers).status_code == 403
    selected = client.post(f"{path}/default-gitea/select", headers=admin_headers, json={"revision": 1})
    assert selected.status_code == 200
    deleted = client.delete(f"{path}/{source_id}?revision=2", headers=admin_headers)
    assert deleted.status_code == 200
    assert deleted.json()["source"]["revision"] == 3
    from app.db import SessionLocal
    from app.models import ChangeLog
    with SessionLocal() as db:
        rows = db.query(ChangeLog).filter_by(entity_type="system_update").all()
        assert {row.action for row in rows} == {"create", "select", "delete"}
        serialized = str([(row.detail, row.new_value) for row in rows])
        assert "private-source-audit-token" not in serialized
        assert "token_encrypted" not in serialized
    assert "private-source-audit-token" not in created.text


def test_marker_without_job_blocks_mutation_api(client, admin_headers, tmp_path):
    added = updates.add_source(source_values(name="测试来源"))
    source_id = added["active_source_id"]
    checked = updates.check_source(1)
    connected_runner(str(uuid.uuid4()))
    (tmp_path / "update-maintenance.json").write_text("{}")
    path = "/api/system/updates"
    assert client.get(path, headers=admin_headers).json()["maintenance"] is True
    # The application-wide maintenance middleware rejects writes before routing.
    assert client.put(path + "/source", headers=admin_headers, json=source_values(revision=1)).status_code == 503
    assert client.post(path + "/sources", headers=admin_headers,
                       json=source_values(name="另一源", revision=1, ref="stable")).status_code == 503
    assert client.post(path + "/sources/default-gitea/select", headers=admin_headers,
                       json={"revision": 1}).status_code == 503
    assert client.delete(f"{path}/sources/{source_id}?revision=1", headers=admin_headers).status_code == 503
    assert client.post(path + "/check", headers=admin_headers, json={"source_revision": 1}).status_code == 503
    assert client.post(path + "/install", headers=admin_headers,
                       json={"check_id": checked["check"]["id"], "confirm": True}).status_code == 503


def test_state_save_failure_keeps_new_revision_and_invalidates_old_check(monkeypatch):
    added = updates.add_source(source_values(name="测试来源"))
    old_check = updates.check_source(1)["check"]["id"]
    write = updates._write
    def fail_state(path, value):
        if path.name == "state.json":
            raise OSError("simulated full state storage")
        return write(path, value)
    monkeypatch.setattr(updates, "_write", fail_state)
    with pytest.raises(OSError):
        updates.select_source(updates.DEFAULT_SOURCE_ID, 1)
    refreshed = updates.get_status()
    assert refreshed["active_source_id"] == updates.DEFAULT_SOURCE_ID
    assert refreshed["source"]["revision"] == 2
    assert refreshed["check"] is None
    with pytest.raises(updates.UpdateError, match="失效"):
        updates.request_install(old_check, "admin")
    with pytest.raises(updates.UpdateError, match="已被修改"):
        updates.select_source(added["active_source_id"], 1)
