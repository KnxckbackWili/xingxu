"""HYPE-97 整体审计——已修复缺陷的回归证明测试。

每个用例对应一个已确认缺陷：
1. schedule 更新允许负数/自由状态 → 进度统计污染（已加 ge=0 / 状态枚举）
2. 现场车辆 JSON 导出丢车型链接 → 重新导入后车辆档案与车型脱钩（已补 vehicle_type/model_name 导出）
3. 快捷导入校验把 cancelled 状态问题拒之门外 → 作废问题无法原样还原（已把 cancelled 纳入白名单）
4. 交付物审核缺少 manage_plan 能力 + 无提交人即可审核（绕过 C7-4）（已加能力校验 + 必须已提交）
5. 表单类导入（生命周期表等）的 log_change 审计行未提交而丢失（已补 db.commit）
"""

from tests.lifecycle_helpers import versioned
import io
import pytest
from openpyxl import Workbook


# ===== 1. Schedule 字段约束 =====

def test_schedule_model_rejects_negative_quantity_and_freeform_status():
    from pydantic import ValidationError
    from app.routers.schedules import ScheduleUpdate
    with pytest.raises(ValidationError):
        ScheduleUpdate(planned_quantity=-1)
    with pytest.raises(ValidationError):
        ScheduleUpdate(status="weekend")
    ok = ScheduleUpdate(planned_quantity=0, status="done")
    assert ok.planned_quantity == 0
    assert ok.status == "done"


def _project(client, pm_headers, name="审计修复项目"):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"})
    assert r.status_code == 200, r.json()
    return r.json()["id"]


# ===== 2. 现场车辆 JSON round-trip 保留车型链接 =====

def test_vehicle_unit_roundtrip_preserves_vehicle_link(client, pm_headers):
    pid = _project(client, pm_headers, "整车链接导出")
    v = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                    json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2}).json()
    unit = client.post(f"/api/projects/{pid}/vehicle-units", headers=pm_headers,
                       json={"asset_code": "AGV-001", "fleet_no": "1",
                             "current_stage": "planned", "vehicle_id": v["id"]}).json()
    assert unit["vehicle_id"] == v["id"], "源项目车辆档案应已链接车型"

    snapshot = client.get(f"/api/projects/{pid}/export/json", headers=pm_headers).json()
    assert len(snapshot["vehicle_units"]) == 1
    # 修复点：导出的现场车辆必须带车型/型号，否则导入时无法 relink
    assert snapshot["vehicle_units"][0]["vehicle_type"] == "潜伏式"
    assert snapshot["vehicle_units"][0]["model_name"] == "AGV-500"

    snapshot["project"]["name"] = "整车链接导入"
    new_id = client.post("/api/projects/import/json", headers=pm_headers, json=snapshot).json()["id"]

    units = client.get(f"/api/projects/{new_id}/vehicle-units", headers=pm_headers).json()
    assert len(units) == 1
    assert units[0]["vehicle_type"] == "潜伏式"
    assert units[0]["model_name"] == "AGV-500"
    assert units[0]["vehicle_id"], "导入后现场车辆必须重新链接到新项目车型，而不是悬空"


# ===== 3. cancelled 问题可被快捷导入原样还原 =====

def test_quick_import_accepts_cancelled_issue(client, pm_headers):
    pid = _project(client, pm_headers, "作废问题导出")
    issue = client.post(f"/api/projects/{pid}/issues", headers=pm_headers,
                        json={"title": "已作废的问题"}).json()
    from app.db import SessionLocal
    from app.models import Issue
    db = SessionLocal()
    try:
        row = db.get(Issue, issue["id"])
        row.status = "cancelled"
        db.commit()
    finally:
        db.close()

    snapshot = client.get(f"/api/projects/{pid}/export/json", headers=pm_headers).json()
    assert any(i["status"] == "cancelled" for i in snapshot["issues"])

    snapshot["project"]["name"] = "作废问题导入"
    r = client.post("/api/projects/import/json", headers=pm_headers, json=snapshot)
    assert r.status_code == 200, r.text
    new_id = r.json()["id"]
    issues = client.get(f"/api/projects/{new_id}/issues", headers=pm_headers).json()
    assert any(i["title"] == "已作废的问题" and i["status"] == "cancelled" for i in issues)


