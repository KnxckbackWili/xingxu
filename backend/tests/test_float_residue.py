"""HYPE-18 二审：导出 / 报告 / 日历三处接口的浮点残差回归验证。

SQL 对 0.1 这类值做 SUM 会累积出 0.30000000000000004 残差；
导出「日程排程」已完成列、报告风险区 done、月历每日 completed
三处聚合点必须 round(qty or 0, 2) 后再输出，否则前端会直接渲染残差。
"""
import io
from datetime import date


def _project_with_float_residue(client, pm_headers, worker_headers):
    """建项目 + 排程 + 对第一条日程报 0.1×3（SQL SUM = 0.30000000000000004）。

    返回 (project_id, entry)，entry 为第一条日程（含 id/task_id/task_name/work_date）。
    """
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "浮点残差回归", "client": "客户F",
        "status": "planning",
        "start_date": "2026-08-01", "new_vehicles": False,
        "end_date": "2026-09-30"})
    assert r.status_code == 200, r.json()
    pid = r.json()["id"]
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                    json={"module_ids": ["mod-03"]})
    assert r.status_code == 200, r.json()
    r = client.get(f"/api/projects/{pid}", headers=pm_headers)
    client.put(f"/api/projects/{pid}", headers=pm_headers,
               json={"members": [*r.json()["members"], "user-worker-001"]})
    r = client.post(f"/api/projects/{pid}/schedule/generate", headers=pm_headers)
    assert r.status_code == 200, r.json()
    # 现场数量填报必须基于已确认下达的计划。
    r = client.post(f"/api/projects/{pid}/schedule/confirm", headers=pm_headers)
    assert r.status_code == 200, r.json()
    entries = client.get(f"/api/projects/{pid}/schedule", headers=pm_headers).json()
    assert entries, "排程应至少一条"
    entry = entries[0]
    # 同一天同一任务报 0.1 × 3 → SQL SUM = 0.30000000000000004
    for i in range(3):
        r = client.post("/api/worker/reports", headers=worker_headers, json={
            "task_id": entry["task_id"], "schedule_entry_id": entry["id"],
            "work_date": entry["work_date"], "completed_quantity": 0.1,
            "client_uuid": f"floatresidue-{i:04d}"})
        assert r.status_code == 200, r.json()
    return pid, entry


def test_delivery_export_preserves_progress_facts_without_float_artifacts(client, pm_headers, worker_headers):
    """The compact workbook and full JSON preserve the three real 0.1 reports."""
    from decimal import Decimal
    from openpyxl import load_workbook
    pid, entry = _project_with_float_residue(client, pm_headers, worker_headers)
    r = client.get(f"/api/projects/{pid}/export/excel", headers=pm_headers)
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert '交付概览' in wb.sheetnames and '日程排程' not in wb.sheetnames
    assert not any(cell.value == 0.30000000000000004 for sheet in wb for row in sheet for cell in row)
    snapshot = client.get(f"/api/projects/{pid}/export/json", headers=pm_headers).json()
    reports = [row for row in snapshot['progress'] if row['task_name']==entry['task_name']]
    assert len(reports) == 3 and sum(Decimal(str(row['completed_quantity'])) for row in reports)==Decimal('0.3')


def test_report_risk_done_rounded(client, pm_headers, worker_headers):
    """报告接口风险区 done 不得出现浮点残差（0.3 < planned×0.5 → 进入逾期风险）。"""
    pid, entry = _project_with_float_residue(client, pm_headers, worker_headers)

    r = client.get(f"/api/projects/{pid}/report", headers=pm_headers,
                   params={"period": "week", "ref_date": "2026-08-31"})
    assert r.status_code == 200
    d = r.json()
    dones = [t["done"] for t in d["risks"]]
    assert dones, "应存在逾期风险任务（done=0.3 < planned×0.5）"
    assert any(done == 0.3 for done in dones), f"done 应为 0.3，实际 {dones}"
    assert all(done == round(done, 2) for done in dones), f"存在浮点残差 {dones}"


def test_schedule_calendar_completed_rounded(client, pm_headers, worker_headers):
    """月历接口每日 completed 不得出现浮点残差。"""
    pid, entry = _project_with_float_residue(client, pm_headers, worker_headers)
    d = date.fromisoformat(entry["work_date"])

    r = client.get("/api/schedule/calendar", headers=pm_headers,
                   params={"project_id": pid, "month": d.month, "year": d.year})
    assert r.status_code == 200
    days = r.json()
    day = next(x for x in days if x["date"] == entry["work_date"])
    assert day["completed"] == 0.3, f"completed 应为 0.3，实际 {day['completed']!r}"
    assert all(x["completed"] == round(x["completed"], 2) for x in days)
