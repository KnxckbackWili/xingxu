"""Lifecycle callers get the complete current evidence failures in one read."""
from dataclasses import asdict

from app.db import SessionLocal
from app.models import AcceptanceRecord, ArchiveChecklist, CheckItem, DailyProgress, Issue, Project, Task, ProjectDocument
from app.services.lifecycle_gates import check_transition
from tests.test_lifecycle_write_integrity import completeable_project


def test_completion_returns_all_blockers_without_changing_project(client, pm_headers):
    pid, tid, cid = completeable_project(client, pm_headers, documents_data=[
        {"name": f"必需资料{number}", "required": True, "done": False} for number in range(7)
    ])
    with SessionLocal() as db:
        db.query(DailyProgress).filter_by(project_id=pid).delete()
        db.query(AcceptanceRecord).filter_by(project_id=pid).delete()
        db.get(CheckItem, cid).is_done = False
        db.add(Issue(project_id=pid, title="未解决故障", reporter_id=db.get(Project, pid).manager))
        db.commit()
        project = db.get(Project, pid)
        version = project.version
        failures = check_transition(db, project, "completed")
        assert {item.type for item in failures} == {"progress", "tasks", "documents", "issues", "acceptance"}
        assert all(item.message and item.url.startswith(f"/pm/projects/{pid}/") for item in failures)
        assert "必需资料6" in next(item.message for item in failures if item.type == "documents")
        assert project.status == "acceptance" and project.version == version
        assert not db.dirty

    response = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "completed"})
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["blockers"] == [asdict(item) for item in failures]
    assert all(item.message in detail["message"] for item in failures)
    with SessionLocal() as db:
        assert db.get(Project, pid).status == "acceptance"
        assert db.get(Project, pid).version == version


def test_archive_lists_retrospective_and_evidence_together_and_rolls_back_rejected_draft(client, pm_headers):
    pid, tid, _ = completeable_project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, pid).status = "completed"
        db.query(ProjectDocument).filter_by(project_id=pid).update({"status": "pending", "waived_reason": ""})
        db.query(AcceptanceRecord).filter_by(project_id=pid).delete()
        db.commit()
        assert {item.type for item in check_transition(db, db.get(Project, pid), "archived")} == {
            "documents", "acceptance", "retrospective"
        }
    response = client.post(f"/api/projects/{pid}/status", headers=pm_headers,
                           json={"status": "archived", "retrospective": "暂存的复盘"})
    assert response.status_code == 400, response.text
    assert {item["type"] for item in response.json()["detail"]["blockers"]} == {"documents", "acceptance"}
    with SessionLocal() as db:
        project = db.get(Project, pid)
        assert project.status == "completed" and not project.retrospective


def test_complete_and_archive_allowed_with_current_evidence(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers)
    with SessionLocal() as db:
        assert check_transition(db, db.get(Project, pid), "completed") == []
    path = f"/api/projects/{pid}/status"
    assert client.post(path, headers=pm_headers, json={"status": "completed"}).status_code == 200
    response = client.post(path, headers=pm_headers, json={"status": "archived", "retrospective": "按计划交付"})
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        assert db.get(Project, pid).retrospective["content"] == "按计划交付"


def test_unarchiving_keeps_historical_restoration_exception(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers)
    with SessionLocal() as db:
        project = db.get(Project, pid)
        project.status = "archived"
        db.query(AcceptanceRecord).filter_by(project_id=pid).delete()
        db.query(DailyProgress).filter_by(project_id=pid).delete()
        db.commit()
        assert check_transition(db, project, "completed") == []
    response = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "completed"})
    assert response.status_code == 200, response.text
