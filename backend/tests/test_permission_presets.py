"""Real preset accounts, durable read-only ceilings, and project-scoped reasons."""
from tests.lifecycle_helpers import versioned
from types import SimpleNamespace

from tests.test_permissions import _project
from tests.test_system_permission_integration import policy


def account(client, admin, preset, name):
    result = client.post('/api/users', headers=admin, json={
        'username': name, 'display_name': name, 'password': 'ReadOnly-test-123',
        'permission_preset': preset,
    })
    assert result.status_code == 200, result.text
    user = result.json()
    login = client.post('/api/auth/login', json={'username': name, 'password': 'ReadOnly-test-123'})
    assert login.status_code == 200, login.text
    return user, {'Authorization': 'Bearer ' + login.json()['access_token']}


def test_presets_create_the_selected_role_and_audit_resolved_role(client, admin_headers):
    from app.db import SessionLocal
    from app.models import ChangeLog
    for preset in ('pm', 'worker', 'readonly'):
        user, _ = account(client, admin_headers, preset, 'preset-' + preset)
        assert user['role'] == preset
        with SessionLocal() as db:
            row = db.query(ChangeLog).filter_by(entity_type='user', entity_id=user['id'], action='create').one()
            assert row.new_value['role'] == preset
    assert client.post('/api/users', headers=admin_headers, json={
        'display_name': 'invalid preset', 'password': 'ReadOnly-test-123', 'permission_preset': 'admin',
    }).status_code == 422


def test_readonly_can_view_assigned_project_but_cannot_write_even_with_old_grants(client, admin_headers, pm_headers):
    from app.db import SessionLocal
    from app.models import User
    user, headers = account(client, admin_headers, 'readonly', 'reader')
    pid = _project(client, pm_headers, 'reader project')
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [user['id']]})).status_code == 200
    assert client.get(f'/api/projects/{pid}', headers=headers).status_code == 200
    assert client.get(f'/api/projects/{pid}/export/json', headers=headers).status_code == 200
    # Simulate historical grants left behind when a former writer becomes readonly.
    with SessionLocal() as db:
        actor = db.get(User, user['id'])
        actor.permission_overrides = {'project.update': True, 'worker.issues': True, 'projects.create': True}
        db.commit()
    for method, path, body in [
        ('PUT', f'/api/projects/{pid}', {'description': 'forbidden'}),
        ('POST', f'/api/projects/{pid}/issues', {'title': 'forbidden'}),
        ('POST', '/api/projects', {'name': 'forbidden'}),
        ('POST', f'/api/projects/{pid}/governance-requests', {'request_type': 'transfer', 'reason': 'forbidden'}),
    ]:
        response = client.request(method, path, headers=headers, json=body)
        assert response.status_code == 403, response.text
        assert '只读预设' in response.text
    assert client.get(f'/api/projects/{pid}', headers=headers).json()['description'] != 'forbidden'
    assert set(client.get(f'/api/projects/{pid}', headers=headers).json()['capabilities']) <= {'project.export'}


def test_readonly_ceiling_cannot_be_removed_by_system_or_member_grants(client, admin_headers, pm_headers):
    reader, _ = account(client, admin_headers, 'readonly', 'ceiling-reader')
    pid = _project(client, pm_headers, 'ceiling')
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': [reader['id']]})).status_code == 200
    version = client.get(f"/api/permissions/users/{reader['id']}", headers=admin_headers).json()['version']
    assert client.put(f"/api/permissions/users/{reader['id']}", headers=admin_headers,
                      json={'version': version, 'overrides': {'worker.report': True}}).status_code == 422
    denied = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {
        'member_permissions': [{'user_id': reader['id'], 'capabilities': ['project.manage_plan']}],
    }))
    assert denied.status_code == 400 and '只读预设' in denied.text


def test_readonly_can_change_own_password_and_remains_scoped(client, admin_headers, pm_headers):
    reader, headers = account(client, admin_headers, 'readonly', 'self-reader')
    pid = _project(client, pm_headers, 'private project')
    assert client.get(f'/api/projects/{pid}', headers=headers).status_code == 404
    changed = client.put('/api/auth/password', headers=headers, json={
        'old_password': 'ReadOnly-test-123', 'new_password': 'changed-ReadOnly-123',
    })
    assert changed.status_code == 200, changed.text
    assert client.get('/api/auth/me', headers=headers).status_code == 401
    assert client.post('/api/auth/login', json={'username': reader['username'], 'password': 'changed-ReadOnly-123'}).status_code == 200


def test_delegated_creator_cannot_choose_manager_or_admin_through_preset(client, admin_headers, worker_headers):
    policy(client, admin_headers, 'user-worker-001', {'system.users.manage': True})
    for preset in ('pm', 'admin'):
        result = client.post('/api/users', headers=worker_headers, json={
            'display_name': 'delegated-' + preset, 'password': 'ReadOnly-test-123', 'permission_preset': preset,
        })
        assert result.status_code in (403, 422)
    user, _ = account(client, worker_headers, 'readonly', 'delegated-reader')
    assert user['role'] == 'readonly'


