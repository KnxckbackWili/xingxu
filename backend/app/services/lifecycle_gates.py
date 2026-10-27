"""Read current lifecycle evidence and report every unmet transition condition."""
from dataclasses import dataclass
from fastapi import HTTPException

from sqlalchemy.orm import Session

from app.models import Issue, Project, ProjectDocument, DocumentVersion, VehicleLifecycleEvent


@dataclass(frozen=True)
class Blocker:
    type: str
    message: str
    url: str


def _pending_required_documents(db: Session, project_id: str, *, archiving=False, stages=None, verify_files=True) -> list[str]:
    stages = stages or (('4','5','6','7','8','9') if archiving else ('4','5','6','7'))
    rows = db.query(ProjectDocument).filter(ProjectDocument.project_id==project_id,
        ProjectDocument.stage_key.in_(stages),ProjectDocument.required.is_(True)).all()
    from app.services.project_documents import applicable
    project = db.get(Project, project_id)
    pending=[]
    for row in rows:
        if not applicable(project,row):continue
        from app.models import Attachment
        evidence = db.query(DocumentVersion,Attachment).join(Attachment,Attachment.id==DocumentVersion.attachment_id).filter(
            DocumentVersion.project_document_id==row.id,Attachment.project_id==project_id).order_by(DocumentVersion.uploaded_at.desc().nullslast(),DocumentVersion.id.desc()).first()
        has_attachment = False
        if evidence and not verify_files:
            # Overview guidance reads submission metadata; the actual transition
            # always checks source bytes. Avoid hashing large files on each view.
            has_attachment = bool(evidence[1].file_size and evidence[1].file_size > 0)
        elif evidence:
            try:
                from app.services.project_documents import validate_file
                validate_file(evidence[1]);has_attachment=True
            except (HTTPException, OSError):
                from app.services.file_retention import retained_submission
                has_attachment=retained_submission(db,project,row,evidence[0],evidence[1])
        satisfied = row.status=='submitted' and has_attachment or row.status=='waived' and bool((row.waived_reason or '').strip())
        if not satisfied:pending.append(f'{row.code} {row.name}')
    if archiving:
        from app.services.document_deadlines import missing_lifetime_requirements
        pending.extend(missing_lifetime_requirements(db,project))
    return pending


def check_transition(db: Session, project: Project, target: str) -> list[Blocker]:
    """Return evidence failures without changing project data or stopping at the first one.

    Route authorization, allowed state edges and suspension reasons remain the
    caller's responsibility. The caller includes a newly supplied retrospective
    on the project before checking an archive request.
    """
    blockers = []

    def add(kind, message, page):
        blockers.append(Blocker(kind, message, f"/pm/projects/{project.id}/{page}"))

    if target == "ready" and project.status == "preparing":
        pending = _pending_required_documents(db, project.id, stages=('4',))
        if pending:
            add('kickoff_documents', '第4阶段必需资料尚未提交或缺少真实原件：' + '、'.join(pending), 'documents?stage=4')
    if target == "acceptance" and project.status == "executing":
        from app.services.project_documents import applicable, validate_file
        from app.models import Attachment
        signatures = {'6.10.1': '到货签收单', '6.10.2': '调试完工单', '6.10.3': '上线运行单', '6.10.4': '培训记录表'}
        missing = []
        for code, name in signatures.items():
            rows = db.query(ProjectDocument).filter_by(project_id=project.id, code=code, scope='project').all()
            valid = False
            for document in rows:
                if not applicable(project, document):
                    continue
                if document.status == 'waived' and (document.waived_reason or '').strip():
                    valid = True
                    continue
                version = db.query(DocumentVersion).filter_by(project_document_id=document.id).order_by(DocumentVersion.uploaded_at.desc().nullslast(), DocumentVersion.id.desc()).first()
                attachment = db.get(Attachment, version.attachment_id) if version else None
                if document.status == 'submitted' and attachment and attachment.project_id == project.id:
                    try:
                        validate_file(attachment)
                        valid = True
                    except (HTTPException, OSError):
                        pass
            if not valid:
                missing.append(f'{code} {name}')
        if missing:
            add('signature_documents', '进入验收前请提交真实签单，或明确标记不适用并填写理由：' + '、'.join(missing), 'documents?stage=6')

    completing = target == "completed" and project.status != "archived"
    archiving = target == "archived"
    if completing or archiving:
        from app.services.progress import project_completion_blockers, project_progress_tree
        from app.services.acceptance import acceptance_summary

        if completing:
            percent = project_progress_tree(db, project.id).get("percent", 0)
            if percent < 100 - 1e-6:
                add("progress", f"项目进度未达 100%（当前 {percent:.1f}%），不能标记为已完成", "plan")

        incomplete = project_completion_blockers(db, project.id)
        if incomplete:
            message = (f"完成依据已变化，不能归档：{'、'.join(incomplete)}。请复核检查项；如需补报或调整计划，请先恢复到验收中处理。"
                       if archiving else f"仍有未完成或检查未通过的任务：{'、'.join(incomplete)}")
            add("tasks", message, "plan")

        pending = _pending_required_documents(db, project.id, archiving=archiving)
        if pending:
            message = (f"必需资料尚未提交或缺少真实附件，不能归档：{'、'.join(pending)}。请重新提交后再归档。"
                       if archiving else f"尚有 {len(pending)} 项必需资料未完成，不能标记为已完成：{'、'.join(pending)}")
            add("documents", message, "documents")

        acceptance = acceptance_summary(db, project.id)
        if not acceptance["eligible"]:
            add("acceptance", acceptance["reason"], "documents?acceptance=1")


        open_issues = db.query(Issue).filter(
            Issue.project_id == project.id, (Issue.status.notin_(["closed", "cancelled"]) | Issue.status.is_(None))).count()
        if open_issues:
            add("issues", f"还有 {open_issues} 个未闭环问题（仅关闭或作废算闭环），不能{'归档' if archiving else '标记为已完成'}", "issues")

        faults = db.query(VehicleLifecycleEvent).filter(VehicleLifecycleEvent.project_id == project.id,
            VehicleLifecycleEvent.is_closed.is_not(True), VehicleLifecycleEvent.event_type == 'fault').order_by(VehicleLifecycleEvent.event_date, VehicleLifecycleEvent.id).all()
        if faults:
            add("vehicle_faults", f"还有 {len(faults)} 个车辆故障未关闭：" + '、'.join(row.title or '未命名故障' for row in faults), "vehicles")

        if archiving and not project.retrospective:
            add("retrospective", "归档前请填写项目复盘（成功经验、问题教训、改进建议）", "overview")

    if target == "executing":
        from app.services.dispatch_review import summary as dispatch_summary
        summary = dispatch_summary(db, project, verify_files=True)
        if (summary["entry_unmet"] or summary["missing"]) and not summary["entry_confirmed"]:
            add("entry_conditions", "第5阶段发车前资料尚未齐备或原风险批准已失效，请核对资料，或明确批准风险进场并填写理由", "documents?review=1")

    return blockers


def completion_review(db: Session, project: Project, target="completed", actor=None) -> dict:
    """A read-only snapshot; the real transition always checks the evidence again."""
    from dataclasses import asdict
    from app.services.manual_completion import review_overrides
    blockers = check_transition(db, project, target)
    if actor is not None:
        from app.services.project_documents import filter_blockers
        blockers=filter_blockers(db,project,actor,blockers)
    return {"project_id": project.id, "project_version": project.version, "target": target,
        "allowed": not blockers, "blockers": [asdict(row) for row in blockers],
        "ordinary_check_overrides": review_overrides(db, project.id)}
