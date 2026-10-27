"""文件删除事务和真实证据引用保护。"""

from datetime import date
import pytest
from app.db import SessionLocal
from app.models import Attachment, VehicleLifecycleEvent
from tests.test_execution_workflow_audit import _execution


def test_attachment_delete_commit_failure_keeps_downloadable_file(client, pm_headers, monkeypatch):
    from app.config import UPLOAD_DIR
    from sqlalchemy.orm import Session
    pid, _, _ = _execution(client)
    uploaded = client.post(f'/api/projects/{pid}/documents/files', headers=pm_headers,
                           files={'file': ('proof.txt', b'keep this evidence', 'text/plain')}).json()['file']['id']
    with SessionLocal() as db:
        stored = db.get(Attachment, uploaded).stored_name
    def broken_commit(self):
        raise RuntimeError('synthetic commit failure')
    monkeypatch.setattr(Session, 'commit', broken_commit)
    with pytest.raises(RuntimeError, match='synthetic commit failure'):
        client.delete('/api/files/' + uploaded, headers=pm_headers)
    assert (UPLOAD_DIR / stored).read_bytes() == b'keep this evidence'
    with SessionLocal() as db:
        assert db.get(Attachment, uploaded) is not None


def test_document_history_protects_file_after_explicit_withdrawal(client, pm_headers, worker_headers):
    from tests.document_helpers import requirement, upload_documents
    pid, _, _ = _execution(client)
    row = requirement(client, pm_headers, pid)
    submitted = upload_documents(client, worker_headers, pid, [row['id']], content=b'original proof')['documents'][0]
    aid = submitted['versions'][0]['attachment_id']
    assert client.delete('/api/files/' + aid, headers=pm_headers).status_code == 400
    changed = client.put(f'/api/projects/{pid}/documents/{row["id"]}', headers=worker_headers,
        json={'status': 'pending', 'reason': '需要补充记录', 'version': submitted['version']})
    assert changed.status_code == 200, changed.text
    assert changed.json()['versions'] == submitted['versions']
    assert client.delete('/api/files/' + aid, headers=pm_headers).status_code == 400
    assert client.get('/api/files/' + aid + '/download', headers=pm_headers).content == b'original proof'


@pytest.mark.parametrize('reference_kind', ['acceptance', 'archive', 'vehicle'])
def test_record_evidence_cannot_be_deleted_while_referenced(client, pm_headers, reference_kind):
    from app.models import AcceptanceRecord, ArchiveChecklist, VehicleUnit
    pid, _, _ = _execution(client)
    aid = client.post(f'/api/projects/{pid}/documents/files', headers=pm_headers,
        files={'file': ('record.txt', b'original evidence', 'text/plain')}).json()['file']['id']
    with SessionLocal() as db:
        if reference_kind == 'acceptance':
            db.add(AcceptanceRecord(project_id=pid, accepted_at=date.today(), attachment_id=aid))
        elif reference_kind == 'archive':
            db.add(ArchiveChecklist(project_id=pid, category='资料', item_name='原件', attachment_id=aid))
        else:
            unit = VehicleUnit(project_id=pid, asset_code='R6-proof'); db.add(unit); db.flush()
            event = VehicleLifecycleEvent(project_id=pid, vehicle_unit_id=unit.id, event_type='fault',
                event_date=date.today(), title='实测', attachment_id=aid, operator_id='user-pm-001')
            db.add(event); db.flush(); uid, eid = unit.id, event.id
        db.commit()
    result = client.delete('/api/files/' + aid, headers=pm_headers)
    assert result.status_code == 400, result.text
    assert client.get('/api/files/' + aid + '/download', headers=pm_headers).content == b'original evidence'
    if reference_kind == 'vehicle':
        clear = client.put(f'/api/projects/{pid}/vehicle-units/{uid}/events/{eid}', headers=pm_headers,
                           json={'attachment_id': None})
        assert clear.status_code == 200 and clear.json()['attachment_id'] is None, clear.text
        assert client.delete('/api/files/' + aid, headers=pm_headers).status_code == 200


def test_cleanup_failure_does_not_report_failed_committed_delete(client, pm_headers, monkeypatch):
    from pathlib import Path
    from app.config import UPLOAD_DIR
    pid, _, _ = _execution(client)
    aid = client.post(f'/api/projects/{pid}/documents/files', headers=pm_headers,
        files={'file': ('cleanup.txt', b'orphan safe for cleanup', 'text/plain')}).json()['file']['id']
    with SessionLocal() as db:
        stored = db.get(Attachment, aid).stored_name
    original = Path.unlink
    def deny_file(self, *args, **kwargs):
        if self.name == stored:
            raise PermissionError('synthetic cleanup failure')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', deny_file)
    result = client.delete('/api/files/' + aid, headers=pm_headers)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        assert db.get(Attachment, aid) is None
    assert (UPLOAD_DIR / stored).exists()
