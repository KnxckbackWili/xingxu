"""Template library: the built-in general template plus one template per vehicle type.

A template's content is sections of one-row items (routers/template_items.py). The phases, tasks,
document requirements, vehicle steps and procurement rows read here are compiled from those items
and are what projects are generated from; they are not edited directly.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Literal
import os
import shutil
from uuid import uuid4
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.system_permissions import route_permission
from app.db import get_db
from app.deps import get_current_user, require_admin
from app.time_utils import utcnow
from app.services.change_log import log_change
from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES
from app.config import UPLOAD_DIR
from app.models import User, Phase, Module, Task, CheckItem, Template, TemplateDoc, TemplatePreparationItem

router = APIRouter(prefix="/templates", tags=["模板"])

DEFAULT_TEMPLATE_ID = "default"


def _vehicle_template_steps(db,template_id):
    from app.services.vehicle_progress import template_steps
    from types import SimpleNamespace
    from app.services.vehicle_progress import DEFAULT_STEPS
    return template_steps(db,template_id) or [SimpleNamespace(key=k,name=n) for k,n in DEFAULT_STEPS]


# ===== Template metadata =====

@router.get("")
@route_permission('system.templates.read')
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    result = [{
        "id": DEFAULT_TEMPLATE_ID,
        "name": "通用模板",
        "description": "没有专用模板的车型用它；新建车型模板时也从它复制",
        "version": 1,
        "status": "published",
        "usage_count": 0,
        "is_system": True,
        "vehicle_type": None,
    }]
    from app.models import Project as _P
    # The default template is represented by the virtual "default" entry above.
    # Older databases also contain a metadata row for it; do not expose it twice.
    for t in db.query(Template).filter(Template.is_system.is_(False)).order_by(Template.created_at).all():
        result.append({
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "is_system": False,
            "vehicle_type": t.vehicle_type or None,
            "version": t.version or 1,
            "status": t.status or "draft",
            "usage_count": db.query(_P).filter(_P.template_id == t.id).count(),
        })
    from app.services.template_items import summary
    counts = summary(db)
    empty = {"work": 0, "file": 0, "purchase": 0, "files": 0, "sections": 0}
    for row in result:
        row["summary"] = counts.get(row["id"], empty)
    return result


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    copy_from: Optional[str] = None
    vehicle_type: Optional[str] = Field(default=None, max_length=50)


def _vehicle_type(db: Session, value: Optional[str], template_id: Optional[str] = None) -> Optional[str]:
    """Blank = general template. One template per vehicle type, so a type already taken by another template is refused."""
    value = (value or "").strip() or None
    if value is None:
        return None
    taken = db.query(Template).filter(Template.vehicle_type == value, Template.is_system.is_(False))
    if template_id:
        taken = taken.filter(Template.id != template_id)
    other = taken.first()
    if other is not None:
        raise HTTPException(status_code=409, detail=f"车型「{value}」已有模板「{other.name}」，一个车型只用一个模板")
    return value


@router.post("")
@route_permission('system.templates.manage')
def create_template(data: TemplateCreate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if data.copy_from and data.copy_from != DEFAULT_TEMPLATE_ID and db.get(Template, data.copy_from) is None:
        raise HTTPException(status_code=404, detail="来源模板不存在，请刷新后重试")
    t = Template(name=data.name, description=data.description, is_system=False, vehicle_type=_vehicle_type(db, data.vehicle_type))
    db.add(t)
    db.flush()
    src = data.copy_from or DEFAULT_TEMPLATE_ID
    from app.services.document_requirements import lock_templates, recheck_authority
    from app.services.template_items import copy_template
    lock_templates(db, src, t.id)
    recheck_authority(db, user.id)
    copy_template(db, src, t.id)
    db.flush()
    # C2-4：复制模板补审计
    log_change(db, None, "template", t.id, "create", user.id,
               f"创建模板「{t.name}」（从{'通用模板' if src == DEFAULT_TEMPLATE_ID else src}复制）")
    db.commit()
    return {"id": t.id, "name": t.name}


class TemplateRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    vehicle_type: Optional[str] = Field(default=None, max_length=50)


@router.put("/{template_id}")
@route_permission('system.templates.manage')
def rename_template(template_id: str, data: TemplateRename, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if template_id == DEFAULT_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="通用模板不能重命名")
    from app.services.document_requirements import lock_templates, recheck_authority
    if db.get(Template, template_id) is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    lock_templates(db, template_id)
    recheck_authority(db, user.id)
    t = db.get(Template, template_id)
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    old = {"name": t.name, "description": t.description, "vehicle_type": t.vehicle_type}
    t.name = name
    if data.description is not None:
        t.description = data.description.strip()
    if "vehicle_type" in data.model_fields_set:
        t.vehicle_type = _vehicle_type(db, data.vehicle_type, t.id)
    log_change(db, None, "template", t.id, "update", user.id, f"修改模板「{t.name}」的名称、说明或车型", old, {"name": t.name, "description": t.description, "vehicle_type": t.vehicle_type})
    db.commit()
    return {"id": t.id, "name": t.name, "description": t.description, "vehicle_type": t.vehicle_type}


@router.post("/{template_id}/publish")
@route_permission('system.templates.manage')
def publish_template(template_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.document_requirements import lock_templates, recheck_authority
    lock_templates(db, template_id)
    recheck_authority(db, user.id)
    # 发布：保存当前树为新版本（version+1, status=published）。已生成项目不受影响（任务快照），新项目用新版本。
    if template_id == DEFAULT_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="通用模板始终为已发布状态")
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    new_version = (t.version or 1) + 1
    t.version = new_version
    t.status = "published"
    # C2-3：发布时生成完整版本快照（阶段/模块/任务/检查项/参考文档 JSON），保留最近 10 版
    from app.services.template_items import tree
    snapshot = tree(db, template_id)
    from app.services.document_requirements import list_requirements
    from app.services.vehicle_progress import template_steps
    snapshots = list(t.snapshots or [])
    snapshots.append({
        "version": new_version,
        "at": utcnow().isoformat(),
        "by": user.id,
        "snapshot": snapshot,
        "document_requirements": list_requirements(db, template_id),
        "vehicle_steps": [{"key":r.key,"name":r.name} for r in template_steps(db, template_id)],
    })
    t.snapshots = snapshots[-10:]
    db.flush()
    # C2-4：发布补审计
    log_change(db, None, "template", template_id, "publish", user.id,
               f"发布模板「{t.name}」v{new_version}（快照已存档）",
               {"version": new_version - 1}, {"version": new_version})
    db.commit()
    return {"message": f"已发布 v{new_version}", "version": new_version}


def _remove_template(db: Session, t: Template, user: User):
    """Delete a non-default template's own rows; projects keep their frozen copies."""
    from app.services.document_requirements import clear_requirements
    template_id = t.id
    from app.services.template_items import clear_content
    clear_content(db, template_id)
    clear_requirements(db, template_id)
    _delete_tree(db, template_id)
    from app.models import TemplateProcurementItem
    db.query(TemplatePreparationItem).filter_by(template_id=template_id).delete()
    db.query(TemplateProcurementItem).filter_by(template_id=template_id).delete()
    from app.models import VehicleStep
    db.query(VehicleStep).filter_by(template_id=template_id).delete()
    db.delete(t)


