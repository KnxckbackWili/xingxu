"""SQLAlchemy models for the AGV PM system."""

import uuid
from datetime import date
from app.time_utils import utcnow
from sqlalchemy import (
    Column, Integer, BigInteger, String, Float, Boolean, Date, DateTime,
    ForeignKey, Text, JSON, UniqueConstraint, CheckConstraint, Index, Enum as SAEnum, false, event,
)
from sqlalchemy.orm import relationship, backref
from sqlalchemy.dialects.postgresql import JSONB
from app.db import Base


def gen_uuid():
    return str(uuid.uuid4())


# ===== User & RBAC =====

class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    display_name = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False, default="worker")
    # 角色: admin/director/lead/pm/technician/worker/intern
    phone = Column(String(20), default="")
    email = Column(String(100), default="")
    is_active = Column(Boolean, default=True)
    token_version = Column(Integer, default=0)  # 改密/重置密码时 +1，旧 token 全部失效
    mfa_enabled = Column(Boolean, nullable=False, default=False, server_default=false())
    mfa_secret_encrypted = Column(Text, nullable=True)
    mfa_last_step = Column(BigInteger, nullable=False, default=-1, server_default="-1")
    permission_overrides = Column(JSON, default=dict)  # 空对象继承角色；显式 false 优先
    permission_version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, default=utcnow)


