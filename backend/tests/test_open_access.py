"""所有账号都能看、都能记录所有项目（OPEN_PROJECT_ACCESS 默认开）。"""
from app.db import SessionLocal
from app.models import ChangeLog, Project, User
from tests.test_field_week_t33 import operation, save, weekly_work


def _project(client, headers, name="全员可见项目"):
    response = client.post("/api/projects", headers=headers, json={"name": name, "start_date": "2026-11-01", "end_date": "2027-01-31"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_every_account_sees_every_project_and_new_accounts_join_existing_ones(client, admin_headers, pm_headers, worker_headers):
    pid = _project(client, pm_headers)
    # The worker was never added, yet sees and opens the project.
    assert client.get(f"/api/projects/{pid}", headers=worker_headers).status_code == 200
    assert pid in [row["id"] for row in client.get("/api/projects", headers=worker_headers).json()]
    with SessionLocal() as db:
        active = {row.id for row in db.query(User).filter(User.is_active.is_(True))}
        assert active <= set(db.get(Project, pid).members)
    made = client.post("/api/users", headers=admin_headers, json={"display_name": "新来的工程师", "password": "Sandbox-New-2026!", "role": "worker"})
    assert made.status_code == 200, made.text
    with SessionLocal() as db:
        assert made.json()["id"] in db.get(Project, pid).members
        assert db.query(ChangeLog).filter_by(entity_type="user", entity_id=made.json()["id"]).filter(ChangeLog.detail.like("%加入%个项目%")).count() == 1


def test_published_week_work_is_recorded_by_whoever_did_it_without_claiming(client, pm_headers, worker_headers):
    pid, _units, people, task, cell = weekly_work(client, pm_headers)
    view = client.get("/api/worker/week", headers=worker_headers).json()
    assert [row["id"] for row in view["plans"]] == [cell["id"]] and not view["unassigned"] and not view["assistable"]
    result = save(client, worker_headers, operation(pid, task["id"], kind="work", step_key="", weekly_cell_id=cell["id"]))
    assert result.status_code == 200, result.text
    assert client.get(f"/api/projects/{pid}/weekly-plans", headers=pm_headers, params={"week_start": cell["week_start"], "weeks": 1}).json()["cells"][0]["assignee_ids"] == []


def test_anyone_starts_and_resolves_an_issue_but_only_the_reporter_or_manager_closes_it(client, pm_headers, worker_headers):
    pid = _project(client, pm_headers, "问题全员处理")
    with SessionLocal() as db:
        db.get(Project, pid).status = "executing"; db.commit()
    issue = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={"title": "叉臂异响"}).json()
    started = client.put(f"/api/issues/{issue['id']}", headers=worker_headers, json={"status": "processing", "version": issue["version"]})
    assert started.status_code == 200, started.text
    assert started.json()["assignee_name"]  # whoever starts becomes the handler
    resolved = client.put(f"/api/issues/{issue['id']}", headers=worker_headers, json={"status": "resolved", "resolution": "紧固后复测正常", "version": started.json()["version"]})
    assert resolved.status_code == 200, resolved.text
    assert client.put(f"/api/issues/{issue['id']}", headers=worker_headers, json={"status": "closed", "version": resolved.json()["version"]}).status_code == 403
    listed = client.get("/api/dashboard/issues", headers=worker_headers, params={"include_closed": True}).json()["items"]
    assert issue["id"] in [row["id"] for row in listed]


def test_startup_reconcile_fills_old_projects_once_and_never_removes(client, pm_headers, monkeypatch):
    from app import config
    from app.services.open_access import reconcile
    monkeypatch.setattr(config, "OPEN_PROJECT_ACCESS", False)
    pid = _project(client, pm_headers, "旧项目")
    with SessionLocal() as db:
        before = set(db.get(Project, pid).members or [])
        everyone = {row.id for row in db.query(User).filter(User.is_active.is_(True))}
        assert not everyone <= before
    monkeypatch.setattr(config, "OPEN_PROJECT_ACCESS", True)
    with SessionLocal() as db:
        assert reconcile(db) >= 1
        db.commit()
        members = set(db.get(Project, pid).members)
        assert everyone <= members and before <= members
        assert db.query(ChangeLog).filter_by(project_id=pid).filter(ChangeLog.detail.like("所有账号可见所有项目%")).count() == 1
        assert reconcile(db) == 0
