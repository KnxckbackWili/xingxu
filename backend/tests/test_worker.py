"""Worker workbench tests."""

from app.time_utils import today_in


def _setup(client, pm_headers, worker_id="user-worker-001"):
    """Project with tasks + schedule + worker member."""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "现场测试项目",
        "status": "planning",
        "timezone": "Asia/Shanghai",
        "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30",
    })
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    # Add worker as member
    members = [worker_id]
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": members})
    # Schedule
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200
    issued = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert issued.status_code == 200, issued.text
    return pid


def test_worker_sees_today_tasks(client, pm_headers, worker_headers):
    _setup(client, pm_headers)
    r = client.get("/api/worker/today", headers=worker_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["date"] == today_in("Asia/Shanghai").isoformat()
    # Worker1 is a member, should see the tasks for today
    # (schedule may start after today; check response shape instead of count)
    assert "items" in data


def test_worker_submits_report(client, pm_headers, worker_headers):
    pid = _setup(client, pm_headers)
    # Find a scheduled task with planned > 0
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    entry = next((e for e in entries if e["planned_quantity"] > 0), None)
    assert entry is not None

    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"],
        "schedule_entry_id": entry["id"],
        "work_date": entry["work_date"],
        "completed_quantity": 1,
        "note": "已完成1台",
        "client_uuid": "test-uuid-0001",
    })
    assert r.status_code == 200, r.json()
    assert r.json()["accepted"] is True

    # Duplicate submit → ignored
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"],
        "schedule_entry_id": entry["id"],
        "work_date": entry["work_date"],
        "completed_quantity": 1,
        "client_uuid": "test-uuid-0001",
    })
    assert r.status_code == 200
    assert r.json()["accepted"] is False


def test_worker_cannot_overfill(client, pm_headers, worker_headers):
    pid = _setup(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    entry = next((e for e in entries if e["planned_quantity"] > 0), None)

    # Find target of this task
    r = client.get(f"/api/projects/{pid}/tree", headers=pm_headers)
    tree = r.json()
    target = None
    for ph in tree:
        for m in ph["modules"]:
            for t in m["tasks"]:
                if t["id"] == entry["task_id"]:
                    target = t["target_quantity"]

    # Fill over the target → 400
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"],
        "schedule_entry_id": entry["id"],
        "work_date": entry["work_date"],
        "completed_quantity": (target or 1) + 100,
        "client_uuid": "test-uuid-0002",
    })
    assert r.status_code == 400


def test_worker_records(client, pm_headers, worker_headers):
    _setup(client, pm_headers)
    r = client.get("/api/worker/records", headers=worker_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_batch_sync_dedupe(client, pm_headers, worker_headers):
    pid = _setup(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    entry = next((e for e in entries if e["planned_quantity"] > 0), None)

    # Same client_uuid twice → one synchronized UUID, no permanent queue item.
    payload = [
        {"task_id": entry["task_id"], "schedule_entry_id": entry["id"],
         "work_date": entry["work_date"], "completed_quantity": 1,
         "client_uuid": "sync-uuid-001"},
        {"task_id": entry["task_id"], "schedule_entry_id": entry["id"],
         "work_date": entry["work_date"], "completed_quantity": 1,
         "client_uuid": "sync-uuid-001"},
    ]
    r = client.post("/api/worker/sync", headers=worker_headers, json={"reports": payload})
    assert r.status_code == 200
    assert len(r.json()["accepted"]) == 1
    assert len(r.json()["rejected"]) == 0

    # Simulate a lost first response: retrying an already persisted UUID is
    # still synchronized and must be removable from the device queue.
    r = client.post("/api/worker/sync", headers=worker_headers, json={"reports": payload[:1]})
    assert r.status_code == 200
    assert r.json()["accepted"] == ["sync-uuid-001"]
    assert r.json()["rejected"] == []


def test_worker_can_retract_today_report(client, pm_headers, worker_headers):
    """Worker retracts own report from today; cannot touch others'."""
    pid = _setup(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = next(e for e in r.json() if e["planned_quantity"] > 0)

    # Submit (work_date = today so it can be retracted)
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"],
        "schedule_entry_id": entry["id"],
        "work_date": today_in("Asia/Shanghai").isoformat(),
        "completed_quantity": 1,
        "client_uuid": "retract-0001",
    })
    rid = r.json()["id"]

    # Retract
    r = client.delete(f"/api/worker/reports/{rid}", headers=worker_headers)
    assert r.status_code == 200
    assert "撤回" in r.json()["message"]

    # Double retract → 404
    r = client.delete(f"/api/worker/reports/{rid}", headers=worker_headers)
    assert r.status_code == 404


def test_worker_cannot_retract_others_report(client, pm_headers, worker_headers):
    pid = _setup(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = next(e for e in r.json() if e["planned_quantity"] > 0)
    # worker1 submits (today, so retractable in principle)
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"],
        "schedule_entry_id": entry["id"],
        "work_date": today_in("Asia/Shanghai").isoformat(),
        "completed_quantity": 1,
        "client_uuid": "retract-0002",
    })
    rid = r.json()["id"]
    # worker2 tries to retract it
    w2 = client.post("/api/auth/login", json={"username": "worker2", "password": "worker123"})
    h2 = {"Authorization": f"Bearer {w2.json()['access_token']}"}
    r = client.delete(f"/api/worker/reports/{rid}", headers=h2)
    assert r.status_code == 404