class MfaChallenge(Base):
    __tablename__ = "mfa_challenges"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    purpose = Column(String(20), nullable=False)
    token_version = Column(Integer, nullable=False)
    login_key = Column(String(256), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    pending_secret_encrypted = Column(Text, nullable=True)


class MfaRecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, unique=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    used_at = Column(DateTime, nullable=True)


# ===== AI 内部开放接口 Token =====

class AiApiToken(Base):
    __tablename__ = "ai_api_tokens"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(100), nullable=False)
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    token_prefix = Column(String(16), default="")
    auth_version = Column(Integer, nullable=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    scopes = Column(JSON, default=list)  # ["projects:read", "tasks:read", ...]
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ===== AI 用量预算台账（月度请求/token 计数，按自然月滚动） =====

class AiUsageLedger(Base):
    __tablename__ = "ai_usage_ledger"
    __table_args__ = (UniqueConstraint("month", name="uq_ai_usage_month"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    month = Column(String(7), nullable=False, index=True)  # "YYYY-MM"
    requests = Column(Integer, default=0)
    tokens = Column(Integer, default=0)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

# ===== OrgGroup (组织：大组 → 小组) =====

# ===== Project =====

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("status IN ('preparing','executing','acceptance','completed','archived','suspended')", name="ck_project_status"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(200), nullable=False)
    abbreviation = Column(String(50), default="")
    manager = Column(String(100), default="")  # PM user_id
    technical_manager = Column(String(36), nullable=True)  # 技术负责人（技术经理或技术工程师）
    co_managers = Column(JSON, default=list)  # 项目协管 [{user_id, expires_at}]，仅项目内临时生效
    client = Column(String(200), default="")
    location = Column(String(200), default="")
    timezone = Column(String(64), default="Asia/Shanghai")  # 项目现场时区（俄/越等海外现场按当地日历取"今天"）
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="preparing")
    legacy_lifecycle = Column(JSON, nullable=True)  # read-only original status/suspension/migration provenance
    description = Column(Text, default="")
    staffing_notes = Column(Text, default="")  # 资料中的人员姓名/建议，不自动绑定系统账号
    members = Column(JSON, default=list)  # [user_id, ...]
    member_permissions = Column(JSON, default=list)  # [{user_id, capabilities}]，仅当前成员的项目操作授权
    rest_mode = Column(String(10), default="none")  # none=不休息 one=休周日 two=休周六日
    rest_days = Column(JSON, default=list)  # 手动补充休息日 ["2026-10-01", ...]
    skip_holidays = Column(Boolean, default=False)  # 是否跳过法定节假日（默认不跳过，现场赶工照常排）
    schedule_version = Column(Integer, default=0)  # 日程下达版本号（每次 confirm +1）
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    template_id = Column(String(36), nullable=True)  # 生成来源模板（P3：记录使用情况）
    template_version = Column(Integer, default=0)  # 生成时的模板版本
    portable_unverified_snapshot = Column(JSON, nullable=True)  # immutable imported execution source; never active qualification
    planned_entry_date = Column(Date, nullable=True)  # 历史只读，保留一个版本；新计划使用ProjectEvent
    dispatch_platform = Column(String(20), nullable=True)  # NDC / GRACE / integrated
    readiness_state = Column(String(20), default="preparing")
    # preparing 准备中 / risky 有风险 / pending_confirm 待确认 / ready 已就绪（独立准备状态，不干扰项目状态）
    prep_conditions = Column(JSON, default=list)  # 创建时的准备清单条件选项（need_wms 等）
    prep_confirmed_by = Column(String(36), nullable=True)  # 确认进场人
    prep_confirmed_at = Column(DateTime, nullable=True)
    prep_conclusion = Column(Text, default="")  # 确认结论/遗留项/风险说明
    client_contacts = Column(JSON, default=list)  # 甲方组织与联系人 [{department, team, name, ...}]
    entry_plan = Column(JSON, default=dict)  # 入场交接安排 {mode, entry_date, meeting_point, ...}
    suspension = Column(JSON, default=dict)  # 突发停工上下文 {status_before, reason, suspended_by, suspended_at, resumed_by, resumed_at}
    retrospective = Column(JSON, default=dict)  # C8-3 归档复盘 {success, problems, improvements}
    deleted_at = Column(DateTime, nullable=True)  # C8-4 治理软删除标记（非空=已删除，保留期内可审计）
    version = Column(Integer, default=0)  # 乐观锁版本号（并发写保护）
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ProjectEvent(Base):
    """Project milestones; arrival_all is derived from the complete vehicle fleet."""
    __tablename__ = "project_events"
    __table_args__ = (
        UniqueConstraint("project_id", "event_key", name="uq_project_event_key"),
        CheckConstraint("event_key IN ('internal_kickoff','ship','arrival_all','delivery_signed','commissioning_done','go_live','training_done','acceptance','handover')", name="ck_project_event_key"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    event_key = Column(String(32), nullable=False)
    planned_date = Column(Date, nullable=True)
    actual_at = Column(DateTime, nullable=True)  # naive UTC; arrival_all has date precision
    actual_date = Column(Date, nullable=True)  # signed document date; never invent midnight
    actual_source = Column(JSON, nullable=True)  # explicit manual/signature/legacy audit provenance
    recorded_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, nullable=True)


class ProjectMember(Base):
    """项目成员关系表：替代 JSON members/co_managers 的查询主路径。"""

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(30), default="member")  # member / manager / technical / co_manager
    created_at = Column(DateTime, default=utcnow)


# ===== Vehicle =====

class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_type = Column(String(50), nullable=False)  # 潜伏式/平衡重叉车/堆高车/前移式/滚筒车/顶升车/custom
    model_name = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    configuration = Column(JSON, default=dict)  # 载重、导航、电池、尺寸等扩展配置
    notes = Column(Text, default="")
    sort_order = Column(Integer, default=0)

    project = relationship("Project", backref=backref("vehicles", passive_deletes=True, cascade="all, delete-orphan"))


class VehicleUnit(Base):
    """A physical AGV tracked independently throughout its lifecycle."""
    __tablename__ = "vehicle_units"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(String(36), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_code = Column(String(100), nullable=False)
    serial_number = Column(String(100), default="")
    fleet_no = Column(String(30), default="")  # 车号（生命周期表口径，现场车队编号）
    model_name = Column(String(100), default="")  # 生命周期表导入的车辆型号（未匹配车型档案时保留展示）
    legacy_current_stage = Column(String(80), nullable=True)  # read-only original nine-stage fact
    current_stage = Column(String(80), default="planned")
    current_status = Column(String(30), default="normal")
    location = Column(String(200), default="")
    warranty_end = Column(Date, nullable=True)
    commissioned_at = Column(Date, nullable=True)
    arrived_at = Column(Date, nullable=True)  # Project-local calendar date, no invented time
    note = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("project_id", "asset_code", name="uq_vehicle_unit_asset"),)


class VehicleStep(Base):
    """Template definitions; 'default' is the virtual built-in template."""
    __tablename__ = "vehicle_steps"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    template_id = Column(String(36), nullable=False, index=True)
    key = Column(String(80), nullable=False)
    name = Column(String(200), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    __table_args__ = (UniqueConstraint("template_id", "key", name="uq_vehicle_step_template_key"),)


class ProjectVehicleStep(Base):
    """Frozen project scope; changes to a template cannot rewrite existing work."""
    __tablename__ = "project_vehicle_steps"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(80), nullable=False)
    name = Column(String(300), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    source_task_id = Column(String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    expected_quantity = Column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_project_vehicle_step_key"),)


class VehicleProgress(Base):
    __tablename__ = "vehicle_progress"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_unit_id = Column(String(36), ForeignKey("vehicle_units.id", ondelete="CASCADE"), nullable=False, index=True)
    step_key = Column(String(80), nullable=False)
    is_done = Column(Boolean, nullable=False, default=True)
    done_on = Column(Date, nullable=True)  # NULL only for unidentifiable historical completion dates
    recorded_at = Column(DateTime, nullable=False, default=utcnow)
    done_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, default="")
    migrated = Column(Boolean, nullable=False, default=False)
    source_metadata = Column(JSON, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("vehicle_unit_id", "step_key", name="uq_vehicle_progress_unit_step"),)


class VehicleProgressMigration(Base):
    """Quantity facts whose real vehicle identities were never recorded."""
    __tablename__ = "vehicle_progress_migrations"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    step_key = Column(String(80), nullable=False)
    total_count = Column(Integer, nullable=False)
    unassigned_count = Column(Integer, nullable=False)
    source_metadata = Column(JSON, nullable=False, default=dict)
    __table_args__ = (UniqueConstraint("project_id", "step_key", name="uq_vehicle_progress_migration_step"),
        CheckConstraint("unassigned_count >= 0 AND unassigned_count <= total_count", name="ck_vehicle_progress_migration_count"))


class VehicleLifecycleEvent(Base):
    __tablename__ = "vehicle_lifecycle_events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    vehicle_unit_id = Column(String(36), ForeignKey("vehicle_units.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(30), nullable=False)
    event_date = Column(Date, nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    fault_part = Column(String(200), default="")
    cause = Column(Text, default="")
    action_taken = Column(Text, default="")
    replaced_parts = Column(JSON, default=list)
    downtime_hours = Column(Float, nullable=True)
    verification = Column(Text, default="")
    handler = Column(String(100), default="")
    is_closed = Column(Boolean, default=False)
    stage_after = Column(String(30), default="")
    status_after = Column(String(30), default="")
    location_after = Column(String(200), default="")
    attachment_id = Column(String(36), nullable=True)
    operator_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    extra = Column(JSON, default=dict)  # 生命周期表导入导出的扩展字段：{"category": 问题分类, "fleet_no": 车号, "model_name": 车辆型号}
    import_key = Column(String(64), default="", index=True)  # 生命周期表重复导入幂等键（project+unit+date+title）
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ===== VehicleType (车型字典) =====
# HYPE-63：车型由管理员集中维护（新增/启停/排序），普通业务页面从启用项中选择。
# 历史遗留字符串 custom / 自定义 经 _migrate 归一化为「其他/定制」；字典外历史值仍可显示与编辑。

class VehicleType(Base):
    __tablename__ = "vehicle_types"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(50), unique=True, nullable=False, index=True)  # 唯一车型名称（去首尾空格、非空、≤50）
    is_enabled = Column(Boolean, nullable=False, default=True)  # 启用/停用
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ===== Project inventory =====

class ProjectInventoryItem(Base):
    """Physical goods held or used at a project site, regardless of ownership."""
    __tablename__ = "project_inventory_items"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    item_code = Column(String(100), default="", index=True)
    name = Column(String(200), nullable=False, index=True)
    category = Column(String(30), default="other")
    ownership = Column(String(20), nullable=False, default="company")  # company / client / third_party
    tracking_mode = Column(String(20), default="quantity")  # quantity / serial
    specification = Column(String(300), default="")
    serial_number = Column(String(200), default="")
    quantity = Column(Float, nullable=False, default=0)
    minimum_quantity = Column(Float, nullable=True)
    unit = Column(String(20), default="件")
    status = Column(String(30), default="on_site")
    location = Column(String(200), default="")
    custodian = Column(String(100), default="")
    supplier = Column(String(200), default="")
    received_date = Column(Date, nullable=True)
    expected_return_date = Column(Date, nullable=True)
    note = Column(Text, default="")
    extra = Column(JSON, default=dict)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ProjectInventoryMovement(Base):
    """Immutable quantity/location history for a project inventory item."""
    __tablename__ = "project_inventory_movements"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(String(36), ForeignKey("project_inventory_items.id", ondelete="CASCADE"), nullable=False, index=True)
    movement_type = Column(String(30), nullable=False)
    quantity = Column(Float, nullable=False, default=0)
    balance_after = Column(Float, nullable=False, default=0)
    from_location = Column(String(200), default="")
    to_location = Column(String(200), default="")
    handler = Column(String(100), default="")
    occurred_at = Column(DateTime, default=utcnow, nullable=False)
    # Null marks historical records whose source did not declare a timezone.
    time_basis = Column(String(20), nullable=True, default="utc")
    note = Column(Text, default="")
    operator_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ===== Item application (内部联系单 / 物品申请) =====

class ItemApplication(Base):
    """内部联系单：项目内申请物品/服务（如吊车）的记录，可生成/导入 Word 联系单。"""
    __tablename__ = "item_applications"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(300), default="")  # 联系单标题/申请事项摘要
    item_name = Column(String(200), default="")  # 申请物品/服务名称
    requirement = Column(Text, default="")  # 需求描述
    reason = Column(Text, default="")  # 申请原因
    drawing_no = Column(String(100), default="")  # 图号
    contract_no = Column(String(100), default="")  # 合同号
    amount = Column(String(100), default="")  # 金额（如 "3000元"）
    applicant = Column(String(100), default="")  # 申请人
    approver = Column(String(100), default="")  # 审批人
    department = Column(String(100), default="")  # 申请部门（如 项目技术部）
    apply_date = Column(Date, nullable=True)  # 申请日期
    status = Column(String(20), default="pending")  # pending / approved / rejected
    note = Column(Text, default="")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ===== Phase (阶段) =====

class Phase(Base):
    __tablename__ = "phases"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(String(36), nullable=True, index=True)  # NULL = 系统默认模板
    name = Column(String(100), nullable=False)
    sort_order = Column(Integer, default=0)
    color = Column(String(20), default="#1890ff")
    entry_criteria = Column(Text, default="")
    exit_criteria = Column(Text, default="")
    # 主线阶段（资料编号第4–9阶段）；工作阶段是主线阶段下的工作分组。
    stage_key = Column(String(10), nullable=True)

    project = relationship("Project", backref=backref("phases", passive_deletes=True, cascade="all, delete-orphan"))


@event.listens_for(Phase, "before_insert")
def _phase_stage_default(mapper, connection, target):
    """Every work group sits on the stage backbone; copies pass their source's stage explicitly."""
    if not target.stage_key:
        from app.services.template_stages import infer_phase_stage
        target.stage_key = infer_phase_stage(target.name)


# ===== Module (实施模块) =====

class Module(Base):
    __tablename__ = "modules"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(String(36), nullable=True, index=True)
    source_module_id = Column(String(36), nullable=True, index=True)
    phase_id = Column(String(36), ForeignKey("phases.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(200), nullable=False)
    category = Column(String(20), default="core")  # core / extra
    is_selected = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    description = Column(Text, default="")
    preparation_conditions = Column(JSON, default=list)  # 选用实施模块时带入的准备事项组
    applies_to_all_vehicles = Column(Boolean, default=True)

    phase = relationship("Phase", backref=backref("modules", passive_deletes=True, cascade="all, delete-orphan"))
    project = relationship("Project", backref=backref("modules", passive_deletes=True, cascade="all, delete-orphan"))


# ===== Task =====

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(String(36), nullable=True, index=True)
    module_id = Column(String(36), ForeignKey("modules.id", ondelete="CASCADE"), nullable=True, index=True)
    phase_id = Column(String(36), ForeignKey("phases.id", ondelete="SET NULL"), nullable=True, index=True)
    group_label = Column(String(200), nullable=True, default="")
    scope_conditions = Column(JSON, nullable=True, default=list)
    legacy_work_snapshot = Column(JSON, nullable=True)  # immutable original hierarchy/quantity facts
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    quantity_type = Column(String(20), nullable=False, default="per_vehicle")
    # per_vehicle / manual / fixed
    target_quantity = Column(Float, nullable=True)  # None for per_vehicle (computed)
    unit = Column(String(20), default="台")  # 台/个/次/人/套/项
    standard_hours = Column(Float, nullable=True)  # hours per unit (None = 由统计得出, 不预设)
    safety_flag = Column(Boolean, default=False)
    applicable_vehicle_types = Column(JSON, default=list)  # [] means all types
    sort_order = Column(Integer, default=0)
    depends_on = Column(JSON, default=list)  # [task_id, ...] in template; resolved at copy
    deliverables = Column(JSON, default=list)  # 交付物清单: [{"name": "验收单", "required": true}]
    reference_docs = Column(JSON, default=list)  # 参考文档（生成时从模板任务复制）: [{filename, stored_name, file_size, content_type, note}]
    version = Column(Integer, default=0)  # 乐观锁版本号
    # C2-6：模板源任务 ID——项目任务稳定关联生成它的模板任务，模板任务改名后重生成不再产生新旧两批
    source_task_id = Column(String(36), nullable=True, index=True)
    vehicle_step_key = Column(String(80), nullable=True)  # explicit template/project step, never guessed
    source_vehicle_event_id = Column(String(36), ForeignKey("vehicle_lifecycle_events.id", ondelete="SET NULL"), nullable=True, unique=True)
    # HYPE-71「直接完成」：独立于填报量的手动完成状态（PM/admin 直接把任务标记为已完成，
    # 不伪造 DailyProgress；真实完成量/历史/排程/单位保持不变）。manually_completed=True 时
    # 该任务在任务状态/项目计划进度/最终 100% 判定中按已完成处理，重新打开后恢复按实际完成量计算。
    manually_completed = Column(Boolean, default=False)
    manual_completed_by = Column(String(36), nullable=True)
    manual_completed_role = Column(String(20), nullable=True)
    manual_completed_at = Column(DateTime, nullable=True)
    manual_completed_reason = Column(Text, default="")
    manual_check_overrides = Column(JSON, default=list)

    module = relationship("Module", backref=backref("tasks", passive_deletes=True, cascade="all, delete-orphan"))
    project = relationship("Project", backref=backref("tasks", passive_deletes=True, cascade="all, delete-orphan"))


class ProjectSchedulePolicy(Base):
    """Saved project scheduling choices; absent legacy rows mean scale 1."""
    __tablename__ = "project_schedule_policies"
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    duration_scale = Column(Float, nullable=False, default=1)
    version = Column(Integer, nullable=False, default=0)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class TaskDurationOverride(Base):
    """Project task workday budget, independent of effort statistics or locks."""
    __tablename__ = "task_duration_overrides"
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    workdays = Column(Integer, nullable=False, default=1)
    baseline_quantity = Column(Float, nullable=False, default=1)
    baseline_unit = Column(String(20), nullable=False, default="项")
    # An explicit automatic choice is retained as a tombstone. Old audit data
    # must never resurrect an override the user has deliberately cleared.
    is_active = Column(Boolean, nullable=False, default=True)
    recovered_from_log_id = Column(String(36), nullable=True)
    version = Column(Integer, nullable=False, default=0)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow)


class VehicleCheckDefinition(Base):
    """Immutable project snapshot; definitions carry no inspection qualification."""
    __tablename__ = "vehicle_check_definitions"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    source_check_id = Column(String(36), nullable=False)
    source_version = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)
    name = Column(String(300), nullable=False)
    description = Column(Text, default="")
    is_safety_critical = Column(Boolean, default=False)
    is_required = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)
    __table_args__ = (UniqueConstraint("task_id", "source_check_id", name="uq_vehicle_check_definition_source"),)


