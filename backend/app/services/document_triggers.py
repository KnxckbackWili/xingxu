"""Real, immutable source records connect business events to document obligations.

Callers hold the project lock and own commit/rollback. Neither GET projections
nor imported historical metadata can manufacture a trigger.
"""
from datetime import datetime
from fastapi import HTTPException
from app.models import (DocumentTriggerEvent,ProjectDocumentDefinition,ProjectDocument,
                        VehicleUnit,Issue,User)
from app.services.change_log import log_change
from app.services.document_deadlines import utc,refresh_project

NATURES={'normal':'普通','accident':'事故','quality':'质量问题'}


def issue_events(db,issues):
    ids=[row.id for row in issues]
    return {(row.project_id,row.source_id,row.trigger_type):row for row in db.query(DocumentTriggerEvent).filter(
        DocumentTriggerEvent.source_type=='issue',DocumentTriggerEvent.source_id.in_(ids))}


def issue_trigger_fields(db,issue,events=None):
    """Accident and quality issues point at the trigger event that created their documents."""
    event=None
    if issue.nature in {'accident','quality'}:
        event=(events.get((issue.project_id,issue.id,issue.nature)) if events is not None else db.query(DocumentTriggerEvent).filter_by(
            project_id=issue.project_id,source_type='issue',source_id=issue.id,trigger_type=issue.nature).first())
    return {'nature':issue.nature,'trigger_event_id':event.id if event else None,'source_metadata':issue.source_metadata}


def event_dict(event):
    from app.services.project_documents import iso
    return {'id':event.id,'trigger_type':event.trigger_type,'source_type':event.source_type,
            'source_id':event.source_id,'occurred_at':iso(event.occurred_at),'recorded_at':iso(event.recorded_at),
            'source_metadata':event.source_metadata}


def materialize(db,project,event,actor_id):
    from app.services.project_documents import applicable,instantiate
    if event.project_id!=project.id or not event.occurred_at:
        raise HTTPException(400,'触发来源必须是本项目的真实事件')
    definitions=db.query(ProjectDocumentDefinition).filter_by(project_id=project.id,
        timing_type='on_trigger',trigger_type=event.trigger_type).all()
    units=db.query(VehicleUnit).filter_by(project_id=project.id).all()
    generated=[]
    for definition in definitions:
        if not applicable(project,definition):continue
        for unit in units if definition.scope=='vehicle' else [None]:
            existing=db.query(ProjectDocument.id).filter_by(definition_id=definition.id,trigger_ref=event.id,
                vehicle_unit_id=unit.id if unit else None).first()
            if existing:continue
            row=instantiate(db,project,definition,vehicle=unit,trigger_ref=event.id,triggered_at=event.occurred_at)
            generated.append(row.id)
            log_change(db,project.id,'project_document',row.id,'generate',actor_id,
                f'真实事件生成资料：{row.code} {row.name}',None,
                {'trigger_event_id':event.id,'source_type':event.source_type,'source_id':event.source_id,
                 'occurred_at':event.occurred_at.isoformat()})
    if not generated and not db.query(ProjectDocument.id).filter_by(project_id=project.id,trigger_ref=event.id).first():
        event.source_metadata={**event.source_metadata,'warning':'当前项目未匹配可生成的资料要求，请负责人核对触发规则及车辆范围'}
    refresh_project(db,project,actor_id=actor_id,generate=False)
    return generated


def record(db,project,*,trigger_type,source_type,source_id,source_key,occurred_at,actor_id,metadata):
    if not isinstance(occurred_at,datetime):raise HTTPException(400,'触发来源缺少真实发生或登记时刻')
    event=db.query(DocumentTriggerEvent).filter_by(project_id=project.id,source_key=source_key).first()
    if event:return event
    event=DocumentTriggerEvent(project_id=project.id,trigger_type=trigger_type,source_type=source_type,
        source_id=source_id,source_key=source_key,occurred_at=utc(occurred_at),actor_id=actor_id,source_metadata=metadata)
    db.add(event);db.flush()
    materialize(db,project,event,actor_id)
    log_change(db,project.id,'document_trigger',event.id,'create',actor_id,'登记真实资料触发来源',None,event_dict(event))
    return event


def issue_event(db,project,issue,actor_id,*,previous_nature=None,now=None):
    if issue.project_id!=project.id or db.get(Issue,issue.id) is not issue:
        raise HTTPException(400,'触发问题不属于本项目')
    if issue.nature not in {'accident','quality'}:return None
    changed=previous_nature is not None and previous_nature!=issue.nature
    occurred=utc(now) if changed else issue.created_at
    if occurred is None:raise HTTPException(400,'原问题缺少真实上报时刻，请明确变更性质后登记触发')
    return record(db,project,trigger_type=issue.nature,source_type='issue',source_id=issue.id,
        source_key=f'issue:{issue.id}:{issue.nature}',occurred_at=occurred,actor_id=actor_id,
        metadata={'basis':'nature_changed' if changed else 'reported','title':issue.title,
                  'previous_nature':previous_nature,'reported_at':issue.created_at.isoformat() if issue.created_at else None,
                  'note':'资料截止依据为本次性质变更时刻，不代表事故实际发生日期' if changed else '资料截止依据为真实上报时刻，不代表事故实际发生日期'})


def removal_preview(db,project,removed):
    from app.services.project_documents import applicable
    people={row.id:row for row in db.query(User).filter(User.id.in_(removed))}
    rules=[row for row in db.query(ProjectDocumentDefinition).filter_by(project_id=project.id,
        timing_type='on_trigger',trigger_type='member_leave') if applicable(project,row)]
    return {'project_id':project.id,'version':project.version,
        'removed':[{'user_id':identity,'name':people[identity].display_name if identity in people else '原成员',
                    'documents':[{'code':row.code,'name':row.name,'required':row.required} for row in rules]} for identity in sorted(removed)],
        'warning':'原负责人离开前请完成文档交接；确认后会建立6.7等留存资料，原文档与提交人信息继续保存。',
        'rule_warning':None if rules else '未匹配人员离开资料要求，请先核对项目资料规则'}


def confirm_removals(db,project,removed,confirmed):
    values=confirmed or []
    if len(values)!=len(set(values)) or set(values)!=set(removed):
        raise HTTPException(409,detail={'code':'member_removal_confirmation_required',
            'message':'请逐人核对离开项目前的资料留存要求后再确认移除',**removal_preview(db,project,removed)})


def member_events(db,project,removed,actor_id,now=None):
    now=utc(now)
    for identity in sorted(removed):
        person=db.get(User,identity)
        record(db,project,trigger_type='member_leave',source_type='member_departure',source_id=identity,
            source_key=f'member:{project.version}:{identity}',occurred_at=now,actor_id=actor_id,
            metadata={'basis':'confirmed_member_removal','member_name':person.display_name if person else '原成员',
                'member_id':identity,'project_version':project.version,'note':'已确认负责人更换；离开前文档交接要求，截止为本次更换登记时刻'})


def transfer_departures(db,project):
    """The outgoing manager leaves unless they stay on as technical lead."""
    identity=project.manager
    if not identity:return set()
    return {identity}
