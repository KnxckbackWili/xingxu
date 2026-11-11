"""The sixteen tables of 行序 4: accounts, projects and their five record lists, templates, history."""
from uuid import uuid4

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint)

from app.db import Base
from app.time_utils import utcnow


def gen_uuid() -> str:
    return str(uuid4())


class Row:
    """Columns every editable row has. A row with deleted_at is in the 30-day trash."""
    id = Column(String(36), primary_key=True, default=gen_uuid)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    created_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    username = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(20), nullable=False, default="employee")  # admin / employee
    is_active = Column(Boolean, nullable=False, default=True)
    token_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class LoginFailure(Base):
    """Failed sign-ins per client and username, shared by every web worker."""
    __tablename__ = "login_failures"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    key = Column(String(200), nullable=False)
    bucket = Column(Integer, nullable=False)
    count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("key", "bucket", name="uq_login_failure"),)


class Project(Row, Base):
    __tablename__ = "projects"

    name = Column(String(200), nullable=False)
    contract_no = Column(String(100), nullable=False, default="")
    customer = Column(String(200), nullable=False, default="")
    note = Column(Text, nullable=False, default="")
    is_closed = Column(Boolean, nullable=False, default=False)
    rev = Column(Integer, nullable=False, default=0)  # +1 on every write inside the project
    deleted_by = Column(String(36), nullable=True)


class ProjectStep(Row, Base):
    """One column of the vehicle table: a step every vehicle of the project goes through."""
    __tablename__ = "project_steps"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)


class Vehicle(Row, Base):
    __tablename__ = "vehicles"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_no = Column(String(100), nullable=False)  # 车辆编号, unique among the project's live vehicles
    fleet_no = Column(String(50), nullable=False, default="")  # 车号
    model = Column(String(100), nullable=False, default="")
    config_no = Column(String(100), nullable=False, default="")
    note = Column(Text, nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)


class VehicleMark(Base):
    """A vehicle finished a step. The row existing is the tick."""
    __tablename__ = "vehicle_marks"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(String(36), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String(36), ForeignKey("project_steps.id", ondelete="CASCADE"), nullable=False, index=True)
    done_by = Column(String(36), nullable=True)
    done_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("vehicle_id", "step_id", name="uq_vehicle_mark"),)


class VehicleRecord(Row, Base):
    """One line of the company's lifecycle table for one vehicle."""
    __tablename__ = "vehicle_records"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(String(36), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    happened_on = Column(Date, nullable=True)  # 调车时间记录
    category = Column(String(50), nullable=False, default="")
    content = Column(Text, nullable=False, default="")
    recorded_by_name = Column(String(100), nullable=False, default="")
    recorded_on = Column(Date, nullable=True)


class WorkItem(Row, Base):
    __tablename__ = "work_items"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(String(100), nullable=False, default="")
    name = Column(String(300), nullable=False)
    note = Column(Text, nullable=False, default="")
    done = Column(Boolean, nullable=False, default=False)
    done_by = Column(String(36), nullable=True)
    done_at = Column(DateTime, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)


class Issue(Row, Base):
    __tablename__ = "issues"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id = Column(String(36), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)
    description = Column(Text, nullable=False)
    resolution = Column(Text, nullable=False, default="")
    is_closed = Column(Boolean, nullable=False, default=False)
    closed_by = Column(String(36), nullable=True)
    closed_at = Column(DateTime, nullable=True)


class Document(Row, Base):
    """One line of the list of documents a project has to hand in."""
    __tablename__ = "documents"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    note = Column(Text, nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)


class Item(Row, Base):
    __tablename__ = "items"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    spec = Column(String(300), nullable=False, default="")
    quantity = Column(Float, nullable=True)
    unit = Column(String(30), nullable=False, default="")
    arrived = Column(Boolean, nullable=False, default=False)
    arrived_by = Column(String(36), nullable=True)
    arrived_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)


class File(Row, Base):
    """An uploaded file under a document line, an issue, or the project's other files."""
    __tablename__ = "files"

    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_kind = Column(String(20), nullable=False)  # document / issue / other
    owner_id = Column(String(36), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    size = Column(Integer, nullable=False, default=0)
    mime = Column(String(100), nullable=False, default="application/octet-stream")
    sha256 = Column(String(64), nullable=False, default="")
    storage_path = Column(String(300), nullable=False)  # relative to UPLOAD_DIR


class Template(Row, Base):
    __tablename__ = "templates"

    name = Column(String(200), nullable=False)
    note = Column(Text, nullable=False, default="")
    rev = Column(Integer, nullable=False, default=0)


class TemplateRow(Row, Base):
    """A line of one of a template's four lists; copied into a project when it is created."""
    __tablename__ = "template_rows"

    template_id = Column(String(36), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)  # work / document / step / item
    stage = Column(String(100), nullable=False, default="")
    name = Column(String(300), nullable=False)
    spec = Column(String(300), nullable=False, default="")
    quantity = Column(Float, nullable=True)
    unit = Column(String(30), nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)


class VehicleType(Base):
    __tablename__ = "vehicle_types"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(100), unique=True, nullable=False)
    note = Column(Text, nullable=False, default="")
    is_enabled = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ChangeLog(Base):
    """Who changed what. Rows are only ever added."""
    __tablename__ = "change_logs"

    seq = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(36), nullable=True)  # no FK: history outlives a purged project
    user_id = Column(String(36), nullable=True)
    user_name = Column(String(100), nullable=False, default="")
    kind = Column(String(50), nullable=False)
    row_id = Column(String(64), nullable=False, default="")
    row_label = Column(String(300), nullable=False, default="")
    action = Column(String(20), nullable=False)  # create / update / delete / restore / import / ...
    field = Column(String(50), nullable=False, default="")
    old_value = Column(JSON, nullable=True)
    new_value = Column(JSON, nullable=True)
    detail = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (Index("ix_change_logs_project_seq", "project_id", "seq"),
                      Index("ix_change_logs_row", "row_id", "seq"))
