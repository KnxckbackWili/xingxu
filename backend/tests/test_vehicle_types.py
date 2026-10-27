"""车型字典（HYPE-63）测试：预置种子 / 权限 / CRUD / 排序 / 引用 / 旧数据兼容 / 车辆写入校验 / 导入。"""


def _create_project(client, headers, name="车型测试项目"):
    return client.post("/api/projects", headers=headers, json={
        "name": name,
        "client": "客户A",
        "location": "苏州",
        "start_date": "2026-08-10",
        "end_date": "2026-09-30",
        "new_vehicles": False,
    }).json()["id"]


# ===== 预置种子与读取权限 =====

def test_preset_vehicle_types_seeded(client, pm_headers):
    r = client.get("/api/vehicle-types", headers=pm_headers)
    assert r.status_code == 200
    rows = r.json()
    assert [t["name"] for t in rows] == ["潜伏式", "平衡重叉车", "堆高车", "前移式", "滚筒车", "顶升车", "其他/定制"]
    assert all(t["is_enabled"] for t in rows)


def test_enabled_list_requires_login(client):
    assert client.get("/api/vehicle-types").status_code == 401


def test_all_list_requires_admin(client, pm_headers, worker_headers):
    assert client.get("/api/vehicle-types/all", headers=pm_headers).status_code == 403
    assert client.get("/api/vehicle-types/all", headers=worker_headers).status_code == 403
    # main 的登录接口会种 HttpOnly 会话 cookie（get_current_user 回退读 cookie）：
    # 清掉 pm/worker 登录留下的 cookie 后再验证「未登录 → 401」。
    client.cookies.clear()
    assert client.get("/api/vehicle-types/all").status_code == 401


# ===== 管理员 CRUD / 排序 / 重命名 =====

def test_admin_create_validate_duplicate_empty_long(client, admin_headers, pm_headers):
    r = client.post("/api/vehicle-types", headers=admin_headers, json={"name": "  双向车  "})
    assert r.status_code == 200
    assert r.json()["name"] == "双向车"
    assert r.json()["is_enabled"] is True

    assert client.post("/api/vehicle-types", headers=admin_headers, json={"name": "双向车"}).status_code == 400
    assert client.post("/api/vehicle-types", headers=admin_headers, json={"name": "   "}).status_code == 400
    assert client.post("/api/vehicle-types", headers=admin_headers, json={"name": "长" * 51}).status_code == 400
    # 普通用户（pm）不可新增
    assert client.post("/api/vehicle-types", headers=pm_headers, json={"name": "x"}).status_code == 403


def test_admin_enable_disable(client, admin_headers):
    added = client.post("/api/vehicle-types", headers=admin_headers, json={"name": "临时车型"}).json()
    vid = added["id"]

    r = client.put(f"/api/vehicle-types/{vid}", headers=admin_headers, json={"is_enabled": False})
    assert r.status_code == 200
    assert r.json()["is_enabled"] is False

    enabled_names = [t["name"] for t in client.get("/api/vehicle-types", headers=admin_headers).json()]
    assert "临时车型" not in enabled_names
    all_names = [t["name"] for t in client.get("/api/vehicle-types/all", headers=admin_headers).json()]
    assert "临时车型" in all_names

    r = client.put(f"/api/vehicle-types/{vid}", headers=admin_headers, json={"is_enabled": True})
    assert r.json()["is_enabled"] is True
    assert "临时车型" in [t["name"] for t in client.get("/api/vehicle-types", headers=admin_headers).json()]


def test_admin_reorder(client, admin_headers):
    ids = [t["id"] for t in client.get("/api/vehicle-types/all", headers=admin_headers).json()]
    # 逆序
    r = client.put("/api/vehicle-types/reorder", headers=admin_headers, json={"ids": list(reversed(ids))})
    assert r.status_code == 200
    rows = client.get("/api/vehicle-types/all", headers=admin_headers).json()
    assert [t["id"] for t in rows] == list(reversed(ids))
    assert [t["sort_order"] for t in rows] == list(range(1, len(ids) + 1))
    # 不匹配列表
    assert client.put("/api/vehicle-types/reorder", headers=admin_headers, json={"ids": ids[:-1]}).status_code == 400