# ===== CheckItem (检查项) =====

class CheckItem(Base):
    __tablename__ = "check_items"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(String(36), nullable=True, index=True)
    name = Column(String(300), nullable=False)
    description = Column(Text, default="")
    is_safety_critical = Column(Boolean, default=False)
    is_required = Column(Boolean, default=True)  # required to complete task
    is_applicable = Column(Boolean, default=True)
    not_applicable_reason = Column(Text, default="")
    not_applicable_set_by = Column(String(36), nullable=True)
    not_applicable_set_at = Column(DateTime, nullable=True)
    is_done = Column(Boolean, default=False)  # 通过（现场打勾确认）
    done_by = Column(String(36), nullable=True)
    done_at = Column(DateTime, nullable=True)
    failed = Column(Boolean, default=False)  # 不通过（三态：通过/不通过/不适用）
    failed_reason = Column(Text, default="")  # 不通过原因（必填）
    sort_order = Column(Integer, default=0)
    version = Column(Integer, default=0)  # 乐观锁版本号（现场多端同时打勾保护）

    vehicle_unit_id = Column(String(36), ForeignKey("vehicle_units.id", ondelete="CASCADE"), nullable=True, index=True)
    vehicle_step_key = Column(String(80), nullable=True)
    vehicle_check_definition_id = Column(String(36), ForeignKey("vehicle_check_definitions.id", ondelete="CASCADE"), nullable=True, index=True)
    definition_version = Column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("vehicle_unit_id", "vehicle_check_definition_id", name="uq_vehicle_check_unit_definition"),)

    task = relationship("Task", backref=backref("check_items", passive_deletes=True, cascade="all, delete-orphan"))