def _tree_task_with_checkitems(client, pid, headers):
    """First task in the project tree that carries check items."""
    tree = client.get(f"/api/projects/{pid}/tree", headers=headers).json()
    for ph in tree:
        for m in ph.get("modules", []):
            for t in m.get("tasks", []):
                if t.get("check_items"):
                    return t
    return None


def test_batch_sync_offline_checkitem(client, pm_headers, worker_headers):
    """C5-5：离线队列支持检查项三态——不通过/原因持久化落库。"""
    pid = _setup(client, pm_headers)
    task = _tree_task_with_checkitems(client, pid, pm_headers)
    assert task is not None
    cid = task["check_items"][0]["id"]

    r = client.post("/api/worker/sync", headers=worker_headers, json={
        "ops": [{
            "type": "checkitem",
            "client_uuid": "offline-ci-0001",
            "payload": {"project_id": pid, "check_item_id": cid,
                        "body": {"failed": True, "failed_reason": "离线实测不通过"}},
        }],
    })
    assert r.status_code == 200, r.json()
    assert "offline-ci-0001" in r.json()["accepted"]

    found = None
    tree = client.get(f"/api/projects/{pid}/tree", headers=pm_headers).json()
    for ph in tree:
        for m in ph.get("modules", []):
            for t in m.get("tasks", []):
                for ci in t.get("check_items", []):
                    if ci["id"] == cid:
                        found = ci
    assert found is not None
    assert found["failed"] is True
    assert found["failed_reason"] == "离线实测不通过"


def test_unmatched_legacy_offline_document_preserves_uuid_payload_and_has_no_receipt(client, pm_headers, worker_headers):
    from copy import deepcopy
    from app.db import SessionLocal
    from app.models import OfflineOpReceipt
    pid = _setup(client, pm_headers)
    task = _tree_task_with_checkitems(client, pid, pm_headers)
    operation = {'type': 'deliverable', 'client_uuid': 'offline-deliv-01',
        'payload': {'project_id': pid, 'task_id': task['id'], 'deliverables': [{'name': '离线交付单', 'done': True}]}}
    original = deepcopy(operation)
    for _ in range(2):
        response = client.post('/api/worker/sync', headers=worker_headers, json={'ops': [operation]})
        assert response.status_code == 200, response.text
        assert response.json()['accepted'] == [] and response.json()['rejected'] == ['offline-deliv-01']
        assert '保留原UUID和完整草稿' in response.json()['rejected_detail']['offline-deliv-01']
    assert operation == original
    with SessionLocal() as db:
        assert db.query(OfflineOpReceipt).filter_by(client_uuid='offline-deliv-01').count() == 0


