"""HYPE-83：我的日历本人自助编辑日程（后端权限 seam 与边界）。"""

from datetime import date, timedelta


def _project_with_worker_entry(client, pm_headers):
    """建项目、加入 worker、生成日程并把一条指派给 worker，返回 (pid, entry_id)。"""
    today = date.today()
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "我的日历编辑项目",
        "status": "planning",
        "start_date": (today + timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=30)).isoformat(),
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.put(f"/api/projects/{pid}", headers=pm_headers,
                   json={"members": ["user-worker-001"]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    assert r.status_code == 200, r.text
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200, r.text
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 1})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    assert r.status_code == 200 and r.json(), r.text
    entry_id = r.json()[0]["id"]
    # 明确指派给 worker（PM 管理端点既有能力，同时验证其未被削弱）
    r = client.put(f"/api/schedule/{entry_id}", headers=pm_headers,
                   json={"assignee_id": "user-worker-001"})
    assert r.status_code == 200, r.text
    return pid, entry_id


def _worker_people_plan(client, worker_headers):
    r = client.get("/api/dashboard/people-plan", headers=worker_headers)
    assert r.status_code == 200, r.text
    return r.json()["entries"]


def test_people_plan_returns_edit_form_fields(client, pm_headers, worker_headers):
    """people-plan 补齐 notes / is_locked / version 最小编辑字段。"""
    _project_with_worker_entry(client, pm_headers)
    mine = _worker_people_plan(client, worker_headers)
    assert mine, "worker 应看到自己被指派的条目"
    item = next(e for e in mine if e["assignee_id"] == "user-worker-001")
    assert item["is_locked"] is False
    assert "notes" in item and "version" in item


def test_self_edit_updates_three_fields(client, pm_headers, worker_headers):
    """本人成功修改工作日期 / 计划数量 / 备注，版本自增，项目管理端点可见。"""
    pid, entry_id = _project_with_worker_entry(client, pm_headers)
    item = next(e for e in _worker_people_plan(client, worker_headers) if e["entry_id"] == entry_id)
    new_date = (date.today() + timedelta(days=10)).isoformat()
    r = client.put(f"/api/dashboard/people-plan/{entry_id}/self", headers=worker_headers, json={
        "work_date": new_date,
        "planned_quantity": 3.5,
        "notes": "本人调整",
        "version": item["version"],
    })
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["version"] == item["version"] + 1
    updated = next(e for e in _worker_people_plan(client, worker_headers) if e["entry_id"] == entry_id)
    assert updated["work_date"] == new_date
    assert updated["planned_quantity"] == 3.5
    assert updated["notes"] == "本人调整"
    # 项目日程管理端点同样反映变更（同一数据源，不另立存储）
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = next(e for e in r.json() if e["id"] == entry_id)
    assert entry["work_date"] == new_date and entry["planned_quantity"] == 3.5


def test_other_user_entry_rejected(client, pm_headers, worker_headers):
    """非本人条目拒绝，且与不存在条目返回一致（不泄露存在性）。"""
    pid, entry_id = _project_with_worker_entry(client, pm_headers)
    # 条目指派给 worker；管理员（可见项目但非本人）编辑 → 404
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    item = next(e for e in _worker_people_plan(client, worker_headers) if e["entry_id"] == entry_id)
    r1 = client.put(f"/api/dashboard/people-plan/{entry_id}/self", headers=admin_headers, json={
        "work_date": item["work_date"], "planned_quantity": 1, "notes": "", "version": item["version"]})
    r2 = client.put("/api/dashboard/people-plan/not-exist-entry/self", headers=admin_headers, json={
        "work_date": item["work_date"], "planned_quantity": 1, "notes": "", "version": 0})
    assert r1.status_code == 404 and r2.status_code == 404
    assert r1.json()["detail"] == r2.json()["detail"] == "日程条目不存在"


