"""Seed default roles, admin user, and global template data."""

def seed_preset_templates(db):
    """预置场景模板（幂等：仅当没有用户模板时创建）。"""
    from app.models import Template, Module as Mod, Phase, ChangeLog, DocumentRequirement
    from app.routers.templates import copy_tree

    if not db.query(Phase.id).filter(Phase.project_id.is_(None), Phase.template_id.is_(None), Phase.name != "项目准备").first():
        return

    PRESET_TEMPLATES = [
        {
            "name": "标准 AGV 实施模板",
            "description": "全流程 9 阶段，适合大多数项目",
            "selected_modules": None,
        },
        {
            "name": "潜伏式简版模板",
            "description": "单车型小项目：只保留到货/单车调试/联调/培训验收",
            "selected_modules": ["到货检查", "单车调试", "系统联调", "培训验收"],
        },
        {
            "name": "叉车重载项目模板",
            "description": "叉车/堆高车场景：全核心 + PLC、自动充电",
            "selected_modules": None,
            "extra_modules": ["PLC", "自动充电"],
        },
        {
            "name": "多车型集成模板",
            "description": "多车型 + 外设全配：全模块（含相机/二维码/自动门/电梯）",
            "selected_modules": None,
            "extra_modules": None,
        },
    ]
    for preset in PRESET_TEMPLATES:
        t = db.query(Template).filter(Template.name == preset["name"]).first()
        if t is not None:
            # 只修复旧初始化过早生成的空预置方案；有内容或用户编辑记录的一律保留。
            if db.query(DocumentRequirement.id).filter(DocumentRequirement.template_id == t.id).first() or t.description != preset["description"] or db.query(Phase.id).filter(Phase.template_id == t.id).first() or db.query(Mod.id).filter(Mod.template_id == t.id).first() or db.query(ChangeLog.id).filter(ChangeLog.entity_id == t.id, ChangeLog.entity_type == 'template').first():
                continue
        else:
            t = Template(name=preset["name"], description=preset["description"], is_system=False)
            db.add(t)
            db.flush()
        copy_tree(db, "default", t.id)
        if preset.get("selected_modules") is not None:
            for m in db.query(Mod).filter(Mod.template_id == t.id, Mod.project_id.is_(None)).all():
                m.is_selected = m.name in preset["selected_modules"]
        elif preset.get("extra_modules") is not None:
            for m in db.query(Mod).filter(Mod.template_id == t.id, Mod.project_id.is_(None)).all():
                if m.category == "extra":
                    m.is_selected = m.name in preset["extra_modules"]
        else:
            for m in db.query(Mod).filter(Mod.template_id == t.id, Mod.project_id.is_(None)).all():
                m.is_selected = True
    # 发布一个种子模板：标准模板建好即发布，模板中心至少有一个可直接选用的已发布版本。
    standard = db.query(Template).filter(Template.name == "标准 AGV 实施模板").first()
    if standard and standard.status != "published":
        standard.status = "published"
        standard.version = max(standard.version or 1, 1)
    db.flush()




def _demo_password_hash(env_name: str, fallback_hash: str) -> str:
    """演示账号密码哈希：`DEMO_*_PASSWORD` 环境变量可覆盖默认值（轮换演示凭据，
    对外暴露前必须设置），未设置时退回预计算哈希（演示环境开箱可用、测试快速）。
    """
    import os
    from passlib.context import CryptContext

    override = os.getenv(env_name, "")
    if override:
        if len(override) < 8:
            raise RuntimeError(f"{env_name} 至少需要 8 个字符")
        return CryptContext(schemes=["bcrypt"]).hash(override)
    return fallback_hash


