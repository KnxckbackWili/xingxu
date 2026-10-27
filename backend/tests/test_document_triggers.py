"""T24 business events create actual auditable obligations in one transaction."""
from datetime import datetime,timedelta,timezone
import pytest
from app.db import SessionLocal
from app.models import (Project,Issue,DocumentTriggerEvent,IssueSlaReceipt,ProjectDocument,DocumentVersion,ChangeLog,User,Notification)
from .test_project_documents import create,view,upload


def report(client,headers,pid,nature='normal',**fields):
    result=client.post(f'/api/projects/{pid}/issues',headers=headers,
        json={'title':'真实问题','nature':nature,'issue_type':'hardware',**fields})
    assert result.status_code==200,result.text
    return result.json()


@pytest.mark.parametrize('nature,codes',[('accident',{'6.6'}),('quality',{'6.8.1','6.8.2'})])
def test_report_generates_exact_rules_from_real_source_once(client,admin_headers,nature,codes):
    pid=create(client,admin_headers)['id'];issue=report(client,admin_headers,pid,nature,client_uuid='real-source-key-01')
    repeated=report(client,admin_headers,pid,nature,client_uuid='real-source-key-01')
    assert repeated['id']==issue['id'] and issue['issue_type']=='hardware' and issue['nature']==nature
    rows=[row for row in view(client,admin_headers,pid)['documents'] if row['trigger_event']]
    assert {row['code'] for row in rows}==codes
    start=datetime.fromisoformat(issue['created_at']).replace(tzinfo=timezone.utc)
    for row in rows:
        assert row['trigger_event']['source_id']==issue['id'] and row['trigger_event']['source_type']=='issue'
        assert datetime.fromisoformat(row['triggered_at'])==start
        assert datetime.fromisoformat(row['due_at'])==start+timedelta(hours=24)
        assert not row['due_is_estimated'] and row['due_basis']['kind']=='actual_trigger'
    if nature=='quality':assert next(row for row in rows if row['code']=='6.8.2')['required'] is False
    with SessionLocal() as db:assert db.query(DocumentTriggerEvent).filter_by(project_id=pid).count()==1


def test_nature_change_requires_management_and_records_change_time_without_rewriting_history(client,admin_headers,worker_headers,monkeypatch):
    project=create(client,admin_headers);pid=project['id']
    joined=client.put(f'/api/projects/{pid}',headers=admin_headers,json={'members':[*project['members'],'user-worker-001'],'version':project['version']})
    assert joined.status_code==200,joined.text
    issue=report(client,admin_headers,pid,assignee_id='user-worker-001')
    assert client.put('/api/issues/'+issue['id'],headers=worker_headers,json={'nature':'accident'}).status_code==403
    changed=datetime(2026,11,1,12,34,56)
    monkeypatch.setattr('app.routers.issues.utcnow',lambda:changed)
    result=client.put('/api/issues/'+issue['id'],headers=admin_headers,json={'nature':'accident','version':issue['version']})
    assert result.status_code==200,result.text
    row=next(row for row in view(client,admin_headers,pid)['documents'] if row['code']=='6.6')
    assert row['triggered_at']=='2026-11-01T12:34:56+00:00'
    assert row['trigger_event']['source_metadata']['basis']=='nature_changed'
    assert row['trigger_event']['source_metadata']['reported_at']==issue['created_at']
    assert '不代表事故实际发生日期' in row['trigger_event']['source_metadata']['note']
    assert upload(client,admin_headers,pid,[row['id']]).status_code==200
    newer=client.put('/api/issues/'+issue['id'],headers=admin_headers,json={'nature':'quality','version':result.json()['version']})
    assert newer.status_code==200
    retained=next(item for item in view(client,admin_headers,pid)['documents'] if item['id']==row['id'])
    assert retained['due_at']==row['due_at'] and retained['status']=='submitted'


