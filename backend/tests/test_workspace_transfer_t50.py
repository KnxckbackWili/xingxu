"""Direct transfer and current-fact projections; isolated SQLite/PG HTTP seams."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import json
import pytest
from app.db import SessionLocal
from app.models import User, Project, ProjectDocument, DocumentVersion, ChangeLog, DocumentTriggerEvent, Issue, Attachment, Notification, ProjectDocumentDefinition
from app.time_utils import utcnow
from tests.test_confidential_documents_t26 import setup_project,policy
from tests.document_helpers import requirement,documents,upload_documents


def recipient(client,admin_headers,username='next-pm'):
    response=client.post('/api/users',headers=admin_headers,json={'username':username,'display_name':'下一位项目负责人','password':'Review123!','role':'employee'})
    assert response.status_code==200,response.text
    row=response.json();login=client.post('/api/auth/login',json={'username':username,'password':'Review123!'})
    assert login.status_code==200
    return row['id'],{'Authorization':'Bearer '+login.json()['access_token']}


def preview(client,headers,pid):
    result=client.get(f'/api/projects/{pid}/transfer-preview',headers=headers)
    assert result.status_code==200,result.text
    return result.json()


def transfer(client,headers,pid,target,view,**extra):
    return client.post(f'/api/projects/{pid}/transfer',headers=headers,json={'target_manager_id':target,
        'reason':'明确交接并由新的项目经理接手','version':view['version'],
        'member_removal_confirmations':[row['user_id'] for row in view['removed']],**extra})


def test_current_actor_and_target_are_refreshed_after_lock_and_log_failure_rolls_back(client,pm_headers,admin_headers,monkeypatch):
    from app.services import project_transfer as service
    from sqlalchemy import update
    pid,people=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    view=preview(client,pm_headers,pid);original=service.lock_record
    def withdraw(db,project,**kwargs):
        original(db,project,**kwargs)
        db.execute(update(User).where(User.id==people['pm']).values(token_version=User.token_version+1).execution_options(synchronize_session=False))
    monkeypatch.setattr(service,'lock_record',withdraw)
    assert transfer(client,pm_headers,pid,target,view).status_code==401
    monkeypatch.setattr(service,'lock_record',original)
    def fail(*args,**kwargs):raise RuntimeError('audit unavailable')
    monkeypatch.setattr(service,'log_change',fail)
    with pytest.raises(RuntimeError,match='audit unavailable'):transfer(client,pm_headers,pid,target,view)
    with SessionLocal() as db:
        assert db.get(Project,pid).manager==people['pm'] and db.get(Project,pid).version==view['version']
        assert not db.query(DocumentTriggerEvent).filter_by(project_id=pid,trigger_type='member_leave').first()
        assert not db.query(Notification).filter_by(project_id=pid,ntype='project_membership').first()


def test_simultaneous_admin_transfer_has_one_cas_winner_and_preview_hides_private_requirements(client,pm_headers,admin_headers):
    pid,_=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    rows=documents(client,pm_headers,pid)
    leave=next(row for row in rows['definitions'] if row['code']=='6.7')
    response=client.put(f'/api/projects/{pid}/documents/requirements/{leave["id"]}/confidentiality',headers=pm_headers,
        json={'confidential':True,'confidential_user_ids':[],'version':leave['access_version']})
    assert response.status_code==200,response.text
    with SessionLocal() as db:
        for model in (ProjectDocumentDefinition,ProjectDocument):
            for row in db.query(model).filter_by(project_id=pid,code='6.7'):row.name='PRIVATE-LEAVE-TITLE'
        db.commit()
    view=preview(client,admin_headers,pid)
    assert 'PRIVATE-LEAVE-TITLE' not in json.dumps(view) and view['removed'][0]['documents'][0]['restricted']
    denied=transfer(client,admin_headers,pid,target,view,member_removal_confirmations=[])
    assert denied.status_code==409 and 'PRIVATE-LEAVE-TITLE' not in denied.text
    assert denied.headers['cache-control']=='private, no-store'
    with ThreadPoolExecutor(max_workers=2) as workers:
        results=list(workers.map(lambda _:transfer(client,admin_headers,pid,target,view).status_code,range(2)))
    assert sorted(results)==[200,409]
    with SessionLocal() as db:
        assert db.query(ChangeLog).filter_by(project_id=pid,action='transfer').count()==1
        assert db.query(DocumentTriggerEvent).filter_by(project_id=pid,trigger_type='member_leave').count()==1


def test_current_facts_exist_in_project_list_without_workspace_and_filter_private_deadlines(client,pm_headers,admin_headers,worker_headers):
    pid,people=setup_project(client,pm_headers)
    public=requirement(client,pm_headers,pid,code='6.98',name='PUBLIC-OVERDUE')
    private=requirement(client,pm_headers,pid,code='6.99',name='PRIVATE-OVERDUE')
    assert policy(client,pm_headers,pid,'document',private).status_code==200
    with SessionLocal() as db:
        for identity in (public['id'],private['id']):
            row=db.get(ProjectDocument,identity);row.due_at=utcnow()-timedelta(days=1);row.due_is_estimated=False;row.timing_type='after_event';row.timing_event='ship'
        db.commit()
    listed=client.get('/api/projects',headers=worker_headers)
    assert listed.status_code==200 and listed.headers['cache-control']=='private, no-store'
    row=next(row for row in listed.json() if row['id']==pid)
    assert row['document_attention']['overdue_count']==1
    assert row['vehicle_progress']['percent'] is None and not row['vehicle_progress']['progress_known']
    assert row['next_signoff']['code']=='6.10.1'
    assert 'PRIVATE-OVERDUE' not in json.dumps(row)
    statistics=client.get('/api/dashboard/statistics',headers=worker_headers)
    assert statistics.status_code==200,statistics.text
    stats=statistics.json();assert stats['projects']==1 and stats['documents']['overdue_count']==1
    assert 'PUBLIC-OVERDUE' not in statistics.text and 'PRIVATE-OVERDUE' not in statistics.text and 'project_name' not in statistics.text
    assert set(stats)=={'projects','active_projects','completed_projects','status_distribution','vehicle_progress','documents','issues'}


def test_workbench_and_statistics_only_current_facts_and_issue_closure_no_stale_private_cache(client,pm_headers,admin_headers,monkeypatch):
    import os
    pid,people=setup_project(client,pm_headers)
    row=requirement(client,pm_headers,pid,name='NOW-PRIVATE-ATTENTION')
    with SessionLocal() as db:
        pending=db.get(ProjectDocument,row['id']);pending.due_at=utcnow()+timedelta(minutes=5);pending.timing_type='after_event';pending.timing_event='ship'
        for status,severity in (('waiting_vendor','critical'),('closed','critical'),('cancelled','high'),('processing','low')):
            db.add(Issue(project_id=pid,title='not in aggregate',issue_type='hardware',status=status,severity=severity,reporter_id=people['pm']))
        db.commit()
    monkeypatch.setenv('AGVPM_ENABLE_CACHE','1')
    before=client.get('/api/dashboard/overview',headers=admin_headers)
    assert before.status_code==200,before.text
    assert 'NOW-PRIVATE-ATTENTION' in before.text
    assert before.json()['weekly_plan']=={'state':'available','count':0,'items':[]}
    assert 'people' not in before.json() and 'quantities_by_unit' not in before.text and 'person_days' not in before.text
    assert policy(client,pm_headers,pid,'document',row).status_code==200
    after=client.get('/api/dashboard/overview',headers=admin_headers)
    assert after.status_code==200 and 'NOW-PRIVATE-ATTENTION' not in after.text
    result=client.get('/api/dashboard/statistics',headers=admin_headers).json()
    assert result['issues']=={'open':2,'critical':1}
    assert result['vehicle_progress']['quantity_unknown'] and result['vehicle_progress']['percent'] is None


@pytest.mark.parametrize('change,expected',[('actor_disabled',401),('target_inactive',400)])
def test_permission_and_recipient_changes_after_project_lock_cannot_be_cached(client,pm_headers,admin_headers,monkeypatch,change,expected):
    from app.services import project_transfer as service
    from sqlalchemy import update
    pid,people=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    view=preview(client,pm_headers,pid);original=service.lock_record
    def changed(db,project,**kwargs):
        original(db,project,**kwargs)
        if change=='actor_disabled':db.execute(update(User).where(User.id==people['pm']).values(is_active=False).execution_options(synchronize_session=False))
        else:db.execute(update(User).where(User.id==target).values(is_active=False).execution_options(synchronize_session=False))
    monkeypatch.setattr(service,'lock_record',changed)
    assert transfer(client,pm_headers,pid,target,view).status_code==expected
    with SessionLocal() as db:assert db.get(Project,pid).manager==people['pm']


def test_overview_and_statistics_share_current_issue_and_vehicle_closure_facts(client,pm_headers):
    from app.models import VehicleUnit,VehicleLifecycleEvent
    from datetime import date
    pid,people=setup_project(client,pm_headers)
    with SessionLocal() as db:
        unit=VehicleUnit(project_id=pid,asset_code='PRIVATE-VEHICLE-LABEL',current_status='fault');db.add(unit);db.flush()
        for kind,closed in [('fault',False),('repair',True),('stage_change',False)]:
            db.add(VehicleLifecycleEvent(project_id=pid,vehicle_unit_id=unit.id,event_type=kind,event_date=date.today(),
                title='PRIVATE-VEHICLE-TITLE',is_closed=closed))
        for status,severity in [('open','medium'),('resolved','high'),('closed','critical'),('cancelled','high')]:
            db.add(Issue(project_id=pid,title='PRIVATE-ISSUE-TITLE',status=status,severity=severity,reporter_id=people['pm']))
        db.commit()
    stats=client.get('/api/dashboard/statistics',headers=pm_headers)
    overview=client.get('/api/dashboard/overview',headers=pm_headers)
    assert stats.status_code==overview.status_code==200
    assert stats.json()['issues']=={'open':3,'critical':2}
    row=next(row for row in overview.json()['projects'] if row['id']==pid)
    assert (row['open_issues'],row['critical_issues'])==(3,2)
    assert 'PRIVATE-VEHICLE' not in stats.text and 'PRIVATE-ISSUE' not in stats.text