def test_batch_sync_offline_issue_idempotent(client, pm_headers, worker_headers):
    """C5-5：离线问题上报走 client_uuid 幂等——重发不重复建单。"""
    pid = _setup(client, pm_headers)
    op = {"type": "issue", "client_uuid": "offline-iss-0001",
          "payload": {"project_id": pid, "title": "离线问题上报",
                      "issue_type": "hardware", "severity": "high"}}
    r = client.post("/api/worker/sync", headers=worker_headers, json={"ops": [op, op]})
    assert r.status_code == 200, r.json()
    # 同 uuid 重复发送只算一条 accepted（_accept 去重），且不重复建单
    assert r.json()["accepted"] == ["offline-iss-0001"]

    issues = client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json()
    matching = [i for i in issues if i["title"] == "离线问题上报"]
    assert len(matching) == 1
    assert matching[0]["severity"] == "high"


def test_batch_sync_rejected_detail(client, pm_headers, worker_headers):
    """C5-6：被拒离线条目返回原因，前端被拒列表可查看/重试。"""
    pid = _setup(client, pm_headers)
    task = _tree_task_with_checkitems(client, pid, pm_headers)
    assert task is not None
    cid = task["check_items"][0]["id"]

    # 检查项不通过但没填原因 → 服务端 400 → rejected_detail 带原因
    r = client.post("/api/worker/sync", headers=worker_headers, json={
        "ops": [{
            "type": "checkitem",
            "client_uuid": "rejected-ci-001",
            "payload": {"project_id": pid, "check_item_id": cid,
                        "body": {"failed": True, "failed_reason": ""}},
        }],
    })
    assert r.status_code == 200, r.json()
    assert "rejected-ci-001" in r.json()["rejected"]
    assert "rejected-ci-001" in r.json()["rejected_detail"]
    assert "原因" in r.json()["rejected_detail"]["rejected-ci-001"]


