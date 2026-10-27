"""项目保留快照、归档原件及引用完整性。"""

import pytest


@pytest.mark.parametrize('case', ['missing', 'unsafe', 'legacy'])
def test_archived_file_download_refuses_missing_unsafe_and_legacy_evidence(client, admin_headers, case):
    from app.db import SessionLocal
    from app.models import ProjectArchive
    from app.routers.archives import _archive_checksum
    from app.time_utils import utcnow
    from urllib.parse import quote
    stored = '..\\outside.txt' if case == 'unsafe' else 'round6-nonexistent-file.txt'
    actor = client.get('/api/auth/me', headers=admin_headers).json()['id']
    snapshot = {} if case == 'legacy' else {
        'project': {'manager': actor},
        'records': {'attachments': [{'id': 'negative-original', 'project_id': 'retention-negative',
            'stored_name': stored, 'confidential': False, 'confidential_explicit': False,
            'confidential_user_ids': []}], 'project_documents': [],
            'project_document_definitions': [], 'document_versions': []},
        'binary_files': {'manifest': [{'stored_name': stored, 'filename': 'evidence.txt', 'sha256': '0'*64}]}}
    # Establish real public-file ownership evidence before testing disk/path
    # checks. A missing ACL proof is independently denied by T26 tests.
    with SessionLocal() as db:
        archive = ProjectArchive(project_id='retention-negative', project_name='Negative cases', snapshot=snapshot, change_logs=[], purged_at=utcnow())
        archive.checksum = _archive_checksum(archive)
        db.add(archive); db.commit()
    response = client.get(f'/api/archives/projects/retention-negative/files/{quote(stored, safe="")}', headers=admin_headers)
    assert response.status_code == (400 if case == 'unsafe' else 404), response.text


def test_retention_includes_legacy_task_checks_and_shared_phase_definitions(client, pm_headers):
    from datetime import timedelta
    from app.db import SessionLocal
    from app.models import Project, Module, Phase, Task, CheckItem, ProjectArchive
    from app.services.report_scheduler import purge_soft_deleted_projects
    from app.time_utils import utcnow
    pid = client.post('/api/projects', headers=pm_headers, json={
        'name': 'Legacy retention', 'start_date': '2026-01-01', 'end_date': '2026-12-31', 'new_vehicles': False}).json()['id']
    with SessionLocal() as db:
        phase = db.query(Phase).filter(Phase.project_id.is_(None)).first()
        phase_id = phase.id
        module = Module(project_id=pid, phase_id=phase_id, name='Legacy module'); db.add(module); db.flush()
        task = Task(project_id=pid, module_id=module.id, name='Legacy task'); db.add(task); db.flush()
        check = CheckItem(project_id=None, task_id=task.id, name='Legacy signed check', is_done=True, done_by='user-pm-001', done_at=utcnow())
        db.add(check); db.flush()
        check_id = check.id
        db.get(Project,pid).deleted_at = utcnow()-timedelta(days=31)
        db.commit()
        assert purge_soft_deleted_projects(db)['purged'] == 0
        from app.services.project_retention import project_retention_snapshot
        records = project_retention_snapshot(db, db.get(Project, pid))['records']
        assert any(row['id'] == phase_id for row in records['phases'])
        retained = next(row for row in records['check_items'] if row['id'] == check_id)
        assert retained['is_done'] is True and retained['done_by'] == 'user-pm-001'


def test_retention_preserves_original_evidence_and_verified_file_access(client, pm_headers, admin_headers, worker_headers):
    import json
    from copy import deepcopy
    from datetime import date, timedelta
    from app.db import SessionLocal
    from app.models import Project, ProjectArchive, AcceptanceRecord, ProjectReadinessReview, Attachment
    from app.services.report_scheduler import purge_soft_deleted_projects
    from app.config import UPLOAD_DIR
    from app.time_utils import utcnow
    pid = client.post('/api/projects', headers=pm_headers, json={
        'name': 'Retained evidence', 'start_date': '2026-01-01', 'end_date': '2026-12-31', 'new_vehicles': False}).json()['id']
    uid = client.get('/api/auth/me', headers=pm_headers).json()['id']
    uploaded = client.post(f"/api/projects/{pid}/documents/files", headers=pm_headers,
                           files={"file": ("evidence.txt", b"private content", "text/plain")})
    assert uploaded.status_code == 200, uploaded.text
    archived = {"attachment_id": uploaded.json()['file']['id']}
    with SessionLocal() as db:
        stored_name = db.get(Attachment, archived['attachment_id']).stored_name
        db.add(AcceptanceRecord(project_id=pid, accepted_at=date(2026,1,2), accepted_by=uid, accepted_by_name='Customer signer', conclusion='accepted', notes='RETENTION ACCEPTANCE WITNESS', attachment_id=archived['attachment_id'], created_by=uid))
        db.add(ProjectReadinessReview(project_id=pid, conclusion='risky', reviewer_id=uid, notes='RETENTION READINESS WITNESS', snapshot=[{'name':'Original gate','status':'pending'}]))
        db.get(Project, pid).deleted_at = utcnow() - timedelta(days=31)
        db.commit()
        assert purge_soft_deleted_projects(db)['purged'] == 0
        from tests.legacy_project_deletion import legacy_archive_snapshot
        archive = legacy_archive_snapshot(db, db.get(Project, pid))
        db.delete(db.get(Project, pid)); db.commit()
        text = json.dumps(archive.snapshot)
        assert 'RETENTION ACCEPTANCE WITNESS' in text and 'RETENTION READINESS WITNESS' in text
        assert 'PRIVATE CHAT' not in text and 'password_hash' not in text and 'token_hash' not in text
        records = archive.snapshot['records']
        assert records['acceptance_records'][0]['attachment_id'] == archived['attachment_id']
        assert records['project_readiness_reviews'][0]['reviewer_id'] == uid
        assert archive.snapshot['binary_files']['included'] is False
        assert archive.snapshot['binary_files']['retained_in_uploads'] is True
        assert archive.snapshot['restore_supported'] is False
    url = f'/api/archives/projects/{pid}/files/{stored_name}'
    assert client.get(url, headers=worker_headers).status_code == 403
    assert client.get(url, headers=pm_headers).status_code == 403
    assert client.get(url.replace(pid, 'another-project'), headers=admin_headers).status_code == 404
    response = client.get(url, headers=admin_headers)
    assert response.status_code == 200 and response.content == b'private content'
    assert client.get(f'/api/archives/projects/{pid}/verify', headers=admin_headers).json()['match'] is True
    assert client.get(url, headers=admin_headers).status_code == 200
    path = UPLOAD_DIR / stored_name
    path.write_bytes(b'changed evidence')
    assert client.get(url, headers=admin_headers).status_code == 409
    path.write_bytes(b'private content')
    with SessionLocal() as db:
        archive = db.query(ProjectArchive).filter_by(project_id=pid).one()
        snapshot = deepcopy(archive.snapshot)
        snapshot['project']['name'] = 'tampered'
        archive.snapshot = snapshot
        db.commit()
    assert client.get(url, headers=admin_headers).status_code == 409
    assert client.get(f'/api/archives/projects/{pid}/verify', headers=admin_headers).json()['match'] is False
