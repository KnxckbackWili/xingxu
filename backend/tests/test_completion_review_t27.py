"""Completion checks use closure facts, real files and explicit ordinary overrides."""
from tests.lifecycle_helpers import versioned
from datetime import date
from app.db import SessionLocal
from app.models import Project, Task, CheckItem, Issue, VehicleUnit, VehicleLifecycleEvent, ChangeLog
from app.services.lifecycle_gates import check_transition


def project_work(client, headers):
    from tests.lifecycle_helpers import setup_project
    pid, tasks = setup_project(client, headers)
    tid = tasks[0]['id']
    with SessionLocal() as db:
        project = db.get(Project, pid); project.status = 'executing'
        project.members = ['user-worker-001', 'user-worker-002']
        checks = db.query(CheckItem).filter_by(task_id=tid).all()
        for check in checks:
            check.is_safety_critical = False; check.is_done = True; check.failed = False
        check = checks[0] if checks else CheckItem(task_id=tid, project_id=pid, name='普通复核', is_safety_critical=False)
        db.add(check);db.flush();cid=check.id
        db.commit()
    return pid, tid, cid


def complete(client, headers, pid, tid, reason, *, done=True, override=None):
    """v3 work completion: reason required; ordinary failures need an explicit, versioned owner override."""
    with SessionLocal() as db:
        version = db.get(Task, tid).version or 0
    body = {'version': version, 'is_completed': done, 'reason': reason}
    if override is not None:
        body.update(override_failed=True, failed_checks=override)
    return client.put(f'/api/projects/{pid}/work-items/{tid}/completion', headers=headers, json=body)


def test_reason_required_for_failed_ordinary_check_and_exact_snapshot_is_audited(client, admin_headers):
    pid, tid, cid = project_work(client, admin_headers)
    with SessionLocal() as db:
        check=db.get(CheckItem,cid);check.failed=True;check.is_done=False;check.failed_reason='接口复测未通过';check.version=3;db.commit()
    denied=complete(client,admin_headers,pid,tid,'   ',override=[{'id':cid,'version':3}])
    assert denied.status_code==400 and '必须填写理由' in denied.text
    implicit=complete(client,admin_headers,pid,tid,'未确认覆盖')
    assert implicit.status_code==400 and '明确确认覆盖' in implicit.text
    stale=complete(client,admin_headers,pid,tid,'旧版本覆盖',override=[{'id':cid,'version':2}])
    assert stale.status_code==409
    with SessionLocal() as db:assert not db.get(Task,tid).manually_completed
    accepted=complete(client,admin_headers,pid,tid,'已隔离风险，合同约定后续独立复测',override=[{'id':cid,'version':3}])
    assert accepted.status_code==200,accepted.text
    with SessionLocal() as db:
        task=db.get(Task,tid)
        assert task.manual_check_overrides==[{'check_id':cid,'version':3,'name':db.get(CheckItem,cid).name,'failed_reason':'接口复测未通过'}]
        log=db.query(ChangeLog).filter_by(entity_id=tid,action='complete').one()
        assert log.new_value['ordinary_check_overrides']==task.manual_check_overrides
    result=client.get(f'/api/projects/{pid}/completion-review',headers=admin_headers)
    assert result.status_code==200,result.text
    override=result.json()['ordinary_check_overrides'][0]
    assert override['reason']=='已隔离风险，合同约定后续独立复测' and override['checks'][0]['still_current']


def test_changed_failure_does_not_inherit_a_previous_override(client,admin_headers):
    pid,tid,cid=project_work(client,admin_headers)
    with SessionLocal() as db:
        c=db.get(CheckItem,cid);c.failed=True;c.is_done=False;c.failed_reason='第一次失败';db.commit();version=c.version or 0
    assert complete(client,admin_headers,pid,tid,'明确覆盖第一次失败',override=[{'id':cid,'version':version}]).status_code==200
    with SessionLocal() as db:
        c=db.get(CheckItem,cid);c.version=(c.version or 0)+1;c.failed_reason='新出现的失败';db.commit()
        assert any(row.type=='tasks' for row in check_transition(db,db.get(Project,pid),'completed'))
    response=client.get(f'/api/projects/{pid}/completion-review',headers=admin_headers)
    assert response.json()['ordinary_check_overrides'][0]['checks'][0]['still_current'] is False


