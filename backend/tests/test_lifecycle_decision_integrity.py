"""人工生命周期决策、当前验收范围及权限复核。"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import pytest
from fastapi import HTTPException
from app.db import SessionLocal
from app.models import AcceptanceRecord, ArchiveChecklist, DailyProgress, Module, Phase, Project, ProjectPreparationItem, Task, User


def _project(client, headers, status="preparing"):
    response = client.post("/api/projects", headers=headers, json={
        "name": "生命周期独立验证", "start_date": "2026-09-01",
        "end_date": "2026-12-31", "new_vehicles": False, "status": "preparing",
    })
    assert response.status_code == 200, response.text
    pid = response.json()["id"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.status = status
        db.query(ProjectPreparationItem).filter_by(project_id=pid).delete()
        db.commit()
    if status == "preparing":
        # The former ready stage: stage-4 kickoff evidence in place, only the stage-5 decision left.
        from tests.lifecycle_helpers import submit_kickoff_documents
        submit_kickoff_documents(client, headers, pid)
    return pid


def _preparation(client, headers, pid, **values):
    response = client.post(f"/api/projects/{pid}/procurements", headers=headers,
                           json={"name": "现场必要条件", "is_required": True,
                                 "blocks_entry": True, **values})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _review(client, headers, pid, conclusion="risky", notes="已核对当前风险，由项目负责人接收"):
    manifest = client.post(f"/api/projects/{pid}/documents/dispatch-review", headers=headers)
    assert manifest.status_code == 200, manifest.text
    return client.post(f"/api/projects/{pid}/documents/dispatch-review/confirm", headers=headers,
                       json={"conclusion": conclusion, "notes": notes,
                             "review_token": manifest.json()["review_token"]})


def _status(client, headers, pid, target, **values):
    return client.post(f"/api/projects/{pid}/status", headers=headers,
                       json={"status": target, **values})


def _assert_status(pid, expected):
    with SessionLocal() as db:
        assert db.get(Project, pid).status == expected


def _completion_fixture(client, headers, status="acceptance"):
    pid = _project(client, headers, "acceptance")
    with SessionLocal() as db:
        p = db.get(Project, pid)
        phase = Phase(project_id=pid, name="现场实施")
        db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name="执行范围")
        db.add(module); db.flush()
        task = Task(project_id=pid, phase_id=phase.id, module_id=module.id, name="设备调试", quantity_type="fixed",
                    target_quantity=1)
        db.add(task); db.flush()
        db.add(DailyProgress(project_id=pid, task_id=task.id, user_id=p.manager,
                             work_date=date(2026, 9, 30), completed_quantity=1,
                             client_uuid="independent-complete"))
        for row in db.query(ArchiveChecklist).filter_by(project_id=pid):
            row.is_done = True
        db.commit()
        tid = task.id
    from tests.lifecycle_helpers import complete_vehicle_progress
    complete_vehicle_progress(client, headers, pid)
    completed = client.put(f'/api/projects/{pid}/work-items/{tid}/completion', headers=headers,
        json={'version': 0, 'is_completed': True, 'reason': '已明确核对当前实施工作完成'})
    assert completed.status_code == 200, completed.text
    from tests.document_helpers import complete_documents
    from tests.lifecycle_helpers import register_kickoff
    register_kickoff(client, headers, pid)
    complete_documents(client, headers, pid)
    with SessionLocal() as db:
        db.get(Project, pid).status = status
        db.commit()
    return pid, tid


def _sign(client, headers, pid, conclusion="accepted", day="2026-09-30"):
    response = client.post(f"/api/projects/{pid}/acceptance", headers=headers, json={
        "accepted_by_name": "甲方验收负责人", "accepted_at": day,
        "conclusion": conclusion, "notes": "当前实施范围的验收结论",
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.mark.parametrize("legacy_flag", [None, False, True])
def test_entry_needs_current_risk_review_not_legacy_warning_flag(client, pm_headers, legacy_flag):
    pid = _project(client, pm_headers)
    _preparation(client, pm_headers, pid)
    extra = {} if legacy_flag is None else {"confirm_warnings": legacy_flag}
    response = _status(client, pm_headers, pid, "executing", reason="任意状态备注", **extra)
    assert response.status_code == 400, response.text
    _assert_status(pid, "preparing")
    assert _review(client, pm_headers, pid, notes="  ").status_code == 400
    assert _review(client, pm_headers, pid).status_code == 200
    assert _status(client, pm_headers, pid, "executing", **extra).status_code == 200


@pytest.mark.parametrize("mandatory,blocking", [(True, False), (False, True)])
def test_either_mandatory_or_blocking_prerequisite_needs_risk_decision(client, pm_headers, mandatory, blocking):
    pid = _project(client, pm_headers)
    _preparation(client, pm_headers, pid, is_required=mandatory, blocks_entry=blocking)
    assert _status(client, pm_headers, pid, "executing").status_code == 400


@pytest.mark.parametrize("origin", ["preparing", "suspended"])
def test_every_executing_entry_path_rechecks_current_risk(client, pm_headers, origin):
    """Entering or resuming execution rechecks the current stage-5 risk approval."""
    from tests.test_dispatch_review_t29 import scope, confirm, requirement
    pid, _ = scope(client, pm_headers, status="executing" if origin == "suspended" else origin)
    assert confirm(client, pm_headers, pid).status_code == 200
    if origin == "suspended":
        assert _status(client, pm_headers, pid, "suspended", reason="暂停等待现场").status_code == 200
    requirement(client, pm_headers, pid, "批准后新增的发车资料")
    denied = _status(client, pm_headers, pid, "executing", confirm_warnings=True)
    assert denied.status_code == 400, denied.text
    _assert_status(pid, origin)
    assert confirm(client, pm_headers, pid).status_code == 200
    assert _status(client, pm_headers, pid, "executing").status_code == 200


def test_later_not_ready_supersedes_earlier_risky_decision(client, pm_headers):
    pid = _project(client, pm_headers)
    _preparation(client, pm_headers, pid)
    assert _review(client, pm_headers, pid).status_code == 200
    assert _review(client, pm_headers, pid, conclusion="not_ready", notes="风险暂不接受").status_code == 200
    response = _status(client, pm_headers, pid, "executing")
    assert response.status_code == 400, response.text
    _assert_status(pid, "preparing")


@pytest.mark.parametrize("later", ["rejected", "conditionally_accepted"])
@pytest.mark.parametrize("same_day", [False, True])
def test_latest_nonpass_blocks_completion_even_with_older_pass(client, pm_headers, later, same_day):
    pid, _ = _completion_fixture(client, pm_headers)
    _sign(client, pm_headers, pid, day="2026-09-29")
    current = _sign(client, pm_headers, pid, later, "2026-09-29" if same_day else "2026-09-30")
    response = _status(client, pm_headers, pid, "completed")
    assert response.status_code == 400, response.text
    _assert_status(pid, "acceptance")
    rows = client.get(f"/api/projects/{pid}/acceptance", headers=pm_headers).json()
    assert [row["id"] for row in rows if row["is_effective"]] == [current]
    _sign(client, pm_headers, pid, day="2026-10-01")
    assert _status(client, pm_headers, pid, "completed").status_code == 200


@pytest.mark.parametrize("newest,backfilled,expected", [
    ("rejected", "accepted", 400), ("accepted", "rejected", 200),
])
def test_backfilled_older_signature_does_not_supersede_later_effective_date(client, pm_headers, newest, backfilled, expected):
    pid, _ = _completion_fixture(client, pm_headers)
    current = _sign(client, pm_headers, pid, newest, "2026-09-30")
    _sign(client, pm_headers, pid, backfilled, "2026-09-29")
    rows = client.get(f"/api/projects/{pid}/acceptance", headers=pm_headers).json()
    assert rows[0]["id"] == current
    assert [row["id"] for row in rows if row["is_effective"]] == [current]
    result = _status(client, pm_headers, pid, "completed")
    assert result.status_code == expected, result.text


def test_latest_record_tie_break_is_deterministic(client, pm_headers):
    pid, _ = _completion_fixture(client, pm_headers)
    one = _sign(client, pm_headers, pid)
    two = _sign(client, pm_headers, pid)
    with SessionLocal() as db:
        for rid in (one, two):
            row = db.get(AcceptanceRecord, rid)
            row.created_at = datetime(2026, 10, 1, 9, 0)
            row.conclusion = "rejected" if rid == max(one, two) else "accepted"
        db.commit()
    rows = client.get(f"/api/projects/{pid}/acceptance", headers=pm_headers).json()
    assert [row["id"] for row in rows if row["is_effective"]] == [max(one, two)]
    assert _status(client, pm_headers, pid, "completed").status_code == 400


def test_post_completion_rejection_blocks_archive_and_allows_recovery(client, pm_headers):
    pid, _ = _completion_fixture(client, pm_headers)
    _sign(client, pm_headers, pid)
    assert _status(client, pm_headers, pid, "completed").status_code == 200
    _sign(client, pm_headers, pid, "rejected", "2026-10-01")
    denied = _status(client, pm_headers, pid, "archived", retrospective="发现问题后重新核对")
    assert denied.status_code == 400, denied.text
    _assert_status(pid, "completed")
    assert _status(client, pm_headers, pid, "acceptance").status_code == 200
    _sign(client, pm_headers, pid, day="2026-10-01")
    assert _status(client, pm_headers, pid, "completed").status_code == 200
    assert _status(client, pm_headers, pid, "archived", retrospective="整改后最新验收通过").status_code == 200


def test_added_completed_work_still_requires_new_scope_acceptance(client, pm_headers):
    pid, tid = _completion_fixture(client, pm_headers)
    first = _sign(client, pm_headers, pid)
    with SessionLocal() as db:
        old = db.get(Task, tid)
        added = Task(project_id=pid, module_id=old.module_id, name="追加实施范围",
                     target_quantity=1, manually_completed=True)
        db.add(added); db.commit()
    rows = client.get(f"/api/projects/{pid}/acceptance", headers=pm_headers).json()
    assert rows[0]["id"] == first and not rows[0]["scope_current"]
    result = _status(client, pm_headers, pid, "completed")
    assert result.status_code == 400, result.text
    _sign(client, pm_headers, pid)
    assert _status(client, pm_headers, pid, "completed").status_code == 200


def test_new_required_project_document_cannot_reuse_old_signature(client, pm_headers):
    from tests.document_helpers import requirement, upload_documents
    pid, _ = _completion_fixture(client, pm_headers)
    _sign(client, pm_headers, pid)
    row = requirement(client, pm_headers, pid, name='新增强制安全方案')
    upload_documents(client, pm_headers, pid, [row['id']])
    result = _status(client, pm_headers, pid, 'completed')
    assert result.status_code == 400, result.text
    assert any(blocker['type'] == 'acceptance' for blocker in result.json()['detail']['blockers'])
    _sign(client, pm_headers, pid)
    assert _status(client, pm_headers, pid, 'completed').status_code == 200


def test_cosmetic_project_updates_do_not_invalidate_scope_signoff(client, pm_headers):
    pid, _ = _completion_fixture(client, pm_headers)
    _sign(client, pm_headers, pid)
    from tests.lifecycle_helpers import project_version
    changed = client.put(f"/api/projects/{pid}", headers=pm_headers,
                         json={"description": "文字纠错", "staffing_notes": "排班备注",
                               "version": project_version(client, pm_headers, pid)})
    assert changed.status_code == 200, changed.text
    result = _status(client, pm_headers, pid, "completed")
    assert result.status_code == 200, result.text


@pytest.mark.parametrize('empty_field', ['note', 'template_no'])
def test_empty_optional_material_definition_text_is_not_new_scope(client, pm_headers, empty_field):
    from tests.document_helpers import requirement, upload_documents, documents
    pid, _ = _completion_fixture(client, pm_headers)
    row = requirement(client, pm_headers, pid, name='必需报告')
    upload_documents(client, pm_headers, pid, [row['id']])
    _sign(client, pm_headers, pid)
    definition = next(value for value in documents(client, pm_headers, pid)['definitions'] if value['id'] == row['definition_id'])
    keys = ('stage_key', 'code', 'name', 'template_no', 'required', 'scope', 'platform', 'timing_type', 'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type', 'confidential_default', 'external_visible_default', 'external_never_visible', 'sort_order', 'note')
    body = {key: definition[key] for key in keys}; body[empty_field] = ''
    changed = client.put(f'/api/projects/{pid}/documents/requirements/{definition["id"]}', headers=pm_headers, json=body)
    assert changed.status_code == 200, changed.text
    assert _status(client, pm_headers, pid, 'completed').status_code == 200


def test_legacy_archived_project_can_restore_but_needs_current_signoff_to_rearchive(client, pm_headers):
    pid, _ = _completion_fixture(client, pm_headers, "archived")
    with SessionLocal() as db:
        db.add(AcceptanceRecord(project_id=pid, accepted_by_name="历史客户",
                               accepted_at=date(2026, 9, 30), conclusion="accepted"))
        db.commit()
    assert _status(client, pm_headers, pid, "completed").status_code == 200
    blocked = _status(client, pm_headers, pid, "archived", retrospective="恢复旧档案")
    assert blocked.status_code == 400, blocked.text
    assert _status(client, pm_headers, pid, "acceptance").status_code == 200
    assert _status(client, pm_headers, pid, "completed").status_code == 400
    _sign(client, pm_headers, pid)
    assert _status(client, pm_headers, pid, "completed").status_code == 200
    assert _status(client, pm_headers, pid, "archived", retrospective="补充当前范围签字后归档").status_code == 200


@pytest.mark.parametrize("stage", ["executing", "acceptance"])
def test_percentage_helpers_cannot_advance_or_regress_manual_stage(client, pm_headers, monkeypatch, stage):
    from app.services.status_flow import advance_project_status, regress_project_status
    pid = _project(client, pm_headers, stage)
    for percent in (0, 79.9, 80, 89.9, 90, 94.9, 95, 100):
        monkeypatch.setattr("app.services.progress.project_progress_tree", lambda *_: {"percent": percent})
        with SessionLocal() as db:
            p = db.get(Project, pid)
            for _ in range(3):
                assert advance_project_status(db, p) is None
                assert regress_project_status(db, p) is None
            assert p.status == stage
            db.commit()


@pytest.mark.parametrize("stage,target", [("executing", "preparing")])
def test_stage_requires_authorized_human_action_not_percentage(client, pm_headers, worker_headers, stage, target):
    pid = _project(client, pm_headers, stage)
    worker = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    with SessionLocal() as db:
        p = db.get(Project, pid); p.members = [worker]; db.commit()
    denied = _status(client, worker_headers, pid, target)
    assert denied.status_code == 403, denied.text
    _assert_status(pid, stage)
    allowed = _status(client, pm_headers, pid, target)
    assert allowed.status_code == 200, allowed.text
    _assert_status(pid, target)


@pytest.mark.parametrize("stage", ["executing", "acceptance"])
def test_manual_completion_round_trip_preserves_stage(client, pm_headers, stage):
    pid, tid = _completion_fixture(client, pm_headers, stage)
    path = f"/api/projects/{pid}/work-items/{tid}/completion"
    for completed in (False, True):
        version = client.get(f"/api/projects/{pid}/tasks/{tid}/workspace", headers=pm_headers).json()["task"]["version"]
        response = client.put(path, headers=pm_headers, json={"version": version, "is_completed": completed, "reason": "独立业务纠错验证"})
        assert response.status_code == 200, response.text
        _assert_status(pid, stage)


def test_generic_project_and_agent_tools_cannot_write_stage(client, pm_headers):
    from app.services.ai_tools import ALL_TOOL_MAP
    pid = _project(client, pm_headers, "executing")
    from tests.lifecycle_helpers import project_version
    response = client.put(f"/api/projects/{pid}", headers=pm_headers,
                          json={"status": "acceptance", "description": "普通资料更新",
                                "version": project_version(client, pm_headers, pid)})
    assert response.status_code == 200, response.text
    _assert_status(pid, "executing")
    assert not {"project_status", "change_status", "advance_project_status"} & set(ALL_TOOL_MAP)


@pytest.mark.parametrize("state", ["executing", "commissioning", "pilot", "acceptance", "completed", "archived", "suspended"])
def test_new_project_import_cannot_bypass_lifecycle_decisions(client, pm_headers, state):
    payload = {"type": "agvpm-project", "project": {
        "name": "导入必须保留人工决定", "start_date": "2026-09-01",
        "end_date": "2026-12-31", "status": state,
    }}
    preview = client.post("/api/projects/import/preview", headers=pm_headers, json=payload)
    assert preview.status_code == 200, preview.text
    assert not preview.json()["valid"] and preview.json()["errors"]
    result = client.post("/api/projects/import/json", headers=pm_headers, json=payload)
    assert result.status_code == 400, result.text
    with SessionLocal() as db:
        assert not db.query(Project).filter_by(name="导入必须保留人工决定").count()


@pytest.mark.parametrize("state", ["preparing", "ready"])
def test_allowed_preparation_import_still_requires_explicit_entry_decision(client, pm_headers, state):
    """A legacy ready payload is accepted and lands in preparation like any new project."""
    payload = {"type": "agvpm-project", "project": {
        "name": "导入待进场计划", "start_date": "2026-09-01",
        "end_date": "2026-12-31", "status": state,
    }}
    preview = client.post("/api/projects/import/preview", headers=pm_headers, json=payload)
    assert preview.status_code == 200 and preview.json()["valid"], preview.text
    result = client.post("/api/projects/import/json", headers=pm_headers, json=payload)
    assert result.status_code == 200, result.text
    pid = result.json()["id"]
    _assert_status(pid, "preparing")
    assert _status(client, pm_headers, pid, "executing").status_code == 400


def test_acceptance_can_be_recorded_early_but_cannot_complete_incomplete_work(client, pm_headers):
    pid = _project(client, pm_headers)
    rid = _sign(client, pm_headers, pid)
    with SessionLocal() as db:
        assert db.get(AcceptanceRecord, rid) is not None
        db.get(Project, pid).status = "acceptance"
        db.commit()
    blocked = _status(client, pm_headers, pid, "completed")
    assert blocked.status_code == 400, blocked.text


def test_stale_loaded_scope_does_not_survive_current_status_gate(client, pm_headers):
    from app.routers.projects import ProjectStatusChange, change_status
    pid, tid = _completion_fixture(client, pm_headers)
    _sign(client, pm_headers, pid)
    with SessionLocal() as stale:
        p = stale.get(Project, pid)
        actor = stale.get(User, p.manager)
        original_task = stale.get(Task, tid)
        with SessionLocal() as newer:
            newer.get(Task, tid).description = "新增加现场联动要求"
            newer.commit()
        assert original_task.description != "新增加现场联动要求"
        with pytest.raises(HTTPException) as error:
            change_status(pid, ProjectStatusChange(status="completed"), actor, p, stale)
        assert error.value.status_code == 400
        stale.rollback()
    _assert_status(pid, "acceptance")


def test_stale_actor_loses_stage_authority_after_grant_revocation(client, pm_headers, worker_headers):
    from app.routers.projects import ProjectStatusChange, change_status
    pid = _project(client, pm_headers, "executing")
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    with SessionLocal() as setup:
        p = setup.get(Project, pid)
        p.members = [wid]
        p.member_permissions = [{"user_id": wid, "capabilities": ["project.update"]}]
        setup.commit()
    with SessionLocal() as stale:
        p = stale.get(Project, pid)
        actor = stale.get(User, wid)
        with SessionLocal() as newer:
            newer.get(Project, pid).member_permissions = []
            newer.commit()
        with pytest.raises(HTTPException) as error:
            change_status(pid, ProjectStatusChange(status="preparing"), actor, p, stale)
        assert error.value.status_code == 403
        stale.rollback()
    _assert_status(pid, "executing")


def test_legacy_confirm_ready_is_retired_and_cannot_grant_dispatch_authority(client, pm_headers):
    from tests.test_dispatch_review_t29 import scope
    pid, _ = scope(client, pm_headers)
    path=f'/api/projects/{pid}/preparations/confirm-ready'
    for body in ({'conclusion':'普通备注'}, {'risk_entry':True,'conclusion':'明确接受旧准备风险'}):
        assert client.post(path,headers=pm_headers,json=body).status_code==410
    assert _status(client,pm_headers,pid,'executing').status_code==400
    assert _review(client,pm_headers,pid).status_code==200
    assert _status(client,pm_headers,pid,'executing').status_code==200


def test_explicit_member_stage_authority_is_honored(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers, "executing")
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    from tests.lifecycle_helpers import project_version
    response = client.put(f"/api/projects/{pid}", headers=pm_headers, json={
        "members": [wid], "member_permissions": [{"user_id": wid, "capabilities": ["project.update"]}],
        "version": project_version(client, pm_headers, pid),
    })
    assert response.status_code == 200, response.text
    allowed = _status(client, worker_headers, pid, "preparing")
    assert allowed.status_code == 200, allowed.text


def test_same_clock_acceptance_recordings_preserve_correction_order(client, pm_headers, monkeypatch):
    pid, _ = _completion_fixture(client, pm_headers)
    monkeypatch.setattr("app.services.acceptance.utcnow", lambda: datetime(2026, 10, 1, 9, 0))
    passed = _sign(client, pm_headers, pid)
    rejected = _sign(client, pm_headers, pid, "rejected")
    rows = client.get(f"/api/projects/{pid}/acceptance", headers=pm_headers).json()
    assert rows[0]["id"] == rejected and rows[1]["id"] == passed
    assert rows[0]["created_at"] > rows[1]["created_at"]
    assert _status(client, pm_headers, pid, "completed").status_code == 400


def test_same_clock_review_recordings_preserve_revocation_order(client, pm_headers, monkeypatch):
    pid = _project(client, pm_headers)
    _preparation(client, pm_headers, pid)
    monkeypatch.setattr("app.services.dispatch_review.utcnow", lambda: datetime(2026, 10, 1, 9, 0))
    assert _review(client, pm_headers, pid).status_code == 200
    assert _review(client, pm_headers, pid, "not_ready", "当前风险不可接受").status_code == 200
    rows = client.get(f"/api/projects/{pid}/documents/dispatch-review/history", headers=pm_headers).json()
    assert [row["conclusion"] for row in rows] == ["not_ready", "risky"]
    assert rows[0]["reviewed_at"] > rows[1]["reviewed_at"]
    assert _status(client, pm_headers, pid, "executing").status_code == 400


@pytest.mark.parametrize("tz,day,expected", [
    ("Asia/Shanghai", "2026-10-02", 200),
    ("America/Los_Angeles", "2026-10-02", 400),
    ("America/Los_Angeles", "2026-10-01", 200),
])
def test_new_acceptance_date_uses_project_local_today(client, pm_headers, monkeypatch, tz, day, expected):
    instant = datetime(2026, 10, 2, 0, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("app.time_utils.now_in", lambda zone: instant.astimezone(ZoneInfo(zone)))
    pid = _project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, pid).timezone = tz
        db.commit()
    response = client.post(f"/api/projects/{pid}/acceptance", headers=pm_headers, json={
        "accepted_by_name": "甲方验收负责人", "accepted_at": day, "conclusion": "accepted",
    })
    assert response.status_code == expected, response.text
    with SessionLocal() as db:
        assert db.query(AcceptanceRecord).filter_by(project_id=pid).count() == (1 if expected == 200 else 0)


@pytest.mark.parametrize("current,future,expected", [
    ("rejected", "accepted", 400), (None, "accepted", 400),
    ("accepted", "rejected", 200),
])
def test_legacy_future_record_is_visible_but_cannot_supply_current_decision(client, pm_headers, monkeypatch, current, future, expected):
    pid, _ = _completion_fixture(client, pm_headers)
    monkeypatch.setattr("app.time_utils.project_today", lambda _: date(2026, 10, 2))
    future_id = _sign(client, pm_headers, pid, future)
    with SessionLocal() as db:
        db.get(AcceptanceRecord, future_id).accepted_at = date(2026, 10, 3)
        db.commit()
    current_id = _sign(client, pm_headers, pid, current, "2026-10-02") if current else None
    rows = client.get(f"/api/projects/{pid}/acceptance", headers=pm_headers).json()
    old = next(row for row in rows if row["id"] == future_id)
    assert not old["is_effective"] and not old["effective_date_reached"] and old["invalid_reason"]
    assert [row["id"] for row in rows if row["is_effective"]] == ([current_id] if current else [])
    summary = client.get(f"/api/projects/{pid}", headers=pm_headers).json()["acceptance_summary"]
    assert summary["pending_future_count"] == 1 and summary["warning"]
    assert summary["eligible"] is (expected == 200)
    result = _status(client, pm_headers, pid, "completed")
    assert result.status_code == expected, result.text


def test_agent_token_cannot_be_used_as_a_human_status_session(client, pm_headers, admin_headers):
    from tests.test_agent_api import token, call
    pid = _project(client, pm_headers, "executing")
    _, agent_headers = token(client, admin_headers, scopes=["projects:read"])
    assert call(client, agent_headers, "project_get", project_id=pid).json()["ok"]
    response = _status(client, agent_headers, pid, "commissioning")
    assert response.status_code == 401, response.text
    denied = call(client, agent_headers, "change_set_propose", project_id=pid,
                  title="试图绕过人工阶段决定", description="独立负向边界测试",
                  changes={"status": "commissioning"})
    assert denied.status_code == 404, denied.text
    _assert_status(pid, "executing")


@pytest.mark.parametrize("stage", ["preparing", "archived"])
def test_real_startup_preserves_stage_and_does_not_unlock_archived_edits(client, pm_headers, worker_headers, monkeypatch, stage):
    from app.db import init_db
    pid = _project(client, pm_headers, stage)
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.members = [wid]
        p.member_permissions = [{"user_id": wid, "capabilities": ["project.update"]}]
        db.commit()
    for _ in range(2):
        init_db()
        project = client.get(f"/api/projects/{pid}", headers=worker_headers)
        assert project.status_code == 200, project.text
        assert project.json()["status"] == stage
        assert "project.update" in project.json()["capabilities"]
        changed = client.put(f"/api/projects/{pid}", headers=worker_headers,
                             json={"description": "重启后合法权限仍然有效", "version": project.json()["version"]})
        assert changed.status_code == (400 if stage == "archived" else 200), changed.text
    if stage == "archived":
        assert _status(client, worker_headers, pid, "completed").status_code == 200
        assert _status(client, worker_headers, pid, "acceptance").status_code == 200