def test_batch_and_offline_use_same_true_source_contract(client,admin_headers):
    pid=create(client,admin_headers)['id']
    batch=client.post(f'/api/projects/{pid}/issues/import',headers=admin_headers,json={'items':[
        {'title':'批导质量','nature':'quality','client_uuid':'batch-quality-01'},
        {'title':'批导普通','nature':'normal','client_uuid':'batch-normal-01'}]})
    assert batch.status_code==200 and batch.json()['count']==2
    payload={'ops':[{'type':'issue','client_uuid':'offline-accident-01','payload':{
        'project_id':pid,'title':'离线事故','nature':'accident'}}]}
    first=client.post('/api/worker/sync',headers=admin_headers,json=payload)
    assert first.status_code==200,first.text
    second=client.post('/api/worker/sync',headers=admin_headers,json=payload)
    assert second.status_code==200,second.text
    with SessionLocal() as db:
        assert db.query(Issue).filter_by(project_id=pid).count()==3
        assert db.query(DocumentTriggerEvent).filter_by(project_id=pid).count()==2
        assert db.query(ProjectDocument).filter(ProjectDocument.project_id==pid,ProjectDocument.trigger_ref.isnot(None)).count()==3


def test_removal_preview_and_exact_confirmation_create_one_source_per_person(client,admin_headers):
    project=create(client,admin_headers);pid=project['id']
    original=project['members'];members=original+['user-worker-001','user-worker-002']
    added=client.put(f'/api/projects/{pid}',headers=admin_headers,json={'members':members,'version':project['version']})
    assert added.status_code==200,added.text
    with SessionLocal() as db:before=db.query(ChangeLog).count()
    preview=client.get(f'/api/projects/{pid}/members/removal-preview',headers=admin_headers,
        params=[('removed_ids','user-worker-001'),('removed_ids','user-worker-002')])
    assert preview.status_code==200 and len(preview.json()['removed'])==2
    assert all(any(row['code']=='6.7' for row in person['documents']) for person in preview.json()['removed'])
    with SessionLocal() as db:assert db.query(ChangeLog).count()==before and db.query(DocumentTriggerEvent).count()==0
    request={'members':original,'version':added.json()['version']}
    assert client.put(f'/api/projects/{pid}',headers=admin_headers,json=request).status_code==409
    assert client.put(f'/api/projects/{pid}',headers=admin_headers,json={**request,'member_removal_confirmations':['user-worker-001']}).status_code==409
    removed=client.put(f'/api/projects/{pid}',headers=admin_headers,json={**request,
        'member_removal_confirmations':['user-worker-001','user-worker-002']})
    assert removed.status_code==200,removed.text
    rows=[row for row in view(client,admin_headers,pid)['documents'] if row['code']=='6.7']
    assert len(rows)==2 and len({row['trigger_ref'] for row in rows})==2
    assert {row['trigger_event']['source_id'] for row in rows}=={'user-worker-001','user-worker-002'}
    assert all(row['due_at']==row['triggered_at'] and not row['due_is_estimated'] for row in rows)
    again=client.put(f'/api/projects/{pid}',headers=admin_headers,json={'members':original,'version':removed.json()['version']})
    assert again.status_code==200
    assert len([row for row in view(client,admin_headers,pid)['documents'] if row['code']=='6.7'])==2


def test_issue_trigger_audit_failure_rolls_back_source_documents_and_issue(client,admin_headers,monkeypatch):
    pid=create(client,admin_headers)['id']
    def fail(*args,**kwargs):raise RuntimeError('source audit unavailable')
    monkeypatch.setattr('app.services.document_triggers.log_change',fail)
    with pytest.raises(RuntimeError,match='source audit unavailable'):
        client.post(f'/api/projects/{pid}/issues',headers=admin_headers,json={'title':'事故','nature':'accident'})
    with SessionLocal() as db:
        assert db.query(Issue).filter_by(project_id=pid).count()==0
        assert db.query(DocumentTriggerEvent).filter_by(project_id=pid).count()==0
        assert db.query(ProjectDocument).filter(ProjectDocument.project_id==pid,ProjectDocument.trigger_ref.isnot(None)).count()==0


