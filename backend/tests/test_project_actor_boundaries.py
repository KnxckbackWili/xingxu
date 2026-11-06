import pytest
"""项目参与者校验、人工阶段权限与直接移交。"""
from tests.lifecycle_helpers import versioned


def test_create_project_bad_manager_id_returns_400(client, pm_headers):
    r = client.post('/api/projects', headers=pm_headers, json={'name': '坏负责人', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30', 'manager_id': 'no-such-user'})
    assert r.status_code == 400
    assert '项目经理' in r.json()['detail']

def _project(client, pm_headers, name='功能边界项目'):
    r = client.post('/api/projects', headers=pm_headers, json={'name': name, 'start_date': '2026-08-10', 'status': 'preparing', 'new_vehicles': False, 'end_date': '2026-09-30'})
    assert r.status_code == 200, r.json()
    return r.json()['id']


def test_direct_transfer_bad_recipient_returns_400(client, admin_headers, pm_headers):
    pid = _project(client, pm_headers)
    preview = client.get(f'/api/projects/{pid}/transfer-preview', headers=admin_headers)
    assert preview.status_code == 200, preview.text
    result = client.post(f'/api/projects/{pid}/transfer', headers=admin_headers, json={
        'target_manager_id': 'no-such-user', 'reason': '核对接收人仍真实存在且可接手',
        'version': preview.json()['version'],
        'member_removal_confirmations': [row['user_id'] for row in preview.json()['removed']]})
    assert result.status_code == 400
    assert '项目经理' in result.json()['detail']

def test_director_can_change_status(client, admin_headers, pm_headers):
    from tests.document_helpers import documents, upload_documents
    pid = _project(client, pm_headers)
    rows = documents(client, pm_headers, pid)['documents']
    required = [row['id'] for row in rows if row['stage_key'] == '4' and row['required'] and row['applicable']]
    assert required
    upload_documents(client, pm_headers, pid, required)
    result = client.post('/api/users', headers=admin_headers, json={
        'username': 'dir1', 'password': 'Review123!', 'display_name': '总监一号', 'role': 'director'})
    assert result.status_code == 200, result.text
    login = client.post('/api/auth/login', json={'username': 'dir1', 'password': 'Review123!'})
    assert login.status_code == 200, login.text
    director = {'Authorization': 'Bearer ' + login.json()['access_token']}
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    result = client.post(f'/api/projects/{pid}/status', headers=director, json={'status': 'executing'})
    assert result.status_code == 200, result.text
    assert client.get(f'/api/projects/{pid}', headers=director).json()['status'] == 'executing'

def _login(client, username):
    response = client.post('/api/auth/login', json={'username': username, 'password': 'password123'})
    return {'Authorization': f'Bearer {response.json()['access_token']}'}

def _transfer(client, admin_headers, pid, target_id, requester_headers):
    preview = client.get(f'/api/projects/{pid}/transfer-preview', headers=admin_headers)
    assert preview.status_code == 200, preview.text
    transferred = client.post(f'/api/projects/{pid}/transfer', headers=admin_headers, json={
        'target_manager_id': target_id, 'reason': '岗位调整，已完成风险交底',
        'version': preview.json()['version'],
        'member_removal_confirmations': [row['user_id'] for row in preview.json()['removed']]})
    assert transferred.status_code == 200, transferred.text
    return transferred.json()

def _managed_project(client, headers, name, manager_id=None):
    body = {'name': name, 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'}
    if manager_id:
        body['manager_id'] = manager_id
    r = client.post('/api/projects', headers=headers, json=body)
    assert r.status_code == 200, r.json()
    return r.json()['id']

def _create_user(client, admin_headers, username, role='pm'):
    response = client.post('/api/users', headers=admin_headers, json={'username': username, 'password': 'password123', 'display_name': username, 'role': role})
    assert response.status_code == 200, response.text
    return response.json()['id']
