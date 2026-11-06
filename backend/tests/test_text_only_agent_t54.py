"""Real HTTP+MCP read contracts, current scope/actor and document privacy."""
from datetime import datetime,timedelta
import json
import pytest
from app.db import SessionLocal
from app.models import (Project,User,AiApiToken,ProjectDocument,ProjectDocumentDefinition,DocumentVersion,
                        VehicleProgress,Task,CheckItem,ChangeLog)
from tests.test_agent_api import token,call,mcp_call
from tests.test_confidential_documents_t26 import setup_project,policy
from tests.document_helpers import requirement,upload_documents,documents

NEW_TOOLS={'documents_read','vehicle_progress_read','documents_due_this_week'}
RETIRED={'tasks_tree','get_schedule','schedule_preview','preparations_summary','project_readiness',
         'change_set_merge','inbox_list','project_update','documents_submit','check_complete','share_create'}


def test_catalog_has_only_current_reads_and_retired_calls_cannot_write(client,admin_headers):
    _,headers=token(client,admin_headers)
    catalog=client.get('/api/agent/tools',headers=headers)
    assert catalog.status_code==200 and catalog.headers['cache-control']=='private, no-store'
    tools=catalog.json()['tools'];names={row['name'] for row in tools}
    assert NEW_TOOLS<=names and not RETIRED&names
    assert all(t['annotations']['readOnlyHint'] and not t['annotations']['destructiveHint'] for t in tools)
    mcp=mcp_call(client,headers,'tools/list',{}).json()['result']['tools']
    assert {row['name'] for row in mcp}==names
    for name in RETIRED:assert call(client,headers,name,project_id='unknown').status_code==404
    from app.services.ai_mcp import agent_tool
    with pytest.raises(ValueError,match='只允许读取'):agent_tool('projects:read',writes=True)
    _,limited=token(client,admin_headers,scopes=['projects:read'])
    assert {row['name'] for row in mcp_call(client,limited,'tools/list',{}).json()['result']['tools']}=={'projects_list','project_get'}
    assert call(client,limited,'documents_read',project_id='unknown').status_code==403


def test_old_grants_are_preserved_but_inert_and_new_tokens_cannot_request_them(client,admin_headers):
    row,headers=token(client,admin_headers)
    with SessionLocal() as db:
        db.get(AiApiToken,row['id']).scopes=['projects:read','tasks:read','schedule:read','schedule:preview','preparations:read','inbox:read','change_sets:write'];db.commit()
    response=client.get('/api/ai/internal/tokens',headers=admin_headers)
    current=next(item for item in response.json()['items'] if item['id']==row['id'])
    assert current['scopes']==['projects:read']
    assert all(value.endswith(':read') for value,_ in response.json()['scopes'])
    assert {tool['name'] for tool in client.get('/api/agent/tools',headers=headers).json()['tools']}=={'projects_list','project_get'}
    for scope in ('tasks:read','schedule:preview','schedule:read','preparations:read','documents:write'):
        assert client.post('/api/ai/internal/tokens',headers=admin_headers,json={'name':'invalid','user_id':'user-admin-001','scopes':[scope]}).status_code==400
    with SessionLocal() as db:assert 'schedule:preview' in db.get(AiApiToken,row['id']).scopes


def test_due_this_week_uses_project_sunday_and_never_generates_periods(client,pm_headers,admin_headers,monkeypatch):
    from app.services import document_deadlines as deadlines
    pid,users=setup_project(client,pm_headers)
    first=requirement(client,pm_headers,pid,code='6.97',name='LOCAL-SUNDAY')
    next_week=requirement(client,pm_headers,pid,code='6.98',name='NEXT-LOCAL-WEEK')
    private=requirement(client,pm_headers,pid,code='6.99',name='PRIVATE-WEEK')
    assert policy(client,pm_headers,pid,'document',private).status_code==200
    now=datetime(2026,12,28,0,30)  # UTC Monday, Los Angeles Sunday/ISO W52.
    monkeypatch.setattr(deadlines,'utcnow',lambda:now)
    with SessionLocal() as db:
        db.get(Project,pid).timezone='America/Los_Angeles'
        for identity,due in ((first['id'],datetime(2026,12,28,7)),(next_week['id'],datetime(2026,12,28,9)),(private['id'],datetime(2026,12,28,7))):
            row=db.get(ProjectDocument,identity);row.due_at=due;row.due_is_estimated=False;row.period_key='2026-W52'
        db.commit();before=db.query(ProjectDocument).count()
    _,admin=token(client,admin_headers);_,owner=token(client,admin_headers,user=users['pm'])
    public=call(client,admin,'documents_due_this_week',project_id=pid).json()['data']
    assert public['timezone']=='America/Los_Angeles' and public['period_key']=='2026-W52'
    assert first['id'] in {row['document_id'] for row in public['items']}
    assert next_week['id'] not in {row['document_id'] for row in public['items']} and 'PRIVATE-WEEK' not in json.dumps(public)
    private_view=call(client,owner,'documents_due_this_week',project_id=pid).json()['data']
    assert private['id'] in {row['document_id'] for row in private_view['items']}
    with SessionLocal() as db:assert db.query(ProjectDocument).count()==before


def test_token_scope_is_rechecked_after_http_admission_before_actual_tool(client,admin_headers,pm_headers,monkeypatch):
    from app.routers import agent
    pid,_=setup_project(client,pm_headers);row,headers=token(client,admin_headers)
    original=agent.mcp.call_tool
    async def delayed(name,arguments):
        with SessionLocal() as db:db.get(AiApiToken,row['id']).scopes=['projects:read'];db.commit()
        return await original(name,arguments)
    monkeypatch.setattr(agent.mcp,'call_tool',delayed)
    response=call(client,headers,'documents_read',project_id=pid)
    assert response.status_code==200 and response.json()['ok'] is False
    assert 'Token 未授权' in response.json()['error']

