"""Template library: multiple templates (system default + user templates).

Each template is a 4-level tree (phases → modules → tasks → check items)
identified by template_id. The system default template (template_id NULL)
is seeded at startup; users can copy it, rename, edit, and create new ones.
Projects generate tasks from a chosen template.
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
        "name": "系统默认模板",
        "description": "标准 AGV 实施方案；可按现场需求选择工作范围与设备对接",
        "version": 1,
        "status": "published",
        "usage_count": 0,
        "is_system": True,
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
            "version": t.version or 1,
            "status": t.status or "draft",
            "usage_count": db.query(_P).filter(_P.template_id == t.id).count(),
        })
    return result


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    copy_from: Optional[str] = None


@router.post("")
@route_permission('system.templates.manage')
def create_template(data: TemplateCreate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if data.copy_from and data.copy_from != DEFAULT_TEMPLATE_ID and db.get(Template, data.copy_from) is None:
        raise HTTPException(status_code=404, detail="来源模板不存在，请刷新后重试")
    t = Template(name=data.name, description=data.description, is_system=False)
    db.add(t)
    db.flush()
    src = data.copy_from or DEFAULT_TEMPLATE_ID
    copy_tree(db, src, t.id, actor=user)
    db.flush()
    # C2-4：复制模板补审计
    log_change(db, None, "template", t.id, "create", user.id,
               f"创建模板「{t.name}」（从{'系统默认模板' if src == DEFAULT_TEMPLATE_ID else src}复制）")
    db.commit()
    return {"id": t.id, "name": t.name}


@router.put("/{template_id}")
@route_permission('system.templates.manage')
def rename_template(template_id: str, data: TemplateCreate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if template_id == DEFAULT_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="系统默认模板不能重命名")
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    t.name = data.name
    if data.description:
        t.description = data.description
    db.commit()
    return {"id": t.id, "name": t.name}


@router.post("/{template_id}/publish")
@route_permission('system.templates.manage')
def publish_template(template_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.services.document_requirements import lock_templates, recheck_authority
    lock_templates(db, template_id)
    recheck_authority(db, user.id)
    # 发布：保存当前树为新版本（version+1, status=published）。已生成项目不受影响（任务快照），新项目用新版本。
    if template_id == DEFAULT_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="系统默认模板始终为已发布状态")
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    new_version = (t.version or 1) + 1
    t.version = new_version
    t.status = "published"
    # C2-3：发布时生成完整版本快照（阶段/模块/任务/检查项/参考文档 JSON），保留最近 10 版
    snapshot = get_template_tree(template_id, user, db)
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


@router.delete("/{template_id}")
@route_permission('system.templates.manage')
def delete_template(template_id: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if template_id == DEFAULT_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="系统默认模板不能删除")
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    from app.services.document_requirements import clear_requirements, lock_templates, recheck_authority
    lock_templates(db, template_id)
    recheck_authority(db, user.id)
    clear_requirements(db, template_id)
    _delete_tree(db, template_id)
    from app.models import TemplateProcurementItem
    db.query(TemplatePreparationItem).filter_by(template_id=template_id).delete()
    db.query(TemplateProcurementItem).filter_by(template_id=template_id).delete()
    log_change(db, None, "template", template_id, "delete", user.id, f"删除模板「{t.name}」")
    from app.models import VehicleStep
    db.query(VehicleStep).filter_by(template_id=template_id).delete()
    db.delete(t)
    db.commit()
    return {"message": "模板已删除"}


# ===== Tree copy/delete =====

def copy_tree(db: Session, src_template_id: str, dst_template_id: Optional[str], actor=None):
    from app.services.document_requirements import lock_templates, recheck_authority, track_new_file
    lock_templates(db, src_template_id, dst_template_id)
    if actor is not None:
        recheck_authority(db, actor.id)
    from app.models import TemplatePreparationItem as _TPI
    _delete_tree(db, dst_template_id)
    from app.services.document_requirements import clear_requirements, copy_requirements
    clear_requirements(db, dst_template_id)
    copy_requirements(db, src_template_id, dst_template_id)
    from app.services.vehicle_progress import copy_template_steps
    copy_template_steps(db, src_template_id, dst_template_id)
    # 复制模板采购项
    from app.models import TemplateProcurementItem as _TProc
    db.query(_TPI).filter(_TPI.template_id == dst_template_id).delete()
    db.query(_TProc).filter(_TProc.template_id == dst_template_id).delete()
    src_tid_proc = None if src_template_id == "default" else src_template_id
    for tp in db.query(_TProc).filter(_TProc.template_id == src_tid_proc).all():
        db.add(_TProc(template_id=dst_template_id, name=tp.name, unit=tp.unit,
                      spec=tp.spec, is_required=tp.is_required, risk=tp.risk,
                      sort_order=tp.sort_order))
    db.flush()
    # Retired preparation requirements already travel as canonical legacy document rules.
    src_tid = None if src_template_id == DEFAULT_TEMPLATE_ID else src_template_id
    src_phases = db.query(Phase).filter(Phase.template_id == src_tid, Phase.project_id.is_(None)).order_by(Phase.sort_order).all()
    phase_map = {}
    for ph in src_phases:
        new_ph = Phase(project_id=None, template_id=dst_template_id, name=ph.name, sort_order=ph.sort_order,
                       color=ph.color, entry_criteria=ph.entry_criteria, exit_criteria=ph.exit_criteria, stage_key=ph.stage_key)
        db.add(new_ph)
        db.flush()
        phase_map[ph.id] = new_ph
        for m in db.query(Module).filter(Module.template_id == src_tid, Module.project_id.is_(None), Module.phase_id == ph.id).order_by(Module.sort_order).all():
            new_m = Module(project_id=None, template_id=dst_template_id, phase_id=new_ph.id, name=m.name,
                           category=m.category, is_selected=m.is_selected, sort_order=m.sort_order, description=m.description,
                           preparation_conditions=list(m.preparation_conditions or []))
            db.add(new_m)
            db.flush()
            for t in db.query(Task).filter(Task.template_id == src_tid, Task.project_id.is_(None), Task.module_id == m.id).order_by(Task.sort_order).all():
                new_t = Task(project_id=None, template_id=dst_template_id, module_id=new_m.id, phase_id=new_ph.id, group_label=t.group_label or m.name, scope_conditions=list(t.scope_conditions or m.preparation_conditions or []), legacy_work_snapshot=t.legacy_work_snapshot, name=t.name,
                             description=t.description, quantity_type=t.quantity_type, vehicle_step_key=t.vehicle_step_key, target_quantity=t.target_quantity,
                             unit=t.unit, standard_hours=t.standard_hours, safety_flag=t.safety_flag,
                             applicable_vehicle_types=t.applicable_vehicle_types,
                             deliverables=[], sort_order=t.sort_order)
                db.add(new_t)
                db.flush()
                for ci in db.query(CheckItem).filter(CheckItem.template_id == src_tid, CheckItem.project_id.is_(None), CheckItem.task_id == t.id).order_by(CheckItem.sort_order).all():
                    db.add(CheckItem(project_id=None, template_id=dst_template_id, task_id=new_t.id, name=ci.name,description=ci.description,
                                     is_safety_critical=ci.is_safety_critical, is_required=ci.is_required, sort_order=ci.sort_order))
                # C2-8：复制模板任务参考文档（TemplateDoc 行 + 物理文件独立副本，删除源模板不影响副本）
                for sd in db.query(TemplateDoc).filter(TemplateDoc.task_id == t.id).all():
                    new_stored = sd.stored_name
                    src_path = UPLOAD_DIR / sd.stored_name
                    if src_path.exists():
                        new_stored = f"{uuid4().hex}{os.path.splitext(sd.filename or '')[-1]}"
                        destination = UPLOAD_DIR / new_stored
                        if src_path.is_symlink() or src_path.resolve().parent != UPLOAD_DIR.resolve() or destination.parent.resolve() != UPLOAD_DIR.resolve() or destination.exists():
                            raise HTTPException(409, "来源参考文档路径无效，复制已取消")
                        track_new_file(db, destination)
                        shutil.copy2(src_path, destination)
                    db.add(TemplateDoc(template_id=dst_template_id, task_id=new_t.id, filename=sd.filename,
                                       stored_name=new_stored, file_size=sd.file_size,
                                       content_type=sd.content_type, note=sd.note))

    for t in db.query(Task).filter(Task.project_id.is_(None),Task.template_id==src_tid,Task.module_id.is_(None)).order_by(Task.sort_order):
        if t.phase_id not in phase_map:continue
        new_t=Task(template_id=dst_template_id,phase_id=phase_map[t.phase_id].id,module_id=None,
            **{k:getattr(t,k) for k in ('name','description','quantity_type','target_quantity','unit','standard_hours','safety_flag','applicable_vehicle_types','sort_order','vehicle_step_key','group_label','scope_conditions','legacy_work_snapshot')})
        db.add(new_t);db.flush()
        for ci in db.query(CheckItem).filter_by(task_id=t.id,project_id=None):
            db.add(CheckItem(task_id=new_t.id,template_id=dst_template_id,name=ci.name,description=ci.description,
                is_required=ci.is_required,is_safety_critical=ci.is_safety_critical,sort_order=ci.sort_order))
        for sd in db.query(TemplateDoc).filter_by(task_id=t.id):
            src_path=UPLOAD_DIR/sd.stored_name;stored=sd.stored_name
            if src_path.is_file():
                stored=f"{uuid4().hex}{os.path.splitext(sd.filename or '')[-1]}";destination=UPLOAD_DIR/stored
                if src_path.is_symlink() or src_path.resolve().parent!=UPLOAD_DIR.resolve() or destination.exists():raise HTTPException(409,'来源参考文档路径无效')
                track_new_file(db,destination);shutil.copy2(src_path,destination)
            db.add(TemplateDoc(template_id=dst_template_id,task_id=new_t.id,filename=sd.filename,stored_name=stored,
                file_size=sd.file_size,content_type=sd.content_type,note=sd.note))


def _flat_source_envelopes(db,tid,phase_id,existing_ids=(),*,full_refs=False):
    from app.services.work_items import portable_definition
    grouped={}
    rows=db.query(Task).filter(Task.template_id==tid,Task.project_id.is_(None),Task.phase_id==phase_id).order_by(Task.sort_order,Task.id)
    for task in rows:
        if task.id in existing_ids:continue
        data=portable_definition(db,task);data['id']=task.id
        data['check_items']=[{'id':c.id,'name':c.name,'description':c.description or '','is_required':c.is_required,'is_safety_critical':c.is_safety_critical,'sort_order':c.sort_order} for c in db.query(CheckItem).filter_by(task_id=task.id)]
        data['ref_docs']=[{k:getattr(d,k) for k in (('id','filename','stored_name','file_size','content_type','note','uploaded_by','uploaded_at') if full_refs else ('id','filename','note'))} for d in db.query(TemplateDoc).filter_by(task_id=task.id)]
        label=task.group_label or '工作项'
        envelope=grouped.setdefault(label,{'id':None,'name':label,'category':'core','is_selected':True,'sort_order':task.sort_order or 0,'description':'','preparation_conditions':task.scope_conditions or [],'tasks':[]})
        envelope['tasks'].append(data)
    return list(grouped.values())


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
@router.get("/tree")
@route_permission('system.templates.read')
def get_default_template_tree(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_template_tree(DEFAULT_TEMPLATE_ID, user, db)


@router.get("/export/json")
@route_permission('system.templates.read')
def export_default_template_json(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.document_requirements import export_bundle
    return {"phases": get_template_tree(DEFAULT_TEMPLATE_ID, user, db), "vehicle_steps":[{"key":r.key,"name":r.name} for r in _vehicle_template_steps(db,DEFAULT_TEMPLATE_ID)], **export_bundle(db, DEFAULT_TEMPLATE_ID)}


@router.get("/{template_id}/tree")
@route_permission('system.templates.read')
def get_template_tree(template_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tid = _tid(template_id)
    phases = db.query(Phase).filter(Phase.template_id == tid, Phase.project_id.is_(None)).order_by(Phase.sort_order).all()
    # Load each level once. A full default template previously made 271 business queries.
    from collections import defaultdict
    modules_by_phase, tasks_by_module, checks_by_task, docs_by_task = (defaultdict(list) for _ in range(4))
    for module in db.query(Module).filter(Module.template_id == tid, Module.project_id.is_(None)).order_by(Module.sort_order).all():
        modules_by_phase[module.phase_id].append(module)
    template_tasks = db.query(Task).filter(Task.template_id == tid, Task.project_id.is_(None)).order_by(Task.sort_order).all()
    for task in template_tasks:
        tasks_by_module[task.module_id].append(task)
    for check in db.query(CheckItem).filter(CheckItem.template_id == tid, CheckItem.project_id.is_(None)).order_by(CheckItem.sort_order).all():
        checks_by_task[check.task_id].append(check)
    for doc in db.query(TemplateDoc).filter(TemplateDoc.task_id.in_([task.id for task in template_tasks])).all():
        docs_by_task[doc.task_id].append(doc)
    preparations_by_name = {}
    for prep in db.query(TemplatePreparationItem).filter(TemplatePreparationItem.template_id == tid).all():
        preparations_by_name.setdefault(prep.name, prep)
    result = []
    for ph in phases:
        # C2-2：不再排除「项目准备」阶段——模板编辑器完整展示 9 阶段，
        # 前端保存整棵返回树即包含项目准备，避免保存即销毁。
        mod_list = []
        for m in modules_by_phase[ph.id]:
            task_list = []
            for t in tasks_by_module[m.id]:
                items = checks_by_task[t.id]
                _tpi = preparations_by_name.get(t.name)
                _refs = docs_by_task[t.id]
                task_list.append({
                    "ref_docs": [{"id": d.id, "filename": d.filename} for d in _refs],
                    "id": t.id, "name": t.name, "description": t.description,
                    "quantity_type": t.quantity_type, "vehicle_step_key": t.vehicle_step_key, "target_quantity": t.target_quantity,
                    "unit": t.unit, "standard_hours": t.standard_hours,
                        "group_label": t.group_label, "scope_conditions": t.scope_conditions, "legacy_work_snapshot": t.legacy_work_snapshot, "sort_order": t.sort_order,
                    "safety_flag": t.safety_flag, "applicable_vehicle_types": t.applicable_vehicle_types or [],
                    "check_items": [{"id": c.id, "name": c.name, "description": c.description or "", "is_required": c.is_required, "is_safety_critical": c.is_safety_critical, "sort_order": c.sort_order} for c in items],
                })
            # C2-5：模块标注 prep_only（「项目准备」阶段模块仅生成准备项），供前端向导明确展示
            mod_list.append({"id": m.id, "name": m.name, "category": m.category, "is_selected": m.is_selected,
                             "sort_order": m.sort_order, "description": m.description,
                "preparation_conditions": m.preparation_conditions or [], "tasks": task_list,
                             "prep_only": ph.name in REMINDER_ONLY_PHASE_NAMES})
        result.append({"id": ph.id, "name": ph.name, "sort_order": ph.sort_order, "color": ph.color, "stage_key": ph.stage_key,
                       "entry_criteria": ph.entry_criteria, "exit_criteria": ph.exit_criteria, "modules": mod_list})
    from app.services.work_items import item_dicts
    phase_tasks = defaultdict(list)
    for task in sorted((t for t in template_tasks if t.phase_id), key=lambda t: (t.sort_order is not None, t.sort_order or 0, t.id)):
        phase_tasks[task.phase_id].append(task)
    items = item_dicts(db, [t for rows in phase_tasks.values() for t in rows], checks=True)
    for phase in result:
        existing={t['id'] for m in phase['modules'] for t in m['tasks']}
        if any(t.id not in existing for t in phase_tasks[phase['id']]):
            phase['modules'] += _flat_source_envelopes(db,tid,phase['id'],existing)
        phase['work_items']=[items[t.id] for t in phase_tasks[phase['id']]]
    return result


# ===== Tree edit (full replace) =====

class CheckItemIn(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    is_required: bool = True
    is_safety_critical: bool = False
    sort_order: int = 0


class TaskIn(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    quantity_type: str = Field(default="per_vehicle", pattern="^(per_vehicle|manual|fixed)$")
    target_quantity: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    unit: str = "台"
    safety_flag: bool = False
    applicable_vehicle_types: list = []
    deliverables: list = []  # 提交文件要求：[{name}]——项目生成后为任务交付物
    prep_owner_party: Optional[str] = Field(default=None, pattern="^(project|client|procurement|production|software|company)$")
    prep_blocks_entry: Optional[bool] = None
    prep_risk: Optional[str] = Field(default=None, pattern="^(low|medium|high)$")
    prep_condition: Optional[str] = Field(default=None, pattern="^(default|need_wms|need_charging|client_server|new_vehicles|overseas)$")
    sort_order: int = 0
    vehicle_step_key: Optional[str] = Field(default=None, max_length=80)
    group_label: Optional[str] = Field(default=None, max_length=200)
    scope_conditions: Optional[list[str]] = None
    legacy_work_snapshot: Optional[dict] = None
    check_items: list[CheckItemIn] = []


class ModuleIn(BaseModel):
    id: Optional[str] = None
    is_selected: Optional[bool] = None
    description: str = ""
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="core", pattern="^(core|extra)$")
    sort_order: int = 0
    preparation_conditions: Optional[list[Literal["need_wms", "need_charging"]]] = Field(default=None, max_length=2)
    tasks: list[TaskIn] = []


class PhaseIn(BaseModel):
    id: Optional[str] = None
    entry_criteria: str = ""
    exit_criteria: str = ""
    name: str = Field(..., min_length=1, max_length=100)
    sort_order: int = 0
    color: str = "#1890ff"
    stage_key: Optional[Literal['4', '5', '6', '7', '8', '9']] = None
    modules: list[ModuleIn] = []


class TemplateUpdate(BaseModel):
    phases: list[PhaseIn]
    replace_missing_phases: bool = False
    document_requirements: Optional[list[dict]] = None
    vehicle_steps: Optional[list[dict]] = None
    document_template_files: dict = Field(default_factory=dict)


def _capture_phase_subtree(db: Session, tid, phase_id: str):
    """C2-2：保存模板树前捕获指定阶段完整子树（含参考文档与准备属性），
    供整树替换后回填——防止前端保存载荷缺该阶段时把用户数据销毁。"""
    ph = db.query(Phase).filter(Phase.template_id == tid, Phase.project_id.is_(None), Phase.id == phase_id).first()
    if ph is None:
        return None
    return {
        "id": ph.id, "name": ph.name, "sort_order": ph.sort_order, "color": ph.color, "stage_key": ph.stage_key,
        "entry_criteria": ph.entry_criteria, "exit_criteria": ph.exit_criteria,
        "modules": [
            {
                "id": m.id, "name": m.name, "category": m.category, "is_selected": m.is_selected,
                "sort_order": m.sort_order, "description": m.description,
                "preparation_conditions": m.preparation_conditions or [],
                "tasks": [
                    {
                        "id": t.id, "name": t.name, "description": t.description,
                        "quantity_type": t.quantity_type, "vehicle_step_key": t.vehicle_step_key, "target_quantity": t.target_quantity,
                        "unit": t.unit, "standard_hours": t.standard_hours,
                        "group_label": t.group_label, "scope_conditions": t.scope_conditions, "legacy_work_snapshot": t.legacy_work_snapshot,
                        "safety_flag": t.safety_flag,
                        "applicable_vehicle_types": t.applicable_vehicle_types or [],
                        "sort_order": t.sort_order,
                        "prep_owner_party": None, "prep_blocks_entry": None,
                        "prep_risk": None, "prep_condition": None,
                        "check_items": [
                            {"id": c.id, "name": c.name, "description": c.description or "", "is_required": c.is_required,
                             "is_safety_critical": c.is_safety_critical, "sort_order": c.sort_order}
                            for c in db.query(CheckItem).filter(
                                CheckItem.template_id == tid, CheckItem.project_id.is_(None),
                                CheckItem.task_id == t.id).order_by(CheckItem.sort_order).all()
                        ],
                        "ref_docs": [
                            {"id": d.id, "filename": d.filename, "stored_name": d.stored_name,
                             "file_size": d.file_size, "content_type": d.content_type, "note": d.note,
                             "uploaded_by": d.uploaded_by, "uploaded_at": d.uploaded_at}
                            for d in db.query(TemplateDoc).filter(TemplateDoc.task_id == t.id).all()
                        ],
                    }
                    for t in db.query(Task).filter(
                        Task.template_id == tid, Task.project_id.is_(None),
                        Task.module_id == m.id).order_by(Task.sort_order).all()
                ],
            }
            for m in db.query(Module).filter(
                Module.template_id == tid, Module.project_id.is_(None),
                Module.phase_id == ph.id).order_by(Module.sort_order).all()
        ],
    }


def _capture_all_phases(db: Session, tid):
    """C2-2：保存模板树前捕获模板当前全部阶段子树（含参考文档与准备属性），
    供整树替换后回填——提交载荷缺任意阶段时都不会把该阶段用户数据销毁。"""
    phases = db.query(Phase).filter(
        Phase.template_id == tid, Phase.project_id.is_(None)
    ).order_by(Phase.sort_order).all()
    captures={ph.id:_capture_phase_subtree(db,tid,ph.id) for ph in phases}
    for cap in captures.values():
        existing={t['id'] for m in cap['modules'] for t in m['tasks']}
        cap['modules'] += _flat_source_envelopes(db,tid,cap['id'],existing,full_refs=True)
    return captures


def _restore_phase_subtree(db: Session, tid, cap: dict, submitted_ids=frozenset()):
    """C2-2：把捕获的阶段子树重新写入模板（重建阶段/模块/任务/检查项/参考文档）。"""
    if not cap:
        return
    ph = Phase(id=cap["id"], project_id=None, template_id=tid, name=cap["name"], sort_order=cap["sort_order"],
               color=cap["color"], entry_criteria=cap.get("entry_criteria"), exit_criteria=cap.get("exit_criteria"), stage_key=cap.get("stage_key"))
    db.add(ph)
    db.flush()
    for mcap in cap["modules"]:
        if mcap["id"] in submitted_ids:
            continue
        m = Module(id=mcap["id"], project_id=None, template_id=tid, phase_id=ph.id, name=mcap["name"],
                   category=mcap["category"], is_selected=mcap["is_selected"],
                   sort_order=mcap["sort_order"], description=mcap.get("description"),
                   preparation_conditions=mcap.get("preparation_conditions", []))
        db.add(m)
        db.flush()
        for tcap in mcap["tasks"]:
            if tcap["id"] in submitted_ids:
                continue
            t = Task(id=tcap["id"], project_id=None, template_id=tid, module_id=m.id, phase_id=ph.id, group_label=tcap.get("group_label",m.name), scope_conditions=tcap.get("scope_conditions",m.preparation_conditions or []), name=tcap["name"],
                     description=tcap.get("description"), quantity_type=tcap["quantity_type"], vehicle_step_key=tcap.get("vehicle_step_key"),
                     target_quantity=tcap.get("target_quantity"), unit=tcap.get("unit") or "台",
                     legacy_work_snapshot=tcap.get("legacy_work_snapshot"), standard_hours=tcap.get("standard_hours"), safety_flag=tcap.get("safety_flag", False),
                     applicable_vehicle_types=tcap.get("applicable_vehicle_types") or [],
                     deliverables=[], sort_order=tcap["sort_order"])
            db.add(t)
            db.flush()
            for ci in tcap.get("check_items") or []:
                if ci["id"] in submitted_ids:
                    continue
                db.add(CheckItem(id=ci["id"], project_id=None, template_id=tid, task_id=t.id, name=ci["name"],description=ci.get("description",""),
                                 is_required=ci["is_required"], is_safety_critical=ci["is_safety_critical"],
                                 sort_order=ci["sort_order"]))
            for rd in tcap.get("ref_docs") or []:
                db.add(TemplateDoc(template_id=tid, task_id=t.id, **rd))


@router.put("/{template_id}/tree")
@route_permission('system.templates.manage')
def replace_template_tree(template_id: str, data: TemplateUpdate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _replace_template_tree(template_id, data, user, db, "system.templates.manage")


def _replace_template_tree(template_id, data, user, db, capability):
    if any(any(getattr(task,key) is not None for key in ("prep_owner_party","prep_blocks_entry","prep_risk","prep_condition")) for phase in data.phases for module in phase.modules for task in module.tasks):
        raise HTTPException(400,"旧准备属性已迁入资料要求，不能再写旧模板准备来源")
    if any(task.deliverables for phase in data.phases for module in phase.modules for task in module.tasks):
        raise HTTPException(400, "旧任务交付要求已并入资料要求，请先在资料要求中明确配置")
    from app.services.document_requirements import parse_bundle, replace_bundle
    try:
        documents = parse_bundle(data.model_dump())
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    from app.services.document_requirements import lock_templates, recheck_authority
    lock_templates(db, template_id)
    recheck_authority(db, user.id, capability)
    tid = _tid(template_id)
    if tid is not None and db.get(Template, template_id) is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    # 修改已发布模板 → 回到草稿（重新发布才产生新版本）
    if tid is not None:
        tpl = db.get(Template, template_id)
        if tpl and (tpl.status or "draft") == "published":
            tpl.status = "draft"
    # C2-2：保存前捕获模板全部阶段子树；提交载荷缺任意阶段 → 替换完成后原样回填，
    # 不再让整树删除销毁任何阶段（旧前端缓存 / 老版本导出 JSON 均安全）。
    # 编辑器提交的稳定 ID 保留来源关系；旧导入载荷无 ID 时仍可建立新工作。
    valid_ids = {model: {row.id for row in db.query(model).filter(model.template_id == tid, model.project_id.is_(None)).all()} for model in (Phase, Module, Task, CheckItem)}
    seen_ids = set()
    def retained_id(model, value):
        if not value or value.startswith('tmp-'):
            return None
        if value not in valid_ids[model] or value in seen_ids:
            raise HTTPException(400, '方案内容标识已失效或重复，请重新加载后保存')
        seen_ids.add(value)
        return value
    for ph in data.phases:
        ph.id = retained_id(Phase, ph.id)
        for mod in ph.modules:
            mod.id = retained_id(Module, mod.id)
            for task in mod.tasks:
                task.id = retained_id(Task, task.id)
                for check in task.check_items:
                    check.id = retained_id(CheckItem, check.id)
    old_module_conditions = {m.id: list(m.preparation_conditions or []) for m in db.query(Module).filter(Module.id.in_(valid_ids[Module])).all()}
    old_docs = {}
    for doc in db.query(TemplateDoc).filter(TemplateDoc.task_id.in_(valid_ids[Task])).all():
        old_docs.setdefault(doc.task_id, []).append({key: getattr(doc, key) for key in ('id', 'filename', 'stored_name', 'file_size', 'content_type', 'note', 'uploaded_by', 'uploaded_at')})
    old_work_sources={t.id:{k:getattr(t,k) for k in ("group_label","scope_conditions","legacy_work_snapshot")} for t in db.query(Task).filter(Task.template_id==tid,Task.project_id.is_(None))}
    old_step_keys = {t.id: t.vehicle_step_key for t in db.query(Task).filter(Task.template_id == tid, Task.project_id.is_(None))}
    preserved = _capture_all_phases(db, tid)
    submitted_legacy_names = {ph.name for ph in data.phases if ph.id is None}
    _delete_tree(db, tid)
    db.flush()
    for ph in data.phases:
        phase = Phase(id=ph.id, project_id=None, template_id=tid, name=ph.name, sort_order=ph.sort_order, color=ph.color, entry_criteria=ph.entry_criteria, exit_criteria=ph.exit_criteria, stage_key=ph.stage_key)
        db.add(phase)
        db.flush()
        for m in ph.modules:
            module = Module(id=m.id, project_id=None, template_id=tid, phase_id=phase.id, name=m.name, description=m.description,
                            category=m.category, sort_order=m.sort_order, is_selected=m.is_selected if m.is_selected is not None else (m.category == "core"),
                            preparation_conditions=m.preparation_conditions if m.preparation_conditions is not None else old_module_conditions.get(m.id, []))
            db.add(module)
            db.flush()
            for t in m.tasks:
                task = Task(id=t.id, project_id=None, template_id=tid, module_id=module.id, phase_id=phase.id, group_label=t.group_label if t.group_label is not None else old_work_sources.get(t.id,{}).get("group_label",m.name), scope_conditions=t.scope_conditions if t.scope_conditions is not None else old_work_sources.get(t.id,{}).get("scope_conditions",module.preparation_conditions or []), legacy_work_snapshot=old_work_sources.get(t.id,{}).get("legacy_work_snapshot",t.legacy_work_snapshot), name=t.name,
                            description=t.description, quantity_type=t.quantity_type,
                            vehicle_step_key=t.vehicle_step_key if "vehicle_step_key" in t.model_fields_set else old_step_keys.get(t.id),
                            target_quantity=t.target_quantity, unit=t.unit, standard_hours=None,
                            safety_flag=t.safety_flag, applicable_vehicle_types=t.applicable_vehicle_types,
                            deliverables=[], sort_order=t.sort_order)
                from app.services.vehicle_checks import validate_step
                task.vehicle_step_key = validate_step(db, task, task.vehicle_step_key)
                db.add(task)
                db.flush()
                for doc in old_docs.get(t.id, []):
                    db.add(TemplateDoc(template_id=tid, task_id=task.id, **doc))
                for ci in t.check_items:
                    db.add(CheckItem(id=ci.id, project_id=None, template_id=tid, task_id=task.id, name=ci.name,description=ci.description,
                                     is_required=ci.is_required, is_safety_critical=ci.is_safety_critical, sort_order=ci.sort_order))
    # 提交载荷缺的阶段 → 回填保留副本（含项目准备）
    restored = []
    for phase_id, cap in preserved.items():
        if (not data.replace_missing_phases and phase_id not in seen_ids
                and cap["name"] not in submitted_legacy_names):
            _restore_phase_subtree(db, tid, cap, seen_ids)
            restored.append(cap["name"])
    db.flush()
    # C2-4：保存树补审计
    tpl_name = "系统默认模板"
    if tid is not None:
        tpl = db.get(Template, template_id)
        if tpl:
            tpl_name = tpl.name
    restored_note = ""
    if restored:
        restored_note = f"（已保留缺省阶段：{'、'.join(restored)}）"
    log_change(db, None, "template", template_id, "update", user.id,
               f"保存模板树「{tpl_name}」：{len(data.phases)} 个阶段{restored_note}")
    if data.vehicle_steps is not None:
        from app.routers.vehicle_progress import StepList
        from app.models import VehicleStep
        from pydantic import ValidationError
        try:
            definitions=StepList(steps=data.vehicle_steps).steps
        except ValidationError:
            raise HTTPException(400,"车辆环节定义格式无效") from None
        if len({r.key for r in definitions})!=len(definitions) or any(not r.name.strip() for r in definitions):
            raise HTTPException(400,'车辆环节标识不能重复，名称不能为空')
        db.query(VehicleStep).filter_by(template_id=template_id).delete()
        for i,r in enumerate(definitions):
            db.add(VehicleStep(template_id=template_id,key=r.key,name=r.name.strip(),sort_order=i))
    replace_bundle(db, template_id, documents, user.id, capability)
    db.commit()
    return {"message": "模板已保存"}


@router.get("/{template_id}/export/json")
@route_permission('system.templates.read')
def export_template_json(template_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.document_requirements import export_bundle
    return {"phases": get_template_tree(template_id, user, db), "vehicle_steps": [{"key":r.key,"name":r.name} for r in _vehicle_template_steps(db,template_id)], **export_bundle(db, template_id)}


@router.post("/{template_id}/import/json")
@route_permission('system.template_io.manage')
def import_template_json(template_id: str, data: TemplateUpdate, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    # JSON 是可移植模板。源库/其他模板的 ID 不能写进目标模板，也不应被当成
    # 过期编辑会话拒绝；同一模板重导入仍保留现有身份与参考文档关联。
    from app.services.document_requirements import lock_templates, recheck_authority
    lock_templates(db, template_id)
    recheck_authority(db, user.id, "system.template_io.manage")
    data = data.model_copy(deep=True)
    # Portable pre-T22 task/preparation requirements become unverified legacy
    # definitions. Ordinary editor PUTs continue to reject this retired source.
    from uuid import uuid5,NAMESPACE_URL
    import json
    from app.services.document_requirements import export_bundle
    converted=[]
    for pi,phase in enumerate(data.phases):
        for mi,module in enumerate(phase.modules):
            for ti,task in enumerate(module.tasks):
                original=task.model_dump()
                entries=[('task_deliverable',index,item) for index,item in enumerate(task.deliverables)]
                if task.prep_owner_party is not None or task.prep_risk is not None or task.prep_condition is not None or task.prep_blocks_entry is True:
                    entries.append(('preparation_task',0,{'name':task.name,'required':True}))
                for kind,index,item in entries:
                    if not isinstance(item,(dict,str)):raise HTTPException(400,'旧交付要求必须是名称或对象')
                    source={'kind':'portable_legacy_template','source_type':kind,'phase':{'id':phase.id,'name':phase.name,'sort_order':phase.sort_order},
                        'module':{'id':module.id,'name':module.name},'task':original,'index':index,'original':item}
                    code='legacy.'+uuid5(NAMESPACE_URL,json.dumps([pi,mi,ti,kind,index,source],ensure_ascii=False,sort_keys=True)).hex
                    converted.append({'stage_key':'legacy','code':code,'name':str(item.get('name') or '旧交付要求（未命名）')[:300] if isinstance(item,dict) else item[:300],
                        'required':item.get('required',True) if isinstance(item,dict) else True,'scope':'project','timing_type':'on_demand','source_metadata':source})
                task.deliverables=[]
                for key in ('prep_owner_party','prep_blocks_entry','prep_risk','prep_condition'):setattr(task,key,None)
    if converted:
        if data.document_requirements is None:
            bundle=export_bundle(db,template_id)
            data.document_requirements=bundle['document_requirements'];data.document_template_files=bundle['document_template_files']
        known={row.get('code') for row in data.document_requirements if isinstance(row.get('code'),str)}
        data.document_requirements += [row for row in converted if row['code'] not in known]
    tid = _tid(template_id)
    local_ids = {model: {row.id for row in db.query(model).filter(
        model.template_id == tid, model.project_id.is_(None)).all()}
        for model in (Phase, Module, Task, CheckItem)}
    for phase in data.phases:
        phase.id = phase.id if phase.id in local_ids[Phase] else None
        for module in phase.modules:
            module.id = module.id if module.id in local_ids[Module] else None
            for task in module.tasks:
                task.id = task.id if task.id in local_ids[Task] else None
                for check in task.check_items:
                    check.id = check.id if check.id in local_ids[CheckItem] else None
    _replace_template_tree(template_id, data, user, db, "system.template_io.manage")
    return {"message": "模板导入成功"}


# ===== 模板准备项（准备清单的模板定义：项目从模板生成准备项） =====

class TemplateProcItemBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    unit: str = Field(default="件", max_length=20)
    spec: str = Field(default="", max_length=300)
    is_required: bool = True
    risk: str = Field(default="low", pattern="^(low|medium|high)$")


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


@router.post("/{template_id}/procurements")
@route_permission('system.templates.manage')
def create_template_procurement(template_id: str, data: TemplateProcItemBody,
                                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import TemplateProcurementItem as _TPI
    tid = _tid(template_id)
    if tid is not None and db.get(Template, template_id) is None:
        raise HTTPException(status_code=404, detail="模板不存在")
    max_sort = db.query(_TPI).filter(_TPI.template_id == tid).count()
    t = _TPI(template_id=tid, sort_order=max_sort, **data.model_dump())
    db.add(t)
    db.flush()
    log_change(db, None, "template", template_id, "update", user.id,
               f"模板采购项添加：「{data.name}」{data.unit}")
    db.commit()
    return {"id": t.id, "name": t.name}


@router.put("/{template_id}/procurements/{item_id}")
@route_permission('system.templates.manage')
def update_template_procurement(template_id: str, item_id: str, data: TemplateProcItemBody,
                                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import TemplateProcurementItem as _TPI
    tid = _tid(template_id)
    t = db.get(_TPI, item_id)
    if t is None or t.template_id != tid:
        raise HTTPException(status_code=404, detail="模板采购项不存在")
    for f, v in data.model_dump().items():
        setattr(t, f, v)
    db.flush()
    log_change(db, None, "template", template_id, "update", user.id, f"模板采购项更新：「{t.name}」")
    db.commit()
    return {"id": t.id, "name": t.name}


@router.delete("/{template_id}/procurements/{item_id}")
@route_permission('system.templates.manage')
def delete_template_procurement(template_id: str, item_id: str,
                                user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import TemplateProcurementItem as _TPI
    tid = _tid(template_id)
    t = db.get(_TPI, item_id)
    if t is None or t.template_id != tid:
        raise HTTPException(status_code=404, detail="模板采购项不存在")
    name = t.name
    db.delete(t)
    db.flush()
    log_change(db, None, "template", template_id, "update", user.id, f"模板采购项删除：「{name}」")
    db.commit()
    return {"message": "已删除"}


# ===== 模板任务参考文档（任务执行要参考的资料；生成项目任务时复制物理文件） =====

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
    from app.services.project_retention import is_retained_file
    from app.models import DocumentTemplateFile
    retained = is_retained_file(db, d.stored_name) or db.query(DocumentTemplateFile.id).filter_by(stored_name=d.stored_name).first() is not None
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
