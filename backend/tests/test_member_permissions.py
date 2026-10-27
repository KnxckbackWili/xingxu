"""Explicit project grants preserve membership scope and global roles."""
import pytest
from tests.test_permissions import _project, _user, _login

WORKER = "user-worker-001"


def grant(client, headers, pid, caps):
    return client.put(f"/api/projects/{pid}", headers=headers, json={
        "member_permissions": [{"user_id": WORKER, "capabilities": caps}],
    })


def member_project(client, pm_headers):
    pid = _project(client, pm_headers, "成员授权")
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": [WORKER]}).status_code == 200
    return pid


def test_scoped_grant_enforced_and_revoked(client, pm_headers, worker_headers, admin_headers):
    pid = member_project(client, pm_headers)
    other = _project(client, pm_headers, "不能跨项目")
    path = f"/api/projects/{pid}"
    assert client.put(path, headers=worker_headers, json={"description": "before"}).status_code == 403
    assert grant(client, pm_headers, pid, ["project.update"]).status_code == 200
    detail = client.get(path, headers=worker_headers).json()
    assert detail["capabilities"] == ["project.update"]
    assert detail["grantable_capabilities"] == []
    assert client.put(path, headers=worker_headers, json={"description": "after"}).status_code == 200
    assert client.get(f"/api/projects/{other}", headers=worker_headers).status_code == 404
    assert client.post(f"{path}/tasks/generate", headers=worker_headers, json={"module_ids": ["mod-01"]}).status_code == 403
    assert client.get("/api/auth/me", headers=worker_headers).json()["role"] == "worker"
    assert grant(client, pm_headers, pid, []).status_code == 200
    assert client.put(path, headers=worker_headers, json={"description": "revoked"}).status_code == 403


@pytest.mark.parametrize("cap", ["project.delete", "project.read", "system.admin", "users.manage", "unknown"])
def test_only_bounded_capabilities(client, pm_headers, cap):
    pid = member_project(client, pm_headers)
    assert grant(client, pm_headers, pid, [cap]).status_code == 403
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["member_permissions"] == []


def test_no_redelegation_or_global_promotion(client, pm_headers, worker_headers):
    pid = member_project(client, pm_headers)
    assert grant(client, pm_headers, pid, ["project.manage_members", "project.update"]).status_code == 200
    assert grant(client, worker_headers, pid, ["project.manage_plan"]).status_code == 403
    for payload in ({"co_managers": []}, {"technical_manager_id": WORKER}, {"manager_id": WORKER}):
        assert client.put(f"/api/projects/{pid}", headers=worker_headers, json=payload).status_code == 403
    assert client.put(f"/api/projects/{pid}", headers=worker_headers, json={"members": [WORKER]}).status_code == 200


def test_targets_require_membership_and_removal_revokes(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers, "移除授权")
    assert grant(client, pm_headers, pid, ["project.update"]).status_code == 400
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": [WORKER], "member_permissions": [{"user_id": WORKER, "capabilities": ["project.update"]}]}).status_code == 200
    assert client.get(f'/api/projects/{pid}/members/removal-preview',headers=pm_headers,params={'removed_ids':WORKER}).status_code==200
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": [],'member_removal_confirmations':[WORKER]}).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=worker_headers).status_code == 404
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": [WORKER]}).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=worker_headers).json()["capabilities"] == []


def test_directory_is_project_scoped_and_version_only_denied(client, pm_headers, worker_headers, admin_headers):
    unrelated = _user(client, admin_headers, "unrelated", "worker")
    pid = member_project(client, pm_headers)
    path = f"/api/projects/{pid}"
    assert unrelated not in {row["id"] for row in client.get(path + "/people", headers=worker_headers).json()}
    assert client.get(path + "/people?include_candidates=true", headers=worker_headers).status_code == 403
    assert client.put(path, headers=worker_headers, json={"version": 1}).status_code == 400
    assert grant(client, pm_headers, pid, ["project.manage_members"]).status_code == 200
    assert unrelated in {row["id"] for row in client.get(path + "/people?include_candidates=true", headers=worker_headers).json()}