@router.delete("/{template_id}")
@route_permission('system.templates.manage')
def delete_template(template_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if template_id == DEFAULT_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="通用模板不能删除")
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    from app.services.document_requirements import lock_templates, recheck_authority
    lock_templates(db, template_id)
    recheck_authority(db, user.id)
    log_change(db, None, "template", template_id, "delete", user.id, f"删除模板「{t.name}」")
    _remove_template(db, t, user)
    db.commit()
    return {"message": "模板已删除"}


# ===== Tree copy/delete =====


def _delete_tree(db: Session, template_id: Optional[str]):
    # 先收集任务 id 级联清理参考文档（TemplateDoc 无外键级联）
    task_ids = [tid for (tid,) in db.query(Task.id).filter(
        Task.template_id == template_id, Task.project_id.is_(None)).all()]
    if task_ids:
        db.query(TemplateDoc).filter(TemplateDoc.task_id.in_(task_ids)).delete()
    db.query(CheckItem).filter(CheckItem.template_id == template_id, CheckItem.project_id.is_(None)).delete()
    db.query(Task).filter(Task.template_id == template_id, Task.project_id.is_(None)).delete()
    db.query(Module).filter(Module.template_id == template_id, Module.project_id.is_(None)).delete()
    db.query(Phase).filter(Phase.template_id == template_id, Phase.project_id.is_(None)).delete()


def _tid(template_id: str):
    return None if template_id == DEFAULT_TEMPLATE_ID else template_id


# ===== Tree read =====

# 全局默认模板（模板中心前端调用 /templates/tree 与 /templates/export/json，无 template_id）