def seed_all(db):
    """Seed roles, admin user, and global template.

    v1.2.1：生产环境可用 SEED_DEMO_USERS=0 只创建 admin（不建演示账号）；
    默认保持演示账号（本地开发/测试需要）。
    """
    import os
    import logging
    from passlib.context import CryptContext
    from app.models import User, Phase, Module, Task, CheckItem, Template

    _pwd = CryptContext(schemes=["bcrypt"])
    logger = logging.getLogger(__name__)

    seed_demo = os.getenv("SEED_DEMO_USERS", "0") == "1"
    initial_admin_password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    demo_admin_password = os.getenv("DEMO_ADMIN_PASSWORD", "")
    rotate = os.getenv("ADMIN_PASSWORD_ROTATE", "") == "1"

    # Check if already seeded
    existing = db.query(User).filter_by(username="admin").first()

    # 演示账号暴露面收口（P0-安全，生产必须 SEED_DEMO_USERS=0）：
    # 生产模式不创建演示账号（见下方 seed_demo 分支）；对 seed 内置的存量演示账号
    # （固定 fixture ID，不含业务自建的同名账号）若仍持有公开已知的默认口令
    # （pm123/worker123），一律幂等禁用并使旧会话失效。已由运维轮换为强口令的
    # 演示账号（哈希不再匹配默认口令）不受影响，保持可用。
    if not seed_demo:
        _demo_fixture_ids = ("user-pm-001", "user-worker-001", "user-worker-002")
        _known_demo_defaults = {
            "user-pm-001": "pm123",
            "user-worker-001": "worker123",
            "user-worker-002": "worker123",
        }
        _demo_fixtures = db.query(User).filter(User.id.in_(_demo_fixture_ids)).all()
        _disabled = 0
        for _u in _demo_fixtures:
            _known_pw = _known_demo_defaults.get(_u.id)
            _is_default = False
            if _known_pw:
                try:
                    _is_default = _pwd.verify(_known_pw, _u.password_hash)
                except Exception:
                    _is_default = False
            if _is_default and _u.is_active:
                _u.is_active = False
                _u.token_version = (getattr(_u, "token_version", 0) or 0) + 1
                _disabled += 1
        if _disabled:
            db.flush()
            logger.warning(
                f"生产模式已禁用 {_disabled} 个仍持默认口令的演示账号（pm123/worker123），旧会话全部失效"
            )

    # 存量 admin 显式密码轮换（P0-安全，仅 ADMIN_PASSWORD_ROTATE=1 时生效）：
    # - 显式：必须显式开启轮换标志，不会在每次启动静默改密；
    # - 安全：密码未变则幂等跳过（不重哈希、不失效会话），轮换后
    #   token_version +1 使全部旧会话立即失效；
    # - 不可泄密：明文只来自环境变量，不打印、不写日志、不落盘。
    if existing and rotate:
        rotate_password = initial_admin_password or demo_admin_password
        if not rotate_password or len(rotate_password) < 8:
            raise RuntimeError(
                "ADMIN_PASSWORD_ROTATE=1 时必须同时提供至少 8 位的 "
                "INITIAL_ADMIN_PASSWORD 或 DEMO_ADMIN_PASSWORD"
            )
        if not _pwd.verify(rotate_password, existing.password_hash):
            existing.password_hash = _pwd.hash(rotate_password)
            existing.token_version = (existing.token_version or 0) + 1
            db.flush()
            logger.info("存量 admin 密码已按 ADMIN_PASSWORD_ROTATE 轮换，旧会话全部失效")
        return

    if existing:
        return

    if not seed_demo and not initial_admin_password:
        raise RuntimeError(
            "首次生产启动必须设置 INITIAL_ADMIN_PASSWORD（至少 8 个字符）"
        )
    if initial_admin_password and len(initial_admin_password) < 8:
        raise RuntimeError("INITIAL_ADMIN_PASSWORD 至少需要 8 个字符")
    if demo_admin_password and len(demo_admin_password) < 8:
        raise RuntimeError("DEMO_ADMIN_PASSWORD 至少需要 8 个字符")

    if initial_admin_password:
        admin_password_hash = _pwd.hash(initial_admin_password)
    elif demo_admin_password:
        # 演示模式：管理员密码可经 DEMO_ADMIN_PASSWORD 轮换，不强制硬编码 admin123。
        admin_password_hash = _pwd.hash(demo_admin_password)
    else:
        # Demo/test mode only: admin123.
        admin_password_hash = "$2b$12$XS6QmzmIE6Zq/LSrO91X6.mCA3D1y4X/3xhGBrs2t3WKLOsg4Xu6m"

    # Production receives an operator-supplied bootstrap password. Demo/test
    # mode keeps the precomputed hash so repeated fixture setup stays fast.
    admin = User(
        id="user-admin-001",
        username="admin",
        password_hash=admin_password_hash,
        display_name="系统管理员",
        role="admin",
        is_active=True,
    )
    db.add(admin)

    if seed_demo:
        # Create a demo PM（密码可经 DEMO_PM_PASSWORD 轮换）
        pm = User(
            id="user-pm-001",
            username="pm",
            password_hash=_demo_password_hash("DEMO_PM_PASSWORD", "$2b$12$X0XbdrvjQFhHNVnjMT05xeUX/u4wFFpGR30BL4x7EWbw50QVQeL26"),
            display_name="项目经理",
            role="pm",
            is_active=True,
        )
        db.add(pm)

        # Create demo workers（密码可经 DEMO_WORKER_PASSWORD 轮换）
        _worker_hash = _demo_password_hash("DEMO_WORKER_PASSWORD", "$2b$12$kGMBaDwEyazO8VGpPRPz1.m/qsGKF6mUyYf2UlAM.DY3URm/H7Qh2")
        worker1 = User(
            id="user-worker-001",
            username="worker1",
            password_hash=_worker_hash,
            display_name="现场工程师A",
            role="worker",
            is_active=True,
        )
        db.add(worker1)
        worker2 = User(
            id="user-worker-002",
            username="worker2",
            password_hash=_worker_hash,
            display_name="现场工程师B",
            role="worker",
            is_active=True,
        )
        db.add(worker2)

    db.flush()

    # ===== Seed Global Template =====
    # Phases (8 default phases)
    phase_data = [
        ("phase-09", "项目准备", 1, "#1677ff", "准备清单确认", "必需准备项完成"),
        ("phase-01", "进场准备", 2, "#1890ff", "场地勘测完成、施工方案确认", "网络布线就绪、安全围栏就绪"),
        ("phase-02", "到货检查", 3, "#52c41a", "设备到货", "所有设备开箱检查通过"),
        ("phase-03", "单车调试", 4, "#faad14", "到货检查完成", "所有车辆单车调试通过"),
        ("phase-04", "地图与站点", 5, "#722ed1", "单车调试完成", "地图建图完成、站点设置完成"),
        ("phase-05", "系统部署", 6, "#eb2f96", "地图就绪", "服务器/数据库/通信部署完成"),
        ("phase-06", "系统联调", 7, "#fa541c", "系统部署+外设安装完成", "全系统联调通过"),
        ("phase-07", "试运行", 8, "#13c2c2", "系统联调完成", "连续稳定运行验收标准达成"),
        ("phase-08", "培训验收", 9, "#2f54eb", "试运行通过", "培训完成、终验签字"),
    ]

    phases = {}
    for pid, name, order, color, entry, exit_c in phase_data:
        p = Phase(id=pid, project_id=None, name=name, sort_order=order,
                   color=color, entry_criteria=entry, exit_criteria=exit_c)
        db.add(p)
        phases[pid] = p

    db.flush()

    # Modules per phase (core modules = same name as phase; extra modules in 系统联调)
    modules_data = [
        # Core modules
        ("mod-01", "phase-01", "进场准备", "core", 1),
        ("mod-02", "phase-02", "到货检查", "core", 1),
        ("mod-03", "phase-03", "单车调试", "core", 1),
        ("mod-04", "phase-04", "地图与站点", "core", 1),
        ("mod-05", "phase-05", "系统部署", "core", 1),
        ("mod-06", "phase-06", "系统联调", "core", 1),
        ("mod-07", "phase-07", "试运行", "core", 1),
        ("mod-08", "phase-08", "培训验收", "core", 1),
        # Extra modules (attached to 系统联调 phase by default)
        ("mod-09", "phase-06", "相机", "extra", 2),
        ("mod-10", "phase-06", "二维码扫描", "extra", 3),
        ("mod-11", "phase-06", "自动门", "extra", 4),
        ("mod-12", "phase-06", "电梯", "extra", 5),
        ("mod-13", "phase-06", "PLC", "extra", 6),
        ("mod-14", "phase-06", "PDA", "extra", 7),
        ("mod-15", "phase-06", "自动充电", "extra", 8),
        # 项目准备阶段模块（准备项=模块任务，与进场准备平级；条件模块按项目选项生成）
        ("mod-16", "phase-09", "项目准备", "core", 1),
        ("mod-17", "phase-09", "WMS 接口", "extra", 2),
        ("mod-18", "phase-09", "自动充电", "extra", 3),
        ("mod-19", "phase-09", "客户服务器", "extra", 4),
        ("mod-20", "phase-09", "新造车辆", "extra", 5),
        ("mod-21", "phase-09", "海外项目", "extra", 6),
    ]

    modules = {}
    for mid, pid, name, cat, order in modules_data:
        m = Module(id=mid, project_id=None, phase_id=pid, name=name,
                    preparation_conditions=["need_charging"] if mid=="mod-15" else [],
                    category=cat, is_selected=(cat == "core"), sort_order=order)
        db.add(m)
        modules[mid] = m

    db.flush()

    # Tasks per module (simplified seeding — core tasks for each module)
    tasks_data = [
        ("task-001", "mod-01", "场地勘测", "manual", None, "项", None, False, [], 1),
        ("task-002", "mod-01", "网络与布线", "manual", None, "项", None, False, [], 2),
        ("task-003", "mod-01", "安全围栏检查", "manual", None, "项", None, True, [], 3),
        ("task-004", "mod-01", "施工方案确认", "fixed", 1, "项", None, False, [], 4),
        ("task-005", "mod-02", "开箱检查", "per_vehicle", None, "台", None, False, [], 1),
        ("task-006", "mod-02", "配件清点", "per_vehicle", None, "台", None, False, [], 2),
        ("task-007", "mod-02", "电池与充电器检查", "per_vehicle", None, "台", None, True, [], 3),
        ("task-008", "mod-02", "到货文档归档", "fixed", 1, "项", None, False, [], 4),
        ("task-009", "mod-03", "单车机械与导航调试", "per_vehicle", None, "台", None, False, [], 1),
        ("task-010", "mod-03", "安全激光及停车距离验证", "per_vehicle", None, "台", None, True, [], 2),
        ("task-011", "mod-03", "单车配置和程序备份", "per_vehicle", None, "台", None, False, [], 3),
        ("task-012", "mod-03", "载荷测试", "per_vehicle", None, "台", None, True, [], 4),
        ("task-013", "mod-03", "异常急停测试", "per_vehicle", None, "台", None, True, [], 5),
        ("task-014", "mod-04", "场地建图", "manual", None, "项", None, False, [], 1),
        ("task-015", "mod-04", "站点设置", "manual", None, "个", None, False, [], 2),
        ("task-016", "mod-04", "路径规划与优化", "manual", None, "项", None, False, [], 3),
        ("task-017", "mod-04", "地图验证与备份", "fixed", 1, "项", None, False, [], 4),
        ("task-018", "mod-05", "服务器部署与配置", "fixed", 1, "台", None, False, [], 1),
        ("task-019", "mod-05", "数据库与通信部署", "fixed", 1, "项", None, False, [], 2),
        ("task-020", "mod-05", "网络配置与安全", "fixed", 1, "项", None, False, [], 3),
        ("task-021", "mod-05", "系统备份策略部署", "fixed", 1, "项", None, False, [], 4),
        ("task-022", "mod-06", "多车联调", "per_vehicle", None, "台", None, False, [], 1),
        ("task-023", "mod-06", "任务调度联调", "fixed", 1, "项", None, False, [], 2),
        ("task-024", "mod-06", "异常处理联调", "fixed", 1, "项", None, True, [], 3),
        ("task-025", "mod-06", "系统性能测试", "fixed", 1, "项", None, False, [], 4),
        ("task-026", "mod-07", "连续运行监控", "fixed", 7, "天", None, False, [], 1),
        ("task-027", "mod-07", "异常统计与消缺", "fixed", 1, "项", None, False, [], 2),
        ("task-028", "mod-07", "运行报告编制", "fixed", 1, "项", None, False, [], 3),
        ("task-029", "mod-08", "操作培训", "manual", None, "人", None, False, [], 1),
        ("task-030", "mod-08", "维护培训", "manual", None, "人", None, False, [], 2),
        ("task-031", "mod-08", "最终验收", "fixed", 1, "项", None, False, [], 3),
        ("task-032", "mod-08", "验收文档归档", "fixed", 1, "项", None, False, [], 4),
        ("task-033", "mod-09", "相机安装与标定", "manual", None, "个", None, False, [], 1),
        ("task-034", "mod-09", "相机系统联调", "manual", None, "个", None, False, [], 2),
        ("task-035", "mod-10", "二维码安装", "manual", None, "个", None, False, [], 1),
        ("task-036", "mod-10", "二维码扫描联调", "manual", None, "个", None, False, [], 2),
        ("task-037", "mod-11", "自动门对接安装", "manual", None, "个", None, False, [], 1),
        ("task-038", "mod-11", "自动门联调", "manual", None, "个", None, True, [], 2),
        ("task-039", "mod-12", "电梯对接安装", "manual", None, "个", None, False, [], 1),
        ("task-040", "mod-12", "电梯联调", "manual", None, "个", None, True, [], 2),
        ("task-041", "mod-13", "PLC 接口对接", "manual", None, "个", None, False, [], 1),
        ("task-042", "mod-13", "PLC 信号联调", "manual", None, "个", None, False, [], 2),
        ("task-043", "mod-14", "PDA 终端部署", "manual", None, "个", None, False, [], 1),
        ("task-044", "mod-14", "PDA 系统联调", "manual", None, "个", None, False, [], 2),
        ("task-045", "mod-15", "充电桩安装", "manual", None, "个", None, False, [], 1),
        ("task-046", "mod-15", "自动充电联调", "per_vehicle", None, "台", None, True, [], 2),
        # ===== 项目准备阶段（准备项=任务，与进场准备平级；属性在 template_preparation_items）=====
        ("task-047", "mod-16", "项目实施范围冻结", "manual", 1, "项", None, False, [], 1),
        ("task-048", "mod-16", "现场布局图", "manual", 1, "项", None, False, [], 2),
        ("task-049", "mod-16", "点位表", "manual", 1, "项", None, False, [], 3),
        ("task-050", "mod-16", "客户系统接口文档（WMS/MES）", "manual", 1, "项", None, False, [], 4),
        ("task-051", "mod-16", "验收标准确认", "manual", 1, "项", None, False, [], 5),
        ("task-052", "mod-16", "车辆交付", "manual", 1, "项", None, False, [], 6),
        ("task-053", "mod-16", "调度系统项目配置", "manual", 1, "项", None, False, [], 7),
        ("task-054", "mod-16", "现场施工完成", "manual", 1, "项", None, False, [], 8),
        ("task-055", "mod-16", "网络检查", "manual", 1, "项", None, False, [], 9),
        ("task-056", "mod-16", "实施人员安排", "manual", 1, "项", None, False, [], 10),
        ("task-057", "mod-16", "入场手续", "manual", 1, "项", None, False, [], 11),
        ("task-058", "mod-17", "接口协议确认", "manual", 1, "项", None, False, [], 1),
        ("task-059", "mod-17", "测试环境提供", "manual", 1, "项", None, False, [], 2),
        ("task-060", "mod-17", "测试账号提供", "manual", 1, "项", None, False, [], 3),
        ("task-061", "mod-17", "网络连通检查", "manual", 1, "项", None, False, [], 4),
        ("task-062", "mod-17", "联调计划确认", "manual", 1, "项", None, False, [], 5),
        ("task-063", "mod-18", "充电设备交付", "manual", 1, "项", None, False, [], 1),
        ("task-064", "mod-18", "充电区域施工", "manual", 1, "项", None, False, [], 2),
        ("task-065", "mod-18", "电源条件确认", "manual", 1, "项", None, False, [], 3),
        ("task-066", "mod-18", "充电通讯测试条件", "manual", 1, "项", None, False, [], 4),
        ("task-067", "mod-19", "服务器配置确认", "manual", 1, "项", None, False, [], 1),
        ("task-068", "mod-19", "操作系统准备", "manual", 1, "项", None, False, [], 2),
        ("task-069", "mod-19", "网络端口开放", "manual", 1, "项", None, False, [], 3),
        ("task-070", "mod-19", "远程访问方式确认", "manual", 1, "项", None, False, [], 4),
        ("task-071", "mod-20", "设计冻结", "manual", 1, "项", None, False, [], 1),
        ("task-072", "mod-20", "首车完成", "manual", 1, "项", None, False, [], 2),
        ("task-073", "mod-20", "厂内测试通过", "manual", 1, "项", None, False, [], 3),
        ("task-074", "mod-20", "发货", "manual", 1, "项", None, False, [], 4),
        ("task-075", "mod-20", "到场确认", "manual", 1, "项", None, False, [], 5),
        ("task-076", "mod-21", "发运和清关计划", "manual", 1, "项", None, False, [], 1),
        ("task-077", "mod-21", "人员签证/邀请函", "manual", 1, "项", None, False, [], 2),
        ("task-078", "mod-21", "入场手续（海外）", "manual", 1, "项", None, False, [], 3),
        ("task-079", "mod-21", "当地网络和通信条件", "manual", 1, "项", None, False, [], 4),
        ("task-080", "mod-21", "现场交通住宿安排", "manual", 1, "项", None, False, [], 5),
    ]

    tasks = {}
    for tid, mid, name, qtype, qty, unit, hours, safety, vtypes, order in tasks_data:
        t = Task(id=tid, project_id=None, module_id=mid, phase_id=modules[mid].phase_id, group_label=modules[mid].name, scope_conditions=list(modules[mid].preparation_conditions or []), name=name,
                  quantity_type=qtype, target_quantity=qty, unit=unit, vehicle_step_key=DEFAULT_TASK_VEHICLE_STEPS.get(tid),
                  standard_hours=hours, safety_flag=safety,
                  applicable_vehicle_types=vtypes, sort_order=order)
        db.add(t)
        tasks[tid] = t

    db.flush()

    # Check items per task
    check_items_data = [
        # 进场准备
        ("ci-001", "task-001", "场地尺寸与平整度测量", True, False, 1),
        ("ci-002", "task-001", "通道宽度与转弯半径确认", True, False, 2),
        ("ci-003", "task-002", "WiFi 信号覆盖测试(≥−65dBm)", True, False, 1),
        ("ci-004", "task-002", "网络带宽与延迟测试", True, False, 2),
        ("ci-005", "task-002", "专用 VLAN 配置确认", True, False, 3),
        ("ci-006", "task-003", "安全围栏完整性检查", True, True, 1),
        ("ci-007", "task-003", "警示标识与标线检查", True, True, 2),
        ("ci-008", "task-004", "施工方案各节点签字确认", True, False, 1),

        # 到货检查
        ("ci-009", "task-005", "外观检查无损伤", True, False, 1),
        ("ci-010", "task-005", "核对设备清单与型号", True, False, 2),
        ("ci-011", "task-005", "拍照存档", True, False, 3),
        ("ci-012", "task-006", "配件数量核对", True, False, 1),
        ("ci-013", "task-006", "配件完好性检查", True, False, 2),
        ("ci-014", "task-007", "电池外观与电压检查", True, True, 1),
        ("ci-015", "task-007", "充电器功能测试", True, True, 2),
        ("ci-016", "task-008", "到货签收单归档", True, False, 1),

        # 单车调试
        ("ci-017", "task-009", "机械机构和动作方向调试", True, False, 1),
        ("ci-018", "task-009", "导航及到点精度标定(≤30mm)", True, False, 2),
        ("ci-019", "task-009", "空载运行测试(30分钟)", True, False, 3),
        ("ci-020", "task-010", "安全激光传感器功能验证", True, True, 1),
        ("ci-021", "task-010", "停车距离验证(≤设定值)", True, True, 2),
        ("ci-022", "task-010", "安全PLC信号验证", True, True, 3),
        ("ci-023", "task-011", "车辆参数配置备份", True, False, 1),
        ("ci-024", "task-011", "控制程序版本记录与备份", True, False, 2),
        ("ci-025", "task-012", "额定载荷运行测试", True, True, 1),
        ("ci-026", "task-012", "过载保护验证", True, True, 2),
        ("ci-027", "task-013", "紧急停止按钮功能(100ms内断电)", True, True, 1),
        ("ci-028", "task-013", "碰撞传感器/触边功能", True, True, 2),
        ("ci-029", "task-013", "失速保护验证", True, True, 3),

        # 地图与站点
        ("ci-030", "task-014", "SLAM建图(≥3次,取最优)", True, False, 1),
        ("ci-031", "task-014", "地图精度验证", True, False, 2),
        ("ci-032", "task-015", "工位站点坐标录入", True, False, 1),
        ("ci-033", "task-015", "充电站点设置", True, False, 2),
        ("ci-034", "task-016", "路径规划合理性检查", True, False, 1),
        ("ci-035", "task-016", "交通管制区域设置", True, False, 2),
        ("ci-036", "task-016", "拥堵风险点分析与规避", True, False, 3),
        ("ci-037", "task-017", "地图文件备份(本地+云端)", True, False, 1),

        # 系统部署
        ("ci-038", "task-018", "服务器硬件上架与上电", True, False, 1),
        ("ci-039", "task-018", "操作系统与运行环境安装", True, False, 2),
        ("ci-040", "task-018", "调度系统安装与配置", True, False, 3),
        ("ci-041", "task-019", "数据库安装与初始化", True, False, 1),
        ("ci-042", "task-019", "通信中间件部署(MQTT/OPC UA)", True, False, 2),
        ("ci-043", "task-019", "与WMS/ERP接口配置", True, False, 3),
        ("ci-044", "task-020", "防火墙规则配置", True, False, 1),
        ("ci-045", "task-020", "VPN/远程访问配置", True, False, 2),
        ("ci-046", "task-021", "自动备份脚本部署", True, False, 1),
        ("ci-047", "task-021", "备份恢复测试", True, False, 2),

        # 系统联调
        ("ci-048", "task-022", "多车任务分配测试", True, False, 1),
        ("ci-049", "task-022", "多车交通管制测试", True, False, 2),
        ("ci-050", "task-022", "多车充电调度测试", True, False, 3),
        ("ci-051", "task-023", "任务创建→执行→完成全流程", True, False, 1),
        ("ci-052", "task-023", "任务优先级与抢占测试", True, False, 2),
        ("ci-053", "task-023", "任务取消与重分配测试", True, False, 3),
        ("ci-054", "task-024", "断网恢复测试", True, True, 1),
        ("ci-055", "task-024", "车辆故障自动接管测试", True, True, 2),
        ("ci-056", "task-024", "紧急情况全系统停止测试", True, True, 3),
        ("ci-057", "task-025", "满载吞吐量测试(≥设计值120%)", True, False, 1),
        ("ci-058", "task-025", "系统响应延迟测试(≤200ms)", True, False, 2),

        # 试运行
        ("ci-059", "task-026", "每日运行日志记录", True, False, 1),
        ("ci-060", "task-026", "运行数据统计分析", True, False, 2),
        ("ci-061", "task-026", "连续运行≥7天无重大故障", True, False, 3),
        ("ci-062", "task-027", "异常事件分类统计", True, False, 1),
        ("ci-063", "task-027", "根因分析与整改措施", True, False, 2),
        ("ci-064", "task-027", "整改后复测验证", True, True, 3),
        ("ci-065", "task-028", "试运行报告编制", True, False, 1),
        ("ci-066", "task-028", "运行数据归档", True, False, 2),

        # 培训验收
        ("ci-067", "task-029", "操作手册交付", True, False, 1),
        ("ci-068", "task-029", "操作人员实操考核(100%通过)", True, False, 2),
        ("ci-069", "task-030", "维护手册交付", True, False, 1),
        ("ci-070", "task-030", "维护人员实操考核", True, False, 2),
        ("ci-071", "task-031", "验收标准逐项确认", True, False, 1),
        ("ci-072", "task-031", "客户签字验收", True, False, 2),
        ("ci-073", "task-032", "全部项目文档归档", True, False, 1),
        ("ci-074", "task-032", "系统最终配置快照", True, False, 2),
    ]

    for cid, tid, name, required, safety, order in check_items_data:
        ci = CheckItem(id=cid, task_id=tid, project_id=None,
                        name=name, is_required=required,
                        is_safety_critical=safety, sort_order=order)
        db.add(ci)

    # 默认模板元数据（系统默认模板 = template_id NULL 的树）
    db.add(Template(name="系统默认模板", description="标准 AGV 实施流程", is_system=True))
    db.flush()

    # 预置场景模板（全部可编辑/复制/重命名/删除）
    seed_preset_templates(db)
    # 默认常用采购项库（项目经理显式勾选后才带入）
    seed_template_procurements(db)

    db.commit()
    user_count = 4 if seed_demo else 1
    print(f"✓ Seed data created: {user_count} users, 9 phases, 21 modules + 预置模板 + 常用采购项库")




