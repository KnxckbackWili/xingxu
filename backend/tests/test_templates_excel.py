"""Templates, the vehicle type library, Excel out and in, the company's lifecycle table."""
import io

from openpyxl import Workbook, load_workbook

from tests.test_records import snap, url

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def book(sheets: dict) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def send(client, headers, path, data, preview=False):
    return client.post(path + ("?preview=true" if preview else ""), headers=headers, files={"file": ("in.xlsx", data, XLSX)})


def test_template_rows_edit_like_project_rows(client, staff, staff2):
    made = client.post("/api/templates", headers=staff, json={"name": "叉车项目", "note": ""}).json()
    tid = made["id"]
    row = client.post(f"/api/templates/{tid}/rows", headers=staff, json={"kind": "work", "stage": "准备", "name": "开工会"}).json()
    assert client.post(f"/api/templates/{tid}/rows", headers=staff, json={"kind": "plan", "name": "x"}).status_code == 400
    assert client.patch(f"/api/templates/{tid}/rows/{row['id']}", headers=staff, json={"kind": {"to": "item"}}).status_code == 400
    assert client.patch(f"/api/templates/{tid}/rows/{row['id']}", headers=staff, json={"name": {"from": "开工会", "to": "启动会"}}).status_code == 200
    assert client.patch(f"/api/templates/{tid}/rows/{row['id']}", headers=staff2, json={"name": {"from": "开工会", "to": "碰头会"}}).status_code == 409
    full = client.get(f"/api/templates/{tid}", headers=staff)
    assert [r["name"] for r in full.json()["rows"]] == ["启动会"]
    assert client.get(f"/api/templates/{tid}", headers={**staff, "If-None-Match": full.headers["etag"]}).status_code == 304
    assert client.patch(f"/api/templates/{tid}", headers=staff2, json={"name": {"from": "叉车项目", "to": "叉车标准"}}).json()["name"] == "叉车标准"
    client.delete(f"/api/templates/{tid}/rows/{row['id']}", headers=staff)
    assert client.get(f"/api/templates/{tid}", headers=staff).json()["rows"] == []
    assert client.post(f"/api/templates/{tid}/rows/{row['id']}/restore", headers=staff).status_code == 200
    copy = client.post(f"/api/templates/{tid}/copy", headers=staff, json={}).json()
    assert copy["name"] == "叉车标准 副本" and len(client.get(f"/api/templates/{copy['id']}", headers=staff).json()["rows"]) == 1
    listed = {row["name"]: row["counts"] for row in client.get("/api/templates", headers=staff).json()}
    assert listed["叉车标准"] == {"work": 1, "document": 0, "step": 0, "item": 0} and listed["AGV 实施标准模板"]["step"] == 5
    client.delete(f"/api/templates/{tid}", headers=staff2)
    assert "叉车标准" not in {row["name"] for row in client.get("/api/templates", headers=staff).json()}
    assert client.post(f"/api/templates/{tid}/restore", headers=staff).status_code == 200


def test_a_project_no_longer_follows_its_template(client, staff, project):
    template = client.get("/api/templates", headers=staff).json()[0]
    client.post(f"/api/templates/{template['id']}/rows", headers=staff, json={"kind": "step", "name": "回访"})
    assert "回访" not in [step["name"] for step in snap(client, staff, project)["steps"]]


def test_vehicle_types(client, staff):
    made = client.post("/api/vehicle-types", headers=staff, json={"name": "牵引式", "note": "拖挂"}).json()
    assert client.post("/api/vehicle-types", headers=staff, json={"name": "牵引式"}).status_code == 400
    assert client.patch(f"/api/vehicle-types/{made['id']}", headers=staff, json={"is_enabled": False}).json()["is_enabled"] is False
    project = client.post("/api/projects", headers=staff, json={"name": "p"}).json()
    assert "牵引式" not in client.get(f"/api/projects/{project['id']}", headers=staff).json()["vehicle_types"]
    assert client.delete(f"/api/vehicle-types/{made['id']}", headers=staff).status_code == 200
    assert "牵引式" not in [row["name"] for row in client.get("/api/vehicle-types", headers=staff).json()]


