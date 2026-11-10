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
    role = Column(String(20), nullable=False, default="employee")  # admin 系统管理员 / employee 员工
    # 角色: admin/director/lead/pm/technician/worker/intern
    phone = Column(String(20), default="")
    email = Column(String(100), default="")
    is_active = Column(Boolean, default=True)
    token_version = Column(Integer, default=0)  # 改密/重置密码时 +1，旧 token 全部失效
    mfa_enabled = Column(Boolean, nullable=False, default=False, server_default=false())
    mfa_secret_encrypted = Column(Text, nullable=True)
    mfa_last_step = Column(BigInteger, nullable=False, default=-1, server_default="-1")
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



# ===== Project =====

class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (CheckConstraint("status IN ('preparing','executing','acceptance','completed','archived','suspended')", name="ck_project_status"),)

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(200), nullable=False)
    abbreviation = Column(String(50), default="")
    contract_no = Column(String(100), default="")  # 项目合同号（生命周期表等公司表单使用）
    manager = Column(String(100), default="")  # PM user_id
    client = Column(String(200), default="")
    location = Column(String(200), default="")
    timezone = Column(String(64), default="Asia/Shanghai")  # 项目现场时区（俄/越等海外现场按当地日历取"今天"）
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="preparing")
    description = Column(Text, default="")
    staffing_notes = Column(Text, default="")  # 资料中的人员姓名/建议，不自动绑定系统账号
    rest_mode = Column(String(10), default="none")  # none=不休息 one=休周日 two=休周六日
    rest_days = Column(JSON, default=list)  # 手动补充休息日 ["2026-10-01", ...]
    skip_holidays = Column(Boolean, default=False)  # 是否跳过法定节假日（默认不跳过，现场赶工照常排）
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    template_id = Column(String(36), nullable=True)  # 生成来源模板（P3：记录使用情况）
    template_version = Column(Integer, default=0)  # 生成时的模板版本
    dispatch_platform = Column(String(20), nullable=True)  # NDC / GRACE / integrated
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
    frame_no = Column(String(100), default="")  # 门架号（门架钢印），质量问题反馈单使用
    factory_date = Column(Date, nullable=True)  # 出厂日期（铭牌），质量问题反馈单使用
    model_name = Column(String(100), default="")  # 生命周期表导入的车辆型号（未匹配车型档案时保留展示）
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
    done_on = Column(Date, nullable=True)  # set when is_done
    recorded_at = Column(DateTime, nullable=False, default=utcnow)
    done_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note = Column(Text, default="")
    source_metadata = Column(JSON, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("vehicle_unit_id", "step_key", name="uq_vehicle_progress_unit_step"),)


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


# ===== Task =====

