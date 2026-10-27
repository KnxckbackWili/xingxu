"""旧生命周期与验收来源保全。"""

from tests.lifecycle_helpers import versioned
import pytest
from app.db import SessionLocal
from app.models import Project, ProjectPreparationItem, Task
from tests.test_project_lifecycle_boundaries import project
from tests.test_lifecycle_write_integrity import completeable_project


def ready_project(client, headers):
    from app.models import ProjectDocument, ProjectDocumentDefinition
    pid = project(client, headers, '发车资料门禁')
    with SessionLocal() as db:
        db.get(Project, pid).status = 'ready'
        # Minimal explicit document scope for these gate fixtures. Historical
        # procurement flags no longer configure dispatch authority.
        db.query(ProjectDocument).filter_by(project_id=pid, stage_key='5').delete(synchronize_session=False)
        db.query(ProjectDocumentDefinition).filter_by(project_id=pid, stage_key='5').delete(synchronize_session=False)
        db.commit()
    return pid


def accept(client, headers, pid, conclusion='accepted', day='2026-09-30'):
    response = client.post(f'/api/projects/{pid}/acceptance', headers=headers, json={
        'accepted_by_name': '甲方验收人', 'accepted_at': day, 'conclusion': conclusion})
    assert response.status_code == 200, response.text
    return response.json()


def complete(client, headers, pid):
    return client.post(f'/api/projects/{pid}/status', headers=headers, json={'status': 'completed'})


@pytest.mark.parametrize('confirmation', [None, False, True])
def test_entry_cannot_use_warning_flag_as_risk_approval(client, pm_headers, confirmation):
    pid = ready_project(client, pm_headers)
    body = {'status': 'executing', 'reason': '不是正式风险评审'}
    if confirmation is not None:
        body['confirm_warnings'] = confirmation
    response = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json=body)
    assert response.status_code == 400, response.text
    assert '风险' in response.json()['detail']['message']
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'ready'


def test_entry_accepts_current_risk_review_then_requires_new_review_after_change(client, pm_headers):
    from tests.lifecycle_helpers import approve_risk_entry
    from uuid import uuid4
    pid = ready_project(client, pm_headers)
    approve_risk_entry(client, pm_headers, pid)
    state = f'/api/projects/{pid}/status'
    assert client.post(state, headers=pm_headers, json={'status': 'executing'}).status_code == 200
    assert client.post(state, headers=pm_headers, json={'status': 'ready'}).status_code == 200
    added = client.post(f'/api/projects/{pid}/documents/requirements', headers=pm_headers, json={
        'stage_key': '5', 'code': '5.' + uuid4().hex[:8], 'name': '新增电源确认资料',
        'scope': 'project', 'timing_type': 'on_demand', 'required': True})
    assert added.status_code == 200, added.text
    assert client.post(state, headers=pm_headers, json={'status': 'executing', 'confirm_warnings': True}).status_code == 400


@pytest.mark.parametrize('required,waived,ready_allowed', [(False, False, True), (True, False, False), (True, True, True)])
def test_dispatch_required_optional_and_waived_documents_control_entry(client, pm_headers, required, waived, ready_allowed):
    from uuid import uuid4
    from tests.document_helpers import documents
    pid = ready_project(client, pm_headers)
    response = client.post(f'/api/projects/{pid}/documents/requirements', headers=pm_headers, json={
        'stage_key': '5', 'code': '5.' + uuid4().hex[:8], 'name': '当前发车资料',
        'scope': 'project', 'timing_type': 'on_demand', 'required': required})
    assert response.status_code == 200, response.text
    row = next(row for row in documents(client, pm_headers, pid)['documents'] if row['definition_id'] == response.json()['id'])
    if waived:
        changed = client.put(f'/api/projects/{pid}/documents/{row["id"]}', headers=pm_headers,
            json={'status': 'waived', 'version': row['version'], 'reason': '已核对本项目无该配置，客户明确无需此资料'})
        assert changed.status_code == 200, changed.text
    path = f'/api/projects/{pid}/documents/dispatch-review'
    manifest = client.post(path, headers=pm_headers).json()
    assert len(manifest['entry_unmet']) == (0 if ready_allowed else 1)
    response = client.post(path + '/confirm', headers=pm_headers,
        json={'conclusion': 'ready', 'review_token': manifest['review_token']})
    assert response.status_code == (200 if ready_allowed else 400), response.text
    if ready_allowed:
        assert response.json()['summary']['entry_confirmed']
        assert client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'executing'}).status_code == 200