# ===== ScheduleEntry (日程条目) =====

class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    work_date = Column(Date, nullable=False)
    assignee_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    planned_quantity = Column(Float, default=0)
    status = Column(String(20), default="planned")  # planned / done / skipped
    notes = Column(Text, default="")
    is_confirmed = Column(Boolean, default=False)  # PM confirmed
    is_locked = Column(Boolean, default=False)  # PM hand-tuned, don't overwrite
    version = Column(Integer, default=0)  # 乐观锁版本号

    task = relationship("Task", backref=backref("schedule_entries", passive_deletes=True, cascade="all, delete-orphan"))


# ===== WeeklyPlanCell (周计划，实际执行事实独立保存) =====

class WeeklyPlanCell(Base):
    __tablename__ = "weekly_plan_cells"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    scope_key = Column(String(160), nullable=False)
    scope = Column(JSON, nullable=False, default=dict)
    vehicle_step_key = Column(String(80), nullable=True)  # Explicit plan mapping, not inferred from a later rebind
    week_start = Column(Date, nullable=False, index=True)
    mode = Column(String(20), nullable=False, default="in_progress")
    target_count = Column(Integer, nullable=True)
    intent_review_required = Column(Boolean, nullable=False, default=False)
    assignee_ids = Column(JSON, nullable=False, default=list)
    published = Column(Boolean, nullable=False, default=False)
    published_at = Column(DateTime, nullable=True)
    published_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    is_cancelled = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=False, default="")
    source_metadata = Column(JSON, nullable=True)  # Immutable original daily entries and publication facts
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    version = Column(Integer, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("project_id", "task_id", "scope_key", "week_start", name="uq_weekly_plan_work_scope_week"),
        CheckConstraint("mode IN ('finish','in_progress')", name="ck_weekly_plan_mode"),
        CheckConstraint("target_count IS NULL OR target_count > 0", name="ck_weekly_plan_positive_target"),
    )

    task = relationship("Task", backref=backref("weekly_plan_cells", passive_deletes=True, cascade="all, delete-orphan"))


# ===== DailyProgress (每日填报) =====

class DailyProgress(Base):
    __tablename__ = "daily_progress"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_entry_id = Column(String(36), ForeignKey("schedule_entries.id", ondelete="SET NULL"), nullable=True)
    work_date = Column(Date, nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    completed_quantity = Column(Float, default=0)
    note = Column(Text, default="")
    client_uuid = Column(String(36), nullable=False)  # for offline dedupe
    source = Column(String(20), default="worker")  # HYPE-71：完成量填报来源 worker/pm/admin
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("task_id", "work_date", "user_id", "client_uuid", name="uq_progress_dedupe"),
    )


# ===== Issue (问题) =====