@router.get("/{template_id}/procurements")
@route_permission('system.templates.read')
def list_template_procurements(template_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """常用采购项库（default = 系统默认模板）。"""
    from app.models import TemplateProcurementItem as _TPI
    tid = _tid(template_id)
    rows = db.query(_TPI).filter(_TPI.template_id == tid).order_by(_TPI.sort_order).all()
    return [
        {
            "id": t.id, "name": t.name, "unit": t.unit,
            "spec": t.spec, "is_required": t.is_required, "risk": t.risk,
        }
        for t in rows
    ]


from fastapi import UploadFile, File, Form as FastForm
from starlette.responses import FileResponse
from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE
import os as _os
from app.models import TemplateDoc as _TDoc


def _doc_dict(d: _TDoc) -> dict:
    return {
        "id": d.id, "task_id": d.task_id, "filename": d.filename, "file_size": d.file_size,
        "content_type": d.content_type, "note": d.note,
        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
    }


def _check_template_task(db, template_id: str, task_id: str) -> _TDoc.__mro__[0]:
    """校验模板任务存在（默认模板或指定模板的任务）。"""
    tid = _tid(template_id)
    t = db.get(Task, task_id)
    if t is None or t.project_id is not None or t.template_id != tid:
        raise HTTPException(status_code=404, detail="模板任务不存在")
    return t


@router.get("/{template_id}/tasks/{task_id}/reference-docs")
@route_permission('system.templates.read')
def list_template_task_docs(template_id: str, task_id: str,
                            user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """模板任务参考文档列表（模板中心对所有登录用户可见）。"""
    _check_template_task(db, template_id, task_id)
    docs = db.query(_TDoc).filter(_TDoc.task_id == task_id).order_by(_TDoc.uploaded_at).all()
    return [_doc_dict(d) for d in docs]


@router.post("/{template_id}/tasks/{task_id}/reference-docs")
@route_permission('system.templates.manage')
async def upload_template_task_doc(template_id: str, task_id: str,
                                   file: UploadFile = File(...), note: str = FastForm(default=""),
                                   user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """模板任务上传参考文档（写=require_admin + 审计）。"""
    t = _check_template_task(db, template_id, task_id)
    from app.services.upload_safety import read_upload_limited
    data = await read_upload_limited(file, MAX_UPLOAD_SIZE)
    stored = f"{uuid4().hex}{_os.path.splitext(file.filename or '')[-1]}"
    path = UPLOAD_DIR / stored
    try:
        with open(UPLOAD_DIR / stored, "wb") as f:
            f.write(data)
        d = _TDoc(template_id=_tid(template_id), task_id=task_id, filename=file.filename or stored,
                  stored_name=stored, file_size=len(data), content_type=file.content_type or "",
                  note=note[:300], uploaded_by=user.id)
        db.add(d)
        db.flush()
        log_change(db, None, "template", template_id, "update", user.id,
                   f"模板任务「{t.name}」添加参考文档：{d.filename}")
        db.commit()
    except Exception:
        db.rollback()
        try:
            path.unlink(missing_ok=True)
        except OSError:
            import logging
            logging.getLogger(__name__).warning("Uncommitted template file cleanup deferred")
        raise
    return _doc_dict(d)


@router.delete("/{template_id}/tasks/{task_id}/reference-docs/{doc_id}")
@route_permission('system.templates.manage')
def delete_template_task_doc(template_id: str, task_id: str, doc_id: str,
                             user: User = Depends(require_admin), db: Session = Depends(get_db)):
    """删除模板任务参考文档（含物理文件）。"""
    _check_template_task(db, template_id, task_id)
    d = db.get(_TDoc, doc_id)
    if d is None or d.task_id != task_id:
        raise HTTPException(status_code=404, detail="参考文档不存在")
    fname = d.filename
    path = UPLOAD_DIR / d.stored_name
    from app.models import DocumentTemplateFile
    retained = db.query(DocumentTemplateFile.id).filter_by(stored_name=d.stored_name).first() is not None
    db.delete(d)
    db.flush()
    log_change(db, None, "template", template_id, "update", user.id, f"模板任务参考文档删除：{fname}")
    db.commit()
    # A failed database/audit commit must leave the referenced file readable.
    # Physical cleanup follows successful logical deletion; an orphan is safer
    # than an existing reference to a destroyed file and can be swept later.
    try:
        if not retained:
            path.unlink(missing_ok=True)
    except OSError:
        import logging
        logging.getLogger(__name__).warning("Template reference cleanup deferred: %s", doc_id)
    return {"message": "已删除"}


@router.get("/{template_id}/tasks/{task_id}/reference-docs/{doc_id}/download")
@route_permission('system.templates.read')
def download_template_task_doc(template_id: str, task_id: str, doc_id: str,
                               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """下载模板任务参考文档。"""
    _check_template_task(db, template_id, task_id)
    d = db.get(_TDoc, doc_id)
    if d is None or d.task_id != task_id:
        raise HTTPException(status_code=404, detail="参考文档不存在")
    path = UPLOAD_DIR / d.stored_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="参考文档文件已丢失")
    return FileResponse(path=str(path), filename=d.filename, media_type=d.content_type or "application/octet-stream")