def test_missing_dispatch_document_scope_does_not_bypass_entry_gate(client, pm_headers):
    from app.models import ProjectDocument, ProjectDocumentDefinition
    pid = ready_project(client, pm_headers)
    with SessionLocal() as db:
        assert not db.query(ProjectDocument).filter_by(project_id=pid, stage_key='5').count()
        assert not db.query(ProjectDocumentDefinition).filter_by(project_id=pid, stage_key='5').count()
    response = client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'executing'})
    assert response.status_code == 400, response.text
    assert any(row['type'] == 'entry_conditions' for row in response.json()['detail']['blockers'])


@pytest.mark.parametrize('conclusion', ['rejected', 'conditionally_accepted'])
def test_latest_result_supersedes_historical_pass_for_completion_and_archive(client, pm_headers, conclusion):
    pid, _, _ = completeable_project(client, pm_headers)
    accept(client, pm_headers, pid)
    assert complete(client, pm_headers, pid).status_code == 200
    latest = accept(client, pm_headers, pid, conclusion, '2026-10-01')
    archive = client.post(f'/api/projects/{pid}/status', headers=pm_headers,
                          json={'status': 'archived', 'retrospective': '验收结果已改变'})
    assert archive.status_code == 400, archive.text
    assert client.post(f'/api/projects/{pid}/status', headers=pm_headers, json={'status': 'acceptance'}).status_code == 200
    assert complete(client, pm_headers, pid).status_code == 400
    rows = client.get(f'/api/projects/{pid}/acceptance', headers=pm_headers).json()
    assert [row['id'] for row in rows if row['is_effective']] == [latest['id']]


def test_backdated_pass_does_not_replace_later_failure_and_same_day_recording_is_ordered(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers)
    rejected = accept(client, pm_headers, pid, 'rejected', '2026-10-01')
    accept(client, pm_headers, pid, 'accepted', '2026-09-29')
    assert complete(client, pm_headers, pid).status_code == 400
    rows = client.get(f'/api/projects/{pid}/acceptance', headers=pm_headers).json()
    assert rows[0]['id'] == rejected['id']
    passed = accept(client, pm_headers, pid, 'accepted', '2026-10-01')
    rows = client.get(f'/api/projects/{pid}/acceptance', headers=pm_headers).json()
    assert rows[0]['id'] == passed['id'] and rows[0]['is_effective']
    assert complete(client, pm_headers, pid).status_code == 200


def test_scope_change_needs_new_acceptance_but_notes_do_not(client, pm_headers):
    pid, tid, _ = completeable_project(client, pm_headers)
    accepted = accept(client, pm_headers, pid)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.description = '内部备注修改不改变范围'
        p.staffing_notes = '人员调换'
        db.commit()
    rows = client.get(f'/api/projects/{pid}/acceptance', headers=pm_headers).json()
    assert rows[0]['scope_current'] and rows[0]['scope_verified']
    with SessionLocal() as db:
        db.get(Task, tid).name = '新增范围后的安全调试'
        db.commit()
    assert complete(client, pm_headers, pid).status_code == 400
    summary = client.get(f'/api/projects/{pid}/overview', headers=pm_headers).json()['acceptance_summary']
    assert summary['latest']['id'] == accepted['id']
    assert not summary['eligible'] and not summary['latest']['scope_current']
    assert '范围' in summary['reason']
    accept(client, pm_headers, pid)
    assert complete(client, pm_headers, pid).status_code == 200


