"""HYPE-20 决策视图聚合端点测试：真实数据驱动，无前端硬编码。"""

from datetime import date, timedelta
from tests.legacy_project_deletion import legacy_pending_delete


def _active_project(client, pm_headers, name="决策视图项目A"):
    """创建带任务/日程/问题的活跃项目，返回 project id。"""
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "status": "planning", "start_date": "2026-07-01", "end_date": "2026-12-31",
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    # The analytics fixture explicitly starts planning; new API projects default to draft.
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    assert r.status_code == 200, r.text
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers, json={"module_ids": ["mod-03"]})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.text
    return pid


def test_decision_view_empty(client, admin_headers):
    r = client.get("/api/dashboard/decision-view", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["counts"]["pending_approvals"] == 0
    assert d["counts"]["high_risk_projects"] == 0
    assert d["counts"]["at_risk_projects"] == 0
    assert d["risks"] == []
    assert d["pending_decisions"]["governance"] == []


def test_decision_view_high_risk_with_reasons(client, admin_headers, pm_headers):
    pid = _active_project(client, pm_headers)
    # 严重问题未解决
    client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "AGV 停车精度超标", "severity": "critical"})
    # 逾期任务：把一条日程移到过去且不填报
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    assert entries, "schedule should have entries"
    past = (date.today() - timedelta(days=5)).isoformat()
    client.put(f"/api/schedule/{entries[0]['id']}", headers=pm_headers, json={"work_date": past})

    d = client.get("/api/dashboard/decision-view", headers=admin_headers).json()
    risks = [x for x in d["risks"] if x["project_id"] == pid]
    assert risks, "project must appear as a risk"
    risk = risks[0]
    assert risk["risk_level"] == "high"
    assert any("逾期任务" in reason for reason in risk["reasons"])
    assert any("严重" in reason for reason in risk["reasons"])
    # 谁在跟：项目负责人（pm 是负责人，未在 members 时也应作为跟进人）
    assert any("项目负责人" in f for f in risk["followers"])
    # 需要什么决策
    assert any("督促负责人" in decision for decision in [risk["decision"]])
    # 计数一致
    assert d["counts"]["high_risk_projects"] >= 1
    assert risk["overdue_tasks"] >= 1
    assert risk["critical_issues"] >= 1


def test_decision_view_pending_governance(client, admin_headers, pm_headers):
    pid = _active_project(client, pm_headers)
    legacy_pending_delete(client, pm_headers, pid, "历史待办删除申请")
    d = client.get("/api/dashboard/decision-view", headers=admin_headers).json()
    assert d["counts"]["pending_approvals"] == 1
    g = d["pending_decisions"]["governance"][0]
    assert g["request_type"] == "delete"
    assert g["project_id"] == pid
    assert g["requested_by_name"] == "项目经理"
    # 审批单附带项目上下文（HYPE-20）
    assert g["project_status"] == "executing"
    assert g["project_percent"] == 0
    assert g["project_manager_name"] == "项目经理"


def _unassigned_big_project(client, pm_headers, name="未派工大项目"):
    """创建未来 7 天窗口内有多条未派工日程的项目（6 车 × 4 模块）。"""
    today = date.today()
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": name, "status": "planning", "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=120)).isoformat(),
    })
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "ready"})
    assert r.status_code == 200, r.text
    from tests.lifecycle_helpers import approve_risk_entry
    approve_risk_entry(client, pm_headers, pid)
    r = client.post(f"/api/projects/{pid}/status", headers=pm_headers, json={"status": "executing"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 6})
    assert r.status_code == 200, r.text
    for mod in ["mod-02", "mod-03", "mod-04", "mod-05"]:
        r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": [mod]})
        assert r.status_code == 200, r.text
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.text
    return pid


def _window_count(entries, today):
    """未来 7 天窗口内的条目数（与 decision-view 口径一致）。"""
    end = (today + timedelta(days=6)).isoformat()
    return [e for e in entries if e["work_date"] >= today.isoformat() and e["work_date"] <= end]


