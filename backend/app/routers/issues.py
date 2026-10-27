"""Issue ledger routes."""

from app.services.system_permissions import route_permission
from app.time_utils import utcnow
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_pm
from app.models import User, Issue, Task, VehicleLifecycleEvent, VehicleUnit, Project
from app.services.scope import ensure_project_visible
from app.services.record_lock import lock_writable_project
from app.services.permissions import authorize_project, C_ISSUES
from app.services.change_log import log_change

router = APIRouter(tags=["问题"])

_ISSUE_TYPE_RE = "^(hardware|software|environment|process|safety|other)$"
_STATUS_RE = "^(open|processing|resolved|closed|cancelled)$"
_SEVERITY_LABELS = {"critical": "严重", "high": "高", "medium": "中", "low": "低"}


class IssueCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    issue_type: Optional[str] = Field(default="other", pattern=_ISSUE_TYPE_RE)
    nature: str = Field(default='normal',pattern='^(normal|accident|quality)$')
    severity: str = Field(default="medium", pattern="^(critical|high|medium|low)$")
    task_id: Optional[str] = None
    assignee_id: Optional[str] = None
    extra: Optional[dict] = None  # 分类专属字段：hardware 设备/部位、software 模块版本、process 部门接口人
    client_uuid: Optional[str] = Field(default=None, min_length=8, max_length=64)  # C5-5：离线幂等键


class IssueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    issue_type: Optional[str] = Field(default=None, pattern=_ISSUE_TYPE_RE)
    nature: str|None = Field(default=None,pattern='^(normal|accident|quality)$')
    severity: Optional[str] = Field(default=None, pattern="^(critical|high|medium|low)$")
    status: Optional[str] = Field(default=None, pattern=_STATUS_RE)
    assignee_id: Optional[str] = None
    resolution: Optional[str] = None
    extra: Optional[dict] = None
    version: Optional[int] = None  # 乐观锁版本号


class IssueBulkImport(BaseModel):
    items: list[IssueCreate] = Field(min_length=1, max_length=100)


def _validate_assignee(db: Session, project, assignee_id: str, label="处理人"):
    """处理人必须存在且启用（C6-5）：坏 ID 直接 400，避免脏数据/通知落空。"""
    u = db.get(User, assignee_id)
    if u is None:
        raise HTTPException(status_code=400, detail=f"{label}不存在：{assignee_id[:8]}")
    if not u.is_active:
        raise HTTPException(status_code=400, detail=f"{label}已停用：{u.display_name or assignee_id[:8]}")
    try:
        ensure_project_visible(db, project.id, u)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise HTTPException(400, f"{label}无法访问当前项目，请先添加为项目成员") from None
    from app.services.permissions import project_capabilities
    if u.id not in (project.members or []) and C_ISSUES not in project_capabilities(u, project):
        raise HTTPException(400, f"{label}没有当前项目的问题处理权限，请先添加为项目成员")


def _validate_issue_task(db: Session, project_id: str, task_id: Optional[str]) -> None:
    """HYPE-99：问题关联 task_id 必须真实存在且属于该项目，杜绝跨项目台账串扰。"""
    if not task_id:
        return
    t = db.get(Task, task_id)
    if t is None:
        raise HTTPException(status_code=400, detail="关联的任务不存在")
    if t.project_id != project_id:
        raise HTTPException(status_code=400, detail="关联任务不属于该项目")


def _issue_dict(db: Session, i: Issue, actor: User | None = None,events=None) -> dict:
    project = db.get(Project, i.project_id)
    from app.services.system_permissions import has_permission
    can_close = bool(actor and actor.is_active and actor.role != 'readonly' and project
        and has_permission(actor, 'project.manage_issues', default=True)
        and (actor.role == 'admin' or actor.id in {project.manager, i.reporter_id}))
    reporter = db.get(User, i.reporter_id)
    assignee = db.get(User, i.assignee_id) if i.assignee_id else None
    task = db.get(Task, i.task_id) if i.task_id else None
    from app.services.document_triggers import issue_sla_fields
    return {
        "id": i.id,
        "title": i.title,
        "description": i.description,
        "issue_type": i.issue_type,
        **issue_sla_fields(db,i,events),
        "severity": i.severity,
        "status": i.status,
        "reporter_id": i.reporter_id,
        "can_close": can_close,
        "reporter_name": reporter.display_name if reporter else "",
        "assignee_id": i.assignee_id,
        "assignee_name": assignee.display_name if assignee else "",
        "task_id": i.task_id,
        "task_name": task.name if task else "",
        "extra": i.extra or {},
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
        "resolution": i.resolution,
        "version": i.version or 0,
    }