def test_invisible_project_not_leaked(client, pm_headers, worker_headers):
    """条目在 worker 不可见项目中（即使 assignee 是本人）→ 404 不泄露。"""
    today = date.today()
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "worker不可见项目",
        "status": "planning",
        "start_date": (today + timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=30)).isoformat(),
    })
    pid = r.json()["id"]
    # 不把 worker 加入 members → 项目对 worker 不可见
    client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 1})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"module_ids": ["mod-03"]})
    client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry_id = r.json()[0]["id"]
    denied = client.put(f"/api/schedule/{entry_id}", headers=pm_headers,
                        json={"assignee_id": "user-worker-001"})
    assert denied.status_code == 400, denied.text
    # Simulate a legacy orphan assignment, without weakening the current write
    # validator: even an assignee must not read/edit a now-invisible project.
    from app.db import SessionLocal
    from app.models import ScheduleEntry
    with SessionLocal() as db:
        db.get(ScheduleEntry, entry_id).assignee_id = 'user-worker-001'
        db.commit()

    item = {"work_date": (today + timedelta(days=5)).isoformat(), "planned_quantity": 1,
            "notes": "", "version": 0}
    r1 = client.put(f"/api/dashboard/people-plan/{entry_id}/self", headers=worker_headers, json=item)
    r2 = client.put("/api/dashboard/people-plan/not-exist-entry/self", headers=worker_headers, json=item)
    assert r1.status_code == 404
    assert r1.json() == r2.json()
    # 且 worker 的 people-plan 不返回该项目条目
    assert all(e["project_id"] != pid for e in _worker_people_plan(client, worker_headers))


def test_locked_entry_rejected(client, pm_headers, worker_headers):
    """锁定条目拒绝自助编辑。"""
    pid, entry_id = _project_with_worker_entry(client, pm_headers)
    r = client.put(f"/api/schedule/{entry_id}", headers=pm_headers, json={"is_locked": True})
    assert r.status_code == 200, r.text
    item = next(e for e in _worker_people_plan(client, worker_headers) if e["entry_id"] == entry_id)
    assert item["is_locked"] is True
    r = client.put(f"/api/dashboard/people-plan/{entry_id}/self", headers=worker_headers, json={
        "work_date": item["work_date"], "planned_quantity": 9,
        "notes": "x", "version": item["version"]})
    assert r.status_code == 403
    assert "锁定" in r.json()["detail"]


def test_extra_sensitive_fields_rejected(client, pm_headers, worker_headers):
    """携带执行人 / 状态 / 锁定 / 下达等额外字段 → 422，且条目未被修改。"""
    pid, entry_id = _project_with_worker_entry(client, pm_headers)
    item = next(e for e in _worker_people_plan(client, worker_headers) if e["entry_id"] == entry_id)
    r = client.put(f"/api/dashboard/people-plan/{entry_id}/self", headers=worker_headers, json={
        "work_date": item["work_date"], "planned_quantity": 2, "notes": "x",
        "version": item["version"],
        "assignee_id": "user-worker-002", "status": "skipped",
        "is_locked": True, "is_confirmed": True})
    assert r.status_code == 422
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entry = next(e for e in r.json() if e["id"] == entry_id)
    assert entry["assignee_id"] == "user-worker-001"
    assert entry["status"] == "planned"
    assert entry["is_locked"] is False


def test_optimistic_lock_conflict(client, pm_headers, worker_headers):
    """过期版本 → 409。"""
    pid, entry_id = _project_with_worker_entry(client, pm_headers)
    item = next(e for e in _worker_people_plan(client, worker_headers) if e["entry_id"] == entry_id)
    r = client.put(f"/api/dashboard/people-plan/{entry_id}/self", headers=worker_headers, json={
        "work_date": item["work_date"], "planned_quantity": 2, "notes": "",
        "version": item["version"] + 5})
    assert r.status_code == 409


def test_project_management_endpoint_not_regressed(client, pm_headers, worker_headers):
    """原项目日程管理端点权限语义不变：PM 仍可改执行人/状态/锁定；worker 不可以。"""
    pid, entry_id = _project_with_worker_entry(client, pm_headers)
    # PM 管理端点仍可改状态与锁定（既有能力）
    r = client.put(f"/api/schedule/{entry_id}", headers=pm_headers,
                   json={"status": "done", "is_locked": True})
    assert r.status_code == 200, r.text
    # worker 走管理端点 → 无权限（不因自助端点存在而削弱）
    r = client.put(f"/api/schedule/{entry_id}", headers=worker_headers,
                   json={"notes": "越权"})
    assert r.status_code in (401, 403)