def test_legacy_acceptance_remains_history_without_fabricated_scope(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers, legacy_acceptance=True)
    response = complete(client, pm_headers, pid)
    assert response.status_code == 400, response.text
    assert '历史' in response.json()['detail']['message'] and '范围' in response.json()['detail']['message']
    rows = client.get(f'/api/projects/{pid}/acceptance', headers=pm_headers).json()
    assert len(rows) == 1 and not rows[0]['scope_verified']
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'acceptance'


@pytest.mark.parametrize('state', ['executing', 'commissioning', 'pilot', 'acceptance'])
def test_progress_evaluators_never_move_human_milestones(client, pm_headers, monkeypatch, state):
    from app.services.status_flow import advance_project_status, regress_project_status
    pid = ready_project(client, pm_headers)
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.status = state
        for percent in (0, 80, 90, 95, 100, 0):
            monkeypatch.setattr('app.services.progress.project_progress_tree', lambda *args: {'percent': percent})
            assert advance_project_status(db, p) is None
            assert regress_project_status(db, p) is None
            assert p.status == state
        db.commit()


def test_incremental_migration_preserves_unknown_legacy_acceptance_scope(client, pm_headers, upgrade_legacy_schema):
    from sqlalchemy import text, inspect
    from app.db import engine
    from app.models import AcceptanceRecord
    pid, _, _ = completeable_project(client, pm_headers, legacy_acceptance=True)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE acceptance_records DROP COLUMN scope_fingerprint'))
    upgrade_legacy_schema()
    from app.db import _alembic_sync_schema
    _alembic_sync_schema()
    with SessionLocal() as db:
        row = db.query(AcceptanceRecord).filter_by(project_id=pid).one()
        assert row.scope_fingerprint is None
        assert row.accepted_by_name == '客户代表' and row.conclusion == 'accepted'
        assert db.get(Project, pid).status == 'acceptance'
    column = next(c for c in inspect(engine).get_columns('acceptance_records') if c['name'] == 'scope_fingerprint')
    assert column['nullable'] and column['default'] is None


def test_alembic_upgrade_preserves_legacy_evidence_without_backfill(monkeypatch, tmp_path):
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config
    from app.config import BASE_DIR
    cfg = Config(str(BASE_DIR / 'alembic.ini'))
    cfg.set_main_option('script_location', str(BASE_DIR / 'migrations'))
    path = tmp_path / 'legacy-acceptance.db'
    monkeypatch.setattr('app.config.DATABASE_URL', f'sqlite:///{path}')
    command.upgrade(cfg, 'f7b3c8d2a901')
    engine = sa.create_engine(f'sqlite:///{path}')
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status) VALUES ('legacy','legacy','2026-01-01','2026-02-01','archived')"))
        connection.execute(sa.text("INSERT INTO acceptance_records (id,project_id,accepted_by_name,accepted_at,conclusion,notes) VALUES ('signature','legacy','Original customer','2026-02-01','accepted','Original evidence')"))
    command.upgrade(cfg, 'head')
    with engine.connect() as connection:
        row = connection.execute(sa.text('SELECT accepted_by_name,notes,scope_fingerprint FROM acceptance_records')).one()
        assert tuple(row) == ('Original customer', 'Original evidence', None)
        assert connection.execute(sa.text('SELECT status FROM projects')).scalar() == 'archived'
    engine.dispose()


def test_repeated_startup_migration_never_rewrites_valid_lifecycle_positions(client, pm_headers):
    from app.db import _alembic_sync_schema
    from app.services.project_lifecycle import PROJECT_STATUSES
    from datetime import date
    pid = ready_project(client, pm_headers)
    with SessionLocal() as db:
        manager = db.get(Project, pid).manager
        for status in PROJECT_STATUSES:
            db.add(Project(id='migration-' + status, name=status, manager=manager,
                           start_date=date(2026, 9, 1), end_date=date(2026, 12, 31), status=status))
        db.commit()
        for _ in range(2):
            _alembic_sync_schema()
            db.expire_all()
            assert {db.get(Project, 'migration-' + status).status for status in PROJECT_STATUSES} == set(PROJECT_STATUSES)


