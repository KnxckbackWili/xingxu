"""Report forms: 生命周期表 / 质量问题反馈单 / 内部联系单（物品申请）端到端测试."""

from tests.lifecycle_helpers import versioned
import io
import zipfile
from datetime import datetime

from openpyxl import Workbook, load_workbook


def _project(client, headers, name="表单测试项目"):
    r = client.post("/api/projects", headers=headers, json={
        "name": name, "start_date": "2026-08-01", "end_date": "2026-12-31"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ===== 生命周期表 =====

def test_lifecycle_export(client, pm_headers):
    pid = _project(client, pm_headers)
    unit = client.post(f"/api/projects/{pid}/vehicle-units", headers=pm_headers, json={
        "asset_code": "AGV-001", "fleet_no": "7", "current_stage": "planned"}).json()
    client.post(f"/api/projects/{pid}/vehicle-units/{unit['id']}/events", headers=pm_headers, json={
        "event_type": "fault", "event_date": "2026-08-12", "title": "驱动轮异响",
        "description": "行驶中左轮异响", "action_taken": "更换轴承", "handler": "施泽辉",
        "replaced_parts": [], "is_closed": False, "status_after": "fault"})

    r = client.get(f"/api/projects/{pid}/export/lifecycle", headers=pm_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb.active
    headers = [ws.cell(row=2, column=c).value for c in range(1, 13)]
    assert headers == ["序号", "项目名称", "项目合同号", "型号", "配置号", "车辆编号", "调车时间记录", "车号", "分类", "变更内容", "记录人", "记录时间"]
    assert ws["A1"].value == "AGV生命周期表" and ws["A1"].font.size == 20
    row = [ws.cell(row=3, column=c).value for c in range(1, 13)]
    assert row[1] == "表单测试项目"          # 项目名称
    assert row[5] == "AGV-001"              # 车辆编号
    assert row[6] == "2026.8.12"            # 调车时间记录（公司写法）
    assert row[7] == "7"                    # 车号
    assert row[8] == "故障"                 # 分类：未填时用记录类型
    assert row[9] == "驱动轮异响：更换轴承"   # 变更内容
    assert row[10] == "施泽辉"              # 记录人
    assert row[11] and row[11].count(".") == 2  # 记录时间


def _lifecycle_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["序号", "项目名称", "车辆型号", "车辆编号", "车号", "出现过的问题", "问题描述", "解决方法", "记录人", "记录时间", "问题分类"])
    ws.append(["1", "旧项目", "潜伏式", "77BC00180", "2",
               "光通信接线接错\n安全激光损坏", "现象A\n现象B", "更换光通信\n更换激光",
               "施泽辉", "2023/5/4\n2023-05-21 00:00:00", "硬件问题\n硬件问题"])
    ws.append(["2", "旧项目", "AGVLSYP", "77BC00192", "3", "安全激光损坏",
               "行驶中激光损坏", "更换激光", "裘辉", "2023-06-01", "硬件"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def test_lifecycle_import(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                    files={"file": ("生命周期表.xlsx", _lifecycle_xlsx(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json()["events"] == 3  # 第一行两行拆分 + 第二行一条

    units = client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()
    assert len(units) == 2
    unit1 = next(u for u in units if u["asset_code"] == "77BC00180")
    assert unit1["fleet_no"] == "2"
    detail = client.get(f"/api/projects/{pid}/vehicle-units/{unit1['id']}", headers=pm_headers).json()
    assert len(detail["events"]) == 2
    # 按 event_date 倒序：2023-05-21（现象B）在前，2023-05-04（现象A）在后
    assert detail["events"][0]["extra"]["category"] == "硬件问题"
    assert detail["events"][0]["description"] == "现象B"
    assert detail["events"][1]["description"] == "现象A"


def test_lifecycle_import_idempotent_matching_unit(client, pm_headers):
    pid = _project(client, pm_headers)
    client.post(f"/api/projects/{pid}/vehicle-units", headers=pm_headers, json={
        "asset_code": "77BC00192", "fleet_no": "3", "current_stage": "planned"})
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                    files={"file": ("生命周期表.xlsx", _lifecycle_xlsx(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json()["units"] == 1  # 只新建 77BC00180，77BC00192 复用现有档案
    units = client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()
    assert len(units) == 2


def test_lifecycle_export_model_name(client, pm_headers):
    """车辆型号列导出 model_name（AGVLSYP），而非 vehicle_type（潜伏式）。"""
    pid = _project(client, pm_headers)
    vehicle = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGVLSYP", "quantity": 1}).json()
    unit = client.post(f"/api/projects/{pid}/vehicle-units", headers=pm_headers, json={
        "asset_code": "AGV-001", "vehicle_id": vehicle["id"], "fleet_no": "7",
        "current_stage": "planned"}).json()
    client.post(f"/api/projects/{pid}/vehicle-units/{unit['id']}/events", headers=pm_headers, json={
        "event_type": "fault", "event_date": "2026-08-12", "title": "驱动轮异响",
        "description": "行驶中左轮异响", "action_taken": "更换轴承", "handler": "施泽辉",
        "replaced_parts": [], "is_closed": False, "status_after": "fault"})

    r = client.get(f"/api/projects/{pid}/export/lifecycle", headers=pm_headers)
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb.active
    assert ws.cell(row=2, column=4).value == "型号"
    assert ws.cell(row=3, column=4).value == "AGVLSYP"  # model_name


def test_lifecycle_import_links_vehicle_by_model_name(client, pm_headers):
    """导入按「车辆型号」列匹配 model_name 关联车型档案。"""
    pid = _project(client, pm_headers)
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "AGVLSYP", "quantity": 1}).json()
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                    files={"file": ("生命周期表.xlsx", _lifecycle_xlsx(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    units = client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()
    unit2 = next(u for u in units if u["asset_code"] == "77BC00192")
    detail = client.get(f"/api/projects/{pid}/vehicle-units/{unit2['id']}", headers=pm_headers).json()
    assert detail["model_name"] == "AGVLSYP"      # 车辆型号列按 model_name 关联到车型
    assert detail["vehicle_id"] is not None
    unit1 = next(u for u in units if u["asset_code"] == "77BC00180")
    detail1 = client.get(f"/api/projects/{pid}/vehicle-units/{unit1['id']}", headers=pm_headers).json()
    assert detail1["vehicle_id"] is None          # 车辆型号「潜伏式」无对应 model_name，不建档


def test_lifecycle_import_idempotent_events(client, pm_headers):
    """重复导入同一文件整体幂等：事件不翻倍，并报告跳过数。"""
    pid = _project(client, pm_headers)
    files = {"file": ("生命周期表.xlsx", _lifecycle_xlsx(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r1 = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers, files=files)
    assert r1.status_code == 200, r1.text
    assert r1.json()["events"] == 3 and r1.json()["skipped"] == 0
    r2 = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers, files=files)
    assert r2.status_code == 200, r2.text
    assert r2.json()["events"] == 0 and r2.json()["skipped"] == 3
    units = client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()
    assert len(units) == 2  # 车辆档案也不重复
    detail = client.get(f"/api/projects/{pid}/vehicle-units/{units[0]['id']}", headers=pm_headers).json()
    assert len(detail["events"]) == 2  # 事件总数不变


def test_lifecycle_browser_record_export_reimport_preserves_resolution(client, pm_headers):
    pid = _project(client, pm_headers)
    unit = client.post(f"/api/projects/{pid}/vehicle-units", headers=pm_headers,
                       json={"asset_code": "QA-001"}).json()
    created = client.post(f"/api/projects/{pid}/vehicle-units/{unit['id']}/events", headers=pm_headers,
                          json={"event_type": "fault", "event_date": "2026-10-05", "title": "传感器报警",
                                "action_taken": "紧固连接器", "verification": "连续试运行正常",
                                "fault_part": "传感器", "is_closed": True, "status_after": "normal"})
    assert created.status_code == 200, created.text
    export = client.get(f"/api/projects/{pid}/export/lifecycle", headers=pm_headers)
    for _ in range(2):
        result = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                             files={"file": ("生命周期表.xlsx", export.content,
                                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        assert result.status_code == 200, result.text
        assert result.json()["events"] == 0 and result.json()["skipped"] == 1
    detail = client.get(f"/api/projects/{pid}/vehicle-units/{unit['id']}", headers=pm_headers).json()
    assert len(detail["events"]) == 1 and detail["open_issue_count"] == 0
    assert detail["events"][0]["is_closed"] is True
    assert detail["events"][0]["verification"] == "连续试运行正常"
    assert detail["events"][0]["fault_part"] == "传感器"


def test_lifecycle_import_bad_date_400(client, pm_headers):
    """无法解析的记录时间明确报错，不再静默用当天日期。"""
    pid = _project(client, pm_headers)
    wb = Workbook()
    ws = wb.active
    ws.append(["序号", "项目名称", "车辆型号", "车辆编号", "车号", "出现过的问题", "问题描述", "解决方法", "记录人", "记录时间", "问题分类"])
    ws.append(["1", "旧项目", "AGVLSYP", "77BC00180", "2", "光通信接线接错", "现象A", "更换光通信", "施泽辉", "？？？", "硬件"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                    files={"file": ("生命周期表.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 400, r.text
    assert "记录时间" in r.json()["detail"]
    # 记录时间留空同样报错
    wb2 = Workbook()
    ws2 = wb2.active
    ws2.append(["序号", "项目名称", "车辆型号", "车辆编号", "车号", "出现过的问题", "问题描述", "解决方法", "记录人", "记录时间", "问题分类"])
    ws2.append(["1", "旧项目", "AGVLSYP", "77BC00180", "2", "光通信接线接错", "现象A", "更换光通信", "施泽辉", "", "硬件"])
    buf2 = io.BytesIO()
    wb2.save(buf2)
    r2 = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                     files={"file": ("生命周期表.xlsx", buf2.getvalue(),
                                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r2.status_code == 400, r2.text
    assert "记录时间" in r2.json()["detail"]


def test_lifecycle_import_unmatched_model_name_displayed(client, pm_headers):
    """未匹配车型档案时，导入的车辆型号仍持久化并在列表/详情展示。"""
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                    files={"file": ("生命周期表.xlsx", _lifecycle_xlsx(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    units = client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()
    unit1 = next(u for u in units if u["asset_code"] == "77BC00180")   # 车型「潜伏式」无对应档案
    assert unit1["vehicle_id"] is None
    assert unit1["model_name"] == "潜伏式"        # 列表展示导入的车辆型号
    detail = client.get(f"/api/projects/{pid}/vehicle-units/{unit1['id']}", headers=pm_headers).json()
    assert detail["model_name"] == "潜伏式"        # 单车详情展示导入的车辆型号
    unit2 = next(u for u in units if u["asset_code"] == "77BC00192")
    assert unit2["model_name"] == "AGVLSYP"        # 另一台未匹配档案同样持久化展示


def _quality_form_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.merge_cells("A1:H3")
    ws["A1"] = "产品质量问题反馈单据"
    ws["A4"] = "问题类型 Type"; ws["C4"] = "项目 Project"; ws["G4"] = "反馈人 Name"
    ws["A5"] = "硬件"; ws["C5"] = "天津环晟"; ws["G5"] = "张测试"
    ws["A8"] = "车型 Model"; ws["D8"] = "车辆编号 No."; ws["G8"] = "问题来源 From"
    ws["A9"] = "AGVLSYP"; ws["D9"] = "77BC00255"; ws["G9"] = "项目现场"
    ws["A12"] = "问题部件 Parts"; ws["G12"] = "提交日期 Date"
    ws["A13"] = "伺服电机编码器"; ws["G13"] = "2024-05-08"
    ws["A16"] = "问题简述（或现象）Description"
    ws["A17"] = "行驶时一侧突然断连，另一侧轮子锁死，按急停无效"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def test_quality_form_import(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/import/quality-form", headers=pm_headers,
                    files={"file": ("质量问题反馈单.xlsx", _quality_form_xlsx(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    issue_id = r.json()["id"]
    issue = client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json()
    assert len(issue) == 1
    assert issue[0]["issue_type"] == "hardware"
    assert issue[0]["description"].startswith("行驶时一侧突然断连")
    assert issue[0]["extra"]["vehicle_model"] == "AGVLSYP"
    assert issue[0]["extra"]["vehicle_no"] == "77BC00255"
    assert issue[0]["extra"]["part"] == "伺服电机编码器"
    assert issue[0]["extra"]["reporter_name"] == "张测试"
    assert issue[0]["extra"]["feedback_date"] == "2024-05-08"


def test_quality_form_export(client, pm_headers):
    pid = _project(client, pm_headers)
    issue = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "编码器断连", "description": "行驶时一侧突然断连，另一侧轮子锁死",
        "issue_type": "hardware", "severity": "high",
        "extra": {"vehicle_model": "AGVLSYP", "vehicle_no": "77BC00255", "source": "项目现场",
                  "part": "伺服电机编码器", "feedback_date": "2024-05-08", "reporter_name": "张测试"},
    }).json()
    r = client.get(f"/api/projects/{pid}/issues/{issue['id']}/export/quality-form", headers=pm_headers)
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb.active
    assert ws.title == "质量反馈单据"
    assert "产品质量问题反馈单据" in ws["C1"].value and "No." in ws["A1"].value
    assert ws["A5"].value == "硬件"
    assert ws["F5"].value == "2024.5.8"
    assert ws["D9"].value == "77BC00255"
    assert ws["A13"].value == "伺服电机编码器"
    assert wb["版本管理"]["A4"].value == "A02"


def test_quality_form_export_matches_company_a02_form(client, pm_headers):
    """导出版式对齐公司 A02 版「产品质量问题反馈单据」：合并单元格、字段位置、字体、边框、列宽与打印设置。"""
    pid = _project(client, pm_headers)
    issue = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "导航扩散", "description": "导航扩散",
        "issue_type": "hardware", "severity": "high",
        "extra": {"vehicle_model": "AGVLCDD20", "vehicle_no": "TEST0012", "source": "项目现场", "part": "导航激光",
                  "feedback_date": "2026-10-09", "reporter_name": "张测试", "frame_no": "MJ-0012", "quantity": 1,
                  "factory_date": "2026-03-27", "form_no": "HC-0042"},
    }).json()
    r = client.get(f"/api/projects/{pid}/issues/{issue['id']}/export/quality-form", headers=pm_headers)
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    ws = wb["质量反馈单据"]
    expected_merges = {
        "A1:B3", "C1:I3", "A4:B4", "C4:E4", "F4:G4", "H4:I4", "A5:B7", "C5:E7", "F5:G7", "H5:I7",
        "A8:C8", "D8:G8", "H8:I8", "A9:C11", "D9:G11", "H9:I11", "A12:B12", "C12:E12", "F12:G12", "H12:I12",
        "A13:B15", "C13:E15", "F13:G15", "H13:I15", "A16:I16", "A17:I20", "A21:I21",
        "A22:D22", "E22:I22", "A23:D38", "E23:I38", "A39:D39", "E39:I39", "A40:D53", "E40:I53",
    }
    assert {str(rng) for rng in ws.merged_cells.ranges} == expected_merges
    labels = {"A4": "问题类型 Type", "C4": "项目 Project", "F4": "反馈日期 Date", "H4": "反馈人 Name", "A8": "车型 Model",
              "D8": "车辆编号 No.", "H8": "问题来源 From", "A12": "问题部件 Parts", "C12": "门架号Elevating Frame Number",
              "F12": "数量 Amount", "H12": "出厂日期 Factory Date", "A16": "问题简述（或现象）Description",
              "A22": "问题图片（一）", "E22": "问题图片（二）", "A39": "问题图片（三）", "E39": "问题图片（四）"}
    assert {ref: ws[ref].value for ref in labels} == labels
    values = {"A5": "硬件", "C5": "表单测试项目", "F5": "2026.10.9", "H5": "张测试", "A9": "AGVLCDD20", "D9": "TEST0012",
              "H9": "项目现场", "A13": "导航激光", "C13": "MJ-0012", "F13": 1, "A17": "导航扩散"}
    assert {ref: ws[ref].value for ref in values} == values
    assert ws["H13"].value == datetime(2026, 3, 27) and ws["F13"].number_format == 'General\\ "台"'
    assert ws["A1"].value.strip() == "No. HC-0042"
    assert ws["C1"].font.name == "黑体" and ws["C1"].font.size == 20
    assert ws["A4"].font.name == "宋体" and ws["A4"].font.size == 12 and ws["A5"].font.size == 11
    assert ws["A22"].font.name == "楷体"
    for coord in ("A4", "H5", "D9", "C13", "H13", "A17", "E23"):
        assert ws[coord].border.left.style == "thin" and ws[coord].border.top.style == "thin", coord
    assert ws["I53"].border.right.style == "thin" and ws["I53"].border.bottom.style == "thin"
    assert ws["A21"].border.left.style is None
    assert {col: ws.column_dimensions[col].width for col in ("A", "E", "F", "G", "I")} == {"A": 10.58, "E": 10.58, "F": 5.75, "G": 10.58, "I": 10.58}
    assert ws.oddHeader.left.text.startswith("HCZN-JY-2026-010") and "A/02" in ws.oddHeader.left.text
    assert ws.row_dimensions[20].height == 66 and ws.row_dimensions[21].height == 5.25
    assert ws.page_setup.paperSize == 9 and ws.sheet_properties.pageSetUpPr.fitToPage
    assert [row[0].value for row in wb["版本管理"].iter_rows(min_row=2)] == ["A00", "A01", "A02"]


def test_quality_form_export_import_roundtrip(client, pm_headers):
    """系统导出的质量反馈单再导入：字段一一回填，日期为真实日期值可解析。"""
    pid = _project(client, pm_headers)
    issue = client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "编码器断连", "description": "行驶时一侧突然断连，另一侧轮子锁死",
        "issue_type": "hardware", "severity": "high",
        "extra": {"vehicle_model": "AGVLSYP", "vehicle_no": "77BC00255", "source": "项目现场",
                  "part": "伺服电机编码器", "feedback_date": "2024-05-08", "reporter_name": "张测试"},
    }).json()
    r = client.get(f"/api/projects/{pid}/issues/{issue['id']}/export/quality-form", headers=pm_headers)
    assert r.status_code == 200, r.text
    imp = client.post(f"/api/projects/{pid}/import/quality-form", headers=pm_headers,
                      files={"file": ("质量问题反馈单.xlsx", io.BytesIO(r.content),
                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert imp.status_code == 200, imp.text
    created = client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json()
    assert len(created) == 2
    new_issue = next(i for i in created if i["id"] != issue["id"])
    assert new_issue["issue_type"] == "hardware"
    assert new_issue["description"].startswith("行驶时一侧突然断连")
    assert new_issue["extra"]["vehicle_model"] == "AGVLSYP"
    assert new_issue["extra"]["vehicle_no"] == "77BC00255"
    assert new_issue["extra"]["part"] == "伺服电机编码器"
    assert new_issue["extra"]["reporter_name"] == "张测试"
    assert new_issue["extra"]["feedback_date"] == "2024-05-08"


def test_quality_form_import_invalid_layout_400(client, pm_headers):
    """错版表格（非质量问题反馈单）明确报错。"""
    pid = _project(client, pm_headers)
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "随便一张表"
    ws["A2"] = "数据"
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/projects/{pid}/import/quality-form", headers=pm_headers,
                    files={"file": ("错版.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 400, r.text
    assert "版式" in r.json()["detail"]


def test_quality_form_import_bad_date_400(client, pm_headers):
    """质量问题反馈单提交日期无法解析时明确报错。"""
    pid = _project(client, pm_headers)
    wb = Workbook()
    ws = wb.active
    ws.merge_cells("A1:H3")
    ws["A1"] = "产品质量问题反馈单据"
    ws["A4"] = "问题类型 Type"; ws["C4"] = "项目 Project"; ws["G4"] = "反馈人 Name"
    ws["A5"] = "硬件"; ws["C5"] = "天津环晟"; ws["G5"] = "张测试"
    ws["A8"] = "车型 Model"; ws["D8"] = "车辆编号 No."; ws["G8"] = "问题来源 From"
    ws["A9"] = "AGVLSYP"; ws["D9"] = "77BC00255"; ws["G9"] = "项目现场"
    ws["A12"] = "问题部件 Parts"; ws["G12"] = "提交日期 Date"
    ws["A13"] = "伺服电机编码器"; ws["G13"] = "上周五"
    ws["A16"] = "问题简述（或现象）Description"
    ws["A17"] = "行驶时一侧突然断连"
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/projects/{pid}/import/quality-form", headers=pm_headers,
                    files={"file": ("质量问题反馈单.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 400, r.text
    assert "提交日期" in r.json()["detail"]


def test_quality_form_import_empty_date_400(client, pm_headers):
    """质量问题反馈单提交日期留空同样明确报错，不静默入库。"""
    pid = _project(client, pm_headers)
    wb = Workbook()
    ws = wb.active
    ws.merge_cells("A1:H3")
    ws["A1"] = "产品质量问题反馈单据"
    ws["A4"] = "问题类型 Type"; ws["C4"] = "项目 Project"; ws["G4"] = "反馈人 Name"
    ws["A5"] = "硬件"; ws["C5"] = "天津环晟"; ws["G5"] = "张测试"
    ws["A8"] = "车型 Model"; ws["D8"] = "车辆编号 No."; ws["G8"] = "问题来源 From"
    ws["A9"] = "AGVLSYP"; ws["D9"] = "77BC00255"; ws["G9"] = "项目现场"
    ws["A12"] = "问题部件 Parts"; ws["G12"] = "提交日期 Date"
    ws["A13"] = "伺服电机编码器"; ws["G13"] = ""          # 提交日期留空
    ws["A16"] = "问题简述（或现象）Description"
    ws["A17"] = "行驶时一侧突然断连"
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(f"/api/projects/{pid}/import/quality-form", headers=pm_headers,
                    files={"file": ("质量问题反馈单.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 400, r.text
    assert "提交日期" in r.json()["detail"]
    # 未入库：问题数保持为 0
    assert client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json() == []


# ===== 内部联系单（物品申请） =====

def test_item_application_crud(client, pm_headers):
    pid = _project(client, pm_headers)
    created = client.post(f"/api/projects/{pid}/item-applications", headers=pm_headers, json={
        "title": "更换三支点螺栓需要吊车", "item_name": "吊车", "requirement": "更换三支点螺栓需要使用吊车，共计3000元",
        "reason": "三支点设计缺陷", "contract_no": "HCAGV-2025-170", "applicant": "张测试",
        "department": "项目技术部", "apply_date": "2026-01-07",
    })
    assert created.status_code == 200, created.text
    app_id = created.json()["id"]

    listed = client.get(f"/api/projects/{pid}/item-applications", headers=pm_headers).json()
    assert len(listed) == 1
    assert listed[0]["applicant"] == "张测试"

    updated = client.put(f"/api/projects/{pid}/item-applications/{app_id}", headers=pm_headers, json={
        "title": "更换三支点螺栓需要吊车", "item_name": "吊车", "requirement": "更换三支点螺栓需要使用吊车，共计3000元",
        "reason": "三支点设计缺陷", "contract_no": "HCAGV-2025-170", "applicant": "张测试",
        "department": "项目技术部", "apply_date": "2026-01-07",
        "approver": "王工", "status": "approved"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["approver"] == "王工"
    assert updated.json()["status"] == "approved"

    deleted = client.delete(f"/api/projects/{pid}/item-applications/{app_id}", headers=pm_headers)
    assert deleted.status_code == 200
    assert client.get(f"/api/projects/{pid}/item-applications", headers=pm_headers).json() == []


def _screenshot_item_application_payload(**overrides):
    """截图等价数据：申请部门为空、审批人=11、日期/状态枚举、金额、图号含顿号分隔。"""
    payload = {
        "title": "更换左右支架",
        "item_name": "钣金",
        "requirement": "111",
        "reason": "越南黄轮项目4.5T顶升式AGV，顶升机构上固定接近开光的支架被现场人工叉车撞击导致无法正常使用，故左右两边各需要一个支架进行更换。",
        "drawing_no": "LQPN450-780600-000、LQPN450-780400-...",
        "contract_no": "111",
        "amount": "3000元",
        "applicant": "李世豪",
        "approver": "11",
        "department": "",
        "apply_date": "2026-09-01",
        "status": "pending",
        "note": "111",
    }
    payload.update(overrides)
    return payload


def test_item_application_screenshot_equivalent_submission(client, pm_headers):
    """截图场景：等价提交数据必须成功且只创建一条记录（合法数据不 500、不落两条）。"""
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/item-applications", headers=pm_headers,
                    json=_screenshot_item_application_payload())
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["department"] == ""       # 申请部门为空原样保存
    assert created["approver"] == "11"
    assert created["status"] == "pending"
    assert created["apply_date"] == "2026-09-01"
    assert "、" in created["drawing_no"]     # 图号含顿号分隔原样保存

    listed = client.get(f"/api/projects/{pid}/item-applications", headers=pm_headers).json()
    assert len(listed) == 1                  # 只落一条
    assert listed[0]["applicant"] == "李世豪"

    # 编辑（PUT）同样成功
    upd = client.put(f"/api/projects/{pid}/item-applications/{created['id']}",
                     headers=pm_headers, json=_screenshot_item_application_payload())
    assert upd.status_code == 200, upd.text
    assert upd.json()["item_name"] == "钣金"


def test_item_application_invalid_status_422_not_500(client, pm_headers):
    """截图状态显示「待审批」；若前端传中文标签而非枚举值，接口须返回 422 而非 500，且不落库。"""
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/item-applications", headers=pm_headers,
                    json=_screenshot_item_application_payload(status="待审批"))
    assert r.status_code == 422, r.text      # 明确 4xx，不是 500
    assert client.get(f"/api/projects/{pid}/item-applications", headers=pm_headers).json() == []


def test_item_application_extra_fields_422_not_500(client, pm_headers):
    """编辑弹窗 setFieldsValue({...app}) 若把 id/project_id/created_at/updated_at 也带回请求体，
    extra=forbid 返回 422（明确 4xx），后端不允许静默接受额外字段，也不能因此抛 500。"""
    pid = _project(client, pm_headers)
    payload = _screenshot_item_application_payload()
    payload.update({
        "id": "should-not-accept",
        "project_id": pid,
        "created_at": "2026-09-01T00:00:00",
        "updated_at": "2026-09-01T00:00:00",
    })
    r = client.post(f"/api/projects/{pid}/item-applications", headers=pm_headers, json=payload)
    assert r.status_code == 422, r.text
    assert client.get(f"/api/projects/{pid}/item-applications", headers=pm_headers).json() == []


def test_item_application_field_length_limits_422_not_500(client, pm_headers):
    """边界字段：图号/合同号超 100 字符、备注超 5000 字符 → 422 且不落库；申请部门为空 → 200。"""
    pid = _project(client, pm_headers)
    overlong = "x" * 101
    for override in ({"drawing_no": overlong}, {"contract_no": overlong}, {"note": "y" * 5001}):
        r = client.post(f"/api/projects/{pid}/item-applications", headers=pm_headers,
                        json=_screenshot_item_application_payload(**override))
        assert r.status_code == 422, r.text
    assert client.get(f"/api/projects/{pid}/item-applications", headers=pm_headers).json() == []
    ok = client.post(f"/api/projects/{pid}/item-applications", headers=pm_headers,
                     json=_screenshot_item_application_payload())
    assert ok.status_code == 200, ok.text


def test_item_application_docx_export(client, pm_headers):
    pid = _project(client, pm_headers)
    app = client.post(f"/api/projects/{pid}/item-applications", headers=pm_headers, json={
        "title": "更换三支点螺栓需要吊车", "item_name": "吊车",
        "requirement": "更换三支点螺栓需要使用吊车，共计3000元", "reason": "三支点设计缺陷",
        "contract_no": "HCAGV-2025-170", "applicant": "张测试", "department": "项目技术部",
        "apply_date": "2026-01-07"}).json()
    r = client.get(f"/api/projects/{pid}/item-applications/{app['id']}/export", headers=pm_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml")
    assert zipfile.is_zipfile(io.BytesIO(r.content))


def _item_application_docx() -> bytes:
    from docx import Document
    doc = Document()
    doc.add_paragraph("内部联系单——呼伦贝尔驰宏矿业项目")
    doc.add_paragraph("需求：更换三支点螺栓需要使用吊车，共计3000元")
    doc.add_paragraph("原因：三支点设计缺陷")
    doc.add_paragraph("图号：DWG-01")
    doc.add_paragraph("合同号：HCAGV-2025-170")
    doc.add_paragraph("申请人：张测试")
    doc.add_paragraph("审批人：")
    doc.add_paragraph("项目技术部")
    doc.add_paragraph("2026/1/7")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.getvalue()


def test_item_application_docx_import(client, pm_headers):
    pid = _project(client, pm_headers)
    r = client.post(f"/api/projects/{pid}/import/item-application", headers=pm_headers,
                    files={"file": ("内部联系单-吊车.docx", _item_application_docx(),
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    app_id = r.json()["id"]
    apps = client.get(f"/api/projects/{pid}/item-applications", headers=pm_headers).json()
    assert len(apps) == 1
    app = apps[0]
    assert app["requirement"] == "更换三支点螺栓需要使用吊车，共计3000元"
    assert app["reason"] == "三支点设计缺陷"
    assert app["contract_no"] == "HCAGV-2025-170"
    assert app["applicant"] == "张测试"
    assert app["department"] == "项目技术部"
    assert app["amount"] == "3000元"
    assert app["item_name"] == "吊车"
    assert app["apply_date"] == "2026-01-07"
    assert app_id == app["id"]


def test_item_application_docx_roundtrip(client, pm_headers):
    """系统生成 Word → 回灌导入：申请事项/申请物品/金额/申请日期等字段不丢。"""
    pid = _project(client, pm_headers)
    created = client.post(f"/api/projects/{pid}/item-applications", headers=pm_headers, json={
        "title": "更换三支点螺栓需要吊车", "item_name": "吊车",
        "requirement": "更换三支点螺栓需要使用吊车，共计3000元", "reason": "三支点设计缺陷",
        "drawing_no": "DWG-01", "contract_no": "HCAGV-2025-170", "amount": "3000元",
        "applicant": "张测试", "approver": "王工", "department": "项目技术部",
        "apply_date": "2026-01-07"}).json()
    r = client.get(f"/api/projects/{pid}/item-applications/{created['id']}/export", headers=pm_headers)
    assert r.status_code == 200, r.text
    imp = client.post(f"/api/projects/{pid}/import/item-application", headers=pm_headers,
                      files={"file": ("内部联系单.docx", io.BytesIO(r.content),
                                      "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert imp.status_code == 200, imp.text
    app = client.get(f"/api/projects/{pid}/item-applications/{imp.json()['id']}", headers=pm_headers).json()
    assert app["title"] == "更换三支点螺栓需要吊车"      # 申请事项
    assert app["item_name"] == "吊车"                   # 申请物品/服务
    assert app["requirement"] == "更换三支点螺栓需要使用吊车，共计3000元"
    assert app["reason"] == "三支点设计缺陷"
    assert app["drawing_no"] == "DWG-01"
    assert app["contract_no"] == "HCAGV-2025-170"
    assert app["amount"] == "3000元"                    # 金额
    assert app["applicant"] == "张测试"
    assert app["approver"] == "王工"
    assert app["department"] == "项目技术部"
    assert app["apply_date"] == "2026-01-07"            # 申请日期


def _png(width=4, height=3) -> bytes:
    import struct
    import zlib
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_vehicle_problem_exports_quality_form_with_vehicle_facts_and_photo(client, pm_headers):
    import hashlib
    import zipfile
    from app.config import UPLOAD_DIR
    from app.db import SessionLocal
    from app.models import Attachment
    pid = _project(client, pm_headers)
    vehicle = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={"vehicle_type": "平衡重叉车", "model_name": "AGVLCDD20", "quantity": 1})
    assert vehicle.status_code == 200, vehicle.text
    vehicle = vehicle.json()
    unit = client.post(f"/api/projects/{pid}/vehicle-units", headers=pm_headers, json={
        "asset_code": "TEST0012", "vehicle_id": vehicle["id"], "fleet_no": "52", "frame_no": "MJ-0012", "factory_date": "2026-03-27"}).json()
    assert unit["frame_no"] == "MJ-0012" and unit["factory_date"] == "2026-03-27"
    photo = _png()
    stored = f"test-{unit['id']}.png"
    (UPLOAD_DIR / stored).write_bytes(photo)
    with SessionLocal() as db:
        asset = Attachment(project_id=pid, entity_type="vehicle_event", filename="现场照片.png", stored_name=stored, file_size=len(photo),
                           content_type="image/png", sha256=hashlib.sha256(photo).hexdigest(), uploaded_by="user-pm-001")
        db.add(asset); db.commit(); asset_id = asset.id
    event = client.post(f"/api/projects/{pid}/vehicle-units/{unit['id']}/events", headers=pm_headers, json={
        "event_type": "fault", "event_date": "2026-10-09", "title": "导航扩散", "fault_part": "导航激光", "handler": "张测试",
        "attachment_id": asset_id, "status_after": "fault"})
    assert event.status_code == 200, event.text
    event_id = client.get(f"/api/projects/{pid}/vehicle-units/{unit['id']}", headers=pm_headers).json()["events"][0]["id"]
    r = client.get(f"/api/projects/{pid}/vehicle-events/{event_id}/export/quality-form", headers=pm_headers)
    assert r.status_code == 200, r.text
    ws = load_workbook(io.BytesIO(r.content))["质量反馈单据"]
    assert {ref: ws[ref].value for ref in ("A5", "C5", "F5", "H5", "A9", "D9", "H9", "A13", "C13", "F13", "A17")} == {
        "A5": "硬件", "C5": "表单测试项目", "F5": "2026.10.9", "H5": "张测试", "A9": "AGVLCDD20", "D9": "TEST0012",
        "H9": "项目现场", "A13": "导航激光", "C13": "MJ-0012", "F13": 1, "A17": "导航扩散"}
    assert ws["H13"].value == datetime(2026, 3, 27)
    with zipfile.ZipFile(io.BytesIO(r.content)) as bundle:
        media = [name for name in bundle.namelist() if name.startswith("xl/media/")]
        assert len(media) == 1 and bundle.read(media[0]) == photo
    assert client.get(f"/api/projects/{pid}/vehicle-events/missing/export/quality-form", headers=pm_headers).status_code == 404


def test_a02_form_import_creates_quality_issue_and_fills_the_vehicle_record(client, pm_headers):
    from app.services.report_forms import build_quality_form
    pid = _project(client, pm_headers)
    unit = client.post(f"/api/projects/{pid}/vehicle-units", headers=pm_headers, json={"asset_code": "TEST0012"}).json()
    data = build_quality_form({"form_no": "HC-7", "issue_type": "硬件", "project": "测试客户项目", "feedback_date": "2026-10-09",
                               "reporter": "张测试", "model": "AGVLCDD20", "vehicle_no": "TEST0012", "source": "项目现场",
                               "part": "导航激光", "frame_no": "MJ-0012", "quantity": 1, "factory_date": "2026-03-27",
                               "description": "导航扩散"})
    r = client.post(f"/api/projects/{pid}/import/quality-form", headers=pm_headers,
                    files={"file": ("反馈单.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert "门架号、出厂日期" in r.json()["message"]
    issue = client.get(f"/api/projects/{pid}/issues", headers=pm_headers).json()[0]
    assert issue["nature"] == "quality" and issue["issue_type"] == "hardware"
    assert {key: issue["extra"][key] for key in ("form_no", "frame_no", "quantity", "factory_date", "feedback_date", "part")} == {
        "form_no": "HC-7", "frame_no": "MJ-0012", "quantity": 1, "factory_date": "2026-03-27", "feedback_date": "2026-10-09", "part": "导航激光"}
    detail = client.get(f"/api/projects/{pid}/vehicle-units/{unit['id']}", headers=pm_headers).json()
    assert detail["frame_no"] == "MJ-0012" and detail["factory_date"] == "2026-03-27"


def test_company_lifecycle_table_rows_cover_several_vehicles_and_merged_cells(client, pm_headers):
    pid = _project(client, pm_headers)
    vehicle = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={"vehicle_type": "平衡重叉车", "model_name": "AGVLCDD20", "quantity": 6}).json()
    wb = Workbook()
    ws = wb.active
    ws.merge_cells("A1:L1"); ws["A1"] = "AGV生命周期表"
    ws.append(["序号", "项目名称", "项目合同号", "型号", "配置号", "车辆编号", "调车时间记录", "车号", "分类", "变更内容", "记录人", "记录时间"])
    ws.append([1, "测试客户项目", "HT-2026-001", "AGVLCDD20", "MN1", "TEST01233、TEST01237", "2026.5.23", "51.52", "机械件损坏更换", "下降阀更换", "张测试", "2026.5.31"])
    ws.append([2, "测试客户项目", "HT-2026-001", "AGVLCDD20", "MN1", "TEST01226", "2026.6.2", "61", "软件升级", "调度参数更新", "张测试", "2026.6.2"])
    ws.append([3, None, None, None, None, None, "2026.6.3", None, "电气件更换", "急停按钮更换", "张测试", "2026.6.3"])
    ws.merge_cells("B4:B5"); ws.merge_cells("D4:D5"); ws.merge_cells("F4:F5"); ws.merge_cells("H4:H5")
    buf = io.BytesIO(); wb.save(buf)
    files = {"file": ("生命周期表.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers, files=files)
    assert r.status_code == 200, r.text
    assert r.json()["events"] == 4 and r.json()["units"] == 3
    again = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers, files=files)
    assert again.json()["events"] == 0 and again.json()["skipped"] == 4
    project = client.get(f"/api/projects/{pid}", headers=pm_headers).json()
    assert project["contract_no"] == "HT-2026-001"
    assert next(v for v in project["vehicles"] if v["id"] == vehicle["id"])["configuration"]["config_no"] == "MN1"
    units = {u["asset_code"]: u for u in client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()}
    assert units["TEST01237"]["fleet_no"] == "52" and units["TEST01226"]["vehicle_id"] == vehicle["id"]
    exported = client.get(f"/api/projects/{pid}/export/lifecycle", headers=pm_headers)
    sheet = load_workbook(io.BytesIO(exported.content)).active
    rows = [[cell.value for cell in row] for row in sheet.iter_rows(min_row=3, values_only=False)]
    first = next(row for row in rows if row[9] == "下降阀更换")
    assert first[1:6] == ["表单测试项目", "HT-2026-001", "AGVLCDD20", "MN1", "TEST01233、TEST01237"]
    assert first[6:] == ["2026.5.23", "51.52", "机械件损坏更换", "下降阀更换", "张测试", "2026.5.31"]
    reimport = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                           files={"file": ("导出.xlsx", exported.content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert reimport.json()["events"] == 0


def test_type_added_after_lifecycle_import_takes_its_vehicles_and_config_no(client, pm_headers):
    """Importing before the project has the type leaves vehicles by model; adding the type brings them in."""
    pid = _project(client, pm_headers)
    other = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={"vehicle_type": "平衡重叉车", "model_name": "其他型号", "quantity": 1}).json()
    wb = Workbook()
    ws = wb.active
    ws.append(["AGV生命周期表"])
    ws.append(["序号", "项目名称", "项目合同号", "型号", "配置号", "车辆编号", "调车时间记录", "车号", "分类", "变更内容", "记录人", "记录时间"])
    ws.append([1, "测试客户项目", "HT-2026-001", "AGVLCDD20", "MN1", "TEST01233、TEST01237", "2026.5.23", "51.52", "机械件损坏更换", "下降阀更换", "张测试", "2026.5.31"])
    ws.append([2, "测试客户项目", "HT-2026-001", "AGVX9", "", "TEST09001", "2026.5.24", "9", "软件升级", "调度参数更新", "张测试", "2026.5.24"])
    buf = io.BytesIO(); wb.save(buf)
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                    files={"file": ("生命周期表.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    units = {u["asset_code"]: u for u in client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()}
    assert units["TEST01233"]["vehicle_id"] is None and units["TEST01233"]["model_name"] == "AGVLCDD20"

    added = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                        json={"vehicle_type": "平衡重叉车", "model_name": "AGVLCDD20", "quantity": 2})
    assert added.status_code == 200, added.text
    assert added.json()["configuration"]["config_no"] == "MN1"
    units = {u["asset_code"]: u for u in client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()}
    assert units["TEST01233"]["vehicle_id"] == units["TEST01237"]["vehicle_id"] == added.json()["id"]
    assert units["TEST01233"]["vehicle_type"] == "平衡重叉车"
    assert units["TEST09001"]["vehicle_id"] is None

    # Renaming a type to an imported model brings those vehicles in too; a typed config no is kept.
    client.put(f"/api/projects/{pid}/vehicles/{other['id']}", headers=pm_headers, json={"configuration": {"config_no": "K1"}})
    renamed = client.put(f"/api/projects/{pid}/vehicles/{other['id']}", headers=pm_headers, json={"model_name": "AGVX9"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["configuration"]["config_no"] == "K1"
    units = {u["asset_code"]: u for u in client.get(f"/api/projects/{pid}/vehicle-units", headers=pm_headers).json()}
    assert units["TEST09001"]["vehicle_id"] == other["id"]
    from app.db import SessionLocal
    from app.models import ChangeLog
    with SessionLocal() as db:
        summaries = [row.detail for row in db.query(ChangeLog).filter(ChangeLog.project_id == pid, ChangeLog.entity_type == "vehicle")]
    assert any("同型号已建档车辆 2 台归入此车型" in text for text in summaries)
    assert any("同型号已建档车辆 1 台归入此车型" in text for text in summaries)


def test_lifecycle_dates_without_year_are_refused(client, pm_headers):
    pid = _project(client, pm_headers)
    wb = Workbook(); ws = wb.active
    ws.append(["序号", "项目名称", "项目合同号", "型号", "配置号", "车辆编号", "调车时间记录", "车号", "分类", "变更内容", "记录人", "记录时间"])
    ws.append([1, "项目", "", "M", "", "AGV-1", "5.23", "1", "维修", "更换轮子", "张三", ""])
    buf = io.BytesIO(); wb.save(buf)
    r = client.post(f"/api/projects/{pid}/import/lifecycle", headers=pm_headers,
                    files={"file": ("x.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 400 and "缺年份" in r.json()["detail"]


def test_project_contract_number_is_part_of_basic_info(client, pm_headers):
    pid = _project(client, pm_headers)
    current = client.get(f"/api/projects/{pid}", headers=pm_headers).json()
    saved = client.put(f"/api/projects/{pid}", headers=pm_headers, json={"contract_no": "HT-2026-001", "version": current["version"]})
    assert saved.status_code == 200, saved.text
    assert client.get(f"/api/projects/{pid}", headers=pm_headers).json()["contract_no"] == "HT-2026-001"
