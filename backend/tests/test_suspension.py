"""HYPE-71 整改测试：突发停工状态 + 项目经理完成量权限 + 导出文件名。

覆盖范围：
1. 突发停工生命周期——任意运行中状态可停工、无原因拒绝、停工后现场登记被拒、
   问题仍可写、只能恢复原状态、审计留痕、旧数据无上下文字段不报错。
2. 权限——停工后在线与离线的现场登记都被拒绝；pm 仍可编辑工作项并审核资料版本。
3. 导出文件名——中文/非法字符项目名导出 Excel/JSON/ZIP 的响应头文件名包含
   安全化项目名 + 当天 YYYY-MM-DD + 正确扩展名（含 ASCII fallback）。
"""

from datetime import date
from urllib.parse import unquote


def _project(client, pm_headers, name="突发停工测试项目"):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name,
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    assert r.status_code == 200, r.json()
    return r.json()["id"]


def _set_status_direct(pid, status):
    """测试直改项目状态（绕过流转链，聚焦 suspend 校验本身）。"""
    from app.db import SessionLocal
    from app.models import Project
    with SessionLocal() as db:
        db.get(Project, pid).status = status
        db.commit()


def _setup_active(client, pm_headers, worker_headers=None, name="突发停工测试项目"):
    """On-site project with generated work items (with checks); worker optionally a member."""
    from tests.lifecycle_helpers import versioned
    pid = _project(client, pm_headers, name)
    generated = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-01"]})
    assert generated.status_code == 200, generated.text
    if worker_headers:
        me = client.get("/api/auth/me", headers=worker_headers).json()
        detail = client.get(f"/api/projects/{pid}", headers=pm_headers).json()
        r = client.put(f"/api/projects/{pid}", headers=pm_headers,
                       json=versioned(pid, {"members": [*detail["members"], me["id"]]}))
        assert r.status_code == 200, r.json()
    _set_status_direct(pid, "executing")
    return pid


def _get(client, headers, pid):
    return client.get(f"/api/projects/{pid}", headers=headers).json()


def _suspend(client, headers, pid, reason="现场突发停电，暂停施工"):
    return client.post(f"/api/projects/{pid}/status", headers=headers,
                       json={"status": "suspended", "reason": reason})


def _first_check(pid):
    from app.db import SessionLocal
    from app.models import CheckItem
    with SessionLocal() as db:
        check = db.query(CheckItem).filter_by(project_id=pid).order_by(CheckItem.id).first()
        return check.id, check.version or 0


# ===================== 突发停工生命周期 =====================

def test_any_active_status_can_suspend(client, pm_headers):
    for status in ("preparing", "ready", "executing", "acceptance"):
        pid = _project(client, pm_headers, f"可停工-{status}")
        _set_status_direct(pid, status)
        r = _suspend(client, pm_headers, pid)
        assert r.status_code == 200, (status, r.json())
        assert _get(client, pm_headers, pid)["status"] == "suspended"
        data = _get(client, pm_headers, pid)
        assert data["suspension"]["status_before"] == status
        assert data["suspension"]["reason"] == "现场突发停电，暂停施工"
        assert data["suspension"]["suspended_by_name"]


def test_cannot_suspend_from_non_running_states(client, pm_headers):
    for status in ("completed", "archived"):
        pid = _project(client, pm_headers, f"不可停工-{status}")
        _set_status_direct(pid, status)
        r = _suspend(client, pm_headers, pid)
        assert r.status_code == 400, (status, r.text)
        assert "不能进入突发停工" in r.json()["detail"]


def test_suspend_requires_reason(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers,
                    json={"status": "suspended", "reason": "  "})
    assert r.status_code == 400
    assert "停工原因" in r.json()["detail"]
    # 缺字段同样拒绝
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers,
                    json={"status": "suspended"})
    assert r.status_code == 400
    assert "停工原因" in r.json()["detail"]
    # 未真正进入停工
    assert _get(client, pm_headers, pid)["status"] == "preparing"


def test_after_suspend_field_records_rejected_online_and_offline(client, pm_headers, worker_headers):
    pid = _setup_active(client, pm_headers, worker_headers)
    cid, version = _first_check(pid)
    _suspend(client, pm_headers, pid)
    r = client.put(f"/api/projects/{pid}/check-items/{cid}", headers=worker_headers, json={"is_done": True, "version": version})
    assert r.status_code == 400, r.text
    # 离线同步同样逐项拒绝，且返回原因
    r = client.post("/api/worker/sync", headers=worker_headers, json={"ops": [{
        "type": "checkitem", "client_uuid": "suspend-sync-01",
        "payload": {"project_id": pid, "check_item_id": cid, "body": {"is_done": True, "version": version}}}]})
    assert r.status_code == 200
    assert "suspend-sync-01" in r.json()["rejected"]
    assert r.json()["rejected_detail"]["suspend-sync-01"]


def test_issues_still_writable_when_suspended(client, pm_headers):
    pid = _project(client, pm_headers)
    _suspend(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/issues", headers=pm_headers,
                    json={"title": "停工期间上报的问题", "issue_type": "other", "severity": "medium"})
    assert r.status_code == 200, r.json()
    issues = client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json()
    assert any(i["title"] == "停工期间上报的问题" for i in issues)