class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    template_id = Column(String(36), nullable=True, index=True)
    phase_id = Column(String(36), ForeignKey("phases.id", ondelete="SET NULL"), nullable=True, index=True)
    group_label = Column(String(200), nullable=True, default="")
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    quantity_type = Column(String(20), nullable=False, default="per_vehicle")
    # per_vehicle / manual / fixed
    safety_flag = Column(Boolean, default=False)
    applicable_vehicle_types = Column(JSON, default=list)  # [] means all types
    sort_order = Column(Integer, default=0)
    reference_docs = Column(JSON, default=list)  # 参考文档（生成时从模板任务复制）: [{filename, stored_name, file_size, content_type, note}]
    version = Column(Integer, default=0)  # 乐观锁版本号
    # C2-6：模板源任务 ID——项目任务稳定关联生成它的模板任务，模板任务改名后重生成不再产生新旧两批
    source_task_id = Column(String(36), nullable=True, index=True)
    vehicle_step_key = Column(String(80), nullable=True)  # explicit template/project step, never guessed
    source_vehicle_event_id = Column(String(36), ForeignKey("vehicle_lifecycle_events.id", ondelete="SET NULL"), nullable=True, unique=True)
    # 工作项完成：谁、以什么身份、什么时候、为什么标记完成。
    manually_completed = Column(Boolean, default=False)
    manual_completed_by = Column(String(36), nullable=True)
    manual_completed_role = Column(String(20), nullable=True)
    manual_completed_at = Column(DateTime, nullable=True)
    manual_completed_reason = Column(Text, default="")
    manual_check_overrides = Column(JSON, default=list)

    project = relationship("Project", backref=backref("tasks", passive_deletes=True, cascade="all, delete-orphan"))


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
    写入。纳入 project_id 后与 issues 的跨项目契约一致。
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
    vehicle_type = Column(String(50), nullable=True)  # 适用车型：一个车型一个模板；空 = 通用
    version = Column(Integer, default=1)  # 发布版本号（P3：每次发布 +1）
    status = Column(String(10), default="draft")  # draft / published
    snapshots = Column(JSON, default=list)  # C2-3 发布版本快照 [{version, at, by, snapshot}]
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TemplateSection(Base):
    """A titled part of a template, placed on one company stage (4–9) for gates and deadlines."""
    __tablename__ = "template_sections"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    template_id = Column(String(36), ForeignKey("templates.id", ondelete="CASCADE"), nullable=True, index=True)  # NULL = 通用模板
    title = Column(String(200), nullable=False)
    stage_key = Column(String(8), nullable=False, default="6")
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class TemplateItem(Base):
    """One row of a template: a work item, a file bundle or a purchase, any of which may hand in files.

    The editing source of a template. Phases, tasks, check items, document requirements, vehicle steps
    and procurement rows are compiled from these with the same ids (services/template_items.py).
    """
    __tablename__ = "template_items"
    id = Column(String(36), primary_key=True, default=gen_uuid)
    template_id = Column(String(36), ForeignKey("templates.id", ondelete="CASCADE"), nullable=True, index=True)
    section_id = Column(String(36), ForeignKey("template_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(12), nullable=False)  # work / file / purchase
    name = Column(String(200), nullable=False)
    note = Column(Text, nullable=False, default="")
    optional = Column(Boolean, nullable=False, default=False)  # chosen per project when it is created
    per_vehicle = Column(Boolean, nullable=False, default=False)
    step_key = Column(String(80), nullable=True)  # vehicle step a per-vehicle work item records
    checks = Column(JSON, nullable=False, default=list)  # [{id, name, description, required, safety}]
    files = Column(JSON, nullable=False, default=list)  # [{id, code, name, ...document rule, blank_file_id}]
    quantity = Column(Float, nullable=True)
    unit = Column(String(20), nullable=False, default="")
    spec = Column(String(300), nullable=False, default="")
    extra = Column(JSON, nullable=False, default=dict)  # carried-over values of converted rows
    sort_order = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=0)
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
    job_id = Column(String(50), unique=True, nullable=False)  # weekly_report / document_deadlines / storage_maintenance / notify_outbox_drain
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


class ProjectPreparationItem(Base):
    __tablename__ = "project_preparation_items"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(20), nullable=False, default="procurement")  # 只有 procurement 项目采购
    name = Column(String(200), nullable=False)
    is_required = Column(Boolean, default=True)  # 必需项
    status = Column(String(20), default="not_started")
    # not_started / in_progress / pending / passed / failed / na
    owner_id = Column(String(36), nullable=True)  # 内部跟进人（系统用户）
    owner_party = Column(String(20), default="project")
    # 责任方 5 类：project 项目团队 / client 客户 / procurement 采购 / production 生产 / software 软件
    required_date = Column(Date, nullable=True)  # 项目要求日期（最晚需要）
    committed_date = Column(Date, nullable=True)  # 责任方承诺日期
    forecast_date = Column(Date, nullable=True)  # 当前预计日期（最新情况）
    actual_date = Column(Date, nullable=True)  # 实际完成日期
    risk = Column(String(10), default="low")  # low/medium/high
    completed_by = Column(String(36), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    note = Column(Text, default="")
    extra = Column(JSON, default=dict)  # 采购数量、单位、规格、下单状态和来源
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


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
from app.models.document_triggers import DocumentTriggerEvent  # noqa: E402,F401

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