def test_admin_rename_referenced_forbidden(client, admin_headers, pm_headers):
    # 未引用的可重命名
    added = client.post("/api/vehicle-types", headers=admin_headers, json={"name": "临时命名"}).json()
    r = client.put(f"/api/vehicle-types/{added['id']}", headers=admin_headers, json={"name": "正式命名"})
    assert r.status_code == 200
    assert r.json()["name"] == "正式命名"

    # 已被车辆引用的禁止重命名
    pid = _create_project(client, pm_headers)
    assert client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "平衡重叉车", "model_name": "M1", "quantity": 1}).status_code == 200
    tid = next(t["id"] for t in client.get("/api/vehicle-types/all", headers=admin_headers).json()
               if t["name"] == "平衡重叉车")
    r = client.put(f"/api/vehicle-types/{tid}", headers=admin_headers, json={"name": "叉车"})
    assert r.status_code == 400
    assert "禁止重命名" in r.json()["detail"]


# ===== 车辆写入的字典校验 =====

def test_vehicle_write_validates_dictionary(client, admin_headers, pm_headers, worker_headers):
    pid = _create_project(client, pm_headers)

    # PM 添加启用字典项 → OK
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "潜伏式", "model_name": "A", "quantity": 1})
    assert r.status_code == 200
    assert r.json()["vehicle_type"] == "潜伏式"

    # PM 添加字典外值 → 400
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "不存在的车型", "model_name": "B", "quantity": 1})
    assert r.status_code == 400
    assert "字典" in r.json()["detail"]

    # PM 添加历史 custom → 归一化为「其他/定制」
    r = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "custom", "model_name": "C", "quantity": 1})
    assert r.status_code == 200
    assert r.json()["vehicle_type"] == "其他/定制"

    # 管理员例外：可写入任意非空值
    r = client.post(f"/api/projects/{pid}/vehicles", headers=admin_headers, json={
        "vehicle_type": "特殊进口车", "model_name": "D", "quantity": 1})
    assert r.status_code == 200
    special_id = r.json()["id"]

    # 编辑：保留当前值（字典外历史值）允许；改为字典外新值拒绝
    r = client.put(f"/api/projects/{pid}/vehicles/{special_id}", headers=pm_headers, json={"model_name": "D2"})
    assert r.status_code == 200
    r = client.put(f"/api/projects/{pid}/vehicles/{special_id}", headers=pm_headers, json={"vehicle_type": "特殊进口车"})
    assert r.status_code == 200
    r = client.put(f"/api/projects/{pid}/vehicles/{special_id}", headers=pm_headers, json={"vehicle_type": "别的车"})
    assert r.status_code == 400

    # worker 无权管理项目车辆（项目不可见 → 404，不泄露项目存在性）
    assert client.post(f"/api/projects/{pid}/vehicles", headers=worker_headers, json={
        "vehicle_type": "潜伏式", "model_name": "E", "quantity": 1}).status_code == 404


def test_vehicle_update_preserves_disabled_dictionary_value(client, admin_headers, pm_headers):
    pid = _create_project(client, pm_headers)
    added = client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "堆高车", "model_name": "H", "quantity": 1}).json()

    # 管理员停用「堆高车」
    tid = next(t["id"] for t in client.get("/api/vehicle-types/all", headers=admin_headers).json()
               if t["name"] == "堆高车")
    client.put(f"/api/vehicle-types/{tid}", headers=admin_headers, json={"is_enabled": False})

    # 普通用户编辑时保留已停用的当前值 → 允许；改为其他字典外值 → 拒绝
    r = client.put(f"/api/projects/{pid}/vehicles/{added['id']}", headers=pm_headers, json={"quantity": 5})
    assert r.status_code == 200
    r = client.put(f"/api/projects/{pid}/vehicles/{added['id']}", headers=pm_headers,
                   json={"vehicle_type": "堆高车"})
    assert r.status_code == 200
    r = client.put(f"/api/projects/{pid}/vehicles/{added['id']}", headers=pm_headers,
                   json={"vehicle_type": "无人叉车"})
    assert r.status_code == 400