def test_decision_view_capacity_unassigned(client, admin_headers, pm_headers):
    pid = _unassigned_big_project(client, pm_headers)
    today = date.today()
    # 清空未来日程的派工 → 未派工条目（总数按全量统计，明细仅前 20 条）
    r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
    entries = r.json()
    window = _window_count(entries, today)
    for e in window:
        client.put(f"/api/schedule/{e['id']}", headers=pm_headers, json={"assignee_id": None})
    d = client.get("/api/dashboard/decision-view", headers=admin_headers).json()
    assert "capacity" in d
    assert "unassigned_items" in d["capacity"]
    assert d["counts"]["unassigned_entries"] == len(window)
    assert len(d["capacity"]["unassigned_items"]) <= 20
    assert d["capacity"]["unassigned_entries"] == d["counts"]["unassigned_entries"]


def test_decision_view_unassigned_count_not_truncated(client, admin_headers, pm_headers):
    """未派工总数全量统计，不被明细 limit(20) 截断（一审必改）。"""
    pid = _unassigned_big_project(client, pm_headers)
    today = date.today()
    # 把 25 条未派工日程移进未来 7 天窗口 → 明细被 limit(20) 截断、总数必须全量
    entries = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers).json()
    window_days = [(today + timedelta(days=i)).isoformat() for i in range(7)]
    moved = 0
    for e in entries:
        if moved >= 25:
            break
        if e.get("assignee_id") is not None or e.get("phase_name") == "项目准备":
            continue
        client.put(f"/api/schedule/{e['id']}", headers=pm_headers, json={
            "work_date": window_days[moved % 7]})
        moved += 1
    assert moved >= 25, f"应能移动至少 25 条未派工日程，got {moved}"

    d = client.get("/api/dashboard/decision-view", headers=admin_headers).json()
    total = d["counts"]["unassigned_entries"]
    items = d["capacity"]["unassigned_items"]
    assert total >= 25, f"未派工总数应全量统计，got {total}"
    assert len(items) == 20, "明细应被 limit(20) 截断"
    assert total > len(items), "总数不能被 limit(20) 截断"
    assert d["capacity"]["unassigned_entries"] == total


def test_decision_view_worker_scope(client, pm_headers, worker_headers):
    _active_project(client, pm_headers)  # 无成员，worker 不可见
    d = client.get("/api/dashboard/decision-view", headers=worker_headers).json()
    assert d["counts"]["at_risk_projects"] == 0
    assert d["risks"] == []


