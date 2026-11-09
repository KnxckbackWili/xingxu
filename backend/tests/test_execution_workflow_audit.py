"""Regression coverage for execution authorization and quality follow-up."""
from datetime import date
import pytest


def _execution(client, *, manager='user-pm-001', status='executing'):
    from app.db import SessionLocal
    from app.models import Project, Phase, Task, CheckItem
    with SessionLocal() as db:
        p = Project(name='执行回归', manager=manager,
                    status=status, start_date=date.today(), end_date=date.today())
        db.add(p); db.flush()
        phase = Phase(project_id=p.id, name='现场实施'); db.add(phase); db.flush()
        task = Task(project_id=p.id, phase_id=phase.id, name='调试', quantity_type='fixed')
        db.add(task); db.flush()
        ci = CheckItem(project_id=p.id, task_id=task.id, name='普通检查')
        db.add(ci); db.commit()
        return p.id, task.id, ci.id


def test_worker_can_mark_non_safety_check_not_applicable(client, worker_headers):
    pid, _, cid = _execution(client)
    response = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=worker_headers,
                          json={'is_applicable': False, 'not_applicable_reason': '现场无此配置', 'version': 0})
    assert response.status_code == 200, response.text
    from app.db import SessionLocal
    from app.models import CheckItem
    with SessionLocal() as db:
        ci = db.get(CheckItem, cid)
        assert ci.is_applicable is False and ci.not_applicable_set_by == 'user-worker-001'


def test_archived_check_cannot_be_changed(client, worker_headers):
    pid, _, cid = _execution(client, status='archived')
    response = client.put(f'/api/projects/{pid}/check-items/{cid}', headers=worker_headers, json={'failed': True, 'failed_reason': '归档后修改', 'version': 0})
    assert response.status_code == 400, response.text
    assert '版本' not in response.json()['detail']


def test_worker_na_requires_reason_and_rejects_safety_check(client, worker_headers):
    pid, _, cid = _execution(client)
    url = f'/api/projects/{pid}/check-items/{cid}'
    missing = client.put(url, headers=worker_headers, json={'is_applicable': False, 'version': 0})
    assert missing.status_code == 400 and '原因' in missing.json()['detail'], missing.text
    from app.db import SessionLocal
    from app.models import CheckItem
    with SessionLocal() as db:
        db.get(CheckItem, cid).is_safety_critical = True; db.commit()
    safety = client.put(url, headers=worker_headers, json={'is_applicable': False, 'not_applicable_reason': '不可跳过', 'version': 0})
    assert safety.status_code == 400 and '版本' not in safety.json()['detail'], safety.text


