"""T24 business events create actual auditable obligations in one transaction."""
from tests.lifecycle_helpers import versioned
from datetime import datetime,timedelta,timezone
import pytest
from app.db import SessionLocal
from app.models import (Project,Issue,DocumentTriggerEvent,ProjectDocument,DocumentVersion,ChangeLog,User,Notification)
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


def test_retention_covers_nonempty_trigger_events_before_permanent_purge(client,admin_headers):
    import json
    from .test_project_recycle_bin import _delete
    from .test_retention_unification import prepare,purge
    from app.services.project_deletion import backup_zip,_backup_path
    from app.models import ProjectPermanentBackup
    project=create(client,admin_headers);pid=project['id'];report(client,admin_headers,pid,'accident')
    with SessionLocal() as db:
        event=db.query(DocumentTriggerEvent).filter_by(project_id=pid).one();event_id=event.id
    assert _delete(client,admin_headers,project).status_code==200
    row=client.get(f'/api/project-recycle-bin/projects/{pid}',headers=admin_headers).json()
    response=prepare(client,admin_headers,row);assert response.status_code==200,response.text
    with SessionLocal() as db:
        path=_backup_path(db.get(ProjectPermanentBackup,response.json()['backup_id']).backup_name)
        with backup_zip(path) as bundle:records=json.loads(bundle.read('project-backup.json'))['records']
    assert records['document_trigger_events'][0]['id']==event_id
    assert 'issue_sla_receipts' not in records
    result=purge(client,admin_headers,row,response.json());assert result.status_code==200,result.text
    with SessionLocal() as db:
        assert db.get(DocumentTriggerEvent,event_id) is None


def test_portable_issue_keeps_original_nature_without_forging_new_incident(client,admin_headers):
    pid=create(client,admin_headers)['id'];issue=report(client,admin_headers,pid,'quality')
    exported=client.get(f'/api/projects/{pid}/export/json',headers=admin_headers)
    assert exported.status_code==200
    imported=client.post('/api/projects/import/json',headers=admin_headers,json=exported.json())
    assert imported.status_code==200,imported.text
    new_id=imported.json()['id']
    rows=client.get(f'/api/projects/{new_id}/issues',headers=admin_headers).json()
    assert len(rows)==1 and rows[0]['source_metadata']['original_nature']=='quality'
    assert rows[0]['source_metadata']['original_id']==issue['id'] and 'sla_due_at' not in rows[0]
    with SessionLocal() as db:
        assert db.query(DocumentTriggerEvent).filter_by(project_id=new_id).count()==0
        assert not db.query(ProjectDocument).filter(ProjectDocument.project_id==new_id,ProjectDocument.trigger_ref.isnot(None)).first()