def test_safety_failure_can_never_be_overridden_and_reopen_clears_active_snapshot(client,admin_headers):
    pid,tid,cid=project_work(client,admin_headers)
    with SessionLocal() as db:
        c=db.get(CheckItem,cid);c.failed=True;c.is_done=False;c.is_safety_critical=True;db.commit();version=c.version or 0
    response=complete(client,admin_headers,pid,tid,'任何理由都不能覆盖安全',override=[{'id':cid,'version':version}])
    assert response.status_code==400 and '必需检查尚未满足' in response.text
    with SessionLocal() as db:
        c=db.get(CheckItem,cid);c.is_safety_critical=False;db.commit()
    assert complete(client,admin_headers,pid,tid,'明确覆盖普通失败',override=[{'id':cid,'version':version}]).status_code==200
    assert complete(client,admin_headers,pid,tid,'复测前重新打开',done=False).status_code==200
    with SessionLocal() as db:
        t=db.get(Task,tid);assert not t.manually_completed and t.manual_check_overrides==[]
        assert db.query(ChangeLog).filter_by(entity_id=tid,action='complete').one().new_value['ordinary_check_overrides']


def test_resolved_issue_and_open_vehicle_fault_are_independent_blockers_and_preview_is_read_only(client,admin_headers):
    pid,tid,cid=project_work(client,admin_headers)
    with SessionLocal() as db:
        issue=Issue(project_id=pid,title='已解决待确认',status='resolved',reporter_id='user-worker-001');db.add(issue)
        unit=VehicleUnit(project_id=pid,asset_code='AGV-01');db.add(unit);db.flush()
        fault=VehicleLifecycleEvent(project_id=pid,vehicle_unit_id=unit.id,event_type='fault',event_date=date.today(),title='驱动故障',description='尚未关闭',is_closed=False);db.add(fault);db.commit()
        issue_id,fault_id=issue.id,fault.id;before=db.query(ChangeLog).count();version=db.get(Project,pid).version
    preview=client.get(f'/api/projects/{pid}/completion-review',headers=admin_headers)
    assert preview.status_code==200,preview.text
    assert {'issues','vehicle_faults'} <= {row['type'] for row in preview.json()['blockers']}
    with SessionLocal() as db:
        assert db.query(ChangeLog).count()==before and db.get(Project,pid).version==version and not db.dirty
        db.get(Issue,issue_id).status='closed';db.get(VehicleLifecycleEvent,fault_id).is_closed=True;db.commit()
        assert not ({'issues','vehicle_faults'} & {row.type for row in check_transition(db,db.get(Project,pid),'completed')})


def test_assigned_handler_cannot_close_or_cancel_but_reporter_can(client,admin_headers,worker_headers):
    pid,_,_=project_work(client,admin_headers)
    handler_login=client.post('/api/auth/login',json={'username':'worker2','password':'worker123'})
    handler={'Authorization':'Bearer '+handler_login.json()['access_token']}
    with SessionLocal() as db:
        issue=Issue(project_id=pid,title='等待报告人确认',status='resolved',reporter_id='user-worker-001',assignee_id='user-worker-002');db.add(issue);db.commit();iid=issue.id
    for status in ('closed','cancelled'):
        result=client.put(f'/api/issues/{iid}',headers=handler,json=versioned(iid, {'status':status,'resolution':'处理人试图自己闭环'}, 'Issue'))
        assert result.status_code==403,result.text
    result=client.put(f'/api/issues/{iid}',headers=worker_headers,json=versioned(iid, {'status':'closed'}, 'Issue'))
    assert result.status_code==200,result.text
    with SessionLocal() as db:assert db.get(Issue,iid).status=='closed'


