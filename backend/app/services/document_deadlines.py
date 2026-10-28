"""Site-calendar deadlines, real weekly instances and durable reminder delivery.

All mutations run under the caller's project lock and transaction. Date-only
events remain calendar anchors, never assertions that an event occurred at midnight.
GET projections use the persisted deadline snapshot and never generate work.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import (Project, ProjectEvent, ProjectDocument, ProjectDocumentDefinition,
                        VehicleUnit, User, DocumentNoticeReceipt, ChangeLog)
from app.services.change_log import log_change
from app.services.optimistic import bump_version
from app.services.system_permissions import has_permission
from app.services.project_lifecycle import ACTIVE_PROJECT_STATUSES
from app.time_utils import utcnow


def utc(value):
    if value is None:
        return utcnow()
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def zone(project):
    return ZoneInfo(project.timezone or 'Asia/Shanghai')


def local_now(project, now=None):
    return utc(now).replace(tzinfo=timezone.utc).astimezone(zone(project))


def week_start(day):
    return day - timedelta(days=day.weekday())


def period_key(day):
    year, week, _ = day.isocalendar()
    return f'{year:04}-W{week:02}'


def period_start(key):
    try:
        year, week = key.split('-W')
        result = date.fromisocalendar(int(year), int(week), 1)
        if period_key(result) != key:
            raise ValueError
        return result
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(400, '资料周次必须是有效 ISO 周，如2026-W44') from None


def calendar_anchor(day, project):
    return datetime.combine(day, time.min, zone(project)).astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class Deadline:
    due_at: datetime | None
    estimated: bool
    basis: dict


def calculate(document, project, events, units):
    try:
        return _calculate(document,project,events,units)
    except OverflowError:
        raise HTTPException(400,'事件日期与偏移小时超出日历范围，未修改资料') from None


def _calculate(document, project, events, units):
    """Pure calculation from persisted facts and immutable instance rule fields."""
    kind = document.timing_type
    basis = {'timezone': project.timezone or 'Asia/Shanghai', 'rule': kind}
    if document.stage_key == 'legacy':
        return Deadline(None, False, basis | {'kind': 'unclassified'})
    if kind == 'on_demand':
        return Deadline(None, False, basis | {'kind': 'on_demand'})
    if kind == 'lifetime':
        return Deadline(None, False, basis | {'kind': 'before_archive'})
    if kind == 'weekly':
        start = period_start(document.period_key)
        day = start + timedelta(days=(document.timing_weekday or 7) - 1)
        due = datetime.combine(day, time(23, 59, 59, 999999), zone(project))
        return Deadline(utc(due), False, basis | {'kind': 'weekly', 'period_key': document.period_key,
                                                'deadline_date': day.isoformat(), 'precision': 'minute'})
    if kind == 'on_trigger':
        if document.triggered_at is None or not document.trigger_ref:
            return Deadline(None, False, basis | {'kind': 'awaiting_trigger'})
        return Deadline(utc(document.triggered_at) + timedelta(hours=document.timing_offset_hours or 0), False,
                        basis | {'kind': 'actual_trigger', 'trigger_ref': document.trigger_ref, 'precision': 'datetime',
                                 'actual_at':utc(document.triggered_at).replace(tzinfo=timezone.utc).isoformat()})
    event_key = document.timing_event
    estimated = False
    if event_key == 'vehicle_arrival':
        unit = units.get(document.vehicle_unit_id)
        if not unit or unit.arrived_at is None:
            return Deadline(None, False, basis | {'kind': 'awaiting_event', 'event': event_key})
        anchor = calendar_anchor(unit.arrived_at, project)
        basis |= {'kind': 'actual_date_anchor', 'event': event_key, 'precision': 'date',
                  'actual_date': unit.arrived_at.isoformat(), 'vehicle_unit_id': unit.id}
    else:
        event = events.get(event_key)
        if event and getattr(event, 'actual_date', None) is not None:
            anchor = calendar_anchor(event.actual_date, project)
            basis |= {'kind': 'actual_date_anchor', 'event': event_key, 'precision': 'date', 'actual_date': event.actual_date.isoformat()}
        elif event and event.actual_at is not None:
            anchor = utc(event.actual_at)
            if event_key == 'arrival_all':
                day = anchor.replace(tzinfo=timezone.utc).astimezone(zone(project)).date()
                basis |= {'kind': 'actual_date_anchor', 'event': event_key, 'precision': 'date', 'actual_date': day.isoformat()}
            else:
                basis |= {'kind': 'actual_event', 'event': event_key, 'precision': 'datetime',
                          'actual_at': anchor.replace(tzinfo=timezone.utc).isoformat()}
        elif event and event.planned_date is not None:
            anchor = calendar_anchor(event.planned_date, project)
            estimated = True
            basis |= {'kind': 'planned_date_anchor', 'event': event_key, 'precision': 'date',
                      'planned_date': event.planned_date.isoformat()}
        else:
            return Deadline(None, False, basis | {'kind': 'awaiting_event', 'event': event_key})
    hours = document.timing_offset_hours or 0
    return Deadline(anchor + timedelta(hours=-hours if kind == 'before_event' else hours), estimated, basis)


def validate_owner(db, project, owner_id):
    if owner_id is None:
        return
    person = db.get(User, owner_id, populate_existing=True)
    members = {project.manager, project.technical_manager, *(project.members or [])}
    if person is None or not person.is_active or owner_id not in members or not has_permission(person,'project.read',default=True):
        raise HTTPException(400, '资料负责人必须是可查看本项目的活跃成员或负责人')


def owner_details(project, document, users):
    """Invalid explicit assignments remain visible while fallback keeps alerts actionable."""
    members = {project.manager, project.technical_manager, *(project.members or [])}
    requested = getattr(document, 'owner_id', None)
    manager=users.get(project.manager)
    manager_warning='' if manager and manager.is_active and has_permission(manager,'project.read',default=True) else '项目经理未设置或已停用，逾期升级提醒需管理员接手'
    warning = manager_warning
    for candidate in dict.fromkeys([requested, project.technical_manager, project.manager]):
        person = users.get(candidate)
        eligible=person and person.is_active and candidate in members and has_permission(person,'project.read',default=True)
        if eligible and isinstance(document,ProjectDocument):
            from app.services.project_documents import can_read_document
            if not can_read_document(person,project,document):
                warning='指定负责人未获保密资料查看权限，提醒暂由有权人员接收'
                continue
        if eligible:
            return {'owner_id': requested, 'owner_name': users[requested].display_name if requested in users else '',
                    'effective_owner_id': person.id, 'effective_owner_name': person.display_name,
                    'owner_warning': warning, 'owner_is_default': not requested}
        if candidate:
            warning = '指定负责人或默认技术负责人已停用或离开项目，暂由当前项目负责人接收提醒'+('；'+manager_warning if manager_warning else '')
    return {'owner_id': requested, 'owner_name': users[requested].display_name if requested in users else '',
            'effective_owner_id': None, 'effective_owner_name': '', 'owner_warning': '尚无活跃资料负责人，请项目经理或管理员指派',
            'owner_is_default': not requested}


def _users(db, project, documents):
    ids = {project.manager, project.technical_manager, *(project.members or []),
           *(getattr(row, 'owner_id', None) for row in documents)}
    return {row.id: row for row in db.query(User).filter(User.id.in_(ids))}


SITE_STAGE = '6'


def execution_start(db, project):
    """Local date the project first entered on-site execution, or None before it.

    Uses the structured status audit; projects that reached execution before the
    audit carried the new status (migrated or legacy) fall back to their start date.
    """
    from app.services.project_lifecycle import EXECUTION_PROJECT_STATUSES
    effective = (project.suspension or {}).get('status_before') if project.status == 'suspended' else project.status
    rows = db.query(ChangeLog.new_value, ChangeLog.created_at).filter(
        ChangeLog.project_id == project.id, ChangeLog.entity_type == 'project', ChangeLog.entity_id == project.id,
        ChangeLog.action == 'update').order_by(ChangeLog.created_at).all()
    for value, at in rows:
        if isinstance(value, dict) and value.get('status') == 'executing' and at:
            return utc(at).replace(tzinfo=timezone.utc).astimezone(zone(project)).date()
    if effective in EXECUTION_PROJECT_STATUSES or effective in ('completed', 'archived'):
        return project.start_date
    return None


def generate_weekly(db, project, now=None, actor_id=None):
    """Catch up only weeks during which this project definition actually existed."""
    if project.deleted_at or project.status not in ACTIVE_PROJECT_STATUSES:
        return 0
    current = local_now(project, now).date()
    if project.start_date > current:
        return 0
    from app.services.project_documents import applicable, instantiate
    definitions = db.query(ProjectDocumentDefinition).filter_by(project_id=project.id, timing_type='weekly').all()
    units = db.query(VehicleUnit).filter_by(project_id=project.id).all()
    site_start = execution_start(db, project)
    count = 0
    for definition in definitions:
        if definition.stage_key == 'legacy' or not applicable(project, definition):
            continue
        created = utc(definition.created_at).replace(tzinfo=timezone.utc).astimezone(zone(project)).date()
        floor = max(project.start_date, created)
        if definition.stage_key == SITE_STAGE:
            # 实施阶段的周资料从首次进入现场实施的那一周开始，准备阶段不产生期次。
            if site_start is None:
                continue
            floor = max(floor, site_start)
        first = week_start(floor)
        week = first
        while week <= week_start(current):
            deadline_day=week+timedelta(days=(definition.timing_weekday or 7)-1)
            deadline_at=utc(datetime.combine(deadline_day,time(23,59,59,999999),zone(project)))
            activation=max(utc(definition.created_at),calendar_anchor(project.start_date,project))
            key = period_key(week)
            for unit in units if definition.scope == 'vehicle' else [None]:
                enabled=max(activation,utc(unit.created_at)) if unit and unit.created_at else activation
                if deadline_at<enabled:continue
                existing = db.query(ProjectDocument.id).filter_by(definition_id=definition.id, period_key=key,
                    vehicle_unit_id=unit.id if unit else None).first()
                if existing:
                    continue
                row = instantiate(db, project, definition, vehicle=unit, period_key=key)
                row.owner_id = definition.owner_id
                log_change(db, project.id, 'project_document', row.id, 'generate', actor_id,
                           f'生成{key}资料：{row.code} {row.name}', None,
                           {'period_key': key, 'definition_id': definition.id, 'vehicle_unit_id': row.vehicle_unit_id})
                count += 1
            week += timedelta(days=7)
    return count


def refresh_project(db, project, *, now=None, actor_id=None, generate=True):
    """Caller must serialize on Project; submitted/waived snapshots stay immutable."""
    db.flush()
    generated = generate_weekly(db, project, now, actor_id) if generate else 0
    events = {row.event_key: row for row in db.query(ProjectEvent).filter_by(project_id=project.id)}
    units = {row.id: row for row in db.query(VehicleUnit).filter_by(project_id=project.id)}
    changed = 0
    for row in db.query(ProjectDocument).filter_by(project_id=project.id, status='pending'):
        if row.stage_key=='legacy':continue
        deadline = calculate(row, project, events, units)
        if (row.due_at, bool(row.due_is_estimated), row.due_basis) == (deadline.due_at, deadline.estimated, deadline.basis):
            continue
        before = {'due_at': row.due_at.isoformat() if row.due_at else None, 'due_is_estimated': row.due_is_estimated, 'due_basis': row.due_basis}
        row.due_at, row.due_is_estimated, row.due_basis = deadline.due_at, deadline.estimated, deadline.basis
        bump_version(row, None, db=db)
        log_change(db, project.id, 'project_document', row.id, 'deadline', actor_id,
                   f'按真实规则更新资料截止：{row.code} {row.name}', before,
                   {'due_at': row.due_at.isoformat() if row.due_at else None, 'due_is_estimated': row.due_is_estimated, 'due_basis': row.due_basis})
        changed += 1
    db.flush()
    return {'generated': generated, 'updated': changed}


def due_state(row, project, now=None):
    from app.services.project_documents import applicable
    if row.stage_key == 'legacy':
        return 'unclassified'
    if not applicable(project, row):
        return 'not_applicable'
    if row.status != 'pending':
        return 'satisfied'
    if row.timing_type == 'on_demand':
        return 'on_demand'
    if row.timing_type == 'lifetime':
        return 'before_archive'
    if row.due_at is None:
        return 'awaiting_event'
    if row.due_is_estimated:
        return 'estimated_past_due' if utc(row.due_at) < utc(now) else 'estimated'
    return 'overdue' if utc(row.due_at) < utc(now) else 'upcoming'


def action_summary(db, project, user, now=None, documents=None, users=None):
    from app.services.project_documents import applicable, can_read_document
    now = utc(now)
    start = calendar_anchor(week_start(local_now(project, now).date()), project)
    end = calendar_anchor(week_start(local_now(project, now).date()) + timedelta(days=7), project)
    documents = documents if documents is not None else db.query(ProjectDocument).filter_by(project_id=project.id).all()
    users = users if users is not None else _users(db, project, documents)
    visible = [row for row in documents if row.stage_key != 'legacy' and applicable(project, row)
               and (user is None or can_read_document(user, project, row))]
    def brief(row):
        from app.services.project_documents import iso
        return {'id': row.id, 'document_id': row.id, 'code': row.code, 'name': row.name, 'vehicle_label': row.vehicle_label,
                'period_key': row.period_key, 'due_at': iso(row.due_at), 'due_is_estimated': row.due_is_estimated,
                'due_basis': row.due_basis, 'due_state': due_state(row, project, now), 'status': row.status,
                'overdue_days': max(0, (local_now(project, now).date() - utc(row.due_at).replace(tzinfo=timezone.utc).astimezone(zone(project)).date()).days) if row.due_at else 0,
                **owner_details(project, row, users)}
    pending = [row for row in visible if row.status == 'pending']
    overdue = sorted((row for row in pending if due_state(row, project, now) == 'overdue'), key=lambda row: (row.due_at, row.id))
    this_week = sorted((row for row in pending if row.due_at and start <= utc(row.due_at) < end), key=lambda row: (row.due_at, row.id))
    return {'this_week': [brief(row) for row in this_week], 'this_week_count': len(this_week),
            'overdue': [brief(row) for row in overdue], 'overdue_count': len(overdue),
            'estimated_past_due_count': sum(due_state(row, project, now) == 'estimated_past_due' for row in pending),
            'on_demand': [brief(row) for row in pending if row.timing_type == 'on_demand'],
            'owner_warnings': [brief(row) for row in pending if owner_details(project, row, users)['owner_warning']],
            'period_key': period_key(local_now(project, now).date()), 'timezone': project.timezone,
            'as_of': now.replace(tzinfo=timezone.utc).isoformat()}


def attention_for_projects(db, projects, user, now=None):
    """One document query and one owner query for an entire visible portfolio."""
    from collections import defaultdict
    by_project = defaultdict(list)
    for row in db.query(ProjectDocument).filter(ProjectDocument.project_id.in_([p.id for p in projects])):
        by_project[row.project_id].append(row)
    owner_ids = {row.owner_id for rows in by_project.values() for row in rows}
    owner_ids.update(value for p in projects for value in (p.manager, p.technical_manager))
    users = {row.id: row for row in db.query(User).filter(User.id.in_(owner_ids))}
    return {p.id: action_summary(db, p, user, now, by_project[p.id], users) for p in projects}


def workspace_attention(db, projects, user, now=None):
    summaries = attention_for_projects(db, projects, user, now)
    result = {'this_week': [], 'overdue': [], 'estimated_past_due_count': 0, 'projects': []}
    for project in projects:
        summary = summaries[project.id]
        result['projects'].append({'project_id': project.id, 'project_name': project.name, **summary})
        for kind in ('this_week', 'overdue'):
            result[kind].extend({'project_id': project.id, 'project_name': project.name, 'timezone': project.timezone, **row}
                                for row in summary[kind])
        result['estimated_past_due_count'] += summary['estimated_past_due_count']
    result['this_week_count'] = len(result['this_week'])
    result['overdue_count'] = len(result['overdue'])
    return result


def missing_lifetime_requirements(db, project):
    """Archive must also see requirements waiting for an actual kickoff instance."""
    from app.services.project_documents import applicable
    definitions=db.query(ProjectDocumentDefinition).filter_by(project_id=project.id,timing_type='lifetime',required=True).all()
    existing={(row.definition_id,row.vehicle_unit_id) for row in db.query(ProjectDocument).filter_by(project_id=project.id)}
    units=db.query(VehicleUnit).filter_by(project_id=project.id).all()
    missing=[]
    for rule in definitions:
        if rule.stage_key=='legacy' or not applicable(project,rule):continue
        for unit in units if rule.scope=='vehicle' else [None]:
            if (rule.id,unit.id if unit else None) not in existing:
                missing.append(f'{rule.code} {rule.name}'+(f'（{unit.asset_code}）' if unit else '')+'：等待实际内部启动会建档')
    return missing


def _claim_notice(db, row, recipient_id, kind, now):
    values = {'id': str(uuid4()), 'project_id': row.project_id, 'project_document_id': row.id,
              'recipient_id': recipient_id, 'recipient_key': recipient_id or 'unassigned', 'kind': kind,
              'due_at': row.due_at, 'due_is_estimated': row.due_is_estimated, 'created_at': now}
    if db.bind.dialect.name == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    result = db.execute(insert(DocumentNoticeReceipt).values(**values).on_conflict_do_nothing())
    return result.rowcount == 1


def remind_project(db, project, now=None):
    """No network I/O: notify only creates in-app messages and optional outbox rows."""
    from app.services.project_documents import applicable, can_read_document
    from app.services.notify import notify
    db.flush()
    now = utc(now)
    if project.deleted_at or project.status not in ACTIVE_PROJECT_STATUSES:return {'notified':0,'owner_missing':0}
    rows = db.query(ProjectDocument).filter_by(project_id=project.id, status='pending').filter(ProjectDocument.due_at.isnot(None)).all()
    users = _users(db, project, rows)
    count = missing = 0
    for row in rows:
        if row.stage_key == 'legacy' or not applicable(project, row):
            continue
        due = utc(row.due_at)
        kind = 'overdue' if now > due else 'due_soon' if now >= due - timedelta(days=1) else None
        if kind is None:
            continue
        owner = owner_details(project, row, users)
        recipients = {owner['effective_owner_id']} if owner['effective_owner_id'] else set()
        manager = users.get(project.manager)
        if recipients and not can_read_document(users[owner['effective_owner_id']],project,row):
            recipients.clear()
            if manager and manager.is_active and has_permission(manager,'project.read',default=True):recipients.add(manager.id)
        if kind == 'overdue' and manager and manager.is_active and has_permission(manager,'project.read',default=True):
            recipients.add(manager.id)
        elif kind == 'overdue':
            recipients.update(person.id for person in db.query(User).filter_by(role='admin',is_active=True) if has_permission(person,'project.read',default=True))
        if not recipients:
            missing += 1
            recipients.update(person.id for person in db.query(User).filter_by(role='admin', is_active=True)
                              if has_permission(person,'project.read',default=True) and can_read_document(person,project,row))
            if not recipients and _claim_notice(db, row, None, 'owner_missing', now):
                log_change(db, project.id, 'project_document', row.id, 'reminder_unassigned', None,
                           '资料提醒无人接收，请指定活跃负责人', None, {'due_at': row.due_at.isoformat()})
        for recipient_id in sorted(recipients):
            if not _claim_notice(db, row, recipient_id, kind, now):
                continue
            label = ('预计截止已过' if kind=='overdue' else '资料预计将于1天内截止') if row.due_is_estimated else ('资料已逾期' if kind=='overdue' else '资料将于1天内截止')
            title = f'「{project.name}」{label}'[:200]
            local_due = due.replace(tzinfo=timezone.utc).astimezone(zone(project)).strftime('%Y-%m-%d %H:%M')
            content = f'{row.code} {row.name}'+(f' · {row.vehicle_label}' if row.vehicle_label else '')+f'；{"预计" if row.due_is_estimated else ""}截止 {local_due}（{project.timezone}）。'
            if owner['owner_warning']:
                content += owner['owner_warning']
            # Restricted document names never leave the in-app boundary until T26
            # establishes an explicit channel disclosure policy.
            notify(db, recipient_id, title, content, ntype='document_deadline', project_id=project.id, entity_id=row.id,
                   channels=not row.confidential)
            log_change(db, project.id, 'project_document', row.id, 'remind', None, label, None,
                       {'recipient_id': recipient_id, 'kind': kind, 'due_at': due.isoformat(), 'estimated': row.due_is_estimated})
            count += 1
    return {'notified': count, 'owner_missing': missing}