def test_project_reasons_distinguish_layers_and_enforce_inspector_scope(client, admin_headers, pm_headers, worker_headers):
    reader, _ = account(client, admin_headers, 'readonly', 'reasons-reader')
    pid = _project(client, pm_headers, 'reasons')
    path = f"/api/permissions/projects/{pid}/users/{reader['id']}/reasons"
    data = client.get(path, headers=pm_headers)
    assert data.status_code == 200, data.text
    reasons = {x['key']: x for x in data.json()['items']}
    assert reasons['project.read']['layer'] == 'membership'
    assert reasons['project.update']['layer'] == 'membership'
    assert client.put(f'/api/projects/{pid}', headers=pm_headers,
                      json=versioned(pid, {'members': [reader['id'], 'user-worker-001']})).status_code == 200
    joined = client.get(path, headers=pm_headers).json()
    assert next(x for x in joined['items'] if x['key'] == 'project.update')['layer'] == 'preset'
    assert client.get(path, headers=worker_headers).status_code == 403
    own = client.get(f'/api/permissions/projects/{pid}/users/user-worker-001/reasons', headers=worker_headers)
    assert own.status_code == 200
    assert next(x for x in own.json()['items'] if x['key'] == 'project.update')['layer'] == 'project_role'
    policy(client, admin_headers, 'user-worker-001', {'project.update': False})
    own = client.get(f'/api/permissions/projects/{pid}/users/user-worker-001/reasons', headers=worker_headers)
    assert next(x for x in own.json()['items'] if x['key'] == 'project.update')['layer'] == 'system'
    denied = client.put(f'/api/projects/{pid}', headers=worker_headers, json=versioned(pid, {'description': 'denied'}))
    assert denied.status_code == 403 and '系统禁止' in denied.text


def test_future_action_is_denied_by_readonly_ceiling(monkeypatch):
    from app.services import system_permissions as permissions
    user = SimpleNamespace(role='readonly', is_active=True, permission_overrides={'future.write': True})
    monkeypatch.setitem(permissions.PERMISSIONS, 'future.write', {'default_roles': ['readonly']})
    assert not permissions.has_permission(user, 'future.write')
    assert 'future.write' not in permissions.default_permissions(user)


def test_project_read_denial_reports_system_layer_on_mixed_field_writes(client, admin_headers, pm_headers, worker_headers):
    pid = _project(client, pm_headers, 'system read denial')
    assert client.put(f'/api/projects/{pid}', headers=pm_headers,
                      json=versioned(pid, {'members': ['user-worker-001']})).status_code == 200
    policy(client, admin_headers, 'user-worker-001', {'project.read': False})
    denied = client.put(f'/api/projects/{pid}', headers=worker_headers, json=versioned(pid, {'description': 'denied'}))
    assert denied.status_code == 403 and '系统禁止' in denied.text


def test_get_action_cannot_bypass_readonly_ceiling_with_an_explicit_grant():
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    from app.db import get_db
    from app.deps import create_token, get_current_user
    from app.models import User
    from app.services.system_permissions import route_permission
    app = FastAPI()
    reader = User(id='reader', username='reader', password_hash='opaque', role='readonly', is_active=True,
                  token_version=0, permission_overrides={'worker.report': True})
    def fake_db():
        yield SimpleNamespace(get=lambda model, key: reader)
    app.dependency_overrides[get_db] = fake_db
    @app.get('/future-action')
    @route_permission('worker.report')
    def action(user=Depends(get_current_user)):
        raise AssertionError('readonly must not execute a disallowed action via GET')
    response = TestClient(app).get('/future-action', headers={'Authorization': 'Bearer ' + create_token(reader)})
    assert response.status_code == 403 and '只读预设' in response.text


def test_project_inspectors_get_identical_membership_reason_for_all_outsiders(client, admin_headers, pm_headers):
    from app.db import SessionLocal
    from app.models import User
    outsider, _ = account(client, admin_headers, 'worker', 'outside-policy')
    with SessionLocal() as db:
        user = db.get(User, outsider['id'])
        user.is_active = False
        user.permission_overrides = {'project.manage_plan': False}
        db.commit()
    pid = _project(client, pm_headers, 'outside privacy')
    results = []
    for user_id in (outsider['id'], 'missing-account'):
        response = client.get(f'/api/permissions/projects/{pid}/users/{user_id}/reasons', headers=pm_headers)
        assert response.status_code == 200
        results.append(response.json()['items'])
    assert results[0] == results[1]
    assert {row['layer'] for row in results[0]} == {'membership'}


def test_member_permission_write_respects_system_membership_denial(client, admin_headers, pm_headers):
    pid = _project(client, pm_headers, 'delegation deny')
    assert client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'members': ['user-worker-001']})).status_code == 200
    policy(client, admin_headers, 'user-pm-001', {'project.manage_members': False})
    response = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {
        'member_permissions': [{'user_id': 'user-worker-001', 'capabilities': ['project.manage_plan']}],
    }))
    assert response.status_code == 403 and '系统禁止' in response.text
