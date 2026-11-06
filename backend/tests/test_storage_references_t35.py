"""Known legacy String file links remain real owners of weekly originals."""
from datetime import date,datetime
from uuid import uuid4
import pytest
from app import config,models
from app.db import SessionLocal
from .test_storage_cleanup import weekly,preview,confirm


@pytest.mark.parametrize('kind',['vehicle','checklist','acceptance'])
def test_actual_non_fk_reference_is_protected_while_same_filename_other_original_can_be_cleaned(client,admin_headers,kind):
    pid,rows=weekly(client,admin_headers)
    baseline=preview(client,admin_headers,pid);assert {row['attachment_id'] for row in baseline['candidates']}=={row[1] for row in rows[:2]}
    with SessionLocal() as db:
        db.get(models.Attachment,rows[1][1]).filename=db.get(models.Attachment,rows[0][1]).filename
        if kind=='checklist':db.add(models.ArchiveChecklist(project_id=pid,category='历史文件',item_name='原始清单来源',attachment_id=rows[0][1]))
        elif kind=='acceptance':db.add(models.AcceptanceRecord(project_id=pid,accepted_at=date(2025,1,6),attachment_id=rows[0][1]))
        db.commit()
    if kind=='vehicle':
        unit=client.post(f'/api/projects/{pid}/vehicle-units',headers=admin_headers,json={'asset_code':'REFERENCE-01'});assert unit.status_code==200,unit.text
        linked=client.post(f'/api/projects/{pid}/vehicle-units/{unit.json()["id"]}/events',headers=admin_headers,
            json={'event_type':'fault','event_date':'2025-01-06','title':'真实问题原件引用','attachment_id':rows[0][1]})
        assert linked.status_code==200,linked.text
    current=preview(client,admin_headers,pid)
    assert {row['attachment_id'] for row in current['candidates']}=={rows[1][1]}
    assert any(row['attachment_id']==rows[0][1] and '引用' in row['reason'] for row in current['protected'])
    assert confirm(client,admin_headers,pid,baseline).status_code==409
    result=confirm(client,admin_headers,pid,current);assert result.status_code==200,result.text
    assert (config.UPLOAD_DIR/rows[0][2]).is_file() and not (config.UPLOAD_DIR/rows[1][2]).exists()

