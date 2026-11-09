"""Import/export + clone tests."""

from tests.lifecycle_helpers import versioned
import io
import json
from tests.template_work import default_work


def test_project_export_json(client, pm_headers):
    # Build a project
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "导出测试项目", "client": "客户X",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"})
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 3})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"work_item_ids": default_work("mod-02", "mod-04")})

    r = client.get(f"/api/projects/{pid}/export/json", headers=pm_headers)
    assert r.status_code == 200
    snapshot = r.json()
    assert snapshot["type"] == "agvpm-project"
    assert len(snapshot["vehicles"]) == 1
    assert len(snapshot["modules"]) == 2

    # Import into a new project
    r = client.post("/api/projects/import/json", headers=pm_headers, json=snapshot)
    assert r.status_code == 200
    new_id = r.json()["id"]

    # Verify new project has vehicles + tasks
    r = client.get(f"/api/projects/{new_id}", headers=pm_headers)
    assert r.json()["vehicle_total"] == 3
    r = client.get(f"/api/projects/{new_id}/tree", headers=pm_headers)
    assert len(r.json()) == 2


def test_clone_project(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "克隆源项目", "client": "客户Y",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"})
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "堆高车", "model_name": "Fork-1500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"work_item_ids": default_work("mod-03")})

    r = client.post(f"/api/projects/{pid}/clone", headers=pm_headers, json={
        "name": "克隆目标项目（二期）",
        "start_date": "2026-10-01", "new_vehicles": False,
        "end_date": "2026-11-30",
    })
    assert r.status_code == 200
    new_id = r.json()["id"]

    r = client.get(f"/api/projects/{new_id}", headers=pm_headers)
    data = r.json()
    assert data["name"] == "克隆目标项目（二期）"
    assert data["vehicle_total"] == 2
    assert data["start_date"] == "2026-10-01"

    # Tasks copied
    r = client.get(f"/api/projects/{new_id}/tree", headers=pm_headers)
    tasks = [t for ph in r.json() for t in ph["work_items"]]
    assert len(tasks) == 1  # 单车调试 is one row


def test_project_export_excel(client, pm_headers):
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "Excel导出项目",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"})
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"work_item_ids": default_work("mod-03")})
    r = client.get(f"/api/projects/{pid}/export/excel", headers=pm_headers)
    assert r.status_code == 200
    assert len(r.content) > 500


def test_project_export_excel_sheets(client, pm_headers, worker_headers):
    """导出完整项目工作簿，包括现场物品。"""
    from openpyxl import load_workbook

    # 建项目 + 车型 + 任务 + 排程
    r = client.post("/api/projects", headers=pm_headers, json={
        "name": "7Sheet导出项目",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"})
    pid = r.json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"work_item_ids": default_work("mod-03")})


    # 一个问题（含分类专属字段）
    client.post(f"/api/projects/{pid}/issues", headers=pm_headers, json={
        "title": "充电桩故障", "issue_type": "hardware",
        "extra": {"device": "AGV-03", "affects_schedule": "影响"}})

    r = client.get(f"/api/projects/{pid}/export/excel", headers=pm_headers)
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ['交付概览','生命周期表','问题清单','物资清单','收发流水','交付资料']
    overview = {row[1]:row[2] for row in wb['交付概览'].iter_rows(min_row=3, values_only=True) if row[0]=='项目概况'}
    assert {'项目状态','执行任务数','未闭环问题','整体进度 %'} <= set(overview)
    from app.services.report_forms import LIFECYCLE_HEADERS
    assert [cell.value for cell in wb['生命周期表'][2]][:len(LIFECYCLE_HEADERS)] == LIFECYCLE_HEADERS
    headers = [cell.value for cell in wb['问题清单'][2]]
    assert '解决方案/关闭或作废说明' in headers and '扩展字段' in headers
    assert any('AGV-03' in str(cell.value) for row in wb['问题清单'].iter_rows(min_row=3) for cell in row if cell.value)
    assert '更换配件' in [cell.value for cell in wb['生命周期表'][2]]
    assert [cell.value for cell in wb['物资清单'][1]][:10] == ['物品编码','名称','规格','序列号','归属','现存数量','单位','位置','保管人','说明']
    assert [cell.value for cell in wb['收发流水'][1]][:9] == ['发生时间（UTC）','物品','动作','数量','结余','原位置','新位置','经手人','说明']
    assert {'文件名','资料状态','提交人','提交时间（UTC）','审核信息'} <= set(cell.value for cell in wb['交付资料'][2])