def test_pm_self_add_creates_entry_and_duplicate_rejected(client, pm_headers, worker_headers):
    """PM 本人新增日程：成功创建（未锁定/未确认/version 0），同日同任务重复 409。"""
    pid, _ = _project_with_worker_entry(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    task_id = r.json()[0]["task_id"]
    new_date = (date.today() + timedelta(days=3)).isoformat()
    body = {"project_id": pid, "task_id": task_id, "work_date": new_date,
            "planned_quantity": 2.5, "notes": "本人新增"}
    r = client.post("/api/dashboard/people-plan/self", headers=pm_headers, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["version"] == 0

    mine = [e for e in client.get("/api/dashboard/people-plan", headers=pm_headers).json()["entries"]
            if e["project_id"] == pid]
    item = next(e for e in mine if e["work_date"] == new_date and e["assignee_id"] == "user-pm-001")
    assert item["planned_quantity"] == 2.5 and item["notes"] == "本人新增"
    assert item["is_locked"] is False and item["is_confirmed"] is False and item["version"] == 0

    # 同一天同一任务同一人 → 409
    r = client.post("/api/dashboard/people-plan/self", headers=pm_headers, json=body)
    assert r.status_code == 409


def test_self_add_pm_only(client, worker_headers):
    """worker / intern 不在 PM 端角色范围 → 403。"""
    r = client.post("/api/dashboard/people-plan/self", headers=worker_headers, json={
        "project_id": "p-x", "task_id": "t-x",
        "work_date": date.today().isoformat(), "planned_quantity": 1, "notes": ""})
    assert r.status_code == 403


def test_self_add_invisible_project_and_bad_task(client, pm_headers, lead_headers):
    """项目不可见 → 404（与不存在一致）；任务不存在或不属于该项目 → 404。"""
    today = date.today()
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "worker不可见新增项目",
        "start_date": (today + timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=10)).isoformat(),
    })
    pid = r.json()["id"]  # lead 不是该项目经理/技术经理/协作人 → 不可见
    body = {"project_id": pid, "task_id": "whatever",
            "work_date": (today + timedelta(days=2)).isoformat(), "planned_quantity": 1, "notes": ""}
    r1 = client.post("/api/dashboard/people-plan/self", headers=lead_headers, json=body)
    assert r1.status_code == 404

    # 对 pm 可见的项目，但任务不存在 / 不属于该项目 → 404
    bad_task = dict(body, task_id="not-exist-task")
    r2 = client.post("/api/dashboard/people-plan/self", headers=pm_headers, json=bad_task)
    assert r2.status_code == 404 and r2.json()["detail"] == "任务不存在"


def test_self_add_extra_fields_and_bad_quantity_rejected(client, pm_headers, worker_headers):
    """额外字段（执行人/状态/锁定）与负数计划量均 422，不落库。"""
    pid, _ = _project_with_worker_entry(client, pm_headers)
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    task_id = r.json()[0]["task_id"]
    base = {"project_id": pid, "task_id": task_id,
            "work_date": (date.today() + timedelta(days=4)).isoformat(),
            "planned_quantity": 1, "notes": ""}
    r1 = client.post("/api/dashboard/people-plan/self", headers=pm_headers,
                     json=dict(base, assignee_id="user-worker-001", status="done", is_locked=True))
    assert r1.status_code == 422
    r2 = client.post("/api/dashboard/people-plan/self", headers=pm_headers,
                     json=dict(base, planned_quantity=-1))
    assert r2.status_code == 422
    # 以上请求均未创建条目
    r = client.get("/api/dashboard/people-plan", headers=pm_headers)
    assert all(not (e["project_id"] == pid and e["assignee_id"] == "user-pm-001")
               for e in r.json()["entries"])
