"""生命周期证据写入与归档锁后复核。"""

from datetime import date
import pytest
from fastapi import HTTPException
from app.db import SessionLocal
from app.models import AcceptanceRecord, CheckItem, Phase, Project, ProjectPreparationItem, Task, User
from tests.test_project_lifecycle_boundaries import project


def check_version(cid):
    with SessionLocal() as db:
        return db.get(CheckItem, cid).version or 0


def completeable_project(client, headers, *, documents_data=None, legacy_acceptance=False):
    pid = project(client, headers, '端到端生命周期')
    with SessionLocal() as db:
        p = db.get(Project, pid)
        p.status = 'acceptance'
        phase = Phase(project_id=pid, name='现场实施')
        db.add(phase); db.flush()
        task = Task(project_id=pid, phase_id=phase.id, name='安全调试',
                    quantity_type='fixed')
        db.add(task); db.flush()
        check = CheckItem(project_id=pid, task_id=task.id, name='安全保护', is_safety_critical=True,
                          is_required=True, is_applicable=True, is_done=True)
        db.add(check)
        if legacy_acceptance:
            db.add(AcceptanceRecord(project_id=pid, accepted_by_name='客户代表',
                                   accepted_at=date(2026, 9, 30), conclusion='accepted'))
        db.commit()
        ids = pid, task.id, check.id
    from tests.lifecycle_helpers import complete_vehicle_progress
    complete_vehicle_progress(client, headers, pid)
    completed = client.put(f'/api/projects/{pid}/work-items/{ids[1]}/completion', headers=headers,
        json={'version': 0, 'is_completed': True, 'reason': '已按现行工作口径核对并完成'})
    assert completed.status_code == 200, completed.text
    from tests.document_helpers import complete_documents, requirement, upload_documents
    from tests.lifecycle_helpers import register_kickoff
    register_kickoff(client, headers, pid)
    complete_documents(client, headers, pid)
    for index, item in enumerate(documents_data or []):
        item = {'name': item, 'required': True} if isinstance(item, str) else item
        row = requirement(client, headers, pid, name=item['name'], code=f'6.99.{index + 1}', required=item.get('required', True), note=item.get('description') or item.get('note') or '')
        if item.get('done'):
            upload_documents(client, headers, pid, [row['id']])
    if not legacy_acceptance:
        from tests.lifecycle_helpers import sign_current_scope
        sign_current_scope(client, headers, pid)
    return ids


def test_optional_document_does_not_prevent_completion(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers, documents_data=[
        {'name': '选填补充照片', 'required': False, 'done': False},
        {'name': '必需报告', 'required': True, 'done': True, 'status': 'approved'},
    ])
    result = client.post(f'/api/projects/{pid}/status', headers=pm_headers,
                         json={'status': 'completed'})
    assert result.status_code == 200, result.text


@pytest.mark.parametrize('state', ['pending', 'failed', 'na'])
def test_retracted_preparation_clears_completion_metadata(client, pm_headers, state):
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    created = client.post(path, headers=pm_headers, json={'name': '网络核查'}).json()
    assert client.put(path + '/' + created['id'], headers=pm_headers,
                      json={'status': 'passed'}).status_code == 200
    changed = client.put(path + '/' + created['id'], headers=pm_headers, json={'status': state})
    assert changed.status_code == 200, changed.text
    with SessionLocal() as db:
        row = db.get(ProjectPreparationItem, created['id'])
        assert row.actual_date is None
        assert row.completed_by is None
        assert row.completed_at is None


@pytest.mark.parametrize('operation', ['create', 'update'])
def test_preparation_pass_records_actor_even_with_explicit_actual_date(client, pm_headers, operation):
    pid = project(client, pm_headers)
    path = f'/api/projects/{pid}/procurements'
    payload = {'name': '检查完成', 'status': 'passed', 'actual_date': '2026-09-29'}
    if operation == 'create':
        result = client.post(path, headers=pm_headers, json=payload)
    else:
        created = client.post(path, headers=pm_headers, json={'name': '检查完成'}).json()
        result = client.put(path + '/' + created['id'], headers=pm_headers, json=payload)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        row = db.get(ProjectPreparationItem, result.json()['id'])
        assert row.actual_date == date(2026, 9, 29)
        assert row.completed_by == db.get(Project, pid).manager
        assert row.completed_at is not None