class Issue(Base):
    __tablename__ = "issues"
    # HYPE-99：跨项目约束 —— (project_id, client_uuid) 库级唯一，杜绝并发离线上报/导入
    # 产生重复台账；client_uuid 为 NULL 的历史/普通上报不受约束（PG/SQLite NULL 互不相等）。
    __table_args__ = (
        UniqueConstraint("project_id", "client_uuid", name="uq_issue_project_client_uuid"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(300), nullable=False)
    description = Column(Text, default="")
    issue_type = Column(String(20), default="other")  # hardware/software/environment/process/safety/other
    nature = Column(String(20), nullable=False, default="normal", server_default="normal")
    source_metadata = Column(JSON,nullable=True)  # portable history is read-only provenance, never a new report
    severity = Column(String(20), default="medium")  # critical / high / medium / low
    status = Column(String(20), default="open")  # open / processing / resolved / closed
    reporter_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    assignee_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    resolved_at = Column(DateTime, nullable=True)
    resolution = Column(Text, default="")
    extra = Column(JSON, default=dict)  # 分类专属字段：{"device": "AGV-03", "affects_schedule": "影响"}
    version = Column(Integer, default=0)  # 乐观锁版本号
    client_uuid = Column(String(64), nullable=True)  # C5-5：离线上报幂等键（同项目内唯一）


class OfflineOpReceipt(Base):
    """HYPE-99：离线批处理幂等凭证（checkitem/deliverable/report/issue 共用）。

    批处理逐项在独立会话中执行；每个 client_uuid 先落一张 receipt 再执行真正操作。
    并发重试（多 worker / 用户重复点击同步）时，receipt 唯一约束会拦住第二个写入方，
    使其不重复执行（不重复写台账/审计/通知），直接按幂等成功处理。

    HYPE-99 复审：唯一键含 project_id——离线操作都作用在具体项目上下文上，问题台账的
    库级唯一是 (project_id, client_uuid)；若 receipt 只按 (user_id, op_type, client_uuid)
    去重，同一用户在不同项目复用同一 client_uuid 时会被误判为重复，吞掉第二个项目的
    写入。纳入 project_id 后与 issues 的跨项目契约一致；project_id 为 NULL 的旧版
    数量填报（兼容 reports 列表）不参与 receipt 级去重，仍由 DailyProgress 自身的
    (task_id, work_date, user_id, client_uuid) 唯一约束兜底。
    """

    __tablename__ = "offline_op_receipts"
    __table_args__ = (
        UniqueConstraint("user_id", "op_type", "project_id", "client_uuid",
                         name="uq_offline_op_receipt_user_op_uuid"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    op_type = Column(String(20), nullable=False)  # report / checkitem / deliverable / issue
    client_uuid = Column(String(64), nullable=False)
    project_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=utcnow)



# ===== Template (模板) =====

class Template(Base):
    __tablename__ = "templates"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    is_system = Column(Boolean, default=False)  # 系统默认模板不可删
    version = Column(Integer, default=1)  # 发布版本号（P3：每次发布 +1）
    status = Column(String(10), default="draft")  # draft / published
    snapshots = Column(JSON, default=list)  # C2-3 发布版本快照 [{version, at, by, snapshot}]
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ===== Attachment (附件) =====

class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String(50), default="project")  # project / task / issue
    entity_id = Column(String(36), default="")
    category = Column(String(50), default="")  # 项目文件分类：到货资料/测试记录/问题附件/验收文件
    filename = Column(String(300), nullable=False)
    stored_name = Column(String(100), nullable=False)  # on-disk filename
    file_size = Column(BigInteger().with_variant(Integer,'sqlite'), default=0)
    content_type = Column(String(100), default="")
    uploaded_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)
    confidential = Column(Boolean, nullable=False, default=False, server_default=false())
    confidential_explicit = Column(Boolean, nullable=False, default=False, server_default=false())
    confidential_user_ids = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=list, server_default="[]")
    access_version = Column(Integer, nullable=False, default=1, server_default="1")
    sha256 = Column(String(64), nullable=True)
    removal_record = relationship('FileRemovalRecord',uselist=False,lazy='selectin',passive_deletes='all')


class DocumentTemplateFile(Base):
    """An immutable blank form, independent of any project or execution task."""
    __tablename__ = "document_template_files"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    filename = Column(String(300), nullable=False)
    stored_name = Column(String(100), nullable=False, unique=True)
    file_size = Column(BigInteger().with_variant(Integer,'sqlite'), nullable=False)
    content_type = Column(String(100), nullable=False)
    sha256 = Column(String(64), nullable=False)
    uploaded_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)


class DocumentRequirement(Base):
    __tablename__ = "document_requirements"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    template_id = Column(String(36), ForeignKey("templates.id", ondelete="CASCADE"), nullable=True, index=True)
    stage_key = Column(String(8), nullable=False)
    code = Column(String(40), nullable=False)
    name = Column(String(300), nullable=False)
    template_no = Column(String(100), default="")
    is_group = Column(Boolean, nullable=False, default=False)
    parent_id = Column(String(36), ForeignKey("document_requirements.id", ondelete="SET NULL"), nullable=True)
    required = Column(Boolean, nullable=False, default=True)
    scope = Column(String(20), nullable=True)
    platform = Column(String(20), nullable=True)
    timing_type = Column(String(24), nullable=True)
    timing_event = Column(String(32), nullable=True)
    timing_offset_hours = Column(Integer, nullable=True)
    timing_weekday = Column(Integer, nullable=True)
    trigger_type = Column(String(20), nullable=True)
    confidential_default = Column(Boolean, nullable=False, default=False)
    external_visible_default = Column(Boolean, nullable=False, default=False)
    external_never_visible = Column(Boolean, nullable=False, default=False)
    blank_file_id = Column(String(36), ForeignKey("document_template_files.id", ondelete="SET NULL"), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    note = Column(Text, default="")
    source_metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    __table_args__ = (
        Index("uq_document_requirement_default_code", "code", unique=True,
              sqlite_where=template_id.is_(None), postgresql_where=template_id.is_(None)),
        Index("uq_document_requirement_template_code", "template_id", "code", unique=True,
              sqlite_where=template_id.isnot(None), postgresql_where=template_id.isnot(None)),
    )


# ===== Notification (消息通知) =====

class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, default="")
    ntype = Column(String(30), default="system")  # issue_assigned / schedule / system
    project_id = Column(String(36), nullable=True)
    entity_id = Column(String(36), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


# ===== ArchiveChecklist (归档资料清单) =====

class ArchiveChecklist(Base):
    """Per-project delivery/archive document checklist (AGV delivery docs)."""

    __tablename__ = "archive_checklists"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(100), nullable=False)  # 设计资料/测试记录/培训资料/验收文件...
    item_name = Column(String(200), nullable=False)
    is_required = Column(Boolean, default=True)
    is_done = Column(Boolean, default=False)
    done_by = Column(String(36), nullable=True)
    done_at = Column(DateTime, nullable=True)
    attachment_id = Column(String(36), nullable=True)  # linked uploaded file
    requirements = Column(JSON, default=dict)  # 版本、签字、文件格式和其他交付要求
    sort_order = Column(Integer, default=0)