def test_delete_my_report_status_info(client, pm_headers, worker_headers):
    """C5-4：撤回填报返回状态回退信息（status_changed/prev/new），前端提示真实结果。"""
    pid = _setup(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = next(e for e in r.json() if e["planned_quantity"] > 0)
    r = client.post("/api/worker/reports", headers=worker_headers, json={
        "task_id": entry["task_id"],
        "schedule_entry_id": entry["id"],
        "work_date": today_in("Asia/Shanghai").isoformat(),
        "completed_quantity": 1,
        "client_uuid": "retract-st-01",
    })
    rid = r.json()["id"]

    r = client.delete(f"/api/worker/reports/{rid}", headers=worker_headers)
    assert r.status_code == 200
    body = r.json()
    assert "status_changed" in body
    assert "prev_status" in body
    assert "new_status" in body


# ===== HYPE-99：离线批处理逐项事务/错误隔离/幂等 =====

def _find_checkitem(client, pid, headers, cid):
    tree = client.get(f"/api/projects/{pid}/tree", headers=headers).json()
    for ph in tree:
        for m in ph.get("modules", []):
            for t in m.get("tasks", []):
                for ci in t.get("check_items", []):
                    if ci["id"] == cid:
                        return ci
    return None


def test_batch_sync_rejected_item_leaves_no_partial_state(client, pm_headers, worker_headers):
    """HYPE-99：同批「先拒后成」——被拒检查项不得把 bump_version 的脏状态留给后续成功项提交。

    第一条 failed=True 但缺原因（业务拒绝，此前 bump_version 已执行 UPDATE）；
    第二条同一检查项通过。修复后逐项独立会话回滚，版本只 +1。
    """
    pid = _setup(client, pm_headers)
    task = _tree_task_with_checkitems(client, pid, pm_headers)
    assert task is not None
    cid = task["check_items"][0]["id"]
    v0 = task["check_items"][0]["version"]

    r = client.post("/api/worker/sync", headers=worker_headers, json={
        "ops": [
            {"type": "checkitem", "client_uuid": "h99-iso-rej-01",
             "payload": {"project_id": pid, "check_item_id": cid,
                         "body": {"failed": True, "failed_reason": ""}}},
            {"type": "checkitem", "client_uuid": "h99-iso-ok-01",
             "payload": {"project_id": pid, "check_item_id": cid,
                         "body": {"is_done": True}}},
        ],
    })
    assert r.status_code == 200, r.json()
    assert "h99-iso-rej-01" in r.json()["rejected"]
    assert "h99-iso-ok-01" in r.json()["accepted"]

    ci = _find_checkitem(client, pid, pm_headers, cid)
    assert ci is not None
    assert ci["version"] == v0 + 1, \
        f"被拒项的版本自增被后续成功项提交：{ci['version']} != {v0 + 1}"
    assert ci["is_done"] is True
    assert ci["failed"] is False


def test_batch_sync_malformed_item_rejected_not_500(client, pm_headers, worker_headers):
    """HYPE-99：缺字段/类型错误等坏条目只进 rejected_detail，不整批 500，且不阻断后续正常项。"""
    pid = _setup(client, pm_headers)
    r = client.post("/api/worker/sync", headers=worker_headers, json={
        "ops": [
            # 缺 check_item_id → apply 时 KeyError
            {"type": "checkitem", "client_uuid": "h99-mal-ci-01",
             "payload": {"project_id": pid, "body": {"is_done": True}}},
            # 缺 task_id → apply 时 KeyError
            {"type": "deliverable", "client_uuid": "h99-mal-dl-01",
             "payload": {"project_id": pid, "deliverables": [{"name": "x", "done": True}]}},
            # title 缺失 → IssueCreate 校验失败
            {"type": "issue", "client_uuid": "h99-mal-is-01",
             "payload": {"project_id": pid, "severity": "low"}},
            # body 类型错误 → CheckItemUpdate 校验失败
            {"type": "checkitem", "client_uuid": "h99-mal-ci-02",
             "payload": {"project_id": pid, "check_item_id": "whatever",
                         "body": {"is_done": "not-a-bool"}}},
            # 正常条目照常成功，证明批次继续执行
            {"type": "issue", "client_uuid": "h99-mal-ok-01",
             "payload": {"project_id": pid, "title": "正常问题", "severity": "low"}},
        ],
    })
    assert r.status_code == 200, r.json()
    body = r.json()
    for u in ("h99-mal-ci-01", "h99-mal-dl-01", "h99-mal-is-01", "h99-mal-ci-02"):
        assert u in body["rejected"], u
        assert u in body["rejected_detail"]
        assert body["rejected_detail"][u]
    assert "h99-mal-ok-01" in body["accepted"]
    assert body["rejected_detail"]["h99-mal-ci-01"].startswith("请求不完整")


def test_batch_sync_retry_all_op_types_idempotent(client, pm_headers, worker_headers):
    """HYPE-99：report/checkitem/deliverable/issue 四种离线条目在「首响应丢失重发」时都被幂等吸收。

    重试整批后所有 uuid 仍 accepted，且服务端不重复落库/自增/建单。
    """
    pid = _setup(client, pm_headers)
    task = _tree_task_with_checkitems(client, pid, pm_headers)
    assert task is not None
    cid = task["check_items"][0]["id"]
    v0 = task["check_items"][0]["version"]

    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = next(e for e in r.json() if e["planned_quantity"] > 0)

    from tests.document_helpers import legacy_document, upload_documents
    legacy_id = legacy_document(client, pm_headers, pid, task['id'], name='重试交付物')
    asset = upload_documents(client, worker_headers, pid)['file']
    ops = [
        {"type": "report", "client_uuid": "h99-rp-0001",
         "payload": {"task_id": entry["task_id"], "schedule_entry_id": entry["id"],
                     "work_date": entry["work_date"], "completed_quantity": 1,
                     "client_uuid": "h99-rp-0001"}},
        {"type": "checkitem", "client_uuid": "h99-ci-0001",
         "payload": {"project_id": pid, "check_item_id": cid,
                     "body": {"is_done": True}}},
        {"type": "deliverable", "client_uuid": "h99-dl-0001",
         "payload": {"project_id": pid, "task_id": task["id"],
                     "deliverables": [{"name": "重试交付物", "done": True, "attachment_id": asset["id"]}]}},
        {"type": "issue", "client_uuid": "h99-is-0001",
         "payload": {"project_id": pid, "title": "重试问题", "severity": "low"}},
    ]
    uuids = sorted(o["client_uuid"] for o in ops)

    r1 = client.post("/api/worker/sync", headers=worker_headers, json={"ops": ops})
    assert r1.status_code == 200, r1.json()
    assert sorted(r1.json()["accepted"]) == uuids, r1.json()

    # 第一次响应丢失 → 原样重发整批
    r2 = client.post("/api/worker/sync", headers=worker_headers, json={"ops": ops})
    assert r2.status_code == 200, r2.json()
    assert sorted(r2.json()["accepted"]) == uuids, r2.json()
    assert r2.json()["rejected"] == []

    # 重试不重复：检查项版本只 +1
    ci = _find_checkitem(client, pid, pm_headers, cid)
    assert ci["version"] == v0 + 1, ci["version"]
    # 问题只建一条
    issues = client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json()
    assert len([i for i in issues if i["title"] == "重试问题"]) == 1
    # 填报只落一条
    from app.db import SessionLocal
    from app.models import DailyProgress
    db = SessionLocal()
    try:
        n = db.query(DailyProgress).filter(
            DailyProgress.user_id == "user-worker-001",
            DailyProgress.client_uuid == "h99-rp-0001",
        ).count()
    finally:
        db.close()
    assert n == 1

    from app.models import DocumentVersion
    with SessionLocal() as db:
        assert db.query(DocumentVersion).filter_by(project_document_id=legacy_id).count() == 1


def _project_with_worker(client, pm_headers, name, worker_id="user-worker-001"):
    """Minimal project with the worker as member（离线上报 issue 只需成员资格）。"""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "start_date": "2026-08-10", "new_vehicles": False,
        "end_date": "2026-09-30"})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": [worker_id]})
    assert r.status_code == 200, r.text
    return pid