@router.get("/projects/{project_id}/issues")
@route_permission('project.read')
def list_issues(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ensure_project_visible(db, project_id, user)
    issues = (
        db.query(Issue)
        .filter(Issue.project_id == project_id)
        .order_by(Issue.created_at.desc())
        .all()
    )
    from app.services.document_triggers import issue_events
    events=issue_events(db,issues)
    return [_issue_dict(db, i, user,events) for i in issues]


@router.get("/projects/{project_id}/issue-assignees")
@route_permission('project.read')
def issue_assignees(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only offer people who can open and handle the issue they receive."""
    p = ensure_project_visible(db, project_id, user)
    ids = set(p.members or []) | {p.manager, p.technical_manager}
    ids.update(grant.get("user_id") for grant in p.co_managers or [])
    from sqlalchemy import or_
    candidates = db.query(User).filter(User.is_active.is_(True),
        or_(User.id.in_([uid for uid in ids if uid]), User.role.in_(("admin", "director"))))        .order_by(User.display_name, User.id).all()
    eligible = []
    for candidate in candidates:
        try:
            _validate_assignee(db, p, candidate.id)
        except HTTPException as exc:
            if exc.status_code != 400:
                raise
            continue
        eligible.append({"id": candidate.id, "username": candidate.username,
                         "display_name": candidate.display_name, "role": candidate.role})
    return eligible


@router.get("/projects/{project_id}/vehicle-issues")
@route_permission('project.read')
def list_vehicle_issues(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Vehicle repair records projected into the project attention center without duplicating them."""
    ensure_project_visible(db, project_id, user)
    rows = (db.query(VehicleLifecycleEvent, VehicleUnit)
            .join(VehicleUnit, VehicleUnit.id == VehicleLifecycleEvent.vehicle_unit_id)
            .filter(
                VehicleLifecycleEvent.project_id == project_id,
                VehicleLifecycleEvent.event_type.in_(("fault", "repair", "maintenance", "inspection", "other")),
            )
            .order_by(VehicleLifecycleEvent.is_closed, VehicleLifecycleEvent.event_date.desc())
            .all())
    result = []
    for event, unit in rows:
        operator = db.get(User, event.operator_id) if event.operator_id else None
        result.append({
            "id": event.id,
            "source": "vehicle",
            "vehicle_unit_id": unit.id,
            "asset_code": unit.asset_code,
            "vehicle_status": unit.current_status,
            "title": event.title,
            "description": event.description or "",
            "fault_part": event.fault_part or "",
            "cause": event.cause or "",
            "action_taken": event.action_taken or "",
            "replaced_parts": event.replaced_parts or [],
            "verification": event.verification or "",
            "handler": event.handler or "",
            "downtime_hours": event.downtime_hours,
            "status": "resolved" if event.is_closed else "open",
            "event_type": event.event_type,
            "event_date": event.event_date.isoformat(),
            "reporter_name": operator.display_name if operator else "",
            "updated_at": event.updated_at.isoformat() if event.updated_at else None,
        })
    return result


@router.post("/projects/{project_id}/issues")
@route_permission('worker.issues')
def create_issue(
    project_id: str,
    data: IssueCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 任何人可上报，但必须是该项目成员（或 PM/admin）——防止污染任意项目台账
    p = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, p, user)
    if user.role not in ("admin", "pm", "director", "lead") and user.id not in (p.members or []):
        raise HTTPException(status_code=403, detail="仅项目成员可上报问题")
    if data.assignee_id:
        _validate_assignee(db, p, data.assignee_id)
    # HYPE-99：关联任务必须属于本项目（离线/在线同一入口）
    _validate_issue_task(db, project_id, data.task_id)
    # C5-5：离线幂等——同一 client_uuid 已存在则直接返回（不重复建、不重复通知）
    if data.client_uuid:
        existing = db.query(Issue).filter(
            Issue.project_id == project_id,
            Issue.client_uuid == data.client_uuid,
        ).first()
        if existing is not None:
            return _issue_dict(db, existing, user)
    i = Issue(
        project_id=project_id,
        title=data.title,
        description=data.description,
        issue_type=data.issue_type,
        nature=data.nature,
        severity=data.severity,
        task_id=data.task_id,
        reporter_id=user.id,
        assignee_id=data.assignee_id,
        extra=data.extra or {},
        client_uuid=data.client_uuid,
    )
    try:
        db.add(i)
        db.flush()
        from app.services.document_triggers import issue_event
        issue_event(db,p,i,user.id)
        log_change(db, project_id, "issue", i.id, "create", user.id,
                   f"上报问题：{data.title}（{data.severity}）")
        # Notify assignee if specified
        if data.assignee_id:
            from app.routers.notifications import notify
            assignee = db.get(User, data.assignee_id)
            if assignee:
                notify(db, assignee.id, f"新问题指派给你：{data.title}",
                       f"严重程度：{_SEVERITY_LABELS.get(data.severity, data.severity)} · 上报人：{user.display_name}",
                       ntype="issue_assigned", project_id=project_id, entity_id=i.id)
        # No assignee → notify the project manager (问题不指定处理人时不能无人知晓)
        elif p.manager and p.manager != user.id:
            from app.routers.notifications import notify
            manager = db.get(User, p.manager)
            if manager:
                notify(db, manager.id, f"新问题上报：{data.title}",
                       f"严重程度：{_SEVERITY_LABELS.get(data.severity, data.severity)} · 上报人：{user.display_name}",
                       ntype="issue_reported", project_id=project_id, entity_id=i.id)
        db.commit()
    except IntegrityError:
        # HYPE-99：并发重复（多 worker/多端同时以同一 client_uuid 上报同一项目）→ 幂等忽略。
        # 先回滚本次写，再按 (project_id, client_uuid) 取回先落库的那条，不重复审计/通知。
        db.rollback()
        existing = (
            db.query(Issue)
            .filter(Issue.project_id == project_id, Issue.client_uuid == data.client_uuid)
            .first()
        )
        if existing is not None and data.client_uuid:
            return _issue_dict(db, existing, user)
        raise
    db.refresh(i)
    from app.services.cache import cache_clear
    cache_clear("dashboard:")
    return _issue_dict(db, i, user)


@router.post("/projects/{project_id}/issues/import")
@route_permission('project.manage_issues')
def import_issues(
    project_id: str,
    data: IssueBulkImport,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import AI-reviewed issue candidates as ordinary auditable issue records."""
    p = ensure_project_visible(db, project_id, user)
    lock_writable_project(db, p, user)
    if user.role not in ("admin", "pm", "director", "lead") and user.id not in (p.members or []):
        raise HTTPException(status_code=403, detail="仅项目成员可导入问题")
    # HYPE-99 复审（REJECT 修复）：审计/经理通知必须与问题台账同事务提交。此前先 commit
    # 台账、再 add log_change/notify 且无第二次 commit，而 get_db 请求结束仅 close()，
    # 导致 ChangeLog(action="import")/Notification/NotificationOutbox 全被回滚丢失。
    # 现改为「台账 + 审计 + 通知」在一次 commit 中一并持久化；并发同 client_uuid 冲突时
    # 整个事务回滚，下一轮靠幂等预检跳过已被他人落库的行，仅对本次真正新增的行写审计/
    # 通知——重试/并发绝不重复留痕。
    created = []
    for attempt in range(2):  # 首轮成功即出；并发唯一冲突回滚后按最新库态重试一轮
        created = []
        seen_client_uuids = set()  # 批内去重：同一请求多次出现同一 client_uuid 只建一条
        pending_rows = []  # 本轮待新建的行（已存在的行在此被滤掉）
        for row in data.items:
            if row.assignee_id:
                _validate_assignee(db, p, row.assignee_id)
            # HYPE-99：关联任务必须属于该项目
            _validate_issue_task(db, project_id, row.task_id)
            if row.client_uuid:
                key = row.client_uuid
                if key in seen_client_uuids:
                    continue
                # 幂等：该项目已有同 client_uuid（并发/历史重试）→ 跳过，不重复建/审计/通知
                existing = db.query(Issue.id).filter(
                    Issue.project_id == project_id,
                    Issue.client_uuid == key,
                ).first()
                if existing is not None:
                    seen_client_uuids.add(key)
                    continue
                seen_client_uuids.add(key)
            pending_rows.append(row)
        if not pending_rows:
            # 全部为已有/重复行：没有新建台账，也就不写审计/通知（重试不产生重复副作用）
            break
        try:
            for row in pending_rows:
                issue = Issue(
                    project_id=project_id, title=row.title, description=row.description,
                    issue_type=row.issue_type, severity=row.severity, task_id=row.task_id,
                    nature=row.nature,
                    reporter_id=user.id, assignee_id=row.assignee_id, extra=row.extra or {},
                    client_uuid=row.client_uuid,
                )
                db.add(issue)
                db.flush()
                from app.services.document_triggers import issue_event
                issue_event(db,p,issue,user.id)
                created.append(issue)
            log_change(db, project_id, "issue", project_id, "import", user.id,
                       f"AI 辅助导入问题 {len(created)} 条")
            if p.manager and p.manager != user.id:
                from app.routers.notifications import notify
                notify(db, p.manager, f"AI 辅助导入 {len(created)} 条项目问题",
                       f"操作人：{user.display_name}", ntype="issue_reported", project_id=project_id)
            db.commit()
            break
        except IntegrityError:
            # HYPE-99：并发导入（另一请求已导入部分/全部相同 client_uuid）→ 连同审计/通知
            # 一并回滚，下一轮靠幂等预检跳过已存在的行重试；仍冲突（两轮都失败，极罕见）
            # 则 409 提示调用方重试。
            db.rollback()
            lock_writable_project(db, p, user)
    else:
        raise HTTPException(status_code=409, detail="导入与另一操作并发冲突，请重试")
    from app.services.cache import cache_clear
    cache_clear("dashboard:")
    return {"message": f"已导入 {len(created)} 条问题", "count": len(created)}


@router.put("/issues/{issue_id}")
@route_permission('project.manage_issues')
def update_issue(
    issue_id: str,
    data: IssueUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.permissions import authorize_project, C_ISSUES
    i = db.get(Issue, issue_id)
    if i is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    p = ensure_project_visible(db, i.project_id, user)
    lock_writable_project(db, p, user)
    db.refresh(user)
    if not user.is_active:
        raise HTTPException(401, "账号已停用，请重新登录")
    p = ensure_project_visible(db, i.project_id, user)
    i = db.query(Issue).filter_by(id=issue_id).populate_existing().first()
    if i is None:
        raise HTTPException(404, "问题不存在")
    fields_requested = set(data.model_dump(exclude_unset=True))
    is_closure = data.status in {"closed", "cancelled"}
    may_close = user.role == 'admin' or user.id in {p.manager, i.reporter_id}
    if is_closure and not may_close:
        raise HTTPException(403, "仅项目经理或报告人可关闭或作废问题")
    personal_fields = {"status", "resolution", "version"}
    assigned_update = i.assignee_id == user.id and not is_closure
    reporter_closure = i.reporter_id == user.id and is_closure
    if not ((assigned_update or reporter_closure) and not (fields_requested - personal_fields)):
        authorize_project(user, p, C_ISSUES)
    if data.status == 'cancelled' and not (data.resolution or '').strip():
        raise HTTPException(400, "作废问题必须填写理由")
    from app.services.optimistic import bump_version, require_client_version
    bump_version(i, require_client_version(data.version))
    if data.assignee_id is not None:
        _validate_assignee(db, p, data.assignee_id)
    old_assignee = i.assignee_id
    old_status = i.status
    old_nature = i.nature
    # C6-6：记录字段级变更（old/new）供审计留痕
    old_values = {
        f: getattr(i, f) for f in ["title", "description", "issue_type", "nature", "severity", "status", "assignee_id", "resolution"]
    }
    old_extra = dict(i.extra or {})
    # 状态机守卫：禁止任意跳转（resolved→processing / closed→resolved 等）
    if data.status is not None and data.status != old_status:
        ALLOWED_TRANSITIONS = {
            "open": {"processing", "resolved", "closed", "cancelled"},
            "processing": {"open", "resolved", "closed", "cancelled"},
            "resolved": {"open", "closed"},
            "closed": {"open"},
            "cancelled": {"open"},
        }
        if data.status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise HTTPException(status_code=400, detail=f"不允许的问题状态流转：{old_status} → {data.status}")
    fields = ["title", "description", "issue_type", "nature", "severity", "status", "assignee_id", "resolution"]
    for f in fields:
        v = getattr(data, f)
        if v is not None or (f == "assignee_id" and f in data.model_fields_set):
            setattr(i, f, v)
    if data.extra is not None:
        i.extra = data.extra or {}
    if data.status == "processing" and not i.assignee_id:
        i.assignee_id = user.id  # 开始处理的人即处理人（无需手动指派）
    if data.status == "resolved" or data.status == "closed":
        if i.resolved_at is None:
            i.resolved_at = utcnow()
    if data.status == "open":
        i.resolved_at = None
    db.flush()
    if i.nature!=old_nature:
        from app.services.document_triggers import issue_event
        issue_event(db,p,i,user.id,previous_nature=old_nature,now=utcnow())
    # C6-6：字段级 old/new 审计
    changed_fields = {}
    for f, old_v in old_values.items():
        new_v = getattr(i, f)
        if old_v != new_v:
            changed_fields[f] = {"old": old_v, "new": new_v}
    if (i.extra or {}) != old_extra:
        changed_fields["extra"] = {"old": old_extra, "new": i.extra or {}}
    log_change(db, i.project_id, "issue", i.id, "update", user.id,
               f"更新问题：{i.title} → 状态 {i.status}",
               old_value=changed_fields, new_value=changed_fields)
    # Notify reporter on resolve
    if data.status == "resolved" and i.reporter_id != user.id:
        from app.routers.notifications import notify
        notify(db, i.reporter_id, f"问题已解决：{i.title}",
               f"解决方案：{data.resolution or '（未填写）'} · 处理人：{user.display_name}",
               ntype="issue_resolved", project_id=i.project_id, entity_id=i.id)
    # Notify reporter on cancel（C6-7：作废有独立状态 + 通知，附原因）
    if data.status == "cancelled" and i.reporter_id != user.id:
        from app.routers.notifications import notify
        notify(db, i.reporter_id, f"问题已作废：{i.title}",
               f"作废原因：{data.resolution or '（未填写）'} · 操作人：{user.display_name}",
               ntype="issue_cancelled", project_id=i.project_id, entity_id=i.id)
    # Notify new assignee on reassignment
    if data.assignee_id is not None and data.assignee_id != old_assignee and data.assignee_id != user.id:
        from app.routers.notifications import notify
        new_assignee = db.get(User, data.assignee_id)
        if new_assignee:
            reporter = db.get(User, i.reporter_id)
            notify(db, new_assignee.id, f"新问题指派给你：{i.title}",
                   f"严重程度：{_SEVERITY_LABELS.get(i.severity, i.severity)} · 上报人：{reporter.display_name if reporter else '已删除用户'}",
                   ntype="issue_assigned", project_id=i.project_id, entity_id=i.id)
    db.commit()
    db.refresh(i)
    from app.services.cache import cache_clear
    cache_clear("dashboard:")
    return _issue_dict(db, i, user)


@router.post("/issues/{issue_id}/reopen")
@route_permission('project.manage_issues')
def reopen_issue(
    issue_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """报告人/处理人/PM 重开已解决或已作废的问题（C6-4 闭环）。

    解决不等于结束：报告人验收不满意可一键重开，回到 open 让处理人继续跟进。
    """
    from app.services.permissions import authorize_project, C_ISSUES
    i = db.get(Issue, issue_id)
    if i is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    p = ensure_project_visible(db, i.project_id, user)
    lock_writable_project(db, p, user)
    # 报告人/被指派人可重开；否则需 C_ISSUES
    if not (i.reporter_id == user.id or i.assignee_id == user.id):
        authorize_project(user, p, C_ISSUES)
    if i.status not in ("resolved", "closed", "cancelled"):
        raise HTTPException(status_code=400, detail=f"仅可重开已解决/已作废的问题（当前 {i.status}）")
    from app.services.optimistic import bump_version
    bump_version(i, None)
    i.status = "open"
    i.resolved_at = None
    i.resolution = ""
    db.flush()
    log_change(db, i.project_id, "issue", i.id, "update", user.id,
               f"报告人重开问题：{i.title}")
    # 重开 → 通知当前处理人（若存在）与新上报人
    from app.routers.notifications import notify
    if i.assignee_id and i.assignee_id != user.id:
        notify(db, i.assignee_id, f"问题被重开：{i.title}",
               f"报告人要求继续跟进 · 操作人：{user.display_name}",
               ntype="issue_reopened", project_id=i.project_id, entity_id=i.id)
    if p.status == "completed" and p.manager:
        notify(db, p.manager, f"已完成项目的问题被重开：{i.title}",
               "请确认是否需要返工；如需执行安排或报工，请先将项目从已完成恢复到验收中。",
               ntype="issue_reopened", project_id=i.project_id, entity_id=i.id)
    db.commit()
    db.refresh(i)
    from app.services.cache import cache_clear
    cache_clear("dashboard:")
    return _issue_dict(db, i, user)


@router.delete("/issues/{issue_id}")
@route_permission('project.manage_issues')
def delete_issue(issue_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.permissions import authorize_project, C_ISSUES
    i = db.get(Issue, issue_id)
    if i is None:
        raise HTTPException(status_code=404, detail="问题不存在")
    p = ensure_project_visible(db, i.project_id, user)
    lock_writable_project(db, p, user)
    authorize_project(user, p, C_ISSUES)
    log_change(db, i.project_id, "issue", i.id, "delete", user.id, f"删除问题：{i.title}")
    db.delete(i)
    db.commit()
    from app.services.cache import cache_clear
    cache_clear("dashboard:")
    return {"message": "问题已删除"}