# ===== 导入路径：历史字符串归一化且不丢数据 =====

def test_import_normalizes_legacy_and_keeps_arbitrary_types(client, pm_headers):
    payload = {
        "type": "agvpm-project",
        "project": {
            "name": "导入车型项目", "client": "C", "location": "L",
            "start_date": "2026-08-10", "end_date": "2026-09-30",
        },
        "vehicles": [
            {"vehicle_type": "custom", "model_name": "X", "quantity": 1},
            {"vehicle_type": "自定义", "model_name": "Y", "quantity": 1},
            {"vehicle_type": "进口叉车", "model_name": "Z", "quantity": 1},
        ],
        "modules": [], "vehicle_units": [], "issues": [], "schedule": [], "progress": [],
        "preparations": [], "inventory_items": [], "archive_checklist": [],
    }
    r = client.post("/api/projects/import/json", headers=pm_headers, json=payload)
    assert r.status_code == 200
    pid = r.json()["id"]
    types = sorted(v["vehicle_type"] for v in client.get(f"/api/projects/{pid}/vehicles", headers=pm_headers).json())
    assert types.count("其他/定制") == 2
    assert types.count("进口叉车") == 1
    assert "custom" not in types and "自定义" not in types


def test_clone_preserves_vehicle_types(client, pm_headers):
    pid = _create_project(client, pm_headers)
    client.post(f"/api/projects/{pid}/vehicles", headers=pm_headers, json={
        "vehicle_type": "前移式", "model_name": "F", "quantity": 2})
    r = client.post(f"/api/projects/{pid}/clone", headers=pm_headers, json={"name": "克隆车型项目"})
    assert r.status_code == 200
    new_pid = r.json()["id"]
    vehicles = client.get(f"/api/projects/{new_pid}/vehicles", headers=pm_headers).json()
    assert [v["vehicle_type"] for v in vehicles] == ["前移式"]


# ===== 旧数据迁移归一化 =====

def test_migrate_normalizes_legacy_vehicle_strings(client):
    from datetime import date
    from sqlalchemy.orm import Session
    from app.db import engine
    from app.models import Project, Module, Task, Vehicle
    from app.db import _normalize_legacy_vehicle_types

    db = Session(engine)
    try:
        pid = "proj-legacy"
        db.add(Project(id=pid, name="旧数据项目", start_date=date(2026, 8, 10), end_date=date(2026, 9, 30)))
        mod = Module(id="mod-legacy", project_id=pid, name="调试")
        db.add(mod)
        db.flush()
        db.add(Vehicle(project_id=pid, vehicle_type="custom", model_name="L1", quantity=1))
        db.add(Vehicle(project_id=pid, vehicle_type="自定义", model_name="L2", quantity=1))
        db.add(Vehicle(project_id=pid, vehicle_type="老式叉车", model_name="L3", quantity=1))
        db.add(Task(project_id=pid, module_id=mod.id, name="联调",
                    applicable_vehicle_types=["custom", "潜伏式", "自定义"]))
        db.commit()

        _normalize_legacy_vehicle_types(db)
        db.commit()

        types = sorted(v.vehicle_type for v in db.query(Vehicle).filter(Vehicle.project_id == pid).all())
        assert types == ["其他/定制", "其他/定制", "老式叉车"]
        task = db.query(Task).filter(Task.project_id == pid).first()
        assert sorted(task.applicable_vehicle_types) == ["其他/定制", "其他/定制", "潜伏式"]
    finally:
        db.close()


# ===== 排序：重复 ID 显式拒绝，不产生部分写入 =====

