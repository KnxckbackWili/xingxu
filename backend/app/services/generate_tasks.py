"""Auto task generation: copy selected modules from the global template
into a project, computing target quantities from vehicle configs."""

import os
from typing import Optional
from uuid import uuid4
from sqlalchemy.orm import Session
from app.models import Project, Vehicle, Phase, Module, Task, CheckItem
from app.config import UPLOAD_DIR
from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES


def _upload_dir():
    return UPLOAD_DIR


def sum_vehicle_quantity(db: Session, project_id: str, vehicle_types: list) -> int:
    """Sum vehicle quantities. Empty vehicle_types = all vehicles."""
    q = db.query(Vehicle).filter(Vehicle.project_id == project_id)
    if vehicle_types:
        q = q.filter(Vehicle.vehicle_type.in_(vehicle_types))
    return sum(v.quantity for v in q.all())


def copy_reference_docs(db: Session, template_task, project_task) -> bool:
    """模板任务参考文档 → 项目任务（物理文件复制，任务 JSON 自包含）。幂等：已有文档不重拷。"""
    if project_task.reference_docs:
        return False
    from app.models import TemplateDoc
    src_docs = db.query(TemplateDoc).filter(TemplateDoc.task_id == template_task.id).all()
    if not src_docs:
        return False
    refs = []
    for sd in src_docs:
        src_path = _upload_dir() / sd.stored_name
        if not src_path.exists():
            continue
        new_stored = f"{uuid4().hex}{os.path.splitext(sd.filename or '')[-1]}"
        import shutil
        destination = _upload_dir() / new_stored
        if "creation_copied_files" in db.info:
            db.info["creation_copied_files"].append(destination)
        shutil.copy2(src_path, destination)
        refs.append({
            "filename": sd.filename, "stored_name": new_stored,
            "file_size": sd.file_size, "content_type": sd.content_type,
            "note": sd.note,
        })
    if refs:
        project_task.reference_docs = refs
    return True


def selected_execution_module_ids(db: Session, module_ids: list[str], template_id: str) -> list[str]:
    """拒绝过期、其他模板或项目私有模块，不能悄悄只生成其中一部分。"""
    if not module_ids:
        return []
    tid = None if template_id == "default" else template_id
    rows = db.query(Module.id, Phase.name).join(Phase, Phase.id == Module.phase_id).filter(
        Module.project_id.is_(None), Module.template_id == tid, Module.id.in_(module_ids),
    ).all()
    if {row.id for row in rows} != set(module_ids):
        raise ValueError("所选模块已失效或不属于当前模板，请重新加载模板后再试")
    execution = {row.id for row in rows if row.name not in REMINDER_ONLY_PHASE_NAMES}
    return list(dict.fromkeys(mid for mid in module_ids if mid in execution))


def generate_tasks_for_modules(
    db: Session,
    project: Project,
    module_ids: list[str],
    template_id: str = "default",
    exclude_task_names: Optional[list] = None,
    task_quantities: Optional[dict] = None,
    exclude_task_ids: Optional[list[str]] = None,
) -> dict:
    """exclude_task_names: 不生成的任务名列表；task_quantities: {任务名: 数量} 覆盖。"""
    """Deep-copy tasks + check items of the given template modules into the project.

    Project modules reuse the template module's id (one row per project per module);
    tasks get fresh ids. Re-generation is idempotent per (project, module).
    """
    if task_quantities:
        raise ValueError('工作项不再维护目标数量，请关联真实车辆环节或维护工作完成状态')
    from app.services.work_items import selected_template_work,generate
    selected=selected_template_work(db,template_id,module_ids,exclude_task_ids,exclude_task_names)
    return generate(db,project,selected)


