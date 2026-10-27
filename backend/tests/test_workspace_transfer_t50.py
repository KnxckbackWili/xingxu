"""Direct transfer and current-fact projections; isolated SQLite/PG HTTP seams."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
import json
import pytest
from app.db import SessionLocal
from app.models import (User,Project,ProjectMember,ProjectGovernanceRequest,ProjectDocument,DocumentVersion,
                        ChangeLog,DocumentTriggerEvent,Issue,Attachment,Notification,ProjectDocumentDefinition)
from app.time_utils import utcnow
from tests.test_confidential_documents_t26 import setup_project,policy
from tests.document_helpers import requirement,documents,upload_documents


def recipient(client,admin_headers,username='next-pm'):
    response=client.post('/api/users',headers=admin_headers,json={'username':username,'display_name':'下一位项目经理','password':'Review123!','role':'pm'})
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


def test_direct_transfer_moves_current_owner_acl_creates_real_departure_and_preserves_history(client,pm_headers,admin_headers):
    pid,people=setup_project(client,pm_headers);target,new_headers=recipient(client,admin_headers)
    private=requirement(client,pm_headers,pid,name='PRIVATE-OWNER-SCOPE')
    uploaded=upload_documents(client,pm_headers,pid,[private['id']],content=b'private original')['documents'][0]
    assert policy(client,pm_headers,pid,'document',uploaded).status_code==200
    with SessionLocal() as db:
        old=ProjectGovernanceRequest(project_id=pid,project_name='历史申请',request_type='transfer',requested_by=people['pm'],
            source_manager_id=people['pm'],target_manager_id=target,reason='完整保全的历史申请',status='pending')
        db.add(old);db.commit();history_id=old.id
    view=preview(client,pm_headers,pid)
    assert view['current_manager']['id']==people['pm'] and target in {row['id'] for row in view['candidates']}
    assert [row['user_id'] for row in view['removed']]==[people['pm']]
    result=transfer(client,pm_headers,pid,target,view)
    assert result.status_code==200,result.text
    assert result.json()['manager']==target and result.json()['viewer_retains_access'] is False
    assert result.headers['cache-control']=='private, no-store'
    assert client.get('/api/projects/'+pid,headers=pm_headers).status_code==404
    current=documents(client,new_headers,pid)
    assert private['id'] in {row['id'] for row in current['documents']}
    assert client.get('/api'+uploaded['latest_version']['download_url'],headers=new_headers).content==b'private original'
    with SessionLocal() as db:
        project=db.get(Project,pid)
        assert people['pm'] not in project.members and target in project.members
        assert not db.query(ProjectMember).filter_by(project_id=pid,user_id=people['pm']).first()
        event=db.query(DocumentTriggerEvent).filter_by(project_id=pid,trigger_type='member_leave').one()
        assert event.source_id==people['pm']
        assert db.query(ProjectDocument).filter_by(project_id=pid,trigger_ref=event.id,code='6.7').count()==1
        history=db.get(ProjectGovernanceRequest,history_id)
        assert history.status=='pending' and history.reason=='完整保全的历史申请'
        audit=db.query(ChangeLog).filter_by(project_id=pid,action='transfer').one()
        assert audit.operator_id==people['pm'] and audit.new_value['reason']=='明确交接并由新的项目经理接手'
        from app.services.project_deletion import project_backup_snapshot
        from app.services.project_retention import project_retention_snapshot
        assert project_backup_snapshot(db,project)['records']['project_governance_requests'][0]['id']==history_id
        assert 'project_governance_requests' not in project_retention_snapshot(db,project)['records']


def test_ack_cas_target_and_ordinary_update_cannot_bypass_transfer(client,pm_headers,admin_headers,worker_headers):
    pid,people=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    view=preview(client,pm_headers,pid)
    assert transfer(client,pm_headers,pid,target,view,member_removal_confirmations=[]).status_code==409
    assert transfer(client,pm_headers,pid,target,view,version=view['version']+1).status_code==409
    assert transfer(client,worker_headers,pid,target,view).status_code==403
    for headers in (pm_headers,admin_headers):
        assert client.put('/api/projects/'+pid,headers=headers,json={'manager_id':target,'version':view['version']}).status_code==400
    with SessionLocal() as db:db.get(User,target).is_active=False;db.commit()
    assert transfer(client,pm_headers,pid,target,view).status_code==400
    with SessionLocal() as db:
        assert db.get(Project,pid).manager==people['pm']
        assert db.query(DocumentTriggerEvent).filter_by(project_id=pid,trigger_type='member_leave').count()==0
    for path,method in ((f'/api/projects/{pid}/governance-requests','POST'),('/api/projects/governance/requests','GET'),
            ('/api/projects/governance/requests/old/review','POST'),('/api/projects/governance/requests/old/withdraw','POST'),
            ('/api/projects/governance/requests/old/member-removal-preview','GET')):
        assert client.request(method,path,headers=admin_headers,json={}).status_code==410
    client.cookies.clear()
    assert client.post(f'/api/projects/{pid}/transfer').status_code==401


def test_explicit_retained_role_stays_member_but_never_keeps_implicit_confidential_owner_access(client,pm_headers,admin_headers):
    pid,people=setup_project(client,pm_headers);target,new_headers=recipient(client,admin_headers)
    private=requirement(client,pm_headers,pid,name='NEW-OWNER-ONLY')
    assert policy(client,pm_headers,pid,'document',private).status_code==200
    with SessionLocal() as db:db.get(Project,pid).technical_manager=people['pm'];db.commit()
    view=preview(client,pm_headers,pid);assert view['removed']==[]
    result=transfer(client,pm_headers,pid,target,view)
    assert result.status_code==200 and result.json()['viewer_retains_access']
    assert private['id'] not in {row['id'] for row in documents(client,pm_headers,pid)['documents']}
    assert private['id'] in {row['id'] for row in documents(client,new_headers,pid)['documents']}
    with SessionLocal() as db:assert not db.query(DocumentTriggerEvent).filter_by(project_id=pid,trigger_type='member_leave').first()


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
        worker=db.get(User,people['worker1']);worker.permission_overrides={'workspace.view':False,'insights.view':True};db.commit()
    listed=client.get('/api/projects',headers=worker_headers)
    assert listed.status_code==200 and listed.headers['cache-control']=='private, no-store'
    row=next(row for row in listed.json() if row['id']==pid)
    assert row['document_attention']['overdue_count']==1
    assert row['vehicle_progress']['percent'] is None and not row['vehicle_progress']['progress_known']
    assert row['next_signoff']['code']=='6.10.1'
    assert 'PRIVATE-OVERDUE' not in json.dumps(row)
    assert client.get('/api/dashboard/overview',headers=worker_headers).status_code==403
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
    assert before.json()['weekly_plan']=={'state':'available','count':0,'items':[],'unknown_count':0,'unknown_items':[]}
    assert 'people' not in before.json() and 'quantities_by_unit' not in before.text and 'person_days' not in before.text
    assert policy(client,pm_headers,pid,'document',row).status_code==200
    after=client.get('/api/dashboard/overview',headers=admin_headers)
    assert after.status_code==200 and 'NOW-PRIVATE-ATTENTION' not in after.text
    result=client.get('/api/dashboard/statistics',headers=admin_headers).json()
    assert result['issues']=={'open':2,'critical':1}
    assert result['vehicle_progress']['quantity_unknown'] and result['vehicle_progress']['percent'] is None
    with SessionLocal() as db:db.get(User,people['admin']).permission_overrides={'insights.view':False};db.commit()
    assert client.get('/api/dashboard/statistics',headers=admin_headers).status_code==403


@pytest.mark.parametrize('change,expected',[('actor_permission',403),('actor_readonly',403),('target_inactive',400)])
def test_permission_and_recipient_changes_after_project_lock_cannot_be_cached(client,pm_headers,admin_headers,monkeypatch,change,expected):
    from app.services import project_transfer as service
    from sqlalchemy import update
    pid,people=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    view=preview(client,pm_headers,pid);original=service.lock_record
    def changed(db,project,**kwargs):
        original(db,project,**kwargs)
        if change=='actor_permission':db.execute(update(User).where(User.id==people['pm']).values(permission_overrides={'project.manage_members':False}).execution_options(synchronize_session=False))
        elif change=='actor_readonly':db.execute(update(User).where(User.id==people['pm']).values(role='readonly').execution_options(synchronize_session=False))
        else:db.execute(update(User).where(User.id==target).values(is_active=False).execution_options(synchronize_session=False))
    monkeypatch.setattr(service,'lock_record',changed)
    assert transfer(client,pm_headers,pid,target,view).status_code==expected
    with SessionLocal() as db:assert db.get(Project,pid).manager==people['pm']


def test_full_legacy_governance_row_survives_actual_encrypted_backup_and_purge(client,pm_headers,admin_headers,tmp_path):
    from app.services.project_deletion import backup_zip
    from tests.test_project_recycle_bin import _delete
    from tests.test_retention_unification import prepare,purge
    from app.services import backup_crypto as codec
    pid,people=setup_project(client,pm_headers)
    with SessionLocal() as db:
        row=ProjectGovernanceRequest(project_id=pid,project_name='原名',request_type='transfer',status='pending',
            requested_by=people['pm'],source_manager_id=people['pm'],target_manager_id=people['admin'],reason='保全原理由',review_note='保全原备注')
        db.add(row);db.commit();identity=row.id
    current=client.get('/api/projects/'+pid,headers=pm_headers).json()
    assert _delete(client,pm_headers,current).status_code==200
    recycled=client.get('/api/project-recycle-bin/projects/'+pid,headers=admin_headers).json()
    response=prepare(client,admin_headers,recycled);assert response.status_code==200,response.text
    receipt=response.json();download=client.get('/api/project-recycle-bin/backups/'+receipt['backup_id'],headers=admin_headers)
    assert download.status_code==200
    path=tmp_path/'legacy-history.agvenc';path.write_bytes(download.content);assert codec.is_encrypted(path)
    with backup_zip(path) as bundle:
        saved=json.loads(bundle.read('project-backup.json'))['records']['project_governance_requests']
        assert saved[0]['id']==identity and saved[0]['status']=='pending'
        assert saved[0]['reason']=='保全原理由' and saved[0]['review_note']=='保全原备注'
        assert saved[0]['source_manager_id']==people['pm'] and saved[0]['target_manager_id']==people['admin']
    result=purge(client,admin_headers,recycled,receipt);assert result.status_code==200,result.text
    with SessionLocal() as db:
        assert db.get(Project,pid) is None
        # Governance has no project FK by design: retired historical evidence
        # stays private and unchanged, in addition to its authenticated backup.
        retained=db.get(ProjectGovernanceRequest,identity)
        assert retained.reason=='保全原理由' and retained.status=='pending' and retained.project_id==pid


def test_statistics_known_matrix_counts_only_visible_real_vehicle_steps(client,pm_headers,admin_headers):
    from tests.test_vehicle_progress import setup_fleet
    from app.models import VehicleProgress,ProjectVehicleStep,Task,Phase,Module
    from datetime import date
    pid,units=setup_fleet(client,pm_headers,1)
    with SessionLocal() as db:
        step=db.query(ProjectVehicleStep).filter_by(project_id=pid).order_by(ProjectVehicleStep.sort_order).first()
        db.add(VehicleProgress(project_id=pid,vehicle_unit_id=units[0],step_key=step.key,is_done=True,done_on=date.today()))
        phase=Phase(project_id=pid,name='不应进入统计文本',sort_order=1);db.add(phase);db.flush()
        module=Module(project_id=pid,phase_id=phase.id,name='旧混单位工作');db.add(module);db.flush()
        db.add(Task(project_id=pid,module_id=module.id,name='1000米不应加权车辆百分比',quantity_type='fixed',target_quantity=1000,unit='米',manually_completed=True));db.commit()
    hidden=client.post('/api/projects',headers=admin_headers,json={'name':'HIDDEN-PROJECT','start_date':'2026-01-01','end_date':'2026-12-31'})
    assert hidden.status_code==200
    response=client.get('/api/dashboard/statistics',headers=pm_headers,params={'project_id':hidden.json()['id']})
    assert response.status_code==200,response.text
    result=response.json();assert result['projects']==1
    assert result['vehicle_progress']=={'target':5,'completed':1,'quantity_unknown':False,'unidentified_completed':0,'percent':20.0}
    assert 'HIDDEN-PROJECT' not in response.text and '1000米' not in response.text and 'person_days' not in response.text


def test_archive_and_unrepaired_legacy_status_remain_readonly_for_transfer(client,pm_headers,admin_headers):
    pid,_=setup_project(client,pm_headers);target,_=recipient(client,admin_headers)
    view=preview(client,pm_headers,pid)
    with SessionLocal() as db:db.get(Project,pid).status='archived';db.commit()
    assert client.get(f'/api/projects/{pid}/transfer-preview',headers=admin_headers).status_code==400
    assert transfer(client,admin_headers,pid,target,view).status_code==400
    with SessionLocal() as db:
        project=db.get(Project,pid);project.status='preparing';project.legacy_lifecycle={'requires_repair':True,'original_status':'unrecognized legacy'};db.commit()
    assert transfer(client,admin_headers,pid,target,view).status_code==400


def test_retired_approval_permission_hidden_inert_and_preserved_when_editing_other_policy(client,admin_headers,worker_headers):
    from app.services.system_permissions import has_permission
    with SessionLocal() as db:
        user=db.query(User).filter_by(username='worker1').one();identity=user.id
        user.permission_overrides={'system.governance.review':True,'historical.unknown.flag':{'retained':'original'},'project.read':True};db.commit()
        assert not has_permission(user,'system.governance.review',default=True)
    catalog=client.get('/api/permissions/catalog',headers=admin_headers)
    assert catalog.status_code==200 and 'system.governance.review' not in catalog.text and '移交审批' not in catalog.text
    current=client.get('/api/permissions/users/'+identity,headers=admin_headers).json()
    assert 'system.governance.review' not in current['overrides']
    saved=client.put('/api/permissions/users/'+identity,headers=admin_headers,json={
        'version':current['version'],'overrides':{'project.read':True,'workspace.view':False,'system.governance.review':True}})
    assert saved.status_code==200,saved.text
    with SessionLocal() as db:
        actual=db.get(User,identity)
        assert actual.permission_overrides['system.governance.review'] is True
        assert actual.permission_overrides['historical.unknown.flag']=={'retained':'original'}
    assert 'system.governance.review' not in saved.json()['overrides']
    # Hidden old values cannot be newly granted or flipped by a stale editor.
    assert client.put('/api/permissions/users/'+identity,headers=admin_headers,json={
        'version':saved.json()['version'],'overrides':{'system.governance.review':False}}).status_code==422
    with SessionLocal() as db:other=db.query(User).filter_by(username='worker2').one();other_id=other.id;version=other.permission_version or 0
    assert client.put('/api/permissions/users/'+other_id,headers=admin_headers,json={
        'version':version,'overrides':{'system.governance.review':True}}).status_code==422


def test_retired_governance_never_reappears_in_legacy_decision_read_model(client,pm_headers,admin_headers):
    pid,people=setup_project(client,pm_headers)
    with SessionLocal() as db:
        db.add(ProjectGovernanceRequest(project_id=pid,project_name='PRIVATE-HISTORY-NAME',request_type='transfer',
            requested_by=people['pm'],source_manager_id=people['pm'],target_manager_id=people['admin'],reason='PRIVATE-HISTORY-REASON',status='pending'));db.commit()
    response=client.get('/api/dashboard/decision-view',headers=admin_headers)
    assert response.status_code==410,response.text
    assert 'PRIVATE-HISTORY' not in response.text
    with SessionLocal() as db:assert db.query(ProjectGovernanceRequest).filter_by(project_id=pid).one().reason=='PRIVATE-HISTORY-REASON'


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
