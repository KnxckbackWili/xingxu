"""Regression coverage for issue assignment and transaction recovery."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def setup_issue(client, headers, **fields):
    p = client.post('/api/projects', headers=headers, json={
        'name': '流程审查', 'start_date': '2026-09-15', 'end_date': '2026-10-15',
    })
    assert p.status_code == 200, p.text
    pid = p.json()['id']
    r = client.post(f'/api/projects/{pid}/issues', headers=headers,
                    json={'title': '故障记录', **fields})
    assert r.status_code == 200, r.text
    return pid, r.json()


def test_clear_assignee_and_preserve_omitted_field(client, pm_headers):
    uid = client.get('/api/auth/me', headers=pm_headers).json()['id']
    pid, issue = setup_issue(client, pm_headers, assignee_id=uid)
    r = client.put(f"/api/issues/{issue['id']}", headers=pm_headers,
                   json={'description': '补充描述', 'version': issue['version']})
    assert r.json()['assignee_id'] == uid
    r = client.put(f"/api/issues/{issue['id']}", headers=pm_headers,
                   json={'assignee_id': None, 'version': r.json()['version']})
    assert r.status_code == 200, r.text
    assert r.json()['assignee_id'] is None
    assert client.get(f'/api/projects/{pid}/issues', headers=pm_headers).json()[0]['assignee_id'] is None
    stale = client.put(f"/api/issues/{issue['id']}", headers=pm_headers,
                       json={'assignee_id': uid, 'version': issue['version']})
    assert stale.status_code == 409


def test_import_recovers_from_flush_conflict(client, pm_headers, monkeypatch):
    from app.models import Issue
    pid, _ = setup_issue(client, pm_headers)
    original = Session.flush
    conflicts = []

    def flush_once(self, *args, **kwargs):
        if not conflicts and any(isinstance(row, Issue) and row.client_uuid == 'review-import-001' for row in self.new):
            conflicts.append(True)
            raise IntegrityError('INSERT', {}, Exception('simulated concurrent insert'))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Session, 'flush', flush_once)
    r = client.post(f'/api/projects/{pid}/issues/import', headers=pm_headers,
                    json={'items': [{'title': '导入问题', 'client_uuid': 'review-import-001'}]})
    assert r.status_code == 200, r.text
    assert r.json()['count'] == 1
    assert conflicts == [True]
    again = client.post(f'/api/projects/{pid}/issues/import', headers=pm_headers,
                        json={'items': [{'title': '导入问题', 'client_uuid': 'review-import-001'}]})
    assert again.json()['count'] == 0
    rows = client.get(f'/api/projects/{pid}/issues', headers=pm_headers).json()
    assert len([row for row in rows if row['title'] == '导入问题']) == 1