# 「项目准备」模板阶段的模块与任务（迁移旧库时补插用；新库由 seed_all 直接建）
PREP_PHASE_MODULES = [
    ("mod-16", "项目准备", ["项目实施范围冻结", "现场布局图", "点位表", "客户系统接口文档（WMS/MES）",
                            "验收标准确认", "车辆交付", "调度系统项目配置", "现场施工完成", "网络检查",
                            "实施人员安排", "入场手续"]),
    ("mod-17", "WMS 接口", ["接口协议确认", "测试环境提供", "测试账号提供", "网络连通检查", "联调计划确认"]),
    ("mod-18", "自动充电", ["充电设备交付", "充电区域施工", "电源条件确认", "充电通讯测试条件"]),
    ("mod-19", "客户服务器", ["服务器配置确认", "操作系统准备", "网络端口开放", "远程访问方式确认"]),
    ("mod-20", "新造车辆", ["设计冻结", "首车完成", "厂内测试通过", "发货", "到场确认"]),
    ("mod-21", "海外项目", ["发运和清关计划", "人员签证/邀请函", "入场手续（海外）", "当地网络和通信条件", "现场交通住宿安排"]),
]

TEMPLATE_PREP_ITEMS = [
    # (name, category, required, blocks, party, risk, condition)
    ("项目实施范围冻结", "scope", True, True, "project", "low", "default"),
    ("现场布局图", "scope", True, False, "client", "medium", "default"),
    ("点位表", "scope", True, True, "client", "high", "default"),
    ("客户系统接口文档（WMS/MES）", "scope", False, False, "client", "medium", "default"),
    ("验收标准确认", "scope", True, False, "client", "low", "default"),
    ("车辆交付", "vehicle", True, True, "production", "high", "default"),
    ("调度系统项目配置", "software", True, False, "software", "high", "default"),
    ("现场施工完成", "site", True, True, "client", "high", "default"),
    ("网络检查", "site", True, True, "client", "high", "default"),
    ("实施人员安排", "site", True, False, "project", "medium", "default"),
    ("入场手续", "site", True, True, "project", "medium", "default"),
    # 条件组：need_wms
    ("接口协议确认", "scope", True, True, "client", "high", "need_wms"),
    ("测试环境提供", "scope", True, False, "client", "high", "need_wms"),
    ("测试账号提供", "scope", False, False, "client", "medium", "need_wms"),
    ("网络连通检查", "site", True, True, "client", "high", "need_wms"),
    ("联调计划确认", "software", True, False, "software", "medium", "need_wms"),
    # 条件组：need_charging
    ("充电设备交付", "vehicle", True, True, "procurement", "high", "need_charging"),
    ("充电区域施工", "site", True, True, "client", "high", "need_charging"),
    ("电源条件确认", "site", True, False, "client", "medium", "need_charging"),
    ("充电通讯测试条件", "software", False, False, "software", "low", "need_charging"),
    # 条件组：client_server
    ("服务器配置确认", "scope", True, False, "client", "high", "client_server"),
    ("操作系统准备", "scope", True, False, "client", "medium", "client_server"),
    ("网络端口开放", "site", True, True, "client", "high", "client_server"),
    ("远程访问方式确认", "scope", False, False, "client", "low", "client_server"),
    # 条件组：new_vehicles
    ("设计冻结", "vehicle", True, False, "production", "medium", "new_vehicles"),
    ("首车完成", "vehicle", True, False, "production", "high", "new_vehicles"),
    ("厂内测试通过", "vehicle", True, True, "production", "high", "new_vehicles"),
    ("发货", "vehicle", True, True, "production", "high", "new_vehicles"),
    ("到场确认", "vehicle", True, True, "production", "high", "new_vehicles"),
    # 条件组：overseas
    ("发运和清关计划", "scope", True, True, "project", "high", "overseas"),
    ("人员签证/邀请函", "site", True, True, "project", "high", "overseas"),
    ("入场手续（海外）", "site", True, False, "client", "medium", "overseas"),
    ("当地网络和通信条件", "site", True, False, "client", "medium", "overseas"),
    ("现场交通住宿安排", "site", False, False, "project", "low", "overseas"),
]


