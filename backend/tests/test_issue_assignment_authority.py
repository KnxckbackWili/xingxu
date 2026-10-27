"""问题处理人资格与项目访问范围。"""

from tests.lifecycle_helpers import versioned
import pytest
from app.db import SessionLocal
from app.models import Issue, Project
from tests.test_execution_workflow_audit import _execution


@pytest.mark.parametrize('operation', ['create', 'import', 'assign'])
def test_issue_cannot_be_assigned_to_person_without_project_access(client, pm_headers, operation):
    pid, _, _ = _execution(client)
    payload = {'title': '不能派给项目外人员', 'assignee_id': 'user-worker-002'}
    if operation == 'create':
        result = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json=payload)
    elif operation == 'import':
        result = client.post(f'/api/projects/{pid}/issues/import', headers=pm_headers, json={'items': [payload]})
    else:
        issue = client.post(f'/api/projects/{pid}/issues', headers=pm_headers, json={'title': '待分配'}).json()
        result = client.put(f"/api/issues/{issue['id']}", headers=pm_headers,
                            json={'assignee_id': 'user-worker-002', 'version': issue['version']})
    assert result.status_code == 400, result.text
    with SessionLocal() as db:
        assert not db.query(Issue).filter_by(project_id=pid, assignee_id='user-worker-002').first()


def test_issue_candidates_match_actual_process_permissions(client, pm_headers, worker_headers):
    from app.models import ProjectMember
    pid, _, _ = _execution(client)
    candidates = client.get(f'/api/projects/{pid}/issue-assignees', headers=pm_headers)
    assert candidates.status_code == 200, candidates.text
    ids = {row['id'] for row in candidates.json()}
    assert ids == {'user-admin-001', 'user-pm-001', 'user-worker-001'}
    # A PM who is merely a project member can handle their own assigned issue,
    # without gaining permission to change its title or reassign another person.
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.manager = 'user-admin-001'
        p.members = [*p.members, 'user-pm-001']
        db.commit()
    issue = client.post(f'/api/projects/{pid}/issues', headers=worker_headers,
                        json={'title': '待处理', 'assignee_id': 'user-pm-001'}).json()
    started = client.put(f"/api/issues/{issue['id']}", headers=pm_headers, json=versioned(issue['id'], {'status': 'processing'}, 'Issue'))
    assert started.status_code == 200, started.text
    assert client.put(f"/api/issues/{issue['id']}", headers=pm_headers, json=versioned(issue['id'], {'title': 'unauthorized'}, 'Issue')).status_code == 403