# ===== AcceptanceRecord (验收签字记录) =====

class AcceptanceRecord(Base):
    """项目验收/签字记录（C7-2）：验收人、时间、结论、附件，作为 acceptance→completed 的门禁。"""

    __tablename__ = "acceptance_records"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    accepted_by = Column(String(36), ForeignKey("users.id"), nullable=True)  # 验收人（可不在系统内）
    accepted_by_name = Column(String(100), default="")  # 验收人姓名（签字兜底，兼容甲方人员）
    accepted_at = Column(Date, nullable=False)  # 验收日期
    scope_fingerprint = Column(String(64), nullable=True)  # NULL preserves legacy unknown scope; never backfilled
    conclusion = Column(String(30), default="accepted")  # accepted 通过 / conditionally_accepted 有条件通过 / rejected 不通过
    notes = Column(Text, default="")  # 结论说明/遗留问题
    attachment_id = Column(String(36), nullable=True)  # 验收报告/照片
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ===== SchedulerWatermark (调度水位 E3) =====

class SchedulerWatermark(Base):
    """调度器自愈水位：记录每个后台 job 最近一次成功运行时间。
    进程崩溃/重启后可据此补跑遗漏的日报/周报/SLA 扫描。"""

    __tablename__ = "scheduler_watermarks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    job_id = Column(String(50), unique=True, nullable=False)  # daily_report / weekly_report / issue_sla_scan
    last_success_at = Column(DateTime, nullable=True)
    last_status = Column(String(20), default="ok")
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ===== ChangeLog (变更记录) =====

class ChangeLog(Base):
    __tablename__ = "change_logs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    # nullable: template-level changes have no project
    entity_type = Column(String(50), nullable=False)  # project/vehicle/module/task/schedule/issue
    entity_id = Column(String(36), nullable=False)
    action = Column(String(20), nullable=False)  # create/update/delete/generate/schedule/import
    operator_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    detail = Column(Text, default="")  # human-readable Chinese description
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class RateLimitBucket(Base):
    """T006: PostgreSQL 共享限流计数（单容器多 worker 共用同一额度）。

    按 用户 × 窗口大小 × 时间桶 唯一计数；每次请求原子递增（count < limit 才成功）。
    数据落库 → 容器重启后窗口内额度不被绕过；不同用户额度天然隔离。
    """

    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint("user_id", "bucket", "window", name="uq_rate_limit_user_bucket_window"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    bucket = Column(Integer, nullable=False)  # int(time.time() // window) 时间桶
    window = Column(Integer, nullable=False)  # 窗口秒数（与额度一一对应）
    count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class LoginFailureBucket(Base):
    """T025: 登录失败限流 PostgreSQL 共享计数（复用 T006 共享桶设计）。

    与 rate_limit_buckets 同构：固定窗口桶 + 原子递增（count < limit 才成功），
    多 worker 共用同一计数、容器重启不绕过窗口、不同 key（host:username）隔离。
    与导出限流不同：仅统计失败；成功登录 DELETE 该 key 全部桶（清理语义）。
    """

    __tablename__ = "login_failure_buckets"
    __table_args__ = (
        UniqueConstraint("key", "bucket", "window", name="uq_login_failure_key_bucket_window"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    key = Column(String(255), nullable=False, index=True)  # f"{client_host}:{username}"
    bucket = Column(Integer, nullable=False)  # int(time.time() // window) 时间桶
    window = Column(Integer, nullable=False)  # 窗口秒数（登录固定 900）
    count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AiJob(Base):
    """HYPE-99：AI 整理任务持久化（跨 worker / 重启可读）。

    取代原进程内 job 注册表：job 创建/进度更新/结果查询全部落库，
    WEB_CONCURRENCY>=2 时任意 worker 都能读到任意 worker 创建的 job；
    进程重启后 completed 结果在 TTL 内仍可读；被中断的 queued/running job
    在读取时按 updated_at 陈旧阈值自动置为 failed，绝不无限转圈。
    """

    __tablename__ = "ai_jobs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    kind = Column(String(30), nullable=False, default="generic")
    status = Column(String(20), nullable=False, default="queued")  # queued/running/completed/failed
    percent = Column(Integer, nullable=False, default=2)
    stage = Column(String(40), nullable=False, default="queued")
    message = Column(Text, nullable=False, default="")
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AiRateLimitBucket(Base):
    """HYPE-99：AI 限流 PostgreSQL 共享计数（与通用 rate_limit_buckets 分开）。

    AI 结构化整理按 scope 保存库级共享计数。
    SQLite 测试/本地仍走进程内滑动窗口。
    """

    __tablename__ = "ai_rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint("user_id", "scope", "bucket", "window", name="uq_ai_rate_limit_user_scope_bucket_window"),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    scope = Column(String(20), nullable=False)  # struct（结构化整理）
    bucket = Column(Integer, nullable=False)  # int(time.time() // window)
    window = Column(Integer, nullable=False)  # 窗口秒数
    count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class ProjectArchive(Base):
    """T008: 物理清理前的不可变项目归档（快照 + 审计链 + 校验哈希）。

    仅保留升级前旧归档，本版本不再写新快照；project_id 保留原 ID 但
    不设外键（项目行已删除）。普通业务接口不提供任何写路径，仅管理员只读查询。
    """

    __tablename__ = "project_archives"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), nullable=False, index=True)  # 原 project_id
    project_name = Column(String(200), default="")
    snapshot = Column(JSON, nullable=False)  # 完整项目快照（import_export.project_to_json）
    change_logs = Column(JSON, nullable=False)  # 项目全量变更记录（含操作者名/时间）
    actor_ids = Column(JSON, default=list)  # 涉及的操作者 user_id 列表
    checksum = Column(String(64), nullable=False)  # SHA-256 校验哈希
    purged_at = Column(DateTime, nullable=False)  # 物理清理时间
    created_at = Column(DateTime, default=utcnow)


class ProjectGovernanceRequest(Base):
    """Tracked approvals for project transfer and soft deletion."""
    __tablename__ = "project_governance_requests"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), nullable=False, index=True)
    project_name = Column(String(200), default="")
    request_type = Column(String(20), nullable=False)  # transfer / delete
    status = Column(String(20), default="pending")  # pending / approved / rejected / cancelled
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    target_manager_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    source_manager_id = Column(String(36), nullable=True)
    reason = Column(Text, nullable=False)
    review_note = Column(Text, default="")
    reviewed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)



