"""定时周报：生成报告 → 通知项目 PM。

分层设计：
- 纯函数（generate_and_notify_weekly_report）只依赖 (db, ref_date)，
  可独立单测；
- APScheduler job 是薄壳：自建 SessionLocal（线程任务不可用请求级 get_db），
  commit / rollback 收尾。
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app import config
from app.time_utils import utcnow
from app.db import SessionLocal
from app.models import Project, User
from app.services.change_log import log_change
from app.services.notify import notify
from app.services.system_permissions import has_permission
from app.services.reports import generate_project_report
from app.services.project_lifecycle import ACTIVE_PROJECT_STATUSES

logger = logging.getLogger(__name__)


def _pm_user(db: Session, project: Project) -> Optional[User]:
    """项目 PM 收件人：project.manager（user_id）优先，失活则跳过。"""
    if not project.manager:
        return None
    u = db.get(User, project.manager)
    return u if (u and u.is_active and has_permission(u,'project.read',default=True)) else None


def _deliver(
    db: Session, project: Project, period: str, ref: date, title: str, content: str
) -> bool:
    """通知 PM + 审计（operator_id=None 表示系统操作）。返回是否实际通知。"""
    pm = _pm_user(db, project)
    notified = False
    if pm is not None:
        notify(
            db,
            pm.id,
            title,
            content,
            ntype="report",
            project_id=project.id,
            entity_id=project.id,
        )
        notified = True
    log_change(
        db,
        project.id,
        "project",
        project.id,
        "report",
        None,
        f"系统定时生成「{title}」",
        None,
        {"period": period, "ref_date": ref.isoformat()},
    )
    return notified


def _run(db: Session, period: str, ref: date, label: str) -> dict:
    """遍历活跃项目生成报告并通知 PM。"""
    count = 0
    notified = 0
    skipped = []
    for p in (
        db.query(Project)
        .filter(
            Project.status.in_(ACTIVE_PROJECT_STATUSES),
            Project.deleted_at.is_(None),
        )
        .all()
    ):
        pm=db.get(User,p.manager) if p.manager else None
        from app.services.system_permissions import has_permission
        if pm is None or not pm.is_active or not has_permission(pm,'project.read',default=True):
            skipped.append(p.name);continue
        r = generate_project_report(db,p,period,ref,user=pm)
        s = r["summary"]
        ok = _deliver(
            db,
            p,
            period,
            ref,
            f"「{p.name}」{label}",
            f"周期 {r['period_label']}：实际操作 {s['actual_records']} 条 · {s['person_count']} 人，"
            f"工作完成 {s['completed_work']} 项、车辆环节完成 {s['vehicle_completions']} 条，"
            f"新增问题 {s['issues_opened']}、解决 {s['issues_resolved']}、"
            f"未解决 {s['open_issues']}，下周期周计划 {s['next_period_tasks'] if s['next_period_tasks'] is not None else '尚未读取'}",
        )
        count += 1
        if ok:
            notified += 1
        else:
            skipped.append(p.name)
    return {
        "projects": count,
        "notified": notified,
        "skipped": skipped,
        "period": period,
        "ref_date": ref.isoformat(),
    }


def _weekly_clock():
    try:
        hour,minute=(int(value) for value in config.REPORT_WEEKLY_TIME.split(':'))
        return time(hour,minute)
    except (AttributeError,ValueError,TypeError):
        return time(20,0)


def generate_and_notify_weekly_report(db: Session, ref_date: Optional[date] = None, now=None, _project_id=None) -> dict:
    """Site-local Sunday reports; explicit ref_date selects that ISO week.

    Polling catches up the latest due period. A durable project/week receipt and
    the project lock keep restarts and multiple scheduler workers idempotent.
    """
    from app.models import ProjectReportReceipt,Notification
    from sqlalchemy import null
    from app.services.document_deadlines import local_now,week_start,period_key,period_start,utc
    from app.services.record_lock import lock_record
    now=utc(now)
    result={'projects':0,'notified':0,'skipped':[],'period':'week','periods':[]}
    projects=db.query(Project).filter(Project.status.in_(ACTIVE_PROJECT_STATUSES),Project.deleted_at.is_(None)).order_by(Project.id).all()
    if _project_id is not None:projects=[project for project in projects if project.id==_project_id]
    for project in projects:
        lock_record(db,project,conflict_detail='周报生成与项目修改冲突，请稍后重试')
        if project.deleted_at or project.status not in ACTIVE_PROJECT_STATUSES:continue
        local=local_now(project,now)
        current=week_start(ref_date or local.date())
        if ref_date is None and (local.weekday()!=6 or local.timetz().replace(tzinfo=None)<_weekly_clock()):
            current-=timedelta(days=7)
        if ref_date is None:
            receipts=db.query(ProjectReportReceipt.period_key,ProjectReportReceipt.delivery_pending).filter_by(project_id=project.id).all()
            catchup={period_start(row.period_key) for row in receipts if row.delivery_pending and period_start(row.period_key)<current}
            if receipts:
                cursor=max(period_start(row.period_key) for row in receipts)+timedelta(days=7)
                while cursor<current:
                    catchup.add(cursor);cursor+=timedelta(days=7)
            for missed in sorted(catchup):
                recovered=generate_and_notify_weekly_report(db,ref_date=missed,now=now,_project_id=project.id)
                for field in ('projects','notified'):result[field]+=recovered[field]
                for field in ('skipped','periods'):result[field].extend(recovered[field])
        end=current+timedelta(days=6)
        created=local_now(project,project.created_at).date() if project.created_at else project.start_date
        if end<max(project.start_date,created):continue
        key=period_key(current)
        receipt=db.query(ProjectReportReceipt).filter_by(project_id=project.id,period_key=key).first()
        if receipt and not receipt.delivery_pending:continue
        pm=_pm_user(db,project)
        if pm is None:
            if receipt is None:
                db.add(ProjectReportReceipt(project_id=project.id,period_key=key,delivery_pending=True,delivered_at=null(),
                    summary={'delivery_pending':True,'warning':'没有活跃项目经理','attempted_at':now.isoformat()}))
                for admin in db.query(User).filter_by(role='admin',is_active=True):
                    if not has_permission(admin,'project.read',default=True):continue
                    notify(db,admin.id,f'「{project.name}」周报负责人需核对'[:200],
                           f'{key}周报尚未投递：没有活跃项目经理。请修正项目负责人后重试。',
                           ntype='system',project_id=project.id,channels=False)
                log_change(db,project.id,'project',project.id,'report_unassigned',None,'周报因缺少活跃项目经理等待投递',None,{'period_key':key})
                db.flush()
            result['skipped'].append({'project_id':project.id,'reason':'没有活跃项目经理，尚未投递'})
            continue
        label=f'{current.isoformat()} ~ {end.isoformat()}'
        previous=db.query(Notification).filter(Notification.project_id==project.id,Notification.ntype=='report',
            Notification.title.contains('项目周报'),Notification.content.contains('周期 '+label)).order_by(Notification.created_at.desc()).first()
        if previous:
            values={'recipient_id':previous.user_id,'delivered_at':previous.created_at,'delivery_pending':False,
                    'summary':{'adopted_notification_id':previous.id,'period_label':label}}
            if receipt is None:db.add(ProjectReportReceipt(project_id=project.id,period_key=key,**values))
            else:
                for name,value in values.items():setattr(receipt,name,value)
            log_change(db,project.id,'project',project.id,'report_receipt',None,'接续已有周报投递记录',None,{'period_key':key,'notification_id':previous.id})
            continue
        report=generate_project_report(db,project,'week',current,user=pm,now=now)
        summary=report['summary']
        content=(f'周期 {report["period_label"]}：本周资料提交 {summary["documents_submitted"]} 项 / {summary["document_versions"]} 个版本，'
            f'车辆进度变化 {summary["vehicle_progress_changes"]} 条；新增问题 {summary["issues_opened"]}、解决 {summary["issues_resolved"]}，'
            f'当前逾期资料 {report["document_summary"]["overdue"]} 项。')
        _deliver(db,project,'week',current,f'「{project.name}」项目周报'[:200],content)
        values={'recipient_id':pm.id,'delivered_at':now,'delivery_pending':False,'summary':{**summary,'document_summary':report['document_summary'],
                'document_submissions':report['document_submissions'],'vehicle_progress_changes':report['vehicle_progress_changes']}}
        if receipt is None:db.add(ProjectReportReceipt(project_id=project.id,period_key=key,**values))
        else:
            values['summary']['previous_delivery_warning']=receipt.summary
            for name,value in values.items():setattr(receipt,name,value)
        result['projects']+=1;result['notified']+=1;result['periods'].append({'project_id':project.id,'period_key':key})
        db.flush()
    return result


def maintain_document_deadlines(db: Session, now=None) -> dict:
    from app.services.document_deadlines import utc,remind_project
    from app.services.project_documents import materialize_static
    from app.services.record_lock import lock_record
    now=utc(now)
    result={'projects':0,'notified':0,'owner_missing':0}
    for project in db.query(Project).filter(Project.deleted_at.is_(None),Project.status.in_(ACTIVE_PROJECT_STATUSES)).order_by(Project.id).all():
        lock_record(db,project,conflict_detail='资料规则生成与项目修改冲突，请稍后重试')
        if project.deleted_at or project.status not in ACTIVE_PROJECT_STATUSES:continue
        materialize_static(db,project,now=now)
        summary=remind_project(db,project,now)
        result['projects']+=1;result['notified']+=summary['notified'];result['owner_missing']+=summary['owner_missing']
    return result


def scan_overdue_issues(db: Session, ref_date: Optional[date] = None, now=None) -> dict:
    """Nature-specific elapsed-hour SLA; durable receipts prevent repeated alerts."""
    from app.models import Issue
    from app.services.document_triggers import issue_sla,claim_sla,NATURES,sla_hours,issue_events
    from app.services.document_deadlines import utc
    from app.services.record_lock import lock_record
    now=utc(now)
    scanned=notified=0
    projects=db.query(Project).filter(Project.status.in_(ACTIVE_PROJECT_STATUSES),Project.deleted_at.is_(None)).order_by(Project.id).all()
    for project in projects:
        lock_record(db,project,conflict_detail='问题SLA扫描与项目修改冲突，请稍后重试')
        if project.deleted_at or project.status not in ACTIVE_PROJECT_STATUSES:continue
        rows=db.query(Issue).filter(Issue.project_id==project.id,
            (Issue.status.notin_(['closed','cancelled']) | Issue.status.is_(None))).order_by(Issue.id).all()
        sources=issue_events(db,rows)
        recipients={person.id:person for person in db.query(User).filter(User.is_active.is_(True),User.role=='director')
                    if has_permission(person,'project.read',default=True)}
        pm=_pm_user(db,project)
        if pm:recipients[pm.id]=pm
        if not recipients:
            recipients={person.id:person for person in db.query(User).filter_by(is_active=True,role='admin')
                        if has_permission(person,'project.read',default=True)}
        for issue in rows:
            sla=issue_sla(db,issue,sources)
            if sla['due_at'] is None or now<sla['due_at']:continue
            scanned+=1
            delivered=[]
            for identity in sorted(recipients):
                if not claim_sla(db,issue,identity,sla['hours']):continue
                notify(db,identity,f'「{project.name}」问题 SLA 超时提醒'[:200],
                    f'{issue.title}（{NATURES.get(issue.nature,"普通")}）：已超过{sla["hours"]}小时处理时限，当前{issue.status}。仅关闭或作废算闭环，请核对处理。',
                    ntype='issue_sla',project_id=project.id,entity_id=issue.id)
                delivered.append(identity);notified+=1
            if delivered:
                log_change(db,project.id,'issue',issue.id,'sla',None,'按问题性质发送SLA提醒',None,
                    {'nature':issue.nature,'hours':sla['hours'],'due_at':sla['due_at'].isoformat(),'recipients':delivered,'basis':sla['basis']})
            elif not recipients and claim_sla(db,issue,None,sla['hours']):
                log_change(db,project.id,'issue',issue.id,'sla_unassigned',None,'问题SLA提醒缺少有读取权限的负责人，请管理员接手',None,
                    {'nature':issue.nature,'hours':sla['hours']})
    return {'scanned':scanned,'notified':notified,'sla_days':config.ISSUE_SLA_DAYS,
            'sla_hours':{nature:sla_hours(nature) for nature in NATURES}}


def _parse_hhmm(value: str):
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _record_watermark(db: Session, job_id: str, ok: bool = True) -> None:
    """记录 job 运行水位（E3）：成功记 last_success_at，失败记 last_status=error。"""
    from app.models import SchedulerWatermark

    row = (
        db.query(SchedulerWatermark).filter(SchedulerWatermark.job_id == job_id).first()
    )
    if row is None:
        row = SchedulerWatermark(job_id=job_id)
        db.add(row)
    if ok:
        row.last_success_at = utcnow()
    row.last_status = "ok" if ok else "error"
    row.updated_at = utcnow()
    db.flush()


def _run_with_session(func, job_id: Optional[str] = None) -> None:
    """线程 job 壳：自建会话，独立事务，成功/失败都落水位（E3）。"""
    db = SessionLocal()
    try:
        func(db)
        if job_id:
            _record_watermark(db, job_id, ok=True)
        db.commit()
    except Exception:
        db.rollback()
        if job_id:
            db2 = SessionLocal()
            try:
                _record_watermark(db2, job_id, ok=False)
                db2.commit()
            except Exception:
                db2.rollback()
            finally:
                db2.close()
        logger.exception("定时任务失败（%s）", job_id or "unknown")
    finally:
        db.close()


def _weekly_job() -> None:
    _run_with_session(generate_and_notify_weekly_report, job_id="weekly_report")


def _overdue_job() -> None:
    _run_with_session(scan_overdue_issues, job_id="issue_sla_scan")


def purge_soft_deleted_projects(db: Session, retention_days: int = 30) -> dict:
    """#85 compatibility entrypoint: recycling never schedules permanent deletion."""
    return {'purged': 0, 'blocked': 0, 'disabled': True, 'blocked_reason': '自动物理清理已停用；仅管理员可在回收站备份后明确永久删除'}