def test_selected_package_contains_only_selected_latest_files_and_exact_hashes(client,admin_headers):
    import hashlib,io,json
    from zipfile import ZipFile
    from tests.test_project_documents import create,view,upload
    pid=create(client,admin_headers)['id'];rows=view(client,admin_headers,pid)['documents'][:3]
    assert upload(client,admin_headers,pid,[rows[0]['id'],rows[1]['id']],data=b'old shared file').status_code==200
    assert upload(client,admin_headers,pid,[rows[0]['id']],data=b'new selected file').status_code==200
    assert upload(client,admin_headers,pid,[rows[2]['id']],data=b'unselected private content').status_code==200
    result=client.post(f'/api/projects/{pid}/documents/package',headers=admin_headers,json={'document_ids':[rows[0]['id']]})
    assert result.status_code==200,result.text
    with ZipFile(io.BytesIO(result.content)) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        assert [row['document_id'] for row in manifest['documents']]==[rows[0]['id']]
        assert len(manifest['files'])==1 and len(archive.namelist())==2
        file=manifest['files'][0]
        assert archive.read(file['archive_path'])==b'new selected file'
        assert file['sha256']==hashlib.sha256(b'new selected file').hexdigest()
    result=client.post(f'/api/projects/{pid}/documents/package',headers=admin_headers,json={'document_ids':[rows[0]['id'],rows[1]['id']]})
    assert result.status_code==200
    with ZipFile(io.BytesIO(result.content)) as archive:
        assert len(json.loads(archive.read('manifest.json'))['files'])==2


def test_package_rejects_missing_file_and_cross_project_atomically(client,admin_headers):
    from tests.test_project_documents import create,view,upload
    pid=create(client,admin_headers)['id'];other=create(client,admin_headers)['id']
    row=view(client,admin_headers,pid)['documents'][0];foreign=view(client,admin_headers,other)['documents'][0]
    path=f'/api/projects/{pid}/documents/package'
    assert client.post(path,headers=admin_headers,json={'document_ids':[row['id']]}).status_code==409
    assert upload(client,admin_headers,pid,[row['id']]).status_code==200
    assert client.post(path,headers=admin_headers,json={'document_ids':[row['id'],foreign['id']]}).status_code==404
    assert client.post(path,headers=admin_headers,json={'document_ids':[row['id'],row['id']]}).status_code==422


def test_readonly_export_remains_available_but_confidential_selection_is_denied(client,admin_headers,worker_headers):
    from tests.test_project_documents import create,view,upload
    from app.models import User,ProjectDocument,Attachment,DocumentVersion
    pid=create(client,admin_headers)['id'];row=view(client,admin_headers,pid)['documents'][0]
    result=upload(client,admin_headers,pid,[row['id']]);assert result.status_code==200
    with SessionLocal() as db:
        db.get(User,'user-worker-001').role='readonly';db.get(Project,pid).members=['user-worker-001'];db.commit()
    path=f'/api/projects/{pid}/documents/package'
    assert client.post(path,headers=worker_headers,json={'document_ids':[row['id']]}).status_code==200
    with SessionLocal() as db:
        db.get(ProjectDocument,row['id']).confidential=True;db.get(Attachment,result.json()['file']['id']).confidential=True;db.commit()
    response=client.post(path,headers=worker_headers,json={'document_ids':[row['id']]})
    assert response.status_code==403 and 'application/zip' not in response.headers.get('content-type','')


def test_new_schema_matches_model_and_legacy_completion_never_invents_override_consent(client,admin_headers):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.db import Base,engine
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection,opts={'compare_server_default':True}),Base.metadata)==[]
    pid,tid,cid=project_work(client,admin_headers)
    with SessionLocal() as db:
        task=db.get(Task,tid);task.manually_completed=True;task.manual_completed_reason='原历史完成理由'
        check=db.get(CheckItem,cid);check.failed=True;check.is_done=False;db.commit()
        assert task.manual_check_overrides==[]
        assert any(row.type=='tasks' for row in check_transition(db,db.get(Project,pid),'completed'))