def test_nature_sla_uses_elapsed_hours_configuration_closure_and_durable_dedup(client,admin_headers,monkeypatch):
    from app import config
    from app.services.report_scheduler import scan_overdue_issues
    monkeypatch.setattr(config,'ISSUE_SLA_ACCIDENT_HOURS',6)
    monkeypatch.setattr(config,'ISSUE_SLA_QUALITY_HOURS',8)
    monkeypatch.setattr(config,'ISSUE_SLA_NORMAL_HOURS',72)
    pid=create(client,admin_headers)['id'];ids=[report(client,admin_headers,pid,nature)['id'] for nature in ['normal','accident','quality']]
    now=datetime(2026,11,1,12)
    with SessionLocal() as db:
        db.get(Project,pid).status='preparing'
        for issue in db.query(Issue).filter_by(project_id=pid):issue.created_at=now-timedelta(hours=7)
        for event in db.query(DocumentTriggerEvent).filter_by(project_id=pid):event.occurred_at=now-timedelta(hours=7)
        db.get(Issue,ids[1]).status='resolved';db.commit()
        first=scan_overdue_issues(db,now=now);db.commit()
        assert first['scanned']==1 and first['notified']>=1
        notices=db.query(Notification).filter_by(ntype='issue_sla').count()
        assert scan_overdue_issues(db,now=now)['notified']==0
        assert db.query(Notification).filter_by(ntype='issue_sla').count()==notices
        db.get(Issue,ids[1]).status='closed';db.commit()
        assert scan_overdue_issues(db,now=now)['scanned']==0
        later=scan_overdue_issues(db,now=now+timedelta(hours=2));db.commit()
        assert later['scanned']==1 and later['notified']>=1
        assert {row.nature for row in db.query(IssueSlaReceipt)}=={'accident','quality'}