# ===== ProjectPreparationItem (项目准备项) =====

class ProjectPreparationItem(Base):
    __tablename__ = "project_preparation_items"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(20), nullable=False, default="scope")
    # scope=范围与资料 / procurement=项目采购 / vehicle=车辆 / software=软件 / site=进场条件
    name = Column(String(200), nullable=False)
    task_id = Column(String(36), nullable=True)  # 关联流程任务（模板「进场准备」阶段任务自动成为准备项）
    is_required = Column(Boolean, default=True)  # 必需项
    blocks_entry = Column(Boolean, default=False)  # 阻塞进场
    status = Column(String(20), default="not_started")
    # not_started / in_progress / pending / passed / failed / na
    owner_id = Column(String(36), nullable=True)  # 内部跟进人（系统用户）
    owner_party = Column(String(20), default="project")
    # 责任方 5 类：project 项目团队 / client 客户 / procurement 采购 / production 生产 / software 软件
    required_date = Column(Date, nullable=True)  # 项目要求日期（最晚需要）
    committed_date = Column(Date, nullable=True)  # 责任方承诺日期
    forecast_date = Column(Date, nullable=True)  # 当前预计日期（最新情况）
    planned_date = Column(Date, nullable=True)  # 兼容旧数据（= 要求日期）
    actual_date = Column(Date, nullable=True)  # 实际完成日期
    risk = Column(String(10), default="low")  # low/medium/high
    affected_phase_id = Column(String(36), nullable=True)  # 影响阶段
    affected_task_id = Column(String(36), nullable=True)  # 影响任务
    completed_by = Column(String(36), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    note = Column(Text, default="")
    extra = Column(JSON, default=dict)  # 分类专属：采购数量/车辆节点/软件版本/进场证据等
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ===== ProjectReadinessReview (进场准备评审) =====

class ProjectReadinessReview(Base):
    __tablename__ = "project_readiness_reviews"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    conclusion = Column(String(20), nullable=False)
    # not_ready 暂不进场 / risky 有风险进场 / ready 确认具备进场条件
    reviewer_id = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime, default=utcnow)
    notes = Column(Text, default="")  # 结论说明（有风险进场：允许原因/未完成处理/跟踪人/预计解决日期）
    remaining_risks = Column(JSON, default=list)  # [{item, owner, due, plan}]
    snapshot = Column(JSON, default=list)  # 评审时全部准备项快照 [{name, status, required_date, forecast_date, blocks_entry}]


# ===== TemplatePreparationItem (模板准备项：项目准备清单的模板定义) =====

class TemplatePreparationItem(Base):
    __tablename__ = "template_preparation_items"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    template_id = Column(String(36), nullable=True)  # NULL = 系统默认模板
    name = Column(String(200), nullable=False)
    category = Column(String(20), default="scope")
    is_required = Column(Boolean, default=True)
    blocks_entry = Column(Boolean, default=False)
    owner_party = Column(String(20), default="project")
    risk = Column(String(10), default="low")
    condition = Column(String(20), default="default")
    # default 始终生成 / need_wms / need_charging / client_server / new_vehicles / overseas 按项目选项生成
    sort_order = Column(Integer, default=0)


# ===== TemplateDoc (模板任务参考文档：任务执行要参考的资料，与提交文件相反) =====

class TemplateDoc(Base):
    __tablename__ = "template_docs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    template_id = Column(String(36), nullable=True)  # NULL = 系统默认模板
    task_id = Column(String(36), nullable=False, index=True)  # 模板任务 id
    filename = Column(String(300), nullable=False)
    stored_name = Column(String(100), nullable=False)  # on-disk filename (UPLOAD_DIR)
    file_size = Column(BigInteger().with_variant(Integer,'sqlite'), default=0)
    content_type = Column(String(100), default="")
    note = Column(String(300), default="")  # 文档说明（如：填完交回的确认单模板）
    uploaded_by = Column(String(36), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)


# ===== TemplateProcurementItem (常用采购项库：项目显式选择后带入，独立于任务) =====

class TemplateProcurementItem(Base):
    __tablename__ = "template_procurement_items"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    template_id = Column(String(36), nullable=True)  # NULL = 系统默认模板
    name = Column(String(200), nullable=False)
    unit = Column(String(20), default="件")         # 单位：台/米/箱/套…
    spec = Column(String(300), default="")          # 规格/型号/说明
    due_weeks = Column(Integer, default=0)          # 相对计划进场周数：-2=进场前2周到货，0=进场当天，+1=进场后1周
    condition = Column(String(20), default="default")
    is_required = Column(Boolean, default=True)
    owner_party = Column(String(20), default="procurement")
    risk = Column(String(10), default="low")
    sort_order = Column(Integer, default=0)
# ===== InboxDocument (文档收集箱：待 AI 归类整理的临时文件) =====

# ===== AiUserMemory（AI 个人记忆：按用户保存长期偏好/事实） =====


# ===== UserUnavailability (人员不可用时段：请假/出差/交接等，HYPE-47) =====

class UserUnavailability(Base):
    """某人某段时间不可排程（请假/出差/离职交接/其他）。

    排程分配与人员看板消费：分配时检测目标人员在指派日期是否处于
    不可用时段；看板展示当前不可用人数与近期不可用安排。
    """

    __tablename__ = "user_unavailability"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(String(100), default="其他")
    note = Column(Text, default="")
    created_by = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

# ===== AiChatSession / AiChatMessage（多轮对话持久化） =====
# HYPE-58：AI 会话从进程内存改为数据库存储，切换页面/重启/多 worker 后仍能恢复。



# ===== NotificationOutbox（外部渠道异步投递队列） =====
# HYPE-58：notify() 只写站内通知 + 出站队列，外发由独立 scheduler 进程按批投递，
# 失败带重试/退避；未配置外部渠道时队列直接标记 disabled，不积压。

