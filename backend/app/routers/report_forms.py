"""Report form routes: 生命周期表 / 质量问题反馈单 / 内部联系单（物品申请）。

端到端：生命周期表 Excel 导入导出、质量问题反馈单 Excel 导入导出、
内部联系单（物品申请）记录 CRUD + Word 生成/导入。
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.config import MAX_UPLOAD_SIZE
from app.db import get_db
from app.deps import get_current_user
from app.models import Project, ItemApplication, User
from app.routers.io_routes import _stream_bytes
from app.services import report_forms
from app.services.change_log import log_change
from app.services.permissions import C_INVENTORY, require_project_capability
from app.services.rate_limit import rate_limit_export
from app.services.scope import ensure_project_visible

router = APIRouter(tags=["表单导入导出"])


def _lock_form_project(db: Session, project_id: str, user: User, capability: str) -> Project:
    """Import/record writes serialize with archival, membership and live edits."""
    from app.services.permissions import authorize_project
    from app.services.record_lock import lock_writable_project
    project = ensure_project_visible(db, project_id, user)
    authorize_project(user, project, capability)
    project = lock_writable_project(db, project, user)
    authorize_project(user, project, capability)
    return project


def _application_dict(app: ItemApplication) -> dict:
    return {
        "id": app.id,
        "project_id": app.project_id,
        "title": app.title,
        "item_name": app.item_name,
        "requirement": app.requirement,
        "reason": app.reason,
        "drawing_no": app.drawing_no,
        "contract_no": app.contract_no,
        "amount": app.amount,
        "applicant": app.applicant,
        "approver": app.approver,
        "department": app.department,
        "apply_date": app.apply_date.isoformat() if app.apply_date else None,
        "status": app.status,
        "note": app.note,
        "created_at": app.created_at.isoformat() if app.created_at else None,
        "updated_at": app.updated_at.isoformat() if app.updated_at else None,
    }


class ItemApplicationBody(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(default="", max_length=300)
    item_name: str = Field(default="", max_length=200)
    requirement: str = Field(default="", max_length=5000)
    reason: str = Field(default="", max_length=5000)
    drawing_no: str = Field(default="", max_length=100)
    contract_no: str = Field(default="", max_length=100)
    amount: str = Field(default="", max_length=100)
    applicant: str = Field(default="", max_length=100)
    approver: str = Field(default="", max_length=100)
    department: str = Field(default="", max_length=100)
    apply_date: Optional[date] = None
    status: str = Field(default="pending", pattern="^(pending|approved|rejected)$")
    note: str = Field(default="", max_length=5000)


class ApplicationStatusUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    status: str = Field(pattern="^(pending|approved|rejected)$")
    expected_status: str = Field(pattern="^(pending|approved|rejected)$")


def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read(MAX_UPLOAD_SIZE + 1)
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f"文件超过大小限制（{MAX_UPLOAD_SIZE // 1024 // 1024}MB）")
    return data


# ===== 生命周期表 =====

@router.get("/projects/{project_id}/export/lifecycle")
@route_permission('project.export')
def export_lifecycle(
    project_id: str,
    project: Project = Depends(require_project_capability("project.export")),
    db: Session = Depends(get_db),
    __: User = Depends(rate_limit_export()),
):
    from app.services.generated_document_forms import readable_lifecycle
    from app.services.project_documents import audit_access
    events,assets=readable_lifecycle(db,project,__)
    data = report_forms.lifecycle_to_excel(db, project_id,events=events)
    audit_access(db,project,__,files=assets,action='confidential_export');db.commit()
    return StreamingResponse(
        _stream_bytes(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''AGV%E7%94%9F%E5%91%BD%E5%91%A8%E6%9C%9F%E8%A1%A8.xlsx",'Cache-Control':'private, no-store'},
    )


@router.post("/projects/{project_id}/import/lifecycle")
@route_permission('project.manage_plan')
def import_lifecycle(
    project_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    _: Project = Depends(require_project_capability("project.manage_plan")),
    db: Session = Depends(get_db),
):
    _lock_form_project(db, project_id, user, "project.manage_plan")
    data = _read_upload(file)
    try:
        result = report_forms.lifecycle_from_excel(db, project_id, data, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_change(db, project_id, "vehicle_unit", project_id, "import", user.id,
               f"导入生命周期表：{result['events']} 条车辆问题")
    db.commit()
    return result


# ===== 质量问题反馈单 =====

@router.get("/projects/{project_id}/issues/{issue_id}/export/quality-form")
@route_permission('project.export')
def export_quality_form(
    project_id: str, issue_id: str,
    _: Project = Depends(require_project_capability("project.export")),
    db: Session = Depends(get_db),
    __: User = Depends(rate_limit_export()),
):
    try:
        data = report_forms.quality_form_to_excel(db, project_id, issue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return StreamingResponse(
        _stream_bytes(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename*=UTF-8''%E8%B4%A8%E9%87%8F%E9%97%AE%E9%A2%98%E5%8F%8D%E9%A6%88%E5%8D%95.xlsx"},
    )


@router.post("/projects/{project_id}/import/quality-form")
@route_permission('project.manage_issues')
def import_quality_form(
    project_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    _: Project = Depends(require_project_capability("project.manage_issues")),
    db: Session = Depends(get_db),
):
    _lock_form_project(db, project_id, user, "project.manage_issues")
    data = _read_upload(file)
    try:
        result = report_forms.quality_form_from_excel(db, project_id, data, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_change(db, project_id, "issue", result["id"], "import", user.id,
               f"导入质量问题反馈单：{result['message']}")
    db.commit()
    return result


# ===== 内部联系单（物品申请记录） =====

@router.get("/projects/{project_id}/item-applications")
@route_permission('project.read')
def list_item_applications(
    project_id: str, status: str = Query(default=""), search: str = Query(default=""),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ensure_project_visible(db, project_id, user)
    query = db.query(ItemApplication).filter_by(project_id=project_id)
    if status:
        query = query.filter(ItemApplication.status == status)
    if search:
        like = f"%{search.strip()}%"
        query = query.filter(ItemApplication.title.ilike(like) | ItemApplication.requirement.ilike(like)
                             | ItemApplication.applicant.ilike(like) | ItemApplication.item_name.ilike(like))
    rows = query.order_by(ItemApplication.created_at.desc()).all()
    return [_application_dict(app) for app in rows]


@router.post("/projects/{project_id}/item-applications")
@route_permission('project.manage_inventory')
def create_item_application(
    project_id: str, body: ItemApplicationBody,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _lock_form_project(db, project_id, user, C_INVENTORY)
    app = ItemApplication(project_id=project_id, created_by=user.id, **body.model_dump())
    db.add(app)
    db.flush()
    log_change(db, project_id, "item_application", app.id, "create", user.id,
               f"新建物品申请「{app.title or app.requirement[:40]}」")
    db.commit()
    db.refresh(app)
    return _application_dict(app)


@router.get("/projects/{project_id}/item-applications/{app_id}")
@route_permission('project.read')
def get_item_application(
    project_id: str, app_id: str,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    ensure_project_visible(db, project_id, user)
    app = db.get(ItemApplication, app_id)
    if app is None or app.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品申请不存在")
    return _application_dict(app)


@router.put("/projects/{project_id}/item-applications/{app_id}")
@route_permission('project.manage_inventory')
def update_item_application(
    project_id: str, app_id: str, body: ItemApplicationBody,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _lock_form_project(db, project_id, user, C_INVENTORY)
    app = db.get(ItemApplication, app_id, populate_existing=True)
    if app is None or app.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品申请不存在")
    for key, value in body.model_dump().items():
        setattr(app, key, value)
    log_change(db, project_id, "item_application", app.id, "update", user.id,
               f"更新物品申请「{app.title or app.requirement[:40]}」")
    db.commit()
    db.refresh(app)
    return _application_dict(app)


@router.patch("/projects/{project_id}/item-applications/{app_id}/status")
@route_permission('project.manage_inventory')
def update_application_status(
    project_id: str, app_id: str, body: ApplicationStatusUpdate,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _lock_form_project(db, project_id, user, C_INVENTORY)
    app = db.get(ItemApplication, app_id, populate_existing=True)
    if app is None or app.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品申请不存在")
    if app.status != body.expected_status:
        raise HTTPException(status_code=409, detail="申请状态已被其他人修改，请刷新后重新选择")
    if app.status != body.status:
        app.status = body.status
        log_change(db, project_id, "item_application", app.id, "update", user.id,
                   f"快捷更新物品申请「{app.title or app.requirement[:40]}」状态")
    db.commit()
    db.refresh(app)
    return _application_dict(app)


@router.delete("/projects/{project_id}/item-applications/{app_id}")
@route_permission('project.manage_inventory')
def delete_item_application(
    project_id: str, app_id: str,
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    _lock_form_project(db, project_id, user, C_INVENTORY)
    app = db.get(ItemApplication, app_id, populate_existing=True)
    if app is None or app.project_id != project_id:
        raise HTTPException(status_code=404, detail="物品申请不存在")
    db.delete(app)
    log_change(db, project_id, "item_application", app_id, "delete", user.id, "删除物品申请")
    db.commit()
    return {"message": "物品申请已删除"}


@router.get("/projects/{project_id}/item-applications/{app_id}/export")
@route_permission('project.export')
def export_item_application(
    project_id: str, app_id: str,
    project: Project = Depends(require_project_capability("project.export")),
    db: Session = Depends(get_db),
    __: User = Depends(rate_limit_export()),
):
    from app.services.generated_document_forms import readable_contact
    from app.services.project_documents import audit_access
    assets=readable_contact(db,project,__,app_id)
    try:
        data = report_forms.item_application_to_docx(db, project_id, app_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_access(db,project,__,files=assets,action='confidential_export');db.commit()
    filename = f"%E5%86%85%E9%83%A8%E8%81%94%E7%B3%BB%E5%8D%95-{app_id[:8]}.docx"
    return StreamingResponse(
        _stream_bytes(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}",'Cache-Control':'private, no-store'},
    )


@router.post("/projects/{project_id}/import/item-application")
@route_permission('project.manage_inventory')
def import_item_application(
    project_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    _: Project = Depends(require_project_capability(C_INVENTORY)),
    db: Session = Depends(get_db),
):
    _lock_form_project(db, project_id, user, C_INVENTORY)
    data = _read_upload(file)
    try:
        result = report_forms.item_application_from_docx(db, project_id, data, user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log_change(db, project_id, "item_application", result["id"], "import", user.id,
               f"导入内部联系单：{result['message']}")
    db.commit()
    return result