@pytest.mark.parametrize('operation', ['create', 'update', 'delete', 'import'])
def test_preparation_write_rechecks_archival_after_preload(client, pm_headers, operation):
    from app.routers import preparations as prep
    pid = project(client, pm_headers)
    assert client.post(f'/api/projects/{pid}/procurements', headers=pm_headers, json={'name': '采购核查', 'category': 'procurement'}).status_code == 200
    with SessionLocal() as stale:
        p = stale.get(Project, pid)
        actor = stale.get(User, p.manager)
        item = stale.query(ProjectPreparationItem).filter_by(project_id=pid).first()
        count = stale.query(ProjectPreparationItem).filter_by(project_id=pid).count()
        with SessionLocal() as newer:
            newer.get(Project, pid).status = 'archived'
            newer.commit()
        with pytest.raises(HTTPException) as error:
            if operation == 'create':
                prep.create_item(pid, prep.PrepItemCreate(name='归档后新增'), actor, stale)
            elif operation == 'update':
                prep.update_item(pid, item.id, prep.PrepItemUpdate(name='归档后改名'), actor, stale)
            elif operation == 'delete':
                prep.delete_item(pid, item.id, actor, stale)
            elif operation == 'seed':
                prep.seed_items(pid, actor, stale)
            else:
                prep.import_procurements(pid, prep.ProcurementImportBody(), actor, stale)
        assert error.value.status_code == 400
        stale.rollback()
    with SessionLocal() as db:
        assert db.query(ProjectPreparationItem).filter_by(project_id=pid).count() == count


@pytest.mark.parametrize('operation', ['acceptance'])
def test_completion_evidence_rechecks_archival_after_preload(client, pm_headers, operation):
    from app.routers.projects import create_acceptance, AcceptanceCreate
    pid = project(client, pm_headers)
    with SessionLocal() as setup:
        setup.get(Project, pid).status = 'completed'
        setup.commit()
    with SessionLocal() as stale:
        p = stale.get(Project, pid)
        actor = stale.get(User, p.manager)
        with SessionLocal() as newer:
            newer.get(Project, pid).status = 'archived'
            newer.commit()
        with pytest.raises(HTTPException) as error:
            if operation == 'acceptance':
                create_acceptance(pid, AcceptanceCreate(accepted_by_name='客户', accepted_at=date(2026, 9, 30)), actor, p, stale)
        assert error.value.status_code == 400
        stale.rollback()
    with SessionLocal() as db:
        assert db.query(AcceptanceRecord).filter_by(project_id=pid).count() == 0


@pytest.mark.parametrize('prior', ['preparing'])
def test_pausing_pre_execution_project_does_not_enable_acceptance(client, pm_headers, prior):
    pid = project(client, pm_headers)
    with SessionLocal() as db:
        db.get(Project, pid).status = prior
        db.commit()
    assert client.post(f'/api/projects/{pid}/status', headers=pm_headers,
                       json={'status': 'suspended', 'reason': '准备延期'}).status_code == 200
    result = client.post(f'/api/projects/{pid}/acceptance', headers=pm_headers,
                         json={'accepted_by_name': '客户', 'accepted_at': '2026-09-30'})
    assert result.status_code == 400, result.text


def test_whitespace_is_not_acceptance_signer(client, pm_headers):
    pid, _, _ = completeable_project(client, pm_headers)
    result = client.post(f'/api/projects/{pid}/acceptance', headers=pm_headers,
                         json={'accepted_by_name': '  ', 'accepted_at': '2026-09-30'})
    assert result.status_code in (400, 422), result.text