def test_decision_view_worker_governance_capacity_isolation(client, admin_headers, pm_headers, worker_headers):
    """worker 治理与容量隔离（终审必改）：混合场景——隐藏项目制造真实未派工+真实超载，
    先证管理侧非零正对照，再证 worker 只见自己参与项目、不混入隐藏项目数据。"""
    today = date.today()
    window_end = (today + timedelta(days=6)).isoformat()
    me = client.get("/api/auth/me", headers=worker_headers).json()
    worker_id = me["id"]

    # ===== 隐藏项目 H（worker 非成员）：真实未派工 + 真实超载人员 =====
    h_pid = _unassigned_big_project(client, pm_headers, name="隐藏容量项目")
    # 超载工程师（technician 属可排程角色，admin/pm 均可见）
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "overload", "password": "Review123!",
        "display_name": "超载工程师", "role": "technician"})
    assert r.status_code == 200, r.text
    over_id = r.json()["id"]
    r = client.get(f"/api/projects/{h_pid}", headers=pm_headers)
    client.put(f"/api/projects/{h_pid}", headers=pm_headers, json={
        "members": r.json()["members"] + [over_id]})

    h_entries = client.get(f"/api/projects/{h_pid}/schedule", headers=pm_headers).json()
    assert len(h_entries) >= 8, f"隐藏项目应有充足日程条目，got {len(h_entries)}"
    # 3 条派给超载工程师（本周内，计划数量 20）→ 3×20×4h=240h → 负荷 300%（≥100% 超载）
    for e in h_entries[:3]:
        r = client.put(f"/api/schedule/{e['id']}", headers=pm_headers, json={
            "assignee_id": over_id, "work_date": today.isoformat(), "planned_quantity": 20.0})
        assert r.status_code == 200, r.text
    # 5 条置空并放进未来 7 天窗口 → 隐藏项目真实未派工
    for i, e in enumerate(h_entries[3:8]):
        r = client.put(f"/api/schedule/{e['id']}", headers=pm_headers, json={
            "assignee_id": None, "work_date": (today + timedelta(days=i)).isoformat(),
            "planned_quantity": 1.0})
        assert r.status_code == 200, r.text

    # ===== worker 可见项目 V（worker 是成员）：未来 7 天也有未派工 =====
    v_pid = _unassigned_big_project(client, pm_headers, name="worker可见项目")
    r = client.get(f"/api/projects/{v_pid}", headers=pm_headers)
    client.put(f"/api/projects/{v_pid}", headers=pm_headers, json={
        "members": r.json()["members"] + [worker_id]})
    v_entries = client.get(f"/api/projects/{v_pid}/schedule", headers=pm_headers).json()
    assert len(v_entries) >= 2
    for i, e in enumerate(v_entries[:2]):
        r = client.put(f"/api/schedule/{e['id']}", headers=pm_headers, json={
            "assignee_id": None, "work_date": (today + timedelta(days=i)).isoformat()})
        assert r.status_code == 200, r.text

    # pm 治理申请（隐藏项目）→ worker 非发起人不可见
    legacy_pending_delete(client, pm_headers, h_pid, "历史隔离删除申请")

    # ===== 管理侧正对照：admin / pm 必须看到非零数据与目标人员/项目 =====
    d_admin = client.get("/api/dashboard/decision-view", headers=admin_headers).json()
    assert d_admin["counts"]["unassigned_entries"] >= 5, "admin 应看到隐藏项目未派工"
    assert d_admin["counts"]["overloaded_people"] >= 1
    assert any(p["id"] == over_id for p in d_admin["capacity"]["overloaded"]), "admin 应看到超载工程师"

    d_pm = client.get("/api/dashboard/decision-view", headers=pm_headers).json()
    assert d_pm["counts"]["unassigned_entries"] >= 5
    assert d_pm["counts"]["overloaded_people"] >= 1
    assert any(p["id"] == over_id for p in d_pm["capacity"]["overloaded"]), "pm 应看到超载工程师"
    assert d_pm["counts"]["pending_approvals"] >= 1
    assert any(g["project_id"] == h_pid for g in d_pm["pending_decisions"]["governance"])

    # ===== worker 侧：只看自己范围，不混入隐藏项目 =====
    # worker 可见项目 V 的未派工窗口数（口径与 decision-view 一致：7 天窗口 + 非 skipped + 未派工）
    v_unassigned = len([e for e in client.get(f"/api/projects/{v_pid}/schedule", headers=pm_headers).json()
                        if today.isoformat() <= e["work_date"] <= window_end
                        and e.get("assignee_id") is None and e.get("status") != "skipped"])
    d_w = client.get("/api/dashboard/decision-view", headers=worker_headers).json()
    assert d_w["counts"]["pending_approvals"] == 0
    assert d_w["pending_decisions"]["governance"] == []
    assert d_w["counts"]["overloaded_people"] == 0
    assert not any(p["id"] == over_id for p in d_w["capacity"]["overloaded"]), "worker 不得看到隐藏项目超载人员"
    assert d_w["counts"]["unassigned_entries"] == v_unassigned, "worker 未派工只计自己参与项目"
    assert all(item["project_name"] == "worker可见项目" for item in d_w["capacity"]["unassigned_items"])
    assert "隐藏容量项目" not in [item["project_name"] for item in d_w["capacity"]["unassigned_items"]]


