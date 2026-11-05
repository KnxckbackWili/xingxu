"""Seed default roles, admin user, and global template data."""

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

    # The built-in template's content is created by migration g3a93b000001 (template sections and rows).

    db.commit()
    user_count = 4 if seed_demo else 1
    print(f"✓ Seed data created: {user_count} users")


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
    """Retired: purchases are rows of the template (template_items) and compiled from them."""
    return


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