def test_acceptance_attachment_satisfies_7_1_with_real_file_and_no_duplicate_version(client,admin_headers):
    from tests.test_project_documents import create,view,upload
    from app.models import AcceptanceRecord,DocumentVersion
    pid=create(client,admin_headers)['id'];signature=next(row for row in view(client,admin_headers,pid)['documents'] if row['code']=='7.1')
    file=upload(client,admin_headers,pid,data=b'customer signature').json()['file']
    with SessionLocal() as db:db.get(Project,pid).status='acceptance';db.commit()
    body={'accepted_by_name':'客户代表','accepted_at':date.today().isoformat(),'conclusion':'accepted','attachment_id':file['id']}
    for _ in range(2):
        response=client.post(f'/api/projects/{pid}/acceptance',headers=admin_headers,json=body)
        assert response.status_code==200,response.text
    current=next(row for row in view(client,admin_headers,pid)['documents'] if row['id']==signature['id'])
    assert current['status']=='submitted' and current['latest_version']['attachment_id']==file['id']
    assert len(current['versions'])==1
    with SessionLocal() as db:assert db.query(AcceptanceRecord).filter_by(project_id=pid).count()==2


def test_failed_acceptance_audit_rolls_back_7_1_submission(client,admin_headers,monkeypatch):
    import pytest
    from tests.test_project_documents import create,view,upload
    from app.models import AcceptanceRecord,DocumentVersion,ProjectDocument
    pid=create(client,admin_headers)['id'];signature=next(row for row in view(client,admin_headers,pid)['documents'] if row['code']=='7.1')
    file=upload(client,admin_headers,pid,data=b'customer signature').json()['file']
    with SessionLocal() as db:db.get(Project,pid).status='acceptance';db.commit()
    def fail(*args,**kwargs):raise RuntimeError('audit unavailable')
    monkeypatch.setattr('app.routers.projects.log_change',fail)
    with pytest.raises(RuntimeError,match='audit unavailable'):
        client.post(f'/api/projects/{pid}/acceptance',headers=admin_headers,json={'accepted_by_name':'客户代表','accepted_at':date.today().isoformat(),'conclusion':'accepted','attachment_id':file['id']})
    with SessionLocal() as db:
        assert db.query(AcceptanceRecord).filter_by(project_id=pid).count()==0
        assert db.query(DocumentVersion).filter_by(project_document_id=signature['id']).count()==0
        assert db.get(ProjectDocument,signature['id']).status=='pending'


def test_migration_preserves_legacy_manual_completion_without_inventing_override(client, tmp_path):
    from uuid import uuid4
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text
    from app import config
    from app.db import engine
    pg = engine.dialect.name == 'postgresql'
    schema = 'manual_override_' + uuid4().hex
    if pg:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        isolated = create_engine(config.DATABASE_URL, connect_args={'options': '-csearch_path=' + schema})
    else:
        isolated = create_engine('sqlite:///' + str(tmp_path / 'legacy-completion.db'))
    cfg = Config(str(config.BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(config.BASE_DIR / 'migrations'))
    def upgrade(revision):
        with isolated.connect() as connection:
            cfg.attributes['connection'] = connection
            command.upgrade(cfg, revision)
    try:
        upgrade(ScriptDirectory.from_config(cfg).get_revision('g3a27b000001').down_revision)
        with isolated.begin() as connection:
            connection.execute(text("INSERT INTO modules(id,name) VALUES('legacy-module','原模板模块')"))
            connection.execute(text("INSERT INTO tasks(id,module_id,name,quantity_type,manually_completed,manual_completed_reason) VALUES('legacy-task','legacy-module','原模板任务','fixed',TRUE,'原历史完成理由')"))
        upgrade('g3a27b000001')
        upgrade('g3a27b000001')
        with isolated.connect() as connection:
            row = connection.execute(text("SELECT manually_completed,manual_completed_reason,manual_check_overrides FROM tasks WHERE id='legacy-task'")).one()
            assert bool(row[0]) and row[1] == '原历史完成理由' and row[2] is None
    finally:
        isolated.dispose()
        if pg:
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
