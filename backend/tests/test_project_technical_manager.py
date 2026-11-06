"""Explicit technical-duty removal preserves membership, grants and work history."""

from tests.lifecycle_helpers import versioned
from datetime import date

import pytest
from tests.template_work import default_work


def _project(client, pm_headers, technical_id):
    response = client.post('/api/projects', headers=pm_headers, json={
        'name': '技术负责人清空回归', 'start_date': '2026-09-01', 'end_date': '2026-10-31',
        'technical_manager_id': technical_id,
    })
    assert response.status_code == 200, response.text
    return response.json()['id']


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
