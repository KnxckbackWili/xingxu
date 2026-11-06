import pytest
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


def test_delegated_creator_cannot_choose_manager_or_admin_through_preset(client, admin_headers, worker_headers):
    policy(client, admin_headers, 'user-worker-001', {'system.users.manage': True})
    for preset in ('pm', 'admin'):
        result = client.post('/api/users', headers=worker_headers, json={
            'display_name': 'delegated-' + preset, 'password': 'ReadOnly-test-123', 'permission_preset': preset,
        })
        assert result.status_code in (403, 422)
    user, _ = account(client, worker_headers, 'readonly', 'delegated-reader')
    assert user['role'] == 'readonly'


def test_future_action_is_denied_by_readonly_ceiling(monkeypatch):
    from app.services import system_permissions as permissions
    user = SimpleNamespace(role='readonly', is_active=True, permission_overrides={'future.write': True})
    monkeypatch.setitem(permissions.PERMISSIONS, 'future.write', {'default_roles': ['readonly']})
    assert not permissions.has_permission(user, 'future.write')
    assert 'future.write' not in permissions.default_permissions(user)


def test_project_read_denial_reports_system_layer_on_mixed_field_writes(client, admin_headers, pm_headers, worker_headers):
    pid = _project(client, pm_headers, 'system read denial')
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