# 默认模板采购项：(名称, 单位, 规格, 必需, 风险)
# 数量不在模板内：项目内带入/创建时再确认数量。
# 到货状态由项目页维护（未申请 / 已下单 / 采购中 / 已到货）。
TEMPLATE_PROCUREMENT_ITEMS = [
    ("AGV 本体", "台", "按合同型号与配置（数量请在项目内确认）", True, "high"),
    ("车载工控机", "台", "含 4G 模块与硬盘（每车 1 台）", False, "medium"),
    ("自动充电桩", "台", "按车辆 1:1 选型，含安装底座", True, "medium"),
    ("安全围栏", "米", "铝合金围栏 1.2m 高，含立柱", False, "medium"),
    ("工业路由器", "台", "4G 工业路由器，双卡", False, "low"),
    ("千兆交换机", "台", "8 口千兆工业级", False, "low"),
    ("网线与水晶头", "箱", "超五类成品线 + 备用水晶头", False, "low"),
    ("WMS 接口服务器", "台", "客户机房机架式，含系统", True, "high"),
    ("客户服务器部署包", "套", "由软件团队提供介质与授权", False, "high"),
    ("海外海运包装", "套", "木箱 + 防潮干燥剂 + 外文标识", True, "high"),
]


def seed_template_procurements(db):
    """默认常用采购项库（幂等，不会自动带入项目）。"""
    from app.models import TemplatePreparationItem, TemplateProcurementItem
    existing = db.query(TemplateProcurementItem).filter(TemplateProcurementItem.template_id.is_(None)).count()
    if existing > 0:
        required_names = {"AGV 本体", "自动充电桩", "WMS 接口服务器", "海外海运包装"}
        for item in db.query(TemplateProcurementItem).filter(TemplateProcurementItem.template_id.is_(None)).all():
            item.is_required = item.name in required_names
        db.flush()
        return
    for i, (name, unit, spec, req, risk) in enumerate(TEMPLATE_PROCUREMENT_ITEMS):
        db.add(TemplateProcurementItem(
            template_id=None, name=name, unit=unit, spec=spec,
            is_required=req, risk=risk, sort_order=i,
        ))
    db.flush()