def test_decision_view_skipped_schedule_not_overload(client, admin_headers, pm_headers):
    """leader 终审必改：people_workload 排除 skipped 日程——高计划量正常日程先证明人员超载，
    设为 skipped 后 people-summary 与 decision-view 均不再计入超载（与未派工口径一致）。"""
    today = date.today()
    # 超载工程师（technician 属可排程角色，admin 全量可见）
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "overload3", "password": "Review123!",
        "display_name": "超载工程师3", "role": "technician"})
    assert r.status_code == 200, r.text
    over_id = r.json()["id"]

    pid = _active_project(client, pm_headers)
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={
        "members": r.json()["members"] + [over_id]})

    entries = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers).json()
    assert len(entries) >= 3
    # 3 条本周正常日程派给超载工程师且计划数量 20 → 3×20×4h=240h → 负荷 300%（≥100% 超载）
    target = []
    for e in entries[:3]:
        r = client.put(f"/api/schedule/{e['id']}", headers=pm_headers, json={
            "assignee_id": over_id, "work_date": today.isoformat(), "planned_quantity": 20.0})
        assert r.status_code == 200, r.text
        target.append(e["id"])

    def overloaded_ids():
        dv = client.get("/api/dashboard/decision-view", headers=admin_headers).json()
        return [p["id"] for p in dv["capacity"]["overloaded"]]

    # 正对照：高计划量正常日程 → people-summary 与 decision-view 都计入超载
    ps = client.get("/api/dashboard/people-summary", headers=admin_headers).json()
    row = next(p for p in ps["people"] if p["id"] == over_id)
    assert row["load_percent"] >= 100, f"正常日程应使人员超载，got {row['load_percent']}"
    assert ps["summary"]["overloaded_people"] >= 1
    assert over_id in overloaded_ids(), "decision-view 应计入超载工程师"

    # 设为 skipped → 两端点均不再计入超载（people_workload 已排除 skipped）
    for eid in target:
        r = client.put(f"/api/schedule/{eid}", headers=pm_headers, json={"status": "skipped"})
        assert r.status_code == 200, r.text

    ps2 = client.get("/api/dashboard/people-summary", headers=admin_headers).json()
    row2 = next(p for p in ps2["people"] if p["id"] == over_id)
    assert row2["load_percent"] < 100, "skipped 日程不得计入负荷"
    assert over_id not in overloaded_ids(), "skipped 后 decision-view 不得计入超载"


def test_governance_requests_include_project_context(client, admin_headers, pm_headers):
    pid = _active_project(client, pm_headers)
    legacy_pending_delete(client, pm_headers, pid, "历史重复项目清理")
    r = client.get("/api/projects/governance/requests", headers=admin_headers)
    assert r.status_code == 200, r.text
    row = next(x for x in r.json() if x["project_id"] == pid)
    assert row["project_status"] == "executing"
    assert row["project_status_label"] == "现场实施"
    assert row["project_manager_name"] == "项目经理"
    assert row["project_percent"] == 0