def test_project_export_package_zip(client, pm_headers, worker_headers):
    """HYPE-58：项目整包 ZIP（xlsx + json + files/ + manifest，含去重/SHA-256/缺失标记）。"""
    import zipfile
    import json as stdjson

    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "整包导出项目",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"}).json()["id"]
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers,
                json={"vehicle_type": "潜伏式", "model_name": "AGV-500", "quantity": 2})
    client.post(f"/api/projects/{pid}/tasks/generate", headers=pm_headers,
                json={"work_item_ids": default_work("mod-03")})

    # 同名附件 × 2 → ZIP 内 files/ 自动去重（-1 序号），manifest 记录 sha256/size
    for content in (b"hello-pkg-1", b"hello-pkg-2"):
        r = client.post(f"/api/projects/{pid}/documents/files", headers=pm_headers,
                        files={"file": ("same.txt", content, "text/plain")})
        assert r.status_code == 200, r.json()

    r = client.get(f"/api/projects/{pid}/export/package", headers=pm_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "项目数据.xlsx" in names
    assert "项目备份.json" in names
    assert "manifest.json" in names
    files_in = [n for n in names if n.startswith("files/")]
    assert len(files_in) == 2, files_in

    manifest = stdjson.loads(zf.read("manifest.json"))
    assert manifest["type"] == "agvpm-project-package"
    assert manifest["project"]["id"] == pid
    assert manifest["file_count"] == 2
    assert manifest["missing_count"] == 0
    paths = [f["archive_path"] for f in manifest["files"]]
    assert len(set(paths)) == len(paths)  # 去重：archive_path 唯一
    for f in manifest["files"]:
        assert f["id"]  # 清单记录附件 id
        assert f["sha256"]
        assert f["size"] > 0
        assert f["archive_path"].startswith("files/")
        # 文件本体与 manifest 的 SHA-256 一致
        disk = zf.read(f["archive_path"])
        import hashlib
        assert hashlib.sha256(disk).hexdigest() == f["sha256"]

    # 同一项目 Excel 接口仍兼容（不删旧接口）
    assert client.get(f"/api/projects/{pid}/export/excel", headers=pm_headers).status_code == 200
    assert client.get(f"/api/projects/{pid}/export/json", headers=pm_headers).status_code == 200

    # 每个员工都能导出项目包
    assert client.get(f"/api/projects/{pid}/export/package", headers=worker_headers).status_code == 200


def test_project_export_package_zip_missing_file(client, pm_headers):
    """磁盘附件缺失时 ZIP 不中断，manifest 显式标错（missing=true），不能静默漏掉。"""
    import zipfile
    import json as stdjson
    from app.config import UPLOAD_DIR

    pid = client.post("/api/projects", headers=pm_headers, json={
        "name": "缺文件导出项目",
        "start_date": "2026-08-10", "new_vehicles": False, "end_date": "2026-09-30"}).json()["id"]
    existing = {path for path in UPLOAD_DIR.rglob("*") if path.is_file()}
    r = client.post(f"/api/projects/{pid}/documents/files", headers=pm_headers,
                    files={"file": ("关键点位表.xlsx", b"\x50\x4b\x03\x04fake-xlsx", "application/vnd.ms-excel")})
    assert r.status_code == 200, r.json()

    # 只删除本用例上传的磁盘文件本体（模拟备份缺失），数据库记录仍在；
    # 其它用例共享的启动期文件不能删，否则后续整系统备份会因原件缺失失败。
    uploaded = {path for path in UPLOAD_DIR.rglob("*") if path.is_file()} - existing
    assert uploaded
    for f in uploaded:
        f.unlink()

    r = client.get(f"/api/projects/{pid}/export/package", headers=pm_headers)
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = stdjson.loads(zf.read("manifest.json"))
    assert manifest["file_count"] == 1
    assert manifest["missing_count"] == 1
    entry = manifest["files"][0]
    assert entry["name"] == "关键点位表.xlsx"
    assert entry["missing"] is True
    assert "sha256" not in entry  # 文件缺失无法计算哈希
    assert not any(n.startswith("files/") for n in zf.namelist())  # 缺失文件不进包体
    # xlsx / json / manifest 本体仍在，导出可用
    assert "项目数据.xlsx" in zf.namelist()
    assert "项目备份.json" in zf.namelist()


def test_ai_quick_import_preview_reports_structural_errors(client, pm_headers):
    payload = {
        "type": "wrong-type",
        "project": {"name": "", "start_date": "2026-09-10", "end_date": "2026-09-01"},
        "vehicle_units": [{"asset_code": "AGV-001"}, {"asset_code": "AGV-001"}],
    }
    preview = client.post("/api/projects/import/preview", headers=pm_headers, json=payload).json()
    assert preview["valid"] is False
    assert len(preview["errors"]) >= 4


def test_quick_import_requires_initial_status_and_preserves_original_payload(client, pm_headers):
    """New project import cannot restore lifecycle authority without its evidence."""
    for status in ("draft", "completed", "archived"):
        payload = {
            "type": "agvpm-project", "version": "2.3",
            "project": {"name": f"导入恢复-{status}", "start_date": "2026-08-01", "end_date": "2026-09-30",
                        "status": status, "conditions": {},
                        "client_contacts": [], "entry_plan": {}},
            "vehicles": [], "vehicle_units": [], "modules": [], "schedule": [],
            "preparations": [], "inventory_items": [], "progress": [], "issues": [],
        }
        r = client.post("/api/projects/import/json", headers=pm_headers, json=payload)
        if status == "draft":
            # A legacy draft maps to the v3 starting state.
            assert r.status_code == 200, r.text
            project = client.get(f"/api/projects/{r.json()['id']}", headers=pm_headers).json()
            assert project["status"] == "preparing"
        else:
            assert r.status_code == 400, r.text
            assert "新建项目导入" in r.json()["detail"]
        assert payload["project"]["status"] == status