def test_batch_sync_offline_issue_same_uuid_across_projects(client, pm_headers, worker_headers):
    """HYPE-99 复审：同一用户在不同项目复用同一 client_uuid 的离线 issue 都必须落库。

    回归点：offline_op_receipts 唯一键曾为 (user_id, op_type, client_uuid)，与 issues 的
    (project_id, client_uuid) 契约不一致——第二个项目的离线问题会被 receipt 误判重复而
    静默吞掉（不建台账却返回 accepted）。纳入 project_id 后两个项目各自建单。
    """
    p1 = _project_with_worker(client, pm_headers, "receipt项目A")
    p2 = _project_with_worker(client, pm_headers, "receipt项目B")
    uuid_ = "h99-cross-receipt-01"
    r = client.post("/api/worker/sync", headers=worker_headers, json={"ops": [
        {"type": "issue", "client_uuid": uuid_,
         "payload": {"project_id": p1, "title": "项目A同键问题", "severity": "high"}},
        {"type": "issue", "client_uuid": uuid_,
         "payload": {"project_id": p2, "title": "项目B同键问题", "severity": "medium"}},
    ]})
    assert r.status_code == 200, r.json()
    assert uuid_ in r.json()["accepted"], r.json()
    assert r.json()["rejected"] == [], r.json()

    for pid, title, sev in ((p1, "项目A同键问题", "high"), (p2, "项目B同键问题", "medium")):
        issues = client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json()
        matching = [i for i in issues if i["title"] == title]
        assert len(matching) == 1, (pid, title, matching)
        assert matching[0]["severity"] == sev


def test_retraction_is_audited_and_archived_projects_are_read_only(client, pm_headers, worker_headers):
    from app.db import SessionLocal
    from app.models import Project, ChangeLog
    pid = _setup(client, pm_headers)
    entry = next(e for e in client.get(f'/api/projects/{pid}/schedule', headers=pm_headers).json() if e['planned_quantity'] > 0)
    result = client.post('/api/worker/reports', headers=worker_headers, json={
        'task_id': entry['task_id'], 'schedule_entry_id': entry['id'],
        'work_date': today_in("Asia/Shanghai").isoformat(), 'completed_quantity': 1, 'client_uuid': 'retract-audit-01',
    })
    assert result.status_code == 200
    rid = result.json()['id']
    with SessionLocal() as db:
        project = db.get(Project, pid)
        previous = project.status
        project.status = 'archived'
        db.commit()
    records = client.get('/api/worker/records', headers=worker_headers).json()
    assert next(row for row in records if row['id'] == rid)['can_retract'] is False
    assert client.delete(f'/api/worker/reports/{rid}', headers=worker_headers).status_code == 400
    with SessionLocal() as db:
        db.get(Project, pid).status = previous
        db.commit()
    assert client.delete(f'/api/worker/reports/{rid}', headers=worker_headers).status_code == 200
    with SessionLocal() as db:
        assert db.query(ChangeLog).filter_by(entity_id=rid, action='delete').count() == 1