def test_decision_view_delivery_quarter_window(client, admin_headers, pm_headers):
    """交付风险只统计下季度窗口内的项目，补前/内/后边界（二审必改）。"""
    today = date.today()
    quarter = (today.month - 1) // 3
    nq_start = date(today.year + (1 if quarter == 3 else 0), (quarter + 1) % 4 * 3 + 1, 1)
    nq_end = date(
        nq_start.year + (1 if nq_start.month == 10 else 0),
        (1 if nq_start.month == 10 else nq_start.month + 3), 1,
    ) - timedelta(days=1)

    def make_overdue(pid):
        r = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers)
        entries = r.json()
        assert entries, "schedule should have entries"
        client.put(f"/api/schedule/{entries[0]['id']}", headers=pm_headers, json={
            "work_date": (today - timedelta(days=5)).isoformat()})

    def in_delivery(pid):
        d = client.get("/api/dashboard/decision-view", headers=admin_headers).json()
        return any(x["project_id"] == pid for x in d["delivery"]["at_risk"]), d

    pid = _active_project(client, pm_headers)
    # 窗口前（早于 nq_start，如本季度或已到期）→ 不误报为下季度交付风险
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={
        "end_date": (nq_start - timedelta(days=1)).isoformat()})
    make_overdue(pid)
    before_in, d_before = in_delivery(pid)
    assert not before_in, "窗口之前结束的项目不得进入下季度交付风险"
    assert d_before["delivery"]["quarter"]["start"] == nq_start.isoformat()
    assert d_before["delivery"]["quarter"]["end"] == nq_end.isoformat()

    # 窗口内（nq_start ~ nq_end）→ 进入交付风险
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={"end_date": nq_end.isoformat()})
    inside_in, _ = in_delivery(pid)
    assert inside_in, "窗口内项目应进入交付风险"
    assert d_before["counts"]["delivery_risks"] >= 0  # 前边界不混入，计数以最终态为准

    # 窗口后（晚于 nq_end）→ 不再计入交付风险
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={
        "end_date": (nq_end + timedelta(days=90)).isoformat()})
    after_in, _ = in_delivery(pid)
    assert not after_in, "窗口之后结束的项目不得进入下季度交付风险"

    # 终态：窗口内项目必须被计数
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={"end_date": nq_end.isoformat()})
    final_in, d_final = in_delivery(pid)
    assert final_in
    assert d_final["counts"]["delivery_risks"] >= 1


def test_decision_view_role_isolation(client, admin_headers, pm_headers, tech_headers):
    """角色隔离（一审必改）：lead 加入成员可见项目，technician 非成员不可见。"""
    pid = _active_project(client, pm_headers)
    client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "隔离测试严重问题", "severity": "high"})
    # 创建 lead 并加入项目成员
    r = client.post("/api/users", headers=admin_headers, json={
        "username": "leadiso", "password": "Review123!",
        "display_name": "技术经理隔离", "role": "lead"})
    assert r.status_code == 200, r.text
    lead_id = r.json()["id"]
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    members = r.json()["members"] + [lead_id]
    client.put(f"/api/projects/{pid}", headers=pm_headers, json={"members": members})
    r = client.post("/api/auth/login", json={"username": "leadiso", "password": "Review123!"})
    assert r.status_code == 200
    lead_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # pm（项目负责人）与 lead（成员）可见项目风险
    for headers in (pm_headers, lead_headers):
        d = client.get("/api/dashboard/decision-view", headers=headers).json()
        assert any(x["project_id"] == pid for x in d["risks"])
    # technician（非成员）不可见
    d = client.get("/api/dashboard/decision-view", headers=tech_headers).json()
    assert d["counts"]["at_risk_projects"] == 0
    assert d["risks"] == []


def test_decision_view_severe_vehicle_fault_counts_as_high_risk(client, admin_headers, pm_headers):
    """严重车辆故障（未关闭故障事件 + 车辆当前故障/停机）计入高风险口径（一审必改）。"""
    pid = _active_project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/vehicle-units", headers=pm_headers, json={
        "asset_code": "AGV-500-001"})
    assert r.status_code == 200, r.text
    unit_id = r.json()["id"]
    # 车辆当前状态置为故障
    r = client.put(f"/api/projects/{pid}/vehicle-units/{unit_id}", headers=pm_headers, json={
        "current_status": "fault"})
    assert r.status_code == 200, r.text
    # 未关闭的 fault 事件
    r = client.post(f"/api/projects/{pid}/vehicle-units/{unit_id}/events", headers=pm_headers, json={
        "event_type": "fault", "event_date": date.today().isoformat(),
        "title": "驱动轮故障停机", "status_after": "fault", "is_closed": False})
    assert r.status_code == 200, r.text

    d = client.get("/api/dashboard/decision-view", headers=admin_headers).json()
    risks = [x for x in d["risks"] if x["project_id"] == pid]
    assert risks, "车辆故障项目必须进入风险列表"
    risk = risks[0]
    assert risk["risk_level"] == "high"
    assert any("严重车辆故障" in reason for reason in risk["reasons"])
    assert risk["critical_issues"] >= 1
    assert d["counts"]["high_risk_projects"] >= 1
