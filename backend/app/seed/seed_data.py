"""What a new installation starts with: the administrator, a template, a few vehicle types."""
import logging
import os

from passlib.context import CryptContext

from app import models

logger = logging.getLogger(__name__)
VEHICLE_TYPES = ("潜伏式", "平衡重叉车", "堆高车", "前移式", "滚筒车", "顶升车", "其他/定制")
DEFAULT_TEMPLATE = {
    "name": "AGV 实施标准模板",
    "note": "新建项目时套用，可以在模板里随意增减。",
    "step": ["到货点检", "单车调试", "联调", "试运行", "交付"],
    "work": [
        ("进场准备", "内部启动会，确认人员和采购清单"), ("进场准备", "场地勘测：尺寸、平整度、通道宽度"),
        ("进场准备", "网络覆盖与带宽测试"), ("进场准备", "施工方案确认"),
        ("现场实施", "服务器与网络部署"), ("现场实施", "调度系统部署"), ("现场实施", "建图与站点设置"),
        ("现场实施", "多车联调与交通管制"), ("现场实施", "上位系统（WMS/MES）对接"),
        ("现场实施", "自动门、电梯等设备对接"), ("现场实施", "连续试运行"),
        ("培训与交付", "操作与维护培训"), ("培训与交付", "客户验收"), ("培训与交付", "项目资料归档"),
    ],
    "document": ["施工方案", "场地勘测记录", "到货点检记录", "单车调试记录", "联调测试记录", "试运行报告",
                 "培训签到表", "操作与维护手册", "验收单", "AGV 生命周期表"],
    "item": [("AGV 本体", "按合同型号与配置", None, "台"), ("自动充电桩", "含安装底座", None, "台"),
             ("网络设备", "工业路由器、交换机、网线", 1, "套"), ("安全围栏", "", None, "米"),
             ("常用备件", "按现场需要", 1, "套")],
}
# A deliberately cheap hash: these accounts exist only in demonstrations and tests.
_demo = CryptContext(schemes=["bcrypt"], bcrypt__rounds=4)
_pwd = CryptContext(schemes=["bcrypt"])


def seed_admin(db) -> None:
    """Make sure someone can sign in as an administrator.

    INITIAL_ADMIN_PASSWORD names the first administrator's password. With ADMIN_PASSWORD_ROTATE=1 it
    also replaces the password of the existing "admin" account, ending its sessions.
    """
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    demo = os.getenv("SEED_DEMO_USERS", "0") == "1"
    if password and len(password) < 8:
        raise RuntimeError("INITIAL_ADMIN_PASSWORD 至少需要 8 个字符")
    admin = db.query(models.User).filter_by(username="admin").first()
    if admin is not None and os.getenv("ADMIN_PASSWORD_ROTATE", "") == "1":
        if not password:
            raise RuntimeError("ADMIN_PASSWORD_ROTATE=1 时必须同时提供至少 8 位的 INITIAL_ADMIN_PASSWORD")
        if not _pwd.verify(password, admin.password_hash):
            admin.password_hash = _pwd.hash(password)
            admin.token_version = (admin.token_version or 0) + 1
            admin.is_active, admin.role = True, "admin"
            logger.info("admin 密码已按 ADMIN_PASSWORD_ROTATE 更换，旧会话全部失效")
        return
    if db.query(models.User.id).filter_by(role="admin", is_active=True).first() is not None:
        return
    if admin is not None:  # the only administrator account exists but is stopped or demoted
        admin.is_active, admin.role = True, "admin"
        return
    if not password and not demo:
        raise RuntimeError("首次启动必须设置 INITIAL_ADMIN_PASSWORD（至少 8 个字符）")
    db.add(models.User(id="user-admin-001", username="admin", display_name="系统管理员", role="admin",
                       password_hash=_pwd.hash(password) if password else _demo.hash("admin123")))
    if demo:
        for username, name in (("zhangwei", "张伟"), ("lina", "李娜")):
            db.add(models.User(username=username, display_name=name, role="employee", password_hash=_demo.hash("demo12345")))


def seed_library(db) -> None:
    """The starting template and vehicle types of a brand-new database."""
    for position, name in enumerate(VEHICLE_TYPES, start=1):
        db.add(models.VehicleType(name=name, sort_order=position))
    template = models.Template(id=models.gen_uuid(), name=DEFAULT_TEMPLATE["name"], note=DEFAULT_TEMPLATE["note"])
    db.add(template)
    db.flush()
    position = 0

    def add(kind, **values):
        nonlocal position
        position += 1
        db.add(models.TemplateRow(template_id=template.id, kind=kind, sort_order=position, **values))

    for name in DEFAULT_TEMPLATE["step"]:
        add("step", name=name)
    for stage, name in DEFAULT_TEMPLATE["work"]:
        add("work", stage=stage, name=name)
    for name in DEFAULT_TEMPLATE["document"]:
        add("document", name=name)
    for name, spec, quantity, unit in DEFAULT_TEMPLATE["item"]:
        add("item", name=name, spec=spec, quantity=quantity, unit=unit)