def test_project_export_then_import_into_another_project(client, staff, project):
    pid = project["project"]["id"]
    vehicle, step = project["vehicles"][0], project["steps"][0]
    client.put(f"/api/projects/{pid}/vehicles/{vehicle['id']}/steps/{step['id']}", headers=staff, json={"done": True})
    client.patch(url(project, "vehicles", vehicle["id"]), headers=staff, json={"model": {"to": "=SUM(1,2)"}, "fleet_no": {"to": "1"}})
    exported = client.get(f"/api/projects/{pid}/export.xlsx", headers=staff)
    assert exported.status_code == 200 and "filename*=UTF-8''" in exported.headers["content-disposition"]
    workbook = load_workbook(io.BytesIO(exported.content))
    assert workbook.sheetnames == ["车辆", "车辆记录", "工作", "问题", "资料", "物品"]
    sheet = workbook["车辆"]
    assert [cell.value for cell in sheet[1]][:5] == ["车辆编号", "车号", "型号", "配置号", "到货点检"]
    assert sheet["C2"].value == "=SUM(1,2)" and sheet["C2"].data_type == "s" and sheet["E2"].value == "✓"
    other = client.post("/api/projects", headers=staff, json={"name": "另一个项目"}).json()["id"]
    client.post(f"/api/projects/{other}/steps", headers=staff, json={"name": "到货点检"})
    preview = send(client, staff, f"/api/projects/{other}/import/vehicles", exported.content, preview=True).json()
    assert preview["preview"] and {row["label"]: row["count"] for row in preview["counts"]} == {"新增车辆": 3, "新增环节打勾": 1}
    assert preview["unknown_models"] == ["=SUM(1,2)"]
    assert client.get(f"/api/projects/{other}", headers=staff).json()["vehicles"] == []  # a preview writes nothing
    assert send(client, staff, f"/api/projects/{other}/import/vehicles", exported.content).status_code == 200
    copied = client.get(f"/api/projects/{other}", headers=staff).json()
    assert [row["vehicle_no"] for row in copied["vehicles"]] == ["车辆1", "车辆2", "车辆3"] and len(copied["marks"]) == 1
    again = send(client, staff, f"/api/projects/{other}/import/vehicles", exported.content).json()
    assert again["counts"] == []  # nothing new the second time
    for kind, count in (("work", 14), ("documents", 10), ("items", 5)):
        result = send(client, staff, f"/api/projects/{other}/import/{kind}", exported.content).json()
        assert result["counts"][0]["count"] == count, (kind, result)
    assert len(client.get(f"/api/projects/{other}", headers=staff).json()["items"]) == 5