def test_recovery_only_to_original_status(client, pm_headers):
    pid = _project(client, pm_headers)
    _suspend(client, pm_headers, pid, "业主叫停")
    # 恢复到非原状态 → 拒绝
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "completed"})
    assert r.status_code == 400
    assert "原状态" in r.json()["detail"]
    # 恢复到原状态 → 成功，且记录恢复人/时间
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "preparing"})
    assert r.status_code == 200, r.json()
    data = _get(client, pm_headers, pid)
    assert data["status"] == "preparing"
    assert data["suspension"]["status_before"] == "preparing"
    assert data["suspension"]["resumed_by_name"]
    assert data["suspension"]["resumed_at"]


def test_suspend_recover_writes_audit(client, pm_headers):
    pid = _project(client, pm_headers)
    _suspend(client, pm_headers, pid, "客户要求暂停")
    client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "preparing"})
    logs = client.get(f"/api/projects/{pid}/logs", headers=pm_headers).json()
    details = " | ".join(l.get("detail", "") for l in logs)
    assert "突发停工" in details
    assert "客户要求暂停" in details
    assert "恢复运行" in details


def test_old_data_without_suspension_field_does_not_error(client, pm_headers):
    """旧数据无 suspension 列/字段：读取为 {}，从无上下文的 suspended 状态恢复给出明确 400。"""
    pid = _project(client, pm_headers)
    _set_status_direct(pid, "suspended")  # suspension 列默认 {}，模拟旧数据
    data = _get(client, pm_headers, pid)
    assert data["status"] == "suspended"
    assert data["suspension"] == {}
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "preparing"})
    assert r.status_code == 400
    assert "缺少停工前状态记录" in r.json()["detail"]


def test_json_export_preserves_suspension_but_new_project_import_cannot_bypass_lifecycle(client, pm_headers):
    pid = _project(client, pm_headers)
    _suspend(client, pm_headers, pid, "出口海运延误，暂停两周")
    snapshot = client.get(f"/api/projects/{pid}/export/json", headers=pm_headers).json()
    assert snapshot["project"]["status"] == "suspended"
    assert snapshot["project"]["suspension"]["reason"] == "出口海运延误，暂停两周"
    rejected = client.post("/api/projects/import/json", headers=pm_headers, json=snapshot)
    assert rejected.status_code == 400, rejected.text
    assert "新建项目导入" in rejected.json()["detail"]
    # The original remains suspended with its history; no silent status reset.
    data = _get(client, pm_headers, pid)
    assert data["status"] == "suspended"
    assert data["suspension"]["reason"] == "出口海运延误，暂停两周"
    assert data["suspension"]["status_before"] == "preparing"


# ===================== 项目经理计划与资料审核 =====================


def test_pm_manages_plan_and_reviews_another_members_document_version(client, pm_headers, worker_headers):
    from tests.document_helpers import documents, upload_documents
    pid = _setup_active(client, pm_headers, worker_headers)
    from app.db import SessionLocal
    from app.models import Task
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=pid).first()
        task_id, task_version = task.id, task.version or 0
    result = client.put(f'/api/projects/{pid}/work-items/{task_id}', headers=pm_headers, json={'name': '场地勘测（PM改名）', 'version': task_version})
    assert result.status_code == 200, result.text
    row = documents(client, pm_headers, pid)['documents'][0]
    version = upload_documents(client, worker_headers, pid, [row['id']])['documents'][0]['versions'][0]
    reviewed = client.post(f'/api/projects/{pid}/documents/{row["id"]}/versions/{version["id"]}/review', headers=pm_headers, json={'decision': 'approved'})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()['review_metadata']['latest_review']['decision'] == 'approved'


# ===================== 导出文件名 =====================

def _export_filename(client, headers, url):
    r = client.get(url, headers=headers)
    assert r.status_code == 200, r.text
    cd = r.headers["content-disposition"]
    assert "filename*=" in cd
    star = cd.split("filename*=")[1].strip()
    fname = unquote(star.split("''")[1])
    return r, fname, cd


def test_export_filename_sanitized_name_plus_date(client, pm_headers):
    today = date.today().isoformat()
    pid = _project(client, pm_headers, "华东/物流:AGV*二期")
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    for url, ext in ((f"/api/projects/{pid}/export/excel", "xlsx"),
                     (f"/api/projects/{pid}/export/json", "json"),
                     (f"/api/projects/{pid}/export/package", "zip")):
        r, fname, cd = _export_filename(client, pm_headers, url)
        assert "华东_物流_AGV_二期" in fname, fname
        assert f"_{today}." in fname, fname
        assert fname.endswith(f".{ext}"), fname
        # ASCII fallback 保留正确扩展名
        assert f'filename="project-export-{today}.{ext}"' in cd


def test_export_filename_fallback_when_name_sanitizes_empty(client, pm_headers):
    """非法字符项目名（全点）→ 安全化后为空 → 回退「项目」，日期与扩展名不变。"""
    today = date.today().isoformat()
    pid = _project(client, pm_headers, "...")
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    r, fname, cd = _export_filename(client, pm_headers, f"/api/projects/{pid}/export/json")
    assert fname.startswith("项目_"), fname
    assert fname.endswith(f"_{today}.json"), fname