def test_quality_excel_preserves_date_metadata_and_can_be_submitted_as_real_6_8_1_file(client,admin_headers):
    pid=create(client,admin_headers)['id']
    issue=report(client,admin_headers,pid,extra={'feedback_date':'2024-05-08','part':'原部件','vehicle_no':'001'})
    exported=client.get(f'/api/projects/{pid}/issues/{issue["id"]}/export/quality-form',headers=admin_headers)
    assert exported.status_code==200,exported.text
    imported=client.post(f'/api/projects/{pid}/import/quality-form',headers=admin_headers,
        files={'file':('原反馈.xlsx',exported.content,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert imported.status_code==200,imported.text
    imported_issue=next(row for row in client.get(f'/api/projects/{pid}/issues',headers=admin_headers).json() if row['id']==imported.json()['id'])
    assert imported_issue['nature']=='quality' and imported_issue['extra']['feedback_date']=='2024-05-08'
    row=next(row for row in view(client,admin_headers,pid)['documents'] if row['code']=='6.8.1')
    assert row['status']=='pending' and row['latest_version'] is None
    assert row['trigger_event']['source_id']==imported_issue['id']
    assert datetime.fromisoformat(row['triggered_at']).replace(tzinfo=None)==datetime.fromisoformat(imported_issue['created_at'])
    assert upload(client,admin_headers,pid,[row['id']],data=exported.content).status_code==200
    submitted=next(item for item in view(client,admin_headers,pid)['documents'] if item['id']==row['id'])
    assert submitted['status']=='submitted'
    assert client.get('/api'+submitted['latest_version']['download_url'],headers=admin_headers).content==exported.content


def test_member_failure_rolls_back_confirmation_source_and_preserves_original_file(client,admin_headers,worker_headers,monkeypatch):
    project=create(client,admin_headers);pid=project['id'];original=project['members']
    added=client.put(f'/api/projects/{pid}',headers=admin_headers,json={'members':[*original,'user-worker-001'],'version':project['version']}).json()
    did=view(client,admin_headers,pid)['documents'][0]['id']
    assert upload(client,worker_headers,pid,[did],data=b'original member file').status_code==200
    from app.services import document_triggers
    real=document_triggers.member_events
    def fail(*args,**kwargs):
        real(*args,**kwargs)
        raise RuntimeError('later membership audit failed')
    monkeypatch.setattr(document_triggers,'member_events',fail)
    with pytest.raises(RuntimeError,match='later membership audit failed'):
        client.put(f'/api/projects/{pid}',headers=admin_headers,json={'members':original,'version':added['version'],
            'member_removal_confirmations':['user-worker-001']})
    with SessionLocal() as db:
        assert 'user-worker-001' in db.get(Project,pid).members and db.get(Project,pid).version==added['version']
        assert db.query(DocumentTriggerEvent).filter_by(project_id=pid).count()==0
        assert db.query(ProjectDocument).filter_by(project_id=pid,code='6.7').count()==0
    row=next(item for item in view(client,admin_headers,pid)['documents'] if item['id']==did)
    assert row['latest_version']['uploaded_by']=='user-worker-001'
    assert client.get('/api'+row['latest_version']['download_url'],headers=admin_headers).content==b'original member file'


def test_instantiate_rejects_fake_cross_project_type_or_time_source(client,admin_headers):
    from fastapi import HTTPException
    from app.models import ProjectDocumentDefinition
    from app.services.project_documents import instantiate
    a=create(client,admin_headers)['id'];b=create(client,admin_headers)['id'];report(client,admin_headers,b,'accident')
    with SessionLocal() as db:
        project=db.get(Project,a);rule=db.query(ProjectDocumentDefinition).filter_by(project_id=a,code='6.6').one()
        other=db.query(DocumentTriggerEvent).filter_by(project_id=b).one()
        for identity,instant in [('fake-source',datetime(2026,1,1)),(other.id,other.occurred_at)]:
            with pytest.raises(HTTPException,match='触发来源'):
                instantiate(db,project,rule,trigger_ref=identity,triggered_at=instant)
        assert db.query(ProjectDocument).filter_by(project_id=a,code='6.6').count()==0


@pytest.mark.parametrize('field,value',[('trigger_ref',[]),('id',['bad']),('trigger_type',['accident'])])
def test_portable_malformed_trigger_refs_fail_before_import_mutations(client,admin_headers,field,value):
    from app.services.project_documents import export_snapshot,parse_snapshot
    pid=create(client,admin_headers)['id'];report(client,admin_headers,pid,'accident')
    with SessionLocal() as db:
        payload=export_snapshot(db,db.get(Project,pid),db.get(User,'user-admin-001'))
        if field=='trigger_ref':payload['project_documents'][0][field]=value
        else:payload['document_trigger_events'][0][field]=value
        before=(db.query(ProjectDocument).count(),db.query(DocumentTriggerEvent).count(),db.query(ChangeLog).count())
        with pytest.raises(ValueError):parse_snapshot(payload)
        assert (db.query(ProjectDocument).count(),db.query(DocumentTriggerEvent).count(),db.query(ChangeLog).count())==before


def test_concurrent_real_source_materialization_creates_one_obligation(client,admin_headers):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.services.record_lock import lock_record
    from app.services.document_triggers import issue_event
    pid=create(client,admin_headers)['id'];iid=report(client,admin_headers,pid)['id']
    with SessionLocal() as db:
        db.get(Issue,iid).nature='accident';db.commit()
    barrier=Barrier(2)
    def run(_):
        with SessionLocal() as db:
            project=db.get(Project,pid);barrier.wait(timeout=10)
            lock_record(db,project,conflict_detail='concurrent trigger')
            event=issue_event(db,project,db.get(Issue,iid),'user-admin-001');db.commit();return event.id
    with ThreadPoolExecutor(max_workers=2) as pool:assert len(set(pool.map(run,range(2))))==1
    with SessionLocal() as db:
        assert db.query(DocumentTriggerEvent).filter_by(project_id=pid).count()==1
        assert db.query(ProjectDocument).filter_by(project_id=pid,code='6.6').count()==1


def test_retention_covers_nonempty_trigger_and_sla_receipts_before_permanent_purge(client,admin_headers):
    import json
    from .test_project_recycle_bin import _delete
    from .test_retention_unification import prepare,purge
    from app.services.project_deletion import backup_zip,_backup_path
    from app.models import ProjectPermanentBackup
    project=create(client,admin_headers);pid=project['id'];iid=report(client,admin_headers,pid,'accident')['id']
    with SessionLocal() as db:
        event=db.query(DocumentTriggerEvent).filter_by(project_id=pid).one();event_id=event.id
        receipt=IssueSlaReceipt(project_id=pid,issue_id=iid,nature='accident',sla_hours=24,
            recipient_id='user-admin-001',recipient_key='user-admin-001')
        db.add(receipt);db.commit();receipt_id=receipt.id
    assert _delete(client,admin_headers,project).status_code==200
    row=client.get(f'/api/project-recycle-bin/projects/{pid}',headers=admin_headers).json()
    response=prepare(client,admin_headers,row);assert response.status_code==200,response.text
    with SessionLocal() as db:
        path=_backup_path(db.get(ProjectPermanentBackup,response.json()['backup_id']).backup_name)
        with backup_zip(path) as bundle:records=json.loads(bundle.read('project-backup.json'))['records']
    assert records['document_trigger_events'][0]['id']==event_id
    assert records['issue_sla_receipts'][0]['id']==receipt_id
    result=purge(client,admin_headers,row,response.json());assert result.status_code==200,result.text
    with SessionLocal() as db:
        assert db.get(DocumentTriggerEvent,event_id) is None and db.get(IssueSlaReceipt,receipt_id) is None


def test_governance_transfer_confirms_and_materializes_only_actual_departing_manager(client,admin_headers,pm_headers):
    from .test_governance_lifecycle_backup import _create_user
    project=create(client,pm_headers);pid=project['id'];target=_create_user(client,admin_headers,'t24-receiver')
    preview=client.get(f'/api/projects/{pid}/transfer-preview',headers=admin_headers)
    assert preview.status_code==200 and [row['user_id'] for row in preview.json()['removed']]==[project['manager']]
    payload={'target_manager_id':target,'reason':'真实岗位移交','version':preview.json()['version']}
    assert client.post(f'/api/projects/{pid}/transfer',headers=admin_headers,json=payload).status_code==409
    with SessionLocal() as db:
        assert db.get(Project,pid).manager==project['manager'] and db.query(DocumentTriggerEvent).count()==0
    result=client.post(f'/api/projects/{pid}/transfer',headers=admin_headers,json={**payload,'member_removal_confirmations':[project['manager']]})
    assert result.status_code==200,result.text
    row=next(row for row in view(client,admin_headers,pid)['documents'] if row['code']=='6.7')
    assert row['trigger_event']['source_id']==project['manager']


def test_portable_issue_keeps_original_nature_without_forging_new_incident_or_sla(client,admin_headers):
    pid=create(client,admin_headers)['id'];issue=report(client,admin_headers,pid,'quality')
    exported=client.get(f'/api/projects/{pid}/export/json',headers=admin_headers)
    assert exported.status_code==200
    imported=client.post('/api/projects/import/json',headers=admin_headers,json=exported.json())
    assert imported.status_code==200,imported.text
    new_id=imported.json()['id']
    rows=client.get(f'/api/projects/{new_id}/issues',headers=admin_headers).json()
    assert len(rows)==1 and rows[0]['source_metadata']['original_nature']=='quality'
    assert rows[0]['source_metadata']['original_id']==issue['id'] and rows[0]['sla_due_at'] is None and rows[0]['sla_warning']
    with SessionLocal() as db:
        assert db.query(DocumentTriggerEvent).filter_by(project_id=new_id).count()==0
        assert not db.query(ProjectDocument).filter(ProjectDocument.project_id==new_id,ProjectDocument.trigger_ref.isnot(None)).first()
