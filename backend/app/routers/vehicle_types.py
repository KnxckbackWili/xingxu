"""车型字典：普通用户读取启用车型，管理员集中新增/启停/排序。

HYPE-63：车型由字典统一维护，业务页面（项目创建、现场信息）从启用项中选择，
不再硬编码。历史遗留字符串 custom / 自定义 经 _migrate 归一化为「其他/定制」；
字典外的历史值仍保留并允许编辑（见 projects.py 的车辆写入校验）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission, route_permission_contextual, route_permission_exempt
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.models import Task, User, Vehicle, VehicleType
from app.services.change_log import log_change

router = APIRouter(prefix="/vehicle-types", tags=["车型字典"])

# 历史车型字符串 → 字典规范名（custom/自定义 均指「其他/定制」）
LEGACY_VEHICLE_TYPE_ALIASES = {"custom": "其他/定制", "自定义": "其他/定制"}


def normalize_vehicle_type(value) -> str:
    """去首尾空格 + 历史别名归一化。"""
    v = (value or "").strip()
    return LEGACY_VEHICLE_TYPE_ALIASES.get(v, v)


def vehicle_type_dict(t: VehicleType) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "is_enabled": bool(t.is_enabled),
        "sort_order": t.sort_order,
    }


def vehicle_type_referenced(db: Session, name: str) -> bool:
    """车型是否已被项目车辆 / 任务（含模板任务）的适用车型引用。"""
    if db.query(Vehicle).filter(Vehicle.vehicle_type == name).count() > 0:
        return True
    for task in db.query(Task).filter(Task.applicable_vehicle_types.isnot(None)).all():
        if name in (task.applicable_vehicle_types or []):
            return True
    return False


def validate_vehicle_type_value(db: Session, value, *, current_value=None, allow_legacy: bool = False) -> str:
    """车辆写入时的字典校验（projects.py 复用）。

    - 去首尾空格、非空、≤50 字；
    - 允许：启用的字典项；编辑时保留当前值（含已停用/字典外历史值）；
    - 管理员例外：allow_legacy=True 时接受任意非空字符串（管理员掌握字典）。
    """
    v = normalize_vehicle_type(value)
    if not v:
        raise HTTPException(status_code=400, detail="车型不能为空")
    if len(v) > 50:
        raise HTTPException(status_code=400, detail="车型名称过长（最多 50 字）")
    if allow_legacy:
        return v
    entry = db.query(VehicleType).filter(VehicleType.name == v).first()
    if entry is not None and entry.is_enabled:
        return v
    if current_value is not None and v == normalize_vehicle_type(current_value):
        return v
    raise HTTPException(
        status_code=400,
        detail=f"车型「{v}」不在启用的车型字典中，请从可用车型中选择；或先由管理员在「车型管理」中新增",
    )


class VehicleTypeCreate(BaseModel):
    # 长度上限由 validate 逻辑统一给出中文 400 提示（去首尾空格后非空、≤50）。
    name: str = Field(..., min_length=1)
    sort_order: Optional[int] = None


class VehicleTypeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    is_enabled: Optional[bool] = None
    sort_order: Optional[int] = None


class VehicleTypeReorder(BaseModel):
    ids: list[str]


@router.get("", response_model=list)
@route_permission_exempt('登录业务共用的启用车型字典')
def list_enabled_vehicle_types(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """普通用户读取启用的车型（业务页面选择项）。"""
    rows = db.query(VehicleType).filter(VehicleType.is_enabled.is_(True)) \
        .order_by(VehicleType.sort_order, VehicleType.name).all()
    return [vehicle_type_dict(t) for t in rows]


@router.get("/all", response_model=list)
@route_permission_contextual('system.vehicle_types.view', 'system.vehicle_types.manage', reason='处理器按车型查看或维护权限校验')
def list_all_vehicle_types(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """管理员或获查看/维护授权的成员读取全部车型（含已停用），供管理界面维护。"""
    from app.services.system_permissions import has_permission
    if not (has_permission(user, "system.vehicle_types.view", default=user.role == "admin") or has_permission(user, "system.vehicle_types.manage", default=user.role == "admin")):
        raise HTTPException(403, "没有车型管理查看权限")
    rows = db.query(VehicleType).order_by(VehicleType.sort_order, VehicleType.name).all()
    return [vehicle_type_dict(t) for t in rows]


@router.post("", response_model=dict)
@route_permission('system.vehicle_types.manage')
def create_vehicle_type(
    data: VehicleTypeCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员新增车型（名称去首尾空格、非空、≤50、不可重复）。"""
    name = normalize_vehicle_type(data.name)
    if not name:
        raise HTTPException(status_code=400, detail="车型名称不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="车型名称过长（最多 50 字）")
    if db.query(VehicleType).filter(VehicleType.name == name).first() is not None:
        raise HTTPException(status_code=400, detail=f"车型「{name}」已存在")
    sort_order = data.sort_order
    if sort_order is None:
        max_order = db.query(VehicleType).order_by(VehicleType.sort_order.desc()).first()
        sort_order = (max_order.sort_order + 1) if max_order is not None and max_order.sort_order is not None else 1
    t = VehicleType(name=name, is_enabled=True, sort_order=sort_order)
    db.add(t)
    db.flush()
    log_change(db, None, "vehicle_type", t.id, "create", user.id, f"新增车型「{name}」")
    db.commit()
    db.refresh(t)
    return vehicle_type_dict(t)


@router.put("/reorder")
@route_permission('system.vehicle_types.manage')
def reorder_vehicle_types(
    data: VehicleTypeReorder,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员调整车型排序：按 ids 顺序整体覆盖 sort_order。"""
    rows = db.query(VehicleType).all()
    by_id = {t.id: t for t in rows}
    if len(data.ids) != len(rows):
        raise HTTPException(status_code=400, detail="排序列表与车型字典不一致")
    if len(set(data.ids)) != len(data.ids):
        raise HTTPException(status_code=400, detail="排序列表存在重复车型 ID，已拒绝，排序未改动")
    if any(i not in by_id for i in data.ids):
        raise HTTPException(status_code=400, detail="排序列表与车型字典不一致")
    for index, tid in enumerate(data.ids, start=1):
        by_id[tid].sort_order = index
    log_change(db, None, "vehicle_type", "reorder", "update", user.id, "调整车型排序")
    db.commit()
    return {"ok": True}


@router.put("/{vehicle_type_id}", response_model=dict)
@route_permission('system.vehicle_types.manage')
def update_vehicle_type(
    vehicle_type_id: str,
    data: VehicleTypeUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """管理员修改车型（启停/排序；重命名仅限未被引用，否则拒绝并建议「新建 + 停用旧项」）。"""
    t = db.get(VehicleType, vehicle_type_id)
    if t is None:
        raise HTTPException(status_code=404, detail="车型不存在")

    detail_parts = []
    if data.name is not None:
        new_name = normalize_vehicle_type(data.name)
        if not new_name:
            raise HTTPException(status_code=400, detail="车型名称不能为空")
        if len(new_name) > 50:
            raise HTTPException(status_code=400, detail="车型名称过长（最多 50 字）")
        if new_name != t.name:
            dup = db.query(VehicleType).filter(VehicleType.name == new_name).first()
            if dup is not None:
                raise HTTPException(status_code=400, detail=f"车型「{new_name}」已存在")
            if vehicle_type_referenced(db, t.name):
                raise HTTPException(
                    status_code=400,
                    detail=f"车型「{t.name}」已被项目车辆或模板任务引用，禁止重命名；请新建车型并停用旧项",
                )
            detail_parts.append(f"重命名「{t.name}」→「{new_name}」")
            t.name = new_name

    if data.is_enabled is not None:
        detail_parts.append(f"{'启用' if data.is_enabled else '停用'}「{t.name}」")
        t.is_enabled = data.is_enabled

    if data.sort_order is not None:
        detail_parts.append(f"排序 → {data.sort_order}")
        t.sort_order = data.sort_order

    if detail_parts:
        log_change(db, None, "vehicle_type", t.id, "update", user.id, "；".join(detail_parts))
    db.commit()
    db.refresh(t)
    return vehicle_type_dict(t)