def test_reorder_rejects_duplicate_ids(client, admin_headers):
    """重复 ID 必须 400：旧实现只比长度和存在性，[a,a,b] 会被接受并漏写 c。"""
    ids = [t["id"] for t in client.get("/api/vehicle-types/all", headers=admin_headers).json()]
    dup = ids[:1] + ids[:1] + ids[2:]  # 长度不变但首项重复，缺失倒数第二项
    assert len(dup) == len(ids)
    assert set(dup) != set(ids)
    r = client.put("/api/vehicle-types/reorder", headers=admin_headers, json={"ids": dup})
    assert r.status_code == 400
    assert "重复" in r.json()["detail"]


def test_reorder_rejected_duplicate_leaves_sort_unchanged(client, admin_headers):
    """被拒绝的重复排序不得部分写入：所有 sort_order 保持原样。"""
    before = client.get("/api/vehicle-types/all", headers=admin_headers).json()
    ids = [t["id"] for t in before]
    dup = [ids[0], ids[0]] + ids[1:6]  # 长度不变，但首项重复、末项缺失
    assert len(dup) == len(ids)
    r = client.put("/api/vehicle-types/reorder", headers=admin_headers, json={"ids": dup})
    assert r.status_code == 400
    after = client.get("/api/vehicle-types/all", headers=admin_headers).json()
    assert [(t["id"], t["sort_order"]) for t in after] == [(t["id"], t["sort_order"]) for t in before]


# ===== 种子：幂等 + 并发安全（多 worker 首次启动唯一键竞态） =====

def test_seed_vehicle_types_idempotent(client):
    """重复 seed（模拟重启 / 多 worker 重复启动）不重复、不报唯一键错误，顺序不变。"""
    from app.db import SessionLocal
    from app.seed.seed_data import PRESET_VEHICLE_TYPES, seed_vehicle_types
    from app.models import VehicleType

    db = SessionLocal()
    try:
        seed_vehicle_types(db)
        db.commit()
        rows = db.query(VehicleType).order_by(VehicleType.sort_order).all()
        assert [t.name for t in rows] == PRESET_VEHICLE_TYPES
        assert len(rows) == len(PRESET_VEHICLE_TYPES)
    finally:
        db.close()


def test_seed_vehicle_types_preserves_admin_changes(client, admin_headers):
    """管理员停用/重排后再次 seed，只补缺失项，不覆盖管理员修改。"""
    from app.db import SessionLocal
    from app.seed.seed_data import seed_vehicle_types
    from app.models import VehicleType

    all_rows = client.get("/api/vehicle-types/all", headers=admin_headers).json()
    tid = next(t["id"] for t in all_rows if t["name"] == "堆高车")
    client.put(f"/api/vehicle-types/{tid}", headers=admin_headers, json={"is_enabled": False})

    db = SessionLocal()
    try:
        seed_vehicle_types(db)
        db.commit()
        rows = {t.name: t for t in db.query(VehicleType).all()}
        assert rows["堆高车"].is_enabled is False  # 停用被保留
        assert len(rows) == 7
    finally:
        db.close()


def test_seed_vehicle_types_concurrent_empty_dict_sqlite(client):
    """双会话并发面对空字典 seed（多 worker 首次启动竞态）：不抛唯一键错误，恰好一份。"""
    import threading
    from app.db import SessionLocal
    from app.seed.seed_data import PRESET_VEHICLE_TYPES, seed_vehicle_types
    from app.models import VehicleType

    # 制造“两个 worker 首次面对空字典”的起点
    db = SessionLocal()
    try:
        db.query(VehicleType).delete()
        db.commit()
    finally:
        db.close()

    errors = []
    barrier = threading.Barrier(2)

    def _seed():
        s = SessionLocal()
        try:
            barrier.wait(timeout=10)
            seed_vehicle_types(s)
            s.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            s.close()

    threads = [threading.Thread(target=_seed) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    assert not errors, [str(e) for e in errors]
    db = SessionLocal()
    try:
        rows = db.query(VehicleType).order_by(VehicleType.sort_order).all()
        assert [t.name for t in rows] == PRESET_VEHICLE_TYPES
        assert len(rows) == len(PRESET_VEHICLE_TYPES)
    finally:
        db.close()
