import pytest
"""System grants affect real feature routes without changing resource ownership."""
from tests.lifecycle_helpers import versioned
from tests.test_permissions import _project

WORKER = 'user-worker-001'

def policy(client, admin, uid, changes):
    old = client.get(f'/api/permissions/users/{uid}', headers=admin)
    assert old.status_code == 200, old.text
    current = old.json()
    result = client.put(f'/api/permissions/users/{uid}', headers=admin,
                        json={'version': current['version'], 'overrides': {**current['overrides'], **changes}})
    assert result.status_code == 200, result.text
    return result.json()


def test_grant_and_revoke_template_edit_on_same_worker_session(client, admin_headers, worker_headers):
    assert client.post('/api/templates', headers=worker_headers, json={'name': 'denied'}).status_code == 403
    policy(client, admin_headers, WORKER, {'system.templates.manage': True})
    assert client.post('/api/templates', headers=worker_headers, json={'name': 'delegated'}).status_code == 200
    assert client.get('/api/auth/me', headers=worker_headers).json()['role'] == 'worker'
    policy(client, admin_headers, WORKER, {'system.templates.manage': False})
    assert client.post('/api/templates', headers=worker_headers, json={'name': 'revoked'}).status_code == 403


def test_vehicle_read_grant_is_read_only_and_dictionary_stays_available(client, admin_headers, worker_headers):
    policy(client, admin_headers, WORKER, {'system.vehicle_types.view': True})
    assert client.get('/api/vehicle-types/all', headers=worker_headers).status_code == 200
    assert client.post('/api/vehicle-types', headers=worker_headers, json={'name': 'not-authorized'}).status_code == 403
    policy(client, admin_headers, WORKER, {'system.vehicle_types.view': False})
    assert client.get('/api/vehicle-types/all', headers=worker_headers).status_code == 403
    assert client.get('/api/vehicle-types', headers=worker_headers).status_code == 200


def test_account_maintainer_cannot_promote_or_touch_admin(client, admin_headers, worker_headers):
    policy(client, admin_headers, WORKER, {'system.users.manage': True})
    rows = client.get('/api/users', headers=worker_headers)
    assert rows.status_code == 200
    admin_id = next(u['id'] for u in rows.json() if u['username'] == 'admin')
    assert client.put(f'/api/users/{WORKER}', headers=worker_headers, json={'role': 'admin'}).status_code == 403
    assert client.put(f'/api/users/{WORKER}', headers=worker_headers, json={'role': 'director'}).status_code == 403
    assert client.put(f'/api/users/{admin_id}', headers=worker_headers, json={'display_name': 'protected'}).status_code == 403
    assert client.put(f'/api/users/{WORKER}', headers=worker_headers, json={'display_name': 'delegated-profile'}).status_code == 200
    assert client.get('/api/auth/me', headers=worker_headers).json()['role'] == 'worker'








def test_delegated_token_manager_can_only_mint_for_self_and_revoke_access(client, admin_headers, worker_headers):
    policy(client, admin_headers, WORKER, {'system.agent_tokens.manage': True})
    admin_id = client.get('/api/auth/me', headers=admin_headers).json()['id']
    assert client.post('/api/ai/internal/tokens', headers=worker_headers, json={'name': 'forged', 'user_id': admin_id}).status_code == 403
    created = client.post('/api/ai/internal/tokens', headers=worker_headers, json={'name': 'own', 'user_id': WORKER})
    assert created.status_code == 200, created.text
    bearer = {'Authorization': 'Bearer ' + created.json()['token']}
    assert client.get('/api/agent/tools', headers=bearer).status_code == 200
    policy(client, admin_headers, WORKER, {'system.agent.use': False})
    assert client.get('/api/agent/tools', headers=bearer).status_code == 403


def test_basic_login_survives_message_and_history_denial(client, admin_headers, worker_headers):
    policy(client, admin_headers, WORKER, {'personal.messages.use': False, 'personal.records.read': False})
    assert client.get('/api/notifications/unread-count', headers=worker_headers).status_code == 403
    assert client.get('/api/worker/records', headers=worker_headers).status_code == 403
    assert client.get('/api/auth/me', headers=worker_headers).status_code == 200


def test_audit_denial_applies_to_overview_without_blocking_project_data(client, admin_headers, pm_headers):
    pid = _project(client, pm_headers, 'audit scope')
    overview = client.get(f'/api/projects/{pid}/overview', headers=pm_headers)
    assert overview.status_code == 200 and overview.json()['logs']
    policy(client, admin_headers, 'user-pm-001', {'system.audit.read': False})
    assert client.get(f'/api/projects/{pid}/logs', headers=pm_headers).status_code == 403
    overview = client.get(f'/api/projects/{pid}/overview', headers=pm_headers)
    assert overview.status_code == 200
    assert overview.json()['logs'] == []
    assert overview.json()['project']['id'] == pid


def test_repair_workspace_capability_is_revoked_with_issue_action(client, admin_headers, pm_headers):
    from tests.test_work_workspace import assigned_repair
    pid, unit, event, work = assigned_repair(client, pm_headers)
    path = f"/api/projects/{pid}/tasks/{work['task_id']}/workspace"
    assert client.get(path, headers=pm_headers).json()['can_update_repair']
    policy(client, admin_headers, 'user-pm-001', {'worker.issues': False})
    detail = client.get(path, headers=pm_headers)
    assert detail.status_code == 200
    assert detail.json()['repair']['id'] == event
    assert not detail.json()['can_update_repair']
    assert client.put(f'/api/projects/{pid}/vehicle-units/{unit}/events/{event}', headers=pm_headers,
                      json={'action_taken': 'revoked'}).status_code == 403