def test_lifecycle_table_round_trip(client, staff, project):
    pid = project["project"]["id"]
    company = book({"AGV生命周期表": [
        ["AGV生命周期表"], ["序号", "项目名称", "项目合同号", "型号", "配置号", "车辆编号", "调车时间记录", "车号", "分类", "变更内容", "记录人", "记录时间"],
        [1, "苏州工厂", "HT-2026-001", "潜伏式", "C-01", "A001、A002", "2026.5.23", "1.2", "软件", "升级导航程序", "张伟", "2026.5.24"],
        [2, "苏州工厂", "HT-2026-001", "牵引式", "C-02", "A003", "2026/6/1", "3", "硬件", "更换驱动轮", "李娜", ""],
        [3, "苏州工厂", "HT-2026-001", "潜伏式", "C-01", "A001", "5.30", "1", "", "加固支架", "", ""],
        [4, "苏州工厂", "", "", "", "", "", "", "", "没有车辆编号的行被忽略", "", ""]]})
    preview = send(client, staff, f"/api/projects/{pid}/import/lifecycle", company, preview=True).json()
    assert {row["label"]: row["count"] for row in preview["counts"]} == {"新增车辆": 3, "新增车辆记录": 4}
    assert preview["unknown_models"] == ["牵引式"]
    assert send(client, staff, f"/api/projects/{pid}/import/lifecycle", company).status_code == 200
    data = snap(client, staff, project)
    a1 = next(row for row in data["vehicles"] if row["vehicle_no"] == "A001")
    assert (a1["fleet_no"], a1["model"], a1["config_no"]) == ("1", "潜伏式", "C-01")
    mine = sorted((r["content"], r["category"], r["happened_on"], r["recorded_by_name"], r["recorded_on"])
                  for r in data["vehicle_records"] if r["vehicle_id"] == a1["id"])
    assert mine == [("加固支架", "", None, "", None), ("升级导航程序", "软件", "2026-05-23", "张伟", "2026-05-24")]
    again = send(client, staff, f"/api/projects/{pid}/import/lifecycle", company).json()
    assert {row["label"]: row["count"] for row in again["counts"]} == {"跳过重复记录": 4}
    exported = client.get(f"/api/projects/{pid}/lifecycle.xlsx", headers=staff)
    sheet = load_workbook(io.BytesIO(exported.content)).active
    assert sheet.title == "AGV生命周期表" and [cell.value for cell in sheet[2]][5:8] == ["车辆编号", "调车时间记录", "车号"]
    lines = [[cell.value for cell in row] for row in sheet.iter_rows(min_row=3)]
    shared = next(line for line in lines if line[9] == "升级导航程序")
    assert shared[1:9] == ["苏州工厂", "HT-2026-001", "潜伏式", "C-01", "A001、A002", "2026.5.23", "1.2", "软件"] and shared[11] == "2026.5.24"
    assert [line[0] for line in lines] == list(range(1, len(lines) + 1))
    assert any(line[5] == "车辆1" and not line[9] for line in lines)  # vehicles without records are listed too
    # what was exported reads back into an empty project as the same vehicles and records
    other = client.post("/api/projects", headers=staff, json={"name": "回读"}).json()["id"]
    assert send(client, staff, f"/api/projects/{other}/import/lifecycle", exported.content).status_code == 200
    back = client.get(f"/api/projects/{other}", headers=staff).json()
    assert len(back["vehicles"]) == 6 and len(back["vehicle_records"]) == 4 and back["project"]["contract_no"] == "HT-2026-001"


def test_import_reports_bad_files_and_bad_rows(client, staff, project):
    pid = project["project"]["id"]
    assert send(client, staff, f"/api/projects/{pid}/import/items", b"not excel").status_code == 400
    assert send(client, staff, f"/api/projects/{pid}/import/items", book({"物品": [["品名"], ["x"]]})).status_code == 400
    assert send(client, staff, f"/api/projects/{pid}/import/plans", b"x").status_code == 422
    result = send(client, staff, f"/api/projects/{pid}/import/items", book({"物品": [
        ["名称", "规格", "数量", "单位"], ["托盘", "", "很多", "个"], ["线槽", "40mm", 12.5, "米"], ["", "只有规格", 1, ""]]})).json()
    assert {row["label"]: row["count"] for row in result["counts"]} == {"新增物品": 1} and result["problem_count"] == 1
    assert "第 2 行" in result["problems"][0]
    assert snap(client, staff, project)["items"][-1]["quantity"] == 12.5


def test_template_excel_round_trip(client, staff):
    source = client.get("/api/templates", headers=staff).json()[0]
    exported = client.get(f"/api/templates/{source['id']}/export.xlsx", headers=staff)
    assert load_workbook(io.BytesIO(exported.content)).sheetnames == ["工作", "资料", "车辆环节", "物品"]
    target = client.post("/api/templates", headers=staff, json={"name": "空模板"}).json()["id"]
    preview = send(client, staff, f"/api/templates/{target}/import", exported.content, preview=True).json()
    assert {row["label"]: row["count"] for row in preview["counts"]} == {"新增工作": 14, "新增资料": 10, "新增车辆环节": 5, "新增物品": 5}
    assert client.get(f"/api/templates/{target}", headers=staff).json()["rows"] == []
    send(client, staff, f"/api/templates/{target}/import", exported.content)
    rows = client.get(f"/api/templates/{target}", headers=staff).json()["rows"]
    assert len(rows) == 34 and next(row for row in rows if row["name"] == "网络设备")["quantity"] == 1
    assert send(client, staff, f"/api/templates/{target}/import", book({"别的": [["x"]]})).status_code == 400
