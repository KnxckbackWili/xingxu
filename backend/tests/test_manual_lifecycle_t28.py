"""Human lifecycle decisions and business dates on actual submitted sign-offs."""
from tests.lifecycle_helpers import versioned
from datetime import date, datetime
import json

from app.db import SessionLocal
from app.models import Project, ProjectEvent, Attachment, DocumentVersion, Task, Module, Phase, ScheduleEntry
from app.services.project_lifecycle import PROJECT_STATUSES
from tests.document_helpers import documents, upload_documents


def create(client, headers):
    response = client.post('/api/projects', headers=headers, json={
        'name': '人工状态项目', 'start_date': '2026-01-01', 'end_date': '2026-12-31'})
    assert response.status_code == 200, response.text
    return response.json()


def state(client, headers, pid, target):
    return client.post(f'/api/projects/{pid}/status', headers=headers, json={'status': target})


def test_five_states_plus_suspension_and_new_project_cannot_skip_gates(client, admin_headers):
    # The former ready stage is merged into preparing.
    assert set(PROJECT_STATUSES) == {'preparing','executing','acceptance','completed','archived','suspended'}
    assert create(client, admin_headers)['status'] == 'preparing'
    for value in ('draft','planning','commissioning','pilot','ready','executing','completed'):
        response = client.post('/api/projects', headers=admin_headers, json={
            'name':'不得跳阶段','start_date':'2026-01-01','end_date':'2026-12-31','status':value})
        assert response.status_code == 400, (value, response.text)


def test_execution_requires_stage4_and_acceptance_requires_all_four_real_signoffs(client, admin_headers):
    pid = create(client, admin_headers)['id']
    response = state(client, admin_headers, pid, 'executing')
    assert response.status_code == 400 and response.json()['detail']['blockers'][0]['type'] == 'kickoff_documents'
    rows = documents(client, admin_headers, pid)['documents']
    upload_documents(client, admin_headers, pid, [r['id'] for r in rows if r['stage_key']=='4' and r['required']])
    response = state(client, admin_headers, pid, 'executing')
    assert response.status_code == 400 and 'kickoff_documents' not in {b['type'] for b in response.json()['detail']['blockers']}
    with SessionLocal() as db:
        db.get(Project,pid).status='executing'; db.commit()
    response = state(client, admin_headers, pid, 'acceptance')
    assert response.status_code == 400 and all(code in response.text for code in ('6.10.1','6.10.2','6.10.3','6.10.4'))
    upload_documents(client, admin_headers, pid, [r['id'] for r in rows if r['code'] in ('6.10.1','6.10.2','6.10.3','6.10.4')])
    assert state(client, admin_headers, pid, 'acceptance').status_code == 200


def test_signoff_requires_explicit_business_date_and_never_uses_upload_timestamp(client, admin_headers):
    pid=create(client,admin_headers)['id']
    sign=next(r for r in documents(client,admin_headers,pid)['documents'] if r['code']=='6.10.2')
    upload_documents(client,admin_headers,pid,[sign['id']])
    with SessionLocal() as db:
        event=db.query(ProjectEvent).filter_by(project_id=pid,event_key='commissioning_done').first()
        assert event is None or event.actual_at is None and event.actual_date is None
    result=upload_documents(client,admin_headers,pid,[sign['id']],name='signed.txt',milestone_dates=json.dumps({'commissioning_done':'2026-01-02'}))
    events=client.get(f'/api/projects/{pid}/events',headers=admin_headers).json()['events']
    event=next(r for r in events if r['event_key']=='commissioning_done')
    assert event['actual_at'] is None and event['actual_date']=='2026-01-02' and event['actual_precision']=='date'
    assert event['actual_source']['attachment_id']==result['file']['id']
    assert client.get(f'/api/projects/{pid}',headers=admin_headers).json()['status']=='preparing'


def test_wrong_event_future_date_and_conflict_reject_entire_upload_without_losing_old_time(client, admin_headers):
    from app.config import UPLOAD_DIR
    pid=create(client,admin_headers)['id']
    sign=next(r for r in documents(client,admin_headers,pid)['documents'] if r['code']=='6.10.2')
    before=set(UPLOAD_DIR.iterdir())
    for dates in ({'go_live':'2026-01-02'},{'commissioning_done':'2999-01-01'}):
        response=client.post(f'/api/projects/{pid}/documents/files',headers=admin_headers,
            files={'file':('bad.txt',b'not committed')},data={'document_ids':json.dumps([sign['id']]),'milestone_dates':json.dumps(dates)})
        assert response.status_code==400,response.text
        with SessionLocal() as db:
            assert db.query(Attachment).filter_by(project_id=pid).count()==0
            assert db.query(DocumentVersion).filter_by(project_document_id=sign['id']).count()==0
        assert set(UPLOAD_DIR.iterdir())==before
    response=client.put(f'/api/projects/{pid}/events/commissioning_done',headers=admin_headers,
        json=versioned(pid, {'actual_at':'2026-01-03T10:00:00+08:00'}))
    assert response.status_code==200,response.text
    response=client.post(f'/api/projects/{pid}/documents/files',headers=admin_headers,
        files={'file':('contradiction.txt',b'not committed')},data={'document_ids':json.dumps([sign['id']]),'milestone_dates':json.dumps({'commissioning_done':'2026-01-02'})})
    assert response.status_code==409,response.text
    with SessionLocal() as db:
        event=db.query(ProjectEvent).filter_by(project_id=pid,event_key='commissioning_done').one()
        assert event.actual_at==datetime(2026,1,3,2) and event.actual_date is None
        assert db.query(Attachment).filter_by(project_id=pid).count()==0