def seed_template_preparations(db):
    """Retired: T22 freezes old rows and converts their requirements once in migration."""
    return


PRESET_VEHICLE_TYPES = ["潜伏式", "平衡重叉车", "堆高车", "前移式", "滚筒车", "顶升车", "其他/定制"]

# 默认模板中按车辆的工作显式对应 H-2 默认车辆环节；生成项目时随工作复制。
# 存量安装由迁移 g3a30b000002 按同一冻结映射补齐，已生成项目不改。
DEFAULT_TASK_VEHICLE_STEPS = {
    "task-005": "arrival_inspection", "task-006": "arrival_inspection", "task-007": "arrival_inspection",
    "task-009": "single_commissioning", "task-010": "single_commissioning", "task-011": "single_commissioning",
    "task-012": "single_commissioning", "task-013": "single_commissioning",
    "task-022": "system_integration", "task-046": "system_integration",
}


def seed_vehicle_types(db):
    """预置车型字典（并发安全幂等：按方言 INSERT ... ON CONFLICT DO NOTHING）。

    生产以 `uvicorn --workers 2` 运行，每个 worker 的 lifespan 都会调用 init_db()。
    老实现“查询已有名称 → 逐项 INSERT”在空字典并发首次启动时，两个 worker 可能同时
    插入同名车型，触发 name 唯一键冲突导致其中一个 worker 启动失败。
    改为原子插入后：重复/并发启动的 INSERT 被数据库静默跳过，不报唯一键错误，且不会
    覆盖管理员后续的新增/排序/停用（只补缺失项，语义与原实现一致）。
    SQLite（≥3.24）与 PostgreSQL 均支持 `INSERT ... ON CONFLICT DO NOTHING`。
    """
    from sqlalchemy import text
    from app.models import gen_uuid
    from app.time_utils import utcnow

    now = utcnow()
    for i, name in enumerate(PRESET_VEHICLE_TYPES, start=1):
        db.execute(
            text(
                "INSERT INTO vehicle_types "
                "(id, name, is_enabled, sort_order, created_at, updated_at) "
                "VALUES (:id, :name, :is_enabled, :sort_order, :created_at, :updated_at) "
                "ON CONFLICT (name) DO NOTHING"
            ),
            {
                "id": str(gen_uuid()), "name": name, "is_enabled": True,
                "sort_order": i, "created_at": now, "updated_at": now,
            },
        )
    db.flush()