# ===== 4. 交付物审核能力校验 + 必须先提交 =====

def _setup_plan(client, pm_headers, pid):
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": ["mod-03"]})
    assert r.status_code == 200, r.json()


def _add_worker(client, pm_headers, worker_headers, pid):
    wid = client.get("/api/auth/me", headers=worker_headers).json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    members = list(r.json()["members"])
    if wid not in members:
        members.append(wid)
        r = client.put(f"/api/projects/{pid}", headers=pm_headers, json=versioned(pid, {"members": members}))
        assert r.status_code == 200, r.json()
    return wid




def test_document_review_requires_manage_plan_and_real_submitted_version(client, pm_headers, worker_headers):
    from tests.document_helpers import documents, upload_documents
    pid = _project(client, pm_headers, '资料版本审核门禁')
    wid = _add_worker(client, pm_headers, worker_headers, pid)
    row = documents(client, pm_headers, pid)['documents'][0]
    path = f'/api/projects/{pid}/documents/{row["id"]}/versions/missing/review'
    assert client.post(path, headers=pm_headers, json={'decision': 'approved'}).status_code == 404
    submitted = upload_documents(client, worker_headers, pid, [row['id']])['documents'][0]
    version = submitted['versions'][0]
    path = f'/api/projects/{pid}/documents/{row["id"]}/versions/{version["id"]}/review'
    assert client.post(path, headers=worker_headers, json={'decision': 'approved'}).status_code == 403
    reviewed = client.post(path, headers=pm_headers, json={'decision': 'approved'})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()['uploaded_by'] == wid
    metadata = reviewed.json()['review_metadata']['latest_review']
    assert metadata['decision'] == 'approved' and metadata['by'] == client.get('/api/auth/me', headers=pm_headers).json()['id']


# ===== 5. 生命周期表导入写审计行（此前 log_change 后缺 db.commit 被丢弃） =====

def _lifecycle_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["序号", "项目名称", "车辆型号", "车辆编号", "车号", "出现过的问题", "问题描述", "解决方法", "记录人", "记录时间", "问题分类"])
    ws.append(["1", "旧项目", "潜伏式", "77BC00180", "2",
               "光通信接线接错", "现象A", "更换光通信", "施泽辉", "2023/5/4", "硬件问题"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def test_lifecycle_import_writes_audit_row(client, pm_headers):
    pid = _project(client, pm_headers, "导入审计项目")
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                    files={"file": ("生命周期表.xlsx", _lifecycle_xlsx(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    from app.db import SessionLocal
    from app.models import ChangeLog
    db = SessionLocal()
    try:
        rows = db.query(ChangeLog).filter(
            ChangeLog.project_id == pid,
            ChangeLog.entity_type == "vehicle_unit",
            ChangeLog.action == "import",
        ).all()
        assert len(rows) == 1, "导入后应有一条 'import' 审计记录"
    finally:
        db.close()


# ===== 6. AI Token expires_at 字符串解析（此前直接赋给 DateTime 列导致 500） =====

def test_ai_token_create_parses_expiry_and_rejects_invalid(client, admin_headers, pm_headers):
    pm_id = client.get("/api/auth/me", headers=pm_headers).json()["id"]
    r = client.post("/api/ai/internal/tokens", headers=admin_headers, json={
        "name": "限时Token", "user_id": pm_id, "scopes": ["projects:read"],
        "expires_at": "2026-12-31T23:59:59Z"})
    assert r.status_code == 200, r.text
    assert r.json()["expires_at"] is not None, "expires_at 应被解析并落库为时间"
    r2 = client.post("/api/ai/internal/tokens", headers=admin_headers, json={
        "name": "坏Token", "user_id": pm_id, "scopes": ["projects:read"],
        "expires_at": "not-a-date"})
    assert r2.status_code == 400, r2.text