def _purge_job() -> None:
    # Old external callers stay harmless even if they retained this symbol.
    return None


def _outbox_job() -> None:
    """HYPE-58：每分钟投递 notification_outbox 到期条目（独立 scheduler 进程，不阻塞 Web）。"""
    from app.services.notify_channels import deliver_outbox

    _run_with_session(lambda s: deliver_outbox(s), job_id="notify_outbox_drain")


def _document_deadlines_job() -> None:
    _run_with_session(maintain_document_deadlines,job_id='document_deadlines')


def _storage_maintenance_job() -> None:
    from app.services.storage_maintenance import maintain_storage
    _run_with_session(maintain_storage,job_id='storage_maintenance')


def catch_up_missed_jobs() -> dict:
    """Inspect real local periods after restart; receipts prevent duplicate delivery."""
    _document_deadlines_job()
    _weekly_job()
    _overdue_job()
    return {'caught_up':['document_deadlines','weekly_report','issue_sla_scan']}


def start_scheduler():
    """启动后台调度器（线程模型，与 FastAPI 事件循环无冲突）。

    由 main.py lifespan 调用，仅当 config.SCHEDULER_ENABLED 为真。
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler(timezone=config.TIMEZONE)  # 显式时区，勿依赖进程 TZ
    sched.add_job(
        _weekly_job,
        "interval",
        seconds=60,
        id="weekly_report",
        replace_existing=True,
    )
    sched.add_job(_document_deadlines_job,'interval',seconds=60,id='document_deadlines',replace_existing=True)
    sched.add_job(_storage_maintenance_job,'interval',hours=1,id='storage_maintenance',replace_existing=True)
    sched.add_job(
        _overdue_job,
        "interval",
        seconds=60,
        id="issue_sla_scan",
        replace_existing=True,
    )
    # HYPE-58：出站通知队列投递（每分钟，失败可退避重试；见 notify_channels.deliver_outbox）
    sched.add_job(
        _outbox_job,
        "interval",
        seconds=60,
        id="notify_outbox_drain",
        replace_existing=True,
    )
    sched.start()
    # E3 自愈：启动时补跑崩溃期间遗漏的定时任务（水位落后才补，幂等）
    try:
        caught = catch_up_missed_jobs()
        if caught["caught_up"]:
            logger.info("调度器自愈补跑：%s", caught["caught_up"])
    except Exception:
        logger.exception("调度器自愈补跑失败（不影响正常调度）")
    return sched
