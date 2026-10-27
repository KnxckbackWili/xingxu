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


def test_three_reads_use_current_project_scope_and_t26_private_membership(client,pm_headers,admin_headers):
    pid,users=setup_project(client,pm_headers)
    private=requirement(client,pm_headers,pid,code='6.99',name='T54-PRIVATE')
    submitted=upload_documents(client,pm_headers,pid,[private['id']],content=b'private content',name='T54-secret.txt')['documents'][0]
    assert policy(client,pm_headers,pid,'document',submitted).status_code==200
    _,admin=token(client,admin_headers)
    _,owner=token(client,admin_headers,user=users['pm'])
    _,hidden=token(client,admin_headers,user=users['worker1'])
    # Another actual project is outside worker scope.
    foreign=client.post('/api/projects',headers=pm_headers,json={'name':'Other','start_date':'2026-01-01','end_date':'2026-12-31'}).json()['id']
    for name in NEW_TOOLS:
        denied=call(client,hidden,name,project_id=foreign).json()
        assert denied['ok'] is False and 'data' not in denied
        assert call(client,owner,name,project_id=pid).json()['ok']
    assert 'T54-PRIVATE' not in call(client,admin,'documents_read',project_id=pid).text
    allowed=call(client,owner,'documents_read',project_id=pid)
    assert 'T54-PRIVATE' in allowed.text and 'stored_name' not in allowed.text
    assert 'source_metadata' not in allowed.text
    with SessionLocal() as db:
        assert db.query(ChangeLog).filter_by(project_id=pid,action='confidential_view').count()>0
        before={model.__tablename__:db.query(model).count() for model in (Project,ProjectDocument,DocumentVersion,VehicleProgress,Task,CheckItem)}
    for name in NEW_TOOLS:assert call(client,owner,name,project_id=pid).json()['ok']
    with SessionLocal() as db:
        assert {model.__tablename__:db.query(model).count() for model in (Project,ProjectDocument,DocumentVersion,VehicleProgress,Task,CheckItem)}==before
    with SessionLocal() as db:db.get(User,users['pm']).permission_overrides={'project.read':False};db.commit()
    for name in NEW_TOOLS:assert call(client,owner,name,project_id=pid).json()['ok'] is False


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


@pytest.mark.parametrize('path,method',[('/api/ai-projects/organize','post'),('/api/ai-projects/organize/jobs','post'),('/api/ai-projects/test-connection','post'),('/api/ai-projects/skill-bundle?skill=planning','get')])
def test_structured_business_drafting_is_410_even_for_admin_and_never_calls_provider(client,admin_headers,monkeypatch,path,method):
    import app.services.ai_project_assistant as assistant
    calls=[]
    monkeypatch.setattr(assistant,'organize_project',lambda *args,**kwargs:calls.append('project'))
    monkeypatch.setattr(assistant,'organize_domain',lambda *args,**kwargs:calls.append('domain'))
    monkeypatch.setattr(assistant,'test_connection',lambda *args,**kwargs:calls.append('connect'))
    response=client.request(method.upper(),path,headers=admin_headers,json={'skill':'planning','source_text':'do not send'})
    assert response.status_code==410 and response.headers['cache-control']=='private, no-store'
    assert calls==[]
    client.cookies.clear()
    assert client.request(method.upper(),path).status_code==401


def test_queued_legacy_callback_never_restarts_model_and_completed_history_stays_owned(client,admin_headers):
    from app.routers.ai_projects import OrganizeBody,_run_organize_job
    from app.services.ai_jobs import create_job,get_job,set_job
    queued=create_job('user-admin-001','old structured draft')
    _run_organize_job(queued['id'],OrganizeBody(skill='planning'),'user-admin-001')
    assert get_job(queued['id'],'user-admin-001')['status']=='failed'
    finished=create_job('user-admin-001','old completed')
    set_job(finished['id'],status='completed',percent=100,result={'draft':{'old':'owner-only'}})
    _run_organize_job(finished['id'],OrganizeBody(),'user-admin-001')
    assert get_job(finished['id'],'user-admin-001')['result']=={'draft':{'old':'owner-only'}}
    assert client.get('/api/ai-projects/organize/jobs/'+finished['id'],headers=admin_headers).status_code==200
    status=client.get('/api/ai-projects/status',headers=admin_headers).json()
    assert not status['available'] and not status['drafting_enabled'] and status['skills']==[]
    catalog=client.get('/api/ai-projects/capabilities',headers=admin_headers).json()
    names={row['name'] for row in catalog['tools']}
    assert {'get_project_documents','get_vehicle_progress','get_documents_due_this_week'}<=names
    assert not {'get_execution_plan','get_preparations_summary','get_schedule','preview_schedule'}&names
    assert 'budget' in client.get('/api/ai/internal/tokens',headers=admin_headers).json()