DEFAULT_TASK_DELIVERABLES = {
    "场地勘测": [{"name": "现场勘测记录", "required": True, "doc_type": "PDF", "note": "包含尺寸、通道和现场照片"}],
    "施工方案确认": [{"name": "已确认施工方案", "required": True, "doc_type": "PDF", "note": "需客户或项目负责人确认"}],
    "开箱检查": [{"name": "设备开箱照片", "required": True, "doc_type": "照片", "note": "每批设备留存全景与铭牌照片"}],
    "到货文档归档": [{"name": "到货签收单", "required": True, "doc_type": "PDF", "note": "包含签收人和日期"}],
    "安全激光及停车距离验证": [{"name": "安全测试记录", "required": True, "doc_type": "Excel", "note": "记录各速度档停车距离"}],
    "单车配置和程序备份": [{"name": "单车配置备份包", "required": True, "doc_type": "其他", "note": "按车辆编号命名"}],
    "地图验证与备份": [{"name": "地图与站点备份包", "required": True, "doc_type": "其他", "note": "包含地图、站点与版本说明"}],
    "服务器部署与配置": [{"name": "服务器部署记录", "required": True, "doc_type": "Word", "note": "记录地址、版本和关键配置"}],
    "系统性能测试": [{"name": "系统性能测试报告", "required": True, "doc_type": "PDF", "note": "包含吞吐、并发和异常恢复结果"}],
    "运行报告编制": [{"name": "试运行报告", "required": True, "doc_type": "PDF", "note": "汇总连续运行和遗留问题"}],
    "操作培训": [{"name": "培训签到与考核记录", "required": True, "doc_type": "PDF", "note": "包含参训人员签字"}],
    "最终验收": [{"name": "项目验收单", "required": True, "doc_type": "PDF", "note": "需双方签字"}],
    "验收文档归档": [{"name": "最终交付文档清单", "required": True, "doc_type": "Excel", "note": "列明文件名、版本和交付日期"}],
}