def test_grants_do_not_unlock_archived_writes(client, pm_headers, worker_headers):
    pid = member_project(client, pm_headers)
    assert grant(client, pm_headers, pid, ["project.manage_plan", "project.manage_inventory", "project.archive", "project.export"]).status_code == 200
    from app.db import SessionLocal
    from app.models import Project
    with SessionLocal() as db:
        db.get(Project, pid).status = "archived"
        db.commit()
    assert client.post(f"/api/projects/{pid}/procurements", headers=worker_headers, json={"name": "late"}).status_code == 400
    assert client.post(f"/api/projects/{pid}/tasks/generate", headers=worker_headers, json={"module_ids": ["mod-01"]}).status_code == 400
    assert client.post(f"/api/projects/{pid}/documents/files", headers=worker_headers, files={"file": ("late.txt", b"x", "text/plain")}).status_code == 400
    assert client.get(f"/api/projects/{pid}/export/excel", headers=worker_headers).status_code == 200


def test_nonowner_pm_cannot_grant_but_admin_can(client, pm_headers, admin_headers):
    outsider = _user(client, admin_headers, "other-pm", "pm")
    headers = _login(client, "other-pm")
    pid = member_project(client, pm_headers)
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": [WORKER, outsider]}).status_code == 200
    assert client.get(f"/api/projects/{pid}", headers=headers).status_code == 200
    assert grant(client, headers, pid, ["project.update"]).status_code == 403
    assert grant(client, admin_headers, pid, ["project.manage_plan"]).status_code == 200


def test_granted_plan_operations_and_clone_boundary(client, pm_headers, worker_headers):
    pid = member_project(client, pm_headers)
    assert grant(client, pm_headers, pid, ["project.manage_plan", "project.update"]).status_code == 200
    assert client.post(f"/api/projects/{pid}/procurements", headers=worker_headers, json={"name": "授权准备项"}).status_code == 200
    assert client.post(f"/api/projects/{pid}/clone", headers=worker_headers, json={}).status_code == 403
    from app.db import SessionLocal
    from app.models import Project
    with SessionLocal() as db:
        db.get(Project, pid).status = "archived"
        db.commit()
    cloned = client.post(f"/api/projects/{pid}/clone", headers=pm_headers, json={"name": "归档来源克隆"})
    assert cloned.status_code == 200, cloned.text


def test_archive_grant_does_not_grant_material_requirement_or_review_management(client, pm_headers, worker_headers):
    from tests.document_helpers import documents, upload_documents
    pid = member_project(client, pm_headers)
    assert grant(client, pm_headers, pid, ['project.archive']).status_code == 200
    row = documents(client, worker_headers, pid)['documents'][0]
    body = {'stage_key': '6', 'code': '6.99', 'name': '越权要求', 'scope': 'project', 'timing_type': 'on_demand'}
    assert client.post(f'/api/projects/{pid}/documents/requirements', headers=worker_headers, json=body).status_code == 403
    version = upload_documents(client, pm_headers, pid, [row['id']])['documents'][0]['versions'][0]
    assert client.post(f'/api/projects/{pid}/documents/{row["id"]}/versions/{version["id"]}/review', headers=worker_headers, json={'decision': 'approved'}).status_code == 403
    assert client.post(f'/api/projects/{pid}/status', headers=worker_headers, json={'status': 'preparing'}).status_code == 403


def test_explicit_plan_grant_allows_task_completion_and_revoke(client, pm_headers, worker_headers):
    from tests.test_manual_complete import _setup_active, _first_task
    pid = _setup_active(client, pm_headers)
    task = _first_task(client, pm_headers, pid)
    assert client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": [WORKER]}).status_code == 200
    assert grant(client, pm_headers, pid, ["project.manage_plan"]).status_code == 200
    response = client.post(f"/api/worker/tasks/{task['id']}/complete", headers=worker_headers, json={"reason": "授权完成"})
    assert response.status_code == 200, response.text
    assert grant(client, pm_headers, pid, []).status_code == 200
    assert client.post(f"/api/worker/tasks/{task['id']}/reopen", headers=worker_headers, json={}).status_code == 403