def test_unknown_legacy_status_remains_readable_but_cannot_be_edited(client, pm_headers):
    pid = ready_project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, pid).status = 'closed'
        db.commit()
    assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'closed'
    blocked = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'name': '不得修改旧归档'}))
    assert blocked.status_code == 400 and '历史状态' in blocked.json()['detail']
    blocked = client.post(f'/api/projects/{pid}/procurements', headers=pm_headers, json={'name': '新增'})
    assert blocked.status_code == 400 and '历史状态' in blocked.json()['detail']
    blocked = client.post(f'/api/projects/{pid}/schedule/generate', headers=pm_headers)
    assert blocked.status_code == 400 and '历史状态' in blocked.json()['detail']
    with SessionLocal() as db:
        assert db.get(Project, pid).status == 'closed'


def test_legacy_null_recorded_time_is_older_than_a_same_day_current_decision(client, pm_headers):
    from sqlalchemy import event, text
    from app.db import engine
    from app.models import AcceptanceRecord
    pid, _, _ = completeable_project(client, pm_headers, legacy_acceptance=True)
    with SessionLocal() as db:
        legacy = db.query(AcceptanceRecord).filter_by(project_id=pid).one()
        db.execute(text('UPDATE acceptance_records SET created_at=NULL WHERE id=:id'), {'id': legacy.id})
        db.commit()
    rejected = accept(client, pm_headers, pid, 'rejected')
    statements = []
    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', capture)
    try:
        rows = client.get(f'/api/projects/{pid}/acceptance', headers=pm_headers).json()
    finally:
        event.remove(engine, 'before_cursor_execute', capture)
    assert rows[0]['id'] == rejected['id'] and rows[0]['is_effective']
    # PostgreSQL's implicit DESC null ordering differs from SQLite's; make the
    # ordering explicit in executed SQL instead of trusting SQLite-only output.
    assert any('acceptance_records.created_at DESC NULLS LAST' in sql for sql in statements)
    assert complete(client, pm_headers, pid).status_code == 400


def test_document_submission_preserves_material_instruction_and_satisfies_completion(client, pm_headers):
    from tests.document_helpers import documents, upload_documents
    pid, _, _ = completeable_project(client, pm_headers, documents_data=[{'name': '验收资料', 'required': True, 'description': '必须包含原签字页', 'done': False}])
    row = next(value for value in documents(client, pm_headers, pid)['documents'] if value['name'] == '验收资料')
    definition = next(value for value in documents(client, pm_headers, pid)['definitions'] if value['id'] == row['definition_id'])
    assert definition['name'] == '验收资料'
    submitted = upload_documents(client, pm_headers, pid, [row['id']])['documents'][0]
    assert submitted['name'] == definition['name'] and submitted['required'] == definition['required']
    assert submitted['note'] == '必须包含原签字页'
    assert complete(client, pm_headers, pid).status_code == 200


def test_full_init_preserves_archived_lock_and_planning(client, pm_headers, monkeypatch):
    from app.db import init_db
    pid = ready_project(client, pm_headers)
    planning = project(client, pm_headers, '重启后计划状态')
    with SessionLocal() as db:
        db.get(Project, pid).status = 'archived'
        db.commit()
    for _ in range(2):
        init_db()
        assert client.get(f'/api/projects/{pid}', headers=pm_headers).json()['status'] == 'archived'
        assert client.get(f'/api/projects/{planning}', headers=pm_headers).json()['status'] == 'planning'
        blocked = client.put(f'/api/projects/{pid}', headers=pm_headers, json=versioned(pid, {'name': '重启不能解锁'}))
        assert blocked.status_code == 400 and '归档' in blocked.json()['detail']