DEFAULT_REFERENCE_GUIDES = {
    "场地勘测": (
        "现场勘测检查要点.txt",
        "勘测前确认最新布局图；逐项记录通道宽度、转弯半径、地面平整度、网络覆盖和施工限制。\n",
        "进场勘测前阅读",
    ),
    "安全激光及停车距离验证": (
        "安全激光测试要点.txt",
        "分别在空载和额定载荷下测试；记录速度档、触发距离、实际停车距离、复位结果和异常现象。\n",
        "安全测试必读",
    ),
    "地图验证与备份": (
        "地图备份命名规范.txt",
        "文件名使用 项目缩写_地图版本_YYYYMMDD；备份包应包含地图、站点、路径、参数和变更说明。\n",
        "提交地图备份前核对",
    ),
    "最终验收": (
        "项目验收资料清单.txt",
        "验收前核对测试报告、问题关闭清单、培训记录、配置备份、操作维护文档和双方签字页。\n",
        "验收评审前核对",
    ),
}


def seed_task_documents(db):
    """Backfill reference guides only; document requirements are owned by T22."""
    from app.config import UPLOAD_DIR
    from app.models import Task, Template, TemplateDoc

    managed_template_names = {
        "系统默认模板",
        "标准 AGV 实施模板",
        "潜伏式简版模板",
        "叉车重载项目模板",
        "多车型集成模板",
    }
    managed_template_ids = {
        template.id
        for template in db.query(Template).filter(Template.name.in_(managed_template_names)).all()
    }
    template_tasks = db.query(Task).filter(Task.project_id.is_(None)).all()
    template_tasks = [
        task
        for task in template_tasks
        if task.template_id is None or task.template_id in managed_template_ids
    ]
    for task in template_tasks:
        guide = DEFAULT_REFERENCE_GUIDES.get(task.name)
        if not guide:
            continue
        filename, content, note = guide
        existing = db.query(TemplateDoc).filter(
            TemplateDoc.task_id == task.id,
            TemplateDoc.filename == filename,
        ).first()
        if existing:
            continue
        stored_name = f"seed-ref-{task.id}.txt"
        path = UPLOAD_DIR / stored_name
        path.write_text(content, encoding="utf-8")
        db.add(TemplateDoc(
            template_id=task.template_id,
            task_id=task.id,
            filename=filename,
            stored_name=stored_name,
            file_size=path.stat().st_size,
            content_type="text/plain; charset=utf-8",
            note=note,
        ))
    db.flush()
