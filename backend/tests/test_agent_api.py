"""Real HTTP/MCP protocol checks for external agents, project isolation and revocation."""
import json
from concurrent.futures import ThreadPoolExecutor

from app.db import SessionLocal
from app.models import Attachment, AiApiToken, User
def setup_project(client, headers):
    response=client.post('/api/projects',headers=headers,json={'name':'Current Agent reads','start_date':'2026-01-01','end_date':'2026-12-31'})
    assert response.status_code==200,response.text
    return response.json()['id'],[]


def token(client, admin_headers, user='user-admin-001', scopes=None):
    body = {'name': 'Agent regression', 'user_id': user}
    if scopes is not None:
        body['scopes'] = scopes
    r = client.post('/api/ai/internal/tokens', headers=admin_headers, json=body)
    assert r.status_code == 200, r.text
    return r.json(), {'Authorization': f"Bearer {r.json()['token']}"}


def call(client, headers, name, **arguments):
    return client.post(f'/api/agent/tools/{name}', headers=headers, json={'arguments': arguments})


def mcp_call(client, headers, method, params):
    return client.post('/api/ai/mcp/', headers={**headers, 'Accept': 'application/json, text/event-stream'},
                       json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})




def test_new_tools_return_real_project_data_and_pagination(client, admin_headers, pm_headers):
    pid, tasks = setup_project(client, pm_headers)
    _, headers = token(client, admin_headers)
    for name in ('documents_read','vehicle_progress_read','documents_due_this_week'):
        result=call(client,headers,name,project_id=pid)
        assert result.status_code==200 and result.json()['ok'],result.text
    for name in ['project_members', 'project_vehicles', 'project_activity']:
        result = call(client, headers, name, project_id=pid)
        assert result.json()['ok'], result.text
    result = call(client, headers, 'template_get', template_id='default').json()
    assert result['ok'] and result['data']['document_requirements'] and result['data']['vehicle_steps']
    assert call(client, headers, 'templates_list').json()['data'][0]['id'] == 'default'
    assert call(client, headers, 'template_get', template_id='missing').json()['ok'] is False
    with SessionLocal() as db:
        for index in range(3):
            db.add(Attachment(project_id=pid, filename=f'file-{index}.txt', stored_name=f'private-disk-{index}'))
        db.commit()
    first = call(client, headers, 'project_files', project_id=pid, limit=2).json()['data']
    second = call(client, headers, 'project_files', project_id=pid, limit=2, offset=first['next_offset']).json()['data']
    assert len(first['items']) == 2 and len(second['items']) == 1 and second['next_offset'] is None
    assert not set(x['id'] for x in first['items']) & set(x['id'] for x in second['items'])
    assert 'stored_name' not in first['items'][0]
    assert call(client, headers, 'project_files', project_id=pid, limit=101).json()['ok'] is False
    assert call(client, headers, 'project_activity', project_id=pid, limit=-1).json()['ok'] is False


def test_every_new_project_tool_hides_other_projects(client, admin_headers, pm_headers):
    pid, _ = setup_project(client, pm_headers)
    _, headers = token(client, admin_headers, user='user-worker-001')
    for name in ['documents_read', 'vehicle_progress_read', 'documents_due_this_week', 'project_members', 'project_vehicles', 'project_files', 'project_activity']:
        result = call(client, headers, name, project_id=pid).json()
        assert result['ok'] is False, (name, result)
        assert 'data' not in result




def test_inactive_user_expiry_and_last_used_write_coalescing(client, admin_headers):
    from datetime import timedelta
    from app.time_utils import utcnow
    created, headers = token(client, admin_headers)
    assert call(client, headers, 'projects_list').status_code == 200
    with SessionLocal() as db:
        first_used = db.get(AiApiToken, created['id']).last_used_at
    assert call(client, headers, 'projects_list').status_code == 200
    with SessionLocal() as db:
        row = db.get(AiApiToken, created['id'])
        assert row.last_used_at == first_used
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert call(client, headers, 'projects_list').status_code == 401
    with SessionLocal() as db:
        row = db.get(AiApiToken, created['id']); row.expires_at = None
        db.get(User, 'user-admin-001').is_active = False
        db.commit()
    assert call(client, headers, 'projects_list').status_code == 401


def test_concurrent_requests_keep_token_identity_separate(client, admin_headers, pm_headers):
    pid, _ = setup_project(client, pm_headers)
    _, allowed = token(client, admin_headers, scopes=['projects:read'])
    _, denied = token(client, admin_headers, user='user-worker-001', scopes=['projects:read'])
    # Warm last-used timestamps so the actual race checks read identity, not SQLite writers.
    call(client, allowed, 'projects_list'); call(client, denied, 'projects_list')
    def run(index):
        result = call(client, allowed if index % 2 == 0 else denied, 'project_get', project_id=pid).json()
        return index, result['ok']
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, ok in pool.map(run, range(12)):
            assert ok == (index % 2 == 0)


def test_http_catalog_scope_and_parameter_validation(client, admin_headers):
    assert client.get('/api/agent/tools').status_code == 401
    assert client.get('/api/agent/tools', headers=admin_headers).status_code == 401
    _, headers = token(client, admin_headers, scopes=['projects:read'])
    catalog = client.get('/api/agent/tools', headers=headers).json()
    names = {t['name'] for t in catalog['tools']}
    assert names == {'projects_list', 'project_get'}
    project_schema = next(t for t in catalog['tools'] if t['name'] == 'project_get')
    assert 'project_id' in project_schema['inputSchema']['required']
    assert call(client, headers, 'project_get').status_code == 422
    assert call(client, headers, 'missing').status_code == 404
    assert call(client, headers, 'change_set_merge', project_id='x', change_set_id='y').status_code == 404
    assert call(client, headers, 'vehicle_progress_read', project_id='x').status_code == 403


def test_mcp_protocol_and_immediate_revocation(client, admin_headers):
    created, headers = token(client, admin_headers)
    result = mcp_call(client, headers, 'initialize', {
        'protocolVersion': '2025-03-26', 'capabilities': {},
        'clientInfo': {'name': 'Agent integration test', 'version': '1'},
    })
    assert result.status_code == 200, result.text
    assert result.json()['result']['serverInfo']['name'] == 'agv-pm'
    tools = mcp_call(client, headers, 'tools/list', {}).json()['result']['tools']
    from app.services.ai_mcp import TOOL_SCOPES
    assert {tool["name"] for tool in tools} == set(TOOL_SCOPES)
    assert next(t for t in tools if t['name'] == 'project_files')['annotations']['readOnlyHint']
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    result = mcp_call(client, headers, 'tools/call', {'name': 'projects_list', 'arguments': {}})
    assert json.loads(result.json()['result']['content'][0]['text'])['ok']
    denied = mcp_call(client, headers, 'tools/call', {'name': 'change_set_merge', 'arguments': {'project_id': 'x', 'change_set_id': 'y'}})
    assert denied.json()['result']['isError'] is True
    assert client.delete(f"/api/ai/internal/tokens/{created['id']}", headers=admin_headers).status_code == 200
    assert call(client, headers, 'projects_list').status_code == 401
    assert mcp_call(client, headers, 'tools/list', {}).status_code == 401
