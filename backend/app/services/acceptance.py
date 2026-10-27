"""Current acceptance evidence. Reading never rewrites historical records or status."""
import hashlib
import json
from datetime import timedelta
from collections import defaultdict

from app.models import AcceptanceRecord, CheckItem, Task, Vehicle, User, Project, ProjectDocument
from app.time_utils import utcnow



def _canonical_definition(value):
    """JSON numeric representations should not turn 1 into a new scope at 1.0."""
    if isinstance(value, dict):
        return {key: _canonical_definition(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_definition(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _document_definition(item):
    # Ordinary form saves may explicitly send empty text omitted by old rows.
    # Preserve meaningful whitespace/content; only absent/null/empty are equivalent.
    return {key: item.get(key) or '' for key in ('name', 'doc_type', 'description', 'note')}


def acceptance_scope_fingerprint(db, project_id):
    """Hash only execution/quality/delivery definitions, never execution evidence.

    IDs prevent newly created work from reusing an old signature. Sorting avoids
    incidental order changes; user/member, schedule, progress, notes and lifecycle
    changes are not a change of acceptance scope.
    """
    from app.services.progress import execution_tasks
    tasks = execution_tasks(db, project_id)
    # Refresh cached children after the caller's Project lock, just like readiness.
    ids = [task.id for task in tasks]
    tasks = db.query(Task).populate_existing().filter(Task.id.in_(ids)).order_by(Task.id).all() if ids else []
    checks = db.query(CheckItem).populate_existing().filter(CheckItem.task_id.in_(ids)).order_by(CheckItem.id).all() if ids else []
    requirements = []
    # Completion also requires documents attached to reminder-only tasks.
    all_tasks = db.query(Task).populate_existing().filter_by(project_id=project_id).order_by(Task.id).all()
    # T22 moves each original item without changing its business definition. Rebuild
    # the v1 input from immutable migration provenance so existing signatures remain
    # valid only when their original execution scope still matches.
    legacy=defaultdict(list)
    document_rows=db.query(ProjectDocument).populate_existing().filter_by(project_id=project_id).order_by(ProjectDocument.id).all()
    for document in document_rows:
        source=document.source_metadata or {}
        if source.get('kind')=='task_deliverable' and isinstance(source.get('task'),dict) and isinstance(source.get('index'),int):
            legacy[source['task'].get('id')].append((source['index'],source.get('original')))
    def task_deliveries(task):
        return [item for _,item in sorted(legacy[task.id],key=lambda item:item[0])] if task.id in legacy else task.deliverables or []
    required_deliveries = []
    for task in all_tasks:
        for value in task_deliveries(task):
            item = {"name": value} if isinstance(value, str) else value
            if isinstance(item, dict) and item.get("name") and item.get("required", True):
                required_deliveries.append({"task_id": task.id, **_document_definition(item)})
    for task in tasks:
        deliveries = []
        for value in task_deliveries(task):
            item = {'name': value} if isinstance(value, str) else value
            if isinstance(item, dict) and item.get('name') and item.get('required', True):
                deliveries.append(_document_definition(item))
        requirements.append({
            'id': task.id, 'name': task.name, 'description': task.description or '',
            'quantity_type': task.quantity_type, 'target_quantity': float(task.target_quantity or 0),
            'unit': task.unit or '', 'safety_flag': bool(task.safety_flag),
            'applicable_vehicle_types': sorted(task.applicable_vehicle_types or []),
            'deliverables': sorted(deliveries, key=lambda item: json.dumps(item, sort_keys=True)),
        })
    payload = {'version': 1, 'tasks': requirements,
               'required_deliveries': sorted(required_deliveries, key=lambda item: json.dumps(item, sort_keys=True)),
               'checks': [{'id': c.id, 'task_id': c.task_id, 'name': c.name,
                           'description': c.description or '', 'required': bool(c.is_required),
                           'safety': bool(c.is_safety_critical), 'applicable': bool(c.is_applicable)}
                          for c in checks if c.is_required or c.is_safety_critical],
               'vehicles': [{'id': v.id, 'type': v.vehicle_type, 'model': v.model_name,
                             'quantity': v.quantity, 'configuration': v.configuration or {}}
                            for v in db.query(Vehicle).populate_existing().filter_by(project_id=project_id).order_by(Vehicle.id)]}
    # T32's exact g30 legacy link is a redundant representation, not new scope.
    # New explicit links, definitions and real-unit obligations do alter scope.
    from app.models import ProjectVehicleStep, VehicleCheckDefinition
    legacy_links = {(r.source_task_id,r.key) for r in db.query(ProjectVehicleStep).filter_by(project_id=project_id) if r.source_task_id}
    links = [{'task_id':t.id,'step_key':t.vehicle_step_key} for t in tasks
             if t.vehicle_step_key and (t.id,t.vehicle_step_key) not in legacy_links]
    unit_checks = [{key:getattr(c,key) for key in ('id','vehicle_unit_id','vehicle_step_key','vehicle_check_definition_id','definition_version')}
                   for c in checks if c.vehicle_unit_id and (c.is_required or c.is_safety_critical)]
    legacy_check_ids = {c.id for c in checks if not c.vehicle_unit_id}
    definitions = [{key:getattr(d,key) for key in ('id','task_id','source_check_id','source_version','version','name','description','is_required','is_safety_critical')}
                   for d in db.query(VehicleCheckDefinition).filter(VehicleCheckDefinition.task_id.in_(ids)).order_by(VehicleCheckDefinition.id)
                   if d.source_check_id not in legacy_check_ids and (d.is_required or d.is_safety_critical)]
    if links or unit_checks or definitions:
        payload['vehicle_checks']={'links':links,'checks':unit_checks,'definitions':definitions}
    # Future archive/lifetime materials do not alter the acceptance-stage scope.
    # Frozen preparation/archive sources were not part of v1 acceptance scope.
    project=db.get(Project,project_id)
    canonical=[]
    for row in document_rows:
        source=row.source_metadata or {}
        if row.stage_key not in {'4','5','6','7'} or not row.required or source.get('kind') in {'preparation_item','archive_checklist'}:
            continue
        if row.platform and row.platform!=project.dispatch_platform:continue
        canonical.append({key:getattr(row,key) for key in ('id','definition_id','stage_key','code','name','template_no','scope','platform','timing_type','timing_event','timing_offset_hours','timing_weekday','trigger_type','vehicle_unit_id','period_key','trigger_ref','note')})
    if canonical:
        payload['version']=2
        payload['project_documents']=canonical
    return hashlib.sha256(json.dumps(_canonical_definition(payload), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def acceptance_records(db, project_id):
    """Effective date wins; same-day corrections use recorded chronology then ID."""
    return db.query(AcceptanceRecord).populate_existing().filter_by(project_id=project_id).order_by(
        AcceptanceRecord.accepted_at.desc(), AcceptanceRecord.created_at.desc().nullslast(), AcceptanceRecord.id.desc()).all()


def next_acceptance_recorded_at(db, project_id):
    """Project lock serializes new rows; preserve order even if the clock ties/regresses."""
    previous = db.query(AcceptanceRecord.created_at).filter_by(project_id=project_id).order_by(
        AcceptanceRecord.created_at.desc().nullslast()).first()
    now = utcnow()
    return max(now, previous[0] + timedelta(microseconds=1)) if previous and previous[0] else now


def acceptance_dict(db, record, *, latest_id, fingerprint, today):
    creator = db.get(User, record.created_by) if record.created_by else None
    return {
        'id': record.id, 'project_id': record.project_id, 'accepted_by': record.accepted_by,
        'accepted_by_name': record.accepted_by_name, 'accepted_at': record.accepted_at.isoformat(),
        'conclusion': record.conclusion, 'notes': record.notes, 'attachment_id': record.attachment_id,
        'creator_name': creator.display_name if creator else '',
        'created_at': record.created_at.isoformat() if record.created_at else None,
        'is_effective': record.id == latest_id,
        'effective_date_reached': record.accepted_at <= today,
        'invalid_reason': '' if record.accepted_at <= today else '历史验收日期晚于项目当地今天，暂不作为有效验收依据',
        'scope_verified': bool(record.scope_fingerprint),
        'scope_current': bool(record.scope_fingerprint) and record.scope_fingerprint == fingerprint,
    }


def acceptance_evidence(db, project_id):
    records = acceptance_records(db, project_id)
    fingerprint = acceptance_scope_fingerprint(db, project_id)
    from app.time_utils import project_today
    project = db.get(Project, project_id)
    today = project_today(project.timezone if project else None)
    latest = next((record for record in records if record.accepted_at <= today), None)
    return [acceptance_dict(db, record, latest_id=latest.id if latest else None, fingerprint=fingerprint, today=today) for record in records]


def acceptance_summary(db, project_id):
    rows = acceptance_evidence(db, project_id)
    latest = next((row for row in rows if row['is_effective']), None)
    future_count = sum(not row['effective_date_reached'] for row in rows)
    if latest is None:
        reason = '缺少验收签字记录，请先在验收页录入验收结论'
    elif latest['conclusion'] != 'accepted':
        label = '不通过' if latest['conclusion'] == 'rejected' else '有条件通过'
        reason = f'最新有效验收结论为「{label}」，请整改后重新录入通过结论'
    elif not latest['scope_verified']:
        reason = '历史验收记录缺少范围快照，请复核当前范围后重新录入验收结论'
    elif not latest['scope_current']:
        reason = '验收后实施范围或必需质量/交付要求已变化，请复核当前范围后重新录入验收结论'
    else:
        reason = ''
    from app.time_utils import project_today
    project = db.get(Project, project_id)
    return {'latest': latest, 'eligible': not reason, 'reason': reason,
            'as_of_date': project_today(project.timezone if project else None).isoformat(),
            'pending_future_count': future_count,
            'warning': f'{future_count} 条历史验收记录日期晚于项目当地今天，暂不作为有效验收依据' if future_count else ''}


def ensure_current_acceptance(db, project_id):
    from fastapi import HTTPException
    summary = acceptance_summary(db, project_id)
    if not summary['eligible']:
        raise HTTPException(status_code=400, detail=summary['reason'])