def test_task_complete_reopen_and_schedule_publication_never_change_project_state(client,admin_headers):
    pid=create(client,admin_headers)['id']
    with SessionLocal() as db:
        phase=Phase(project_id=pid,name='现场工作');db.add(phase);db.flush()
        module=Module(project_id=pid,phase_id=phase.id,name='工作分组');db.add(module);db.flush()
        task=Task(project_id=pid,module_id=module.id,phase_id=phase.id,name='非车辆工作',quantity_type='fixed',target_quantity=1)
        db.add(task);db.flush();tid=task.id
        db.add(ScheduleEntry(project_id=pid,task_id=tid,work_date=date(2026,1,5),assignee_id='user-worker-001',planned_quantity=1));db.commit()
    response=client.post(f'/api/projects/{pid}/schedule/confirm',headers=admin_headers)
    assert response.status_code==410,response.text  # 按日排程发布已退役
    assert client.get(f'/api/projects/{pid}',headers=admin_headers).json()['status']=='preparing'
    with SessionLocal() as db:db.get(Project,pid).status='executing';db.commit()
    for done in (True,False):
        with SessionLocal() as db:version=db.get(Task,tid).version or 0
        response=client.put(f'/api/projects/{pid}/work-items/{tid}/completion',headers=admin_headers,
                            json={'version':version,'is_completed':done,'reason':'实际现场核对'})
        assert response.status_code==200,response.text
        assert client.get(f'/api/projects/{pid}',headers=admin_headers).json()['status']=='executing'
    from app.services.status_flow import advance_project_status,regress_project_status
    with SessionLocal() as db:
        project=db.get(Project,pid);before=project.version
        assert advance_project_status(db,project) is None and regress_project_status(db,project) is None
        assert project.status=='executing' and project.version==before


def test_unrecognized_legacy_requires_explicit_admin_reset_preserving_original_value(client,admin_headers,pm_headers):
    p=create(client,admin_headers);pid=p['id']
    with SessionLocal() as db:
        project=db.get(Project,pid);project.status='suspended';project.suspension={'status_before':None}
        project.legacy_lifecycle={'original_status':'unrecognized_2x','requires_repair':True};db.commit()
    assert state(client,admin_headers,pid,'preparing').status_code==400
    body={'version':p['version'],'reason':'根据原备份与审计重新核对项目'}
    assert client.post(f'/api/projects/{pid}/lifecycle-repair',headers=pm_headers,json=body).status_code in (403,404)
    assert client.post(f'/api/projects/{pid}/lifecycle-repair',headers=admin_headers,json={**body,'reason':'  '}).status_code==400
    response=client.post(f'/api/projects/{pid}/lifecycle-repair',headers=admin_headers,json=body)
    assert response.status_code==200,response.text
    assert response.json()['status']=='preparing' and response.json()['legacy_lifecycle']['original_status']=='unrecognized_2x'
    assert not response.json()['legacy_lifecycle']['requires_repair']
    assert client.post(f'/api/projects/{pid}/lifecycle-repair',headers=admin_headers,json=body).status_code==409


def test_date_only_kickoff_creates_lifetime_and_same_submission_captures_real_deadline(client,admin_headers):
    pid=create(client,admin_headers)['id']
    rows=documents(client,admin_headers,pid)['documents']
    kickoff=next(row for row in rows if row['code']=='4.5')
    assert not any(row['code']=='9.1' for row in rows)
    upload_documents(client,admin_headers,pid,[kickoff['id']],milestone_dates=json.dumps({'internal_kickoff':'2026-01-02'}))
    rows=documents(client,admin_headers,pid)['documents']
    assert {'9.1','9.2'} <= {row['code'] for row in rows}
    sign=next(row for row in rows if row['code']=='6.10.2')
    upload_documents(client,admin_headers,pid,[sign['id']],milestone_dates=json.dumps({'commissioning_done':'2026-01-03'}))
    sign=next(row for row in documents(client,admin_headers,pid)['documents'] if row['id']==sign['id'])
    assert sign['due_at']=='2026-01-03T16:00:00+00:00' and not sign['due_is_estimated']
    assert sign['due_basis']['precision']=='date' and sign['due_basis']['actual_date']=='2026-01-03'
    # A later correction is not allowed to move already submitted deadlines.
    response=client.put(f'/api/projects/{pid}/events/commissioning_done',headers=admin_headers,json=versioned(pid, {'actual_date':'2026-01-04','reason':'核对签单更正'}))
    assert response.status_code==200,response.text
    current=next(row for row in documents(client,admin_headers,pid)['documents'] if row['id']==sign['id'])
    assert (current['due_at'],current['due_basis'])==(sign['due_at'],sign['due_basis'])
