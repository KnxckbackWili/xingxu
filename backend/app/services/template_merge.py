"""Fold another template into the standard (default) template.

Only what the standard template lacks is added: work groups and work items by
name (with their checks and reference documents), document requirements by
code (with parent groups and blank forms), vehicle steps by key and procurement
items by name. Existing standard content is never overwritten; a work item that
exists in both keeps the union of its applicable vehicle types. Projects keep
their own frozen copies, so they are unaffected.
"""
import os
import shutil
from copy import deepcopy
from uuid import uuid4

from fastapi import HTTPException

from app.config import UPLOAD_DIR
from app.models import (CheckItem, DocumentRequirement, DocumentTemplateFile, Module, Phase, Task, TemplateDoc,
                        TemplateProcurementItem, VehicleStep)
from app.services.execution_scope import REMINDER_ONLY_PHASE_NAMES


def _copy_reference_docs(db, source_task, target_task_id):
    from app.services.document_requirements import track_new_file
    for doc in db.query(TemplateDoc).filter_by(task_id=source_task.id):
        stored = doc.stored_name
        source_path = UPLOAD_DIR / doc.stored_name
        if source_path.is_file():
            stored = f"{uuid4().hex}{os.path.splitext(doc.filename or '')[-1]}"
            destination = UPLOAD_DIR / stored
            if source_path.is_symlink() or source_path.resolve().parent != UPLOAD_DIR.resolve() or destination.exists():
                raise HTTPException(409, "来源参考文档路径无效，合并已取消")
            track_new_file(db, destination)
            shutil.copy2(source_path, destination)
        db.add(TemplateDoc(template_id=None, task_id=target_task_id, filename=doc.filename, stored_name=stored,
                           file_size=doc.file_size, content_type=doc.content_type, note=doc.note))


def _merge_work(db, source_id):
    added = 0
    target_phases = db.query(Phase).filter(Phase.template_id.is_(None), Phase.project_id.is_(None)).all()
    by_key = {(phase.name, phase.stage_key): phase for phase in target_phases}
    for phase in db.query(Phase).filter(Phase.template_id == source_id, Phase.project_id.is_(None)).order_by(Phase.sort_order):
        if phase.name in REMINDER_ONLY_PHASE_NAMES:
            continue
        target = by_key.get((phase.name, phase.stage_key))
        if target is None:
            target = Phase(project_id=None, template_id=None, name=phase.name, sort_order=phase.sort_order, color=phase.color,
                           entry_criteria=phase.entry_criteria, exit_criteria=phase.exit_criteria, stage_key=phase.stage_key)
            db.add(target)
            db.flush()
            by_key[(phase.name, phase.stage_key)] = target
        existing = {task.name: task for task in db.query(Task).filter(Task.template_id.is_(None), Task.project_id.is_(None), Task.phase_id == target.id)}
        for task in db.query(Task).filter(Task.template_id == source_id, Task.project_id.is_(None), Task.phase_id == phase.id).order_by(Task.sort_order, Task.id):
            same = existing.get(task.name)
            if same is not None:
                # "All vehicle types" (empty) already covers everything; otherwise widen to both.
                if same.applicable_vehicle_types and task.applicable_vehicle_types:
                    same.applicable_vehicle_types = sorted(set(same.applicable_vehicle_types) | set(task.applicable_vehicle_types))
                elif same.applicable_vehicle_types and not task.applicable_vehicle_types:
                    same.applicable_vehicle_types = []
                continue
            module = db.get(Module, task.module_id) if task.module_id else None
            copy = Task(project_id=None, template_id=None, phase_id=target.id, module_id=None,
                        group_label=task.group_label or (module.name if module else ''),
                        **{key: getattr(task, key) for key in ('name', 'description', 'quantity_type', 'target_quantity', 'unit', 'standard_hours',
                                                               'safety_flag', 'applicable_vehicle_types', 'sort_order', 'vehicle_step_key',
                                                               'scope_conditions', 'legacy_work_snapshot')})
            db.add(copy)
            db.flush()
            for check in db.query(CheckItem).filter_by(task_id=task.id, project_id=None).order_by(CheckItem.sort_order):
                db.add(CheckItem(project_id=None, template_id=None, task_id=copy.id, name=check.name, description=check.description,
                                 is_required=check.is_required, is_safety_critical=check.is_safety_critical, sort_order=check.sort_order))
            _copy_reference_docs(db, task, copy.id)
            existing[task.name] = copy
            added += 1
    return added


def _merge_documents(db, source_id):
    from app.services.document_requirements import FIELDS, create_file, read_asset
    present = {row.code for row in db.query(DocumentRequirement).filter_by(template_id=None)}
    source = db.query(DocumentRequirement).filter_by(template_id=source_id).order_by(DocumentRequirement.sort_order, DocumentRequirement.code).all()
    missing = [row for row in source if row.code not in present]
    ids, assets = {row.id: str(uuid4()) for row in missing}, {}
    for row in missing:
        if row.blank_file_id and row.blank_file_id not in assets:
            asset = db.get(DocumentTemplateFile, row.blank_file_id)
            if asset is None:
                raise HTTPException(409, "来源空白模板记录缺失，合并已取消")
            copied = create_file(db, read_asset(asset), asset.filename, asset.content_type, asset.uploaded_by)
            copied.uploaded_at = asset.uploaded_at
            assets[row.blank_file_id] = copied.id
        db.add(DocumentRequirement(id=ids[row.id], template_id=None, parent_id=None, blank_file_id=assets.get(row.blank_file_id),
                                   source_metadata=deepcopy(row.source_metadata), **{key: getattr(row, key) for key in FIELDS}))
    db.flush()
    by_code = {row.code: row.id for row in db.query(DocumentRequirement).filter_by(template_id=None)}
    source_codes = {row.id: row.code for row in source}
    for row in missing:
        if row.parent_id:
            # The parent may be a new copy or a group the standard template already had.
            db.get(DocumentRequirement, ids[row.id]).parent_id = ids.get(row.parent_id) or by_code.get(source_codes.get(row.parent_id))
    db.flush()
    return len(missing)


def _merge_steps_and_procurement(db, source_id):
    steps = {row.key for row in db.query(VehicleStep).filter_by(template_id='default')}
    count = len(steps)
    added_steps = 0
    for row in db.query(VehicleStep).filter_by(template_id=source_id).order_by(VehicleStep.sort_order):
        if row.key not in steps:
            db.add(VehicleStep(template_id='default', key=row.key, name=row.name, sort_order=count + added_steps))
            steps.add(row.key)
            added_steps += 1
    names = {row.name for row in db.query(TemplateProcurementItem).filter(TemplateProcurementItem.template_id.is_(None))}
    added_items = 0
    for row in db.query(TemplateProcurementItem).filter_by(template_id=source_id).order_by(TemplateProcurementItem.sort_order):
        if row.name not in names:
            db.add(TemplateProcurementItem(template_id=None, name=row.name, unit=row.unit, spec=row.spec, is_required=row.is_required,
                                           risk=row.risk, sort_order=row.sort_order))
            names.add(row.name)
            added_items += 1
    db.flush()
    return added_steps, added_items


def merge_into_default(db, source_id):
    """Add the source template's missing content to the standard template. Caller deletes the source."""
    from app.services.document_requirements import lock_templates
    lock_templates(db, source_id, 'default')
    work = _merge_work(db, source_id)
    documents = _merge_documents(db, source_id)
    steps, items = _merge_steps_and_procurement(db, source_id)
    return {'work_items': work, 'documents': documents, 'vehicle_steps': steps, 'procurement_items': items}
