"""Explicit technical-duty removal preserves membership, grants and work history."""

from tests.lifecycle_helpers import versioned
from datetime import date

import pytest


def _project(client, pm_headers, technical_id):
    response = client.post('/api/projects', headers=pm_headers, json={
        'name': '技术负责人清空回归', 'start_date': '2026-09-01', 'end_date': '2026-10-31',
        'technical_manager_id': technical_id,
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


@pytest.mark.parametrize('editor_fixture', ['pm_headers', 'admin_headers'])
def test_explicit_clear_preserves_member_grants_and_assigned_history(
    client, pm_headers, worker_headers, editor_fixture, request,
):
    from app.db import SessionLocal
    from app.models import DailyProgress, Module, Phase, ProjectMember, ScheduleEntry, Task
    from app.services.permissions import C_EXPORT, C_PLAN

    editor_headers = request.getfixturevalue(editor_fixture)
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    pid = _project(client, pm_headers, uid)
    granted = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {
        'member_permissions': [{'user_id': uid, 'capabilities': [C_EXPORT]}],
    }))
    assert granted.status_code == 200, granted.text
    before = client.get(f'/api/projects/{pid}', headers=worker_headers).json()
    assert C_PLAN in before['capabilities']

    # An unrelated update must not interpret the omitted field as a clear.
    omitted = client.put(f'/api/projects/{pid}', headers=editor_headers, json=versioned(pid, {'description': '只更新说明'}))
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()['technical_manager'] == uid
    with SessionLocal() as db:
        phase = Phase(project_id=pid, name='实施'); db.add(phase); db.flush()
        module = Module(project_id=pid, phase_id=phase.id, name='调试'); db.add(module); db.flush()
        task = Task(project_id=pid, module_id=module.id, name='已有任务', target_quantity=2); db.add(task); db.flush()
        entry = ScheduleEntry(project_id=pid, task_id=task.id, work_date=date(2026, 10, 5),
                              assignee_id=uid, planned_quantity=2, is_confirmed=True)
        db.add(entry); db.flush()
        report = DailyProgress(project_id=pid, task_id=task.id, schedule_entry_id=entry.id,
                               user_id=uid, work_date=date(2026, 10, 5), completed_quantity=1,
                               client_uuid='technical-clear-history')
        db.add(report); db.flush()
        task_id, entry_id, report_id = task.id, entry.id, report.id
        db.commit()

    cleared = client.put(f'/api/projects/{pid}', headers=editor_headers, json={
        'technical_manager_id': None, 'version': omitted.json()['version'],
    })
    assert cleared.status_code == 200, cleared.text
    # A fresh GET is the persisted state, rather than trusting only the PUT response.
    detail = client.get(f'/api/projects/{pid}', headers=worker_headers)
    assert detail.status_code == 200
    assert detail.json()['technical_manager'] is None
    assert detail.json()['technical_manager_name'] == ''
    assert uid in detail.json()['members']
    assert detail.json()['capabilities'] == [C_EXPORT]
    assert detail.json()['member_permissions'] == [{'user_id': uid, 'capabilities': [C_EXPORT]}]
    assert client.post(f'/api/projects/{pid}/tasks/generate', headers=worker_headers,
                       json={'module_ids': ['mod-01']}).status_code == 403
    with SessionLocal() as db:
        assert db.query(ProjectMember).filter_by(project_id=pid, user_id=uid).count() == 1
        assert db.get(Task, task_id).target_quantity == 2
        assert db.get(ScheduleEntry, entry_id).assignee_id == uid
        assert db.get(DailyProgress, report_id).completed_quantity == 1


@pytest.mark.parametrize('co_manager', [False, True])
def test_technical_member_or_co_manager_cannot_clear_formal_duty(client, pm_headers, worker_headers, co_manager):
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    pid = _project(client, pm_headers, uid)
    if co_manager:
        grant = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {
            'co_managers': [{'user_id': uid, 'expires_at': '2099-12-31'}],
        }))
        assert grant.status_code == 200, grant.text
        assert client.put(f'/api/projects/{pid}', headers=worker_headers,
                          json=versioned(pid, {'description': '协管可更新普通说明'})).status_code == 200
    denied = client.put(f'/api/projects/{pid}', headers=worker_headers, json=versioned(pid, {'technical_manager_id': None}))
    assert denied.status_code == 403
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['technical_manager'] == uid


@pytest.mark.parametrize('replacement', ['missing-user', 'user-admin-001'])
def test_invalid_replacement_does_not_clear_existing_duty(client, pm_headers, worker_headers, replacement):
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    pid = _project(client, pm_headers, uid)
    rejected = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'technical_manager_id': replacement}))
    assert rejected.status_code == 400, rejected.text
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['technical_manager'] == uid


def test_stale_clear_does_not_overwrite_a_new_assignment(client, pm_headers, worker_headers, tech_headers):
    uid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    tech_id = client.get('/api/auth/me', headers=tech_headers).json()['id']
    pid = _project(client, pm_headers, uid)
    old = client.get(f'/api/projects/{pid}', headers=pm_headers).json()
    assigned = client.put(f'/api/projects/{pid}', headers=pm_headers, json={
        'technical_manager_id': tech_id, 'version': old['version'],
    })
    assert assigned.status_code == 200, assigned.text
    rejected = client.put(f'/api/projects/{pid}', headers=pm_headers, json={
        'technical_manager_id': None, 'version': old['version'],
    })
    assert rejected.status_code == 409
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['technical_manager'] == tech_id