class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    notification_id = Column(String(36), nullable=True)  # 关联站内 Notification.id
    user_id = Column(String(36), nullable=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, default="")
    ntype = Column(String(30), default="system")
    project_id = Column(String(36), nullable=True)
    idempotency_key = Column(String(64), nullable=False, unique=True, index=True)  # 幂等键（去重投递）
    status = Column(String(20), default="pending", index=True)  # pending / delivering / delivered / failed / dead / disabled
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    next_retry_at = Column(DateTime, nullable=True, index=True)
    last_error = Column(String(500), default="")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class NotificationChannelConfig(Base):
    """外部通知渠道的管理员界面配置（HYPE-58 通知渠道入口）。

    - 每个渠道一行（channel 唯一）；Webhook 与加签 Secret 用 channel_crypto（Fernet）加密落库，
      任何接口/日志都不得返回或记录明文。
    - 部署环境变量（config.DINGTALK_WEBHOOK_URL 等）优先级高于本表：env 已配置时
      本行配置被忽略（前端只读展示"由部署环境托管"）。
    - 默认不存在行 = 渠道关闭；交付默认关闭，绝不替用户启用。
    """

    __tablename__ = "notification_channel_configs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    channel = Column(String(30), nullable=False, unique=True, index=True)  # dingtalk / json
    enabled = Column(Boolean, default=False, nullable=False)
    webhook_url_encrypted = Column(Text, default="")  # channel_crypto 密文；空=未设置
    secret_encrypted = Column(Text, default="")       # 加签 Secret 密文；空=未设置
    updated_by = Column(String(36), nullable=True)    # 最后修改的管理员 user id
    last_test_at = Column(DateTime, nullable=True)    # 最近一次"发送测试通知"时间
    last_test_success = Column(Boolean, nullable=True)
    last_test_detail = Column(String(300), default="")  # 掩码后的结果描述（绝不含 token/Secret）
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ===== 系统问题反馈（HYPE-72） =====
# 所有登录用户可提交；管理角色（admin/director/pm）可读取列表/详情并更新处理状态。
# 新表由 init_db 的 create_all 幂等创建（容器重启不丢数据），无需 ALTER。

FEEDBACK_STATUS_PENDING = "pending"
FEEDBACK_STATUS_PROCESSING = "processing"
FEEDBACK_STATUS_DONE = "done"
FEEDBACK_STATUSES = (FEEDBACK_STATUS_PENDING, FEEDBACK_STATUS_PROCESSING, FEEDBACK_STATUS_DONE)


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    description = Column(Text, nullable=False)          # 问题描述（必填）
    steps = Column(Text, nullable=False, default="")    # 复现步骤（可选）
    status = Column(String(20), nullable=False, default=FEEDBACK_STATUS_PENDING, index=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


# ===== 个人临时日程（HYPE-88） =====
# PM 端「我的日程」里的临时事项：不挂项目任务（如处理突发故障），单人读写。
# 新表与结构变更通过 Alembic 版本迁移管理。

class PersonalEvent(Base):
    __tablename__ = "personal_events"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)  # HYPE-89：记录归属项目（必填）
    work_date = Column(Date, nullable=False, index=True)
    title = Column(String(100), nullable=False)   # 标题（必填，≤100）
    notes = Column(String(500), default="")       # 备注（选填，≤500）
    created_at = Column(DateTime, default=utcnow)


class ProjectCreationReceipt(Base):
    """一次创建请求的结果；与项目、车型、任务一起提交，重试不重复建项目。"""
    __tablename__ = "project_creation_receipts"
    __table_args__ = (UniqueConstraint("user_id", "client_uuid", name="uq_project_creation_user_uuid"),)
    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), nullable=False)
    client_uuid = Column(String(64), nullable=False)
    request_hash = Column(String(64), nullable=False)
    project_id = Column(String(36), nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utcnow)


# Recoverable project deletion remains available; Alembic owns schema changes.
from app.models.project_deletion import ProjectDeletionRecord, ProjectPermanentBackup  # noqa: E402,F401

from app.models.project_documents import ProjectDocumentDefinition, ProjectDocument, DocumentVersion, DocumentNoticeReceipt, ProjectReportReceipt  # noqa: E402,F401
from app.models.storage import UploadSession,UploadChunk,FileCleanupReceipt,FileRemovalRecord  # noqa: E402,F401
from app.models.document_triggers import DocumentTriggerEvent, IssueSlaReceipt  # noqa: E402,F401

class HolidayCalendar(Base):
    """Explicit complete annual overrides; bundled official years need no seed write."""
    __tablename__ = "holiday_calendars"
    __table_args__ = (CheckConstraint("year >= 1900 AND year <= 2200", name="ck_holiday_calendar_year"),)

    year = Column(Integer, primary_key=True)
    holidays = Column(JSON, nullable=False)
    workdays = Column(JSON, nullable=False)
    source_name = Column(String(300), nullable=False)
    source_url = Column(String(1000), nullable=False)
    published_on = Column(Date, nullable=False)
    note = Column(Text, nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

from app.models.external_shares import ExternalShare, ExternalAccessLog  # noqa: E402,F401


class FieldOperation(Base):
    """Append-only actual field work, independent of plan assignments and dates."""
    __tablename__ = 'field_operations'
    __table_args__ = (UniqueConstraint('project_id','actor_id','client_uuid',name='uq_field_operation_actor_uuid'),
                      UniqueConstraint('project_id','sequence',name='uq_field_operation_sequence'))
    id = Column(String(36),primary_key=True,default=gen_uuid)
    project_id = Column(String(36),ForeignKey('projects.id',ondelete='CASCADE'),nullable=False,index=True)
    kind = Column(String(16),nullable=False)
    target_id = Column(String(36),nullable=False)
    step_key = Column(String(80),nullable=False,default='')
    weekly_cell_id = Column(String(36),nullable=True)
    target_label = Column(String(400),nullable=False,default='')
    actor_id = Column(String(36),ForeignKey('users.id',ondelete='SET NULL'),nullable=True,index=True)
    assisted_user_id = Column(String(36),ForeignKey('users.id',ondelete='SET NULL'),nullable=True)
    completion_date = Column(Date,nullable=False)
    recorded_at = Column(DateTime,nullable=False,default=utcnow)
    is_done = Column(Boolean,nullable=False)
    note = Column(Text,nullable=False,default='')
    action = Column(String(16),nullable=False,default='record')
    replaces_id = Column(String(36),nullable=True)
    root_id = Column(String(36),nullable=True)
    restores_id = Column(String(36),nullable=True)
    reason = Column(Text,nullable=False,default='')
    before_state = Column(JSON,nullable=False,default=dict)
    after_version = Column(Integer,nullable=False)
    sequence = Column(Integer,nullable=False,default=1)
    client_uuid = Column(String(64),nullable=False)
    payload_hash = Column(String(64),nullable=False)
