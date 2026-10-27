"""Dispatch decisions bind actual stage-five document evidence, never procurement."""
import hashlib
import json
from datetime import timedelta
from fastapi import HTTPException
from app.models import ProjectDocument, ProjectDocumentDefinition, DocumentVersion, Attachment, ProjectReadinessReview, User
from app.services import project_documents as docs
from app.services.change_log import log_change
from app.time_utils import utcnow

BASIS = 'dispatch_documents_v1'


def manifest(db, project, *, verify_files=True):
    now = utcnow()
    definitions = [row for row in db.query(ProjectDocumentDefinition).filter_by(project_id=project.id, stage_key='5').populate_existing().all() if docs.applicable(project, row)]
    documents = [row for row in db.query(ProjectDocument).filter_by(project_id=project.id, stage_key='5').populate_existing().all() if docs.applicable(project, row)]
    rows = []
    for document in documents:
        if not document.required:
            continue
        version = db.query(DocumentVersion).filter_by(project_document_id=document.id).order_by(DocumentVersion.uploaded_at.desc().nullslast(), DocumentVersion.id.desc()).populate_existing().first()
        asset = db.get(Attachment, version.attachment_id, populate_existing=True) if version else None
        available = False
        retained = False
        if asset and asset.project_id == project.id and asset.file_size and asset.file_size > 0:
            try:
                if verify_files:
                    docs.validate_file(asset)
                else:
                    path = docs.file_path(asset)
                    if path.stat().st_size != asset.file_size:
                        raise HTTPException(409, '原件大小变化')
                available = True
            except (HTTPException, OSError):
                from app.services.file_retention import retained_submission
                retained = retained_submission(db, project, document, version, asset)
        satisfied = document.status == 'submitted' and (available or retained)
        waived = document.status == 'waived' and bool((document.waived_reason or '').strip())
        rows.append({'basis': BASIS, 'id': document.id, 'kind': 'document', 'code': document.code,
            'name': document.name, 'definition_id': document.definition_id, 'vehicle_unit_id': document.vehicle_unit_id,
            'period_key': document.period_key, 'scope': document.scope, 'is_required': True, 'blocks_entry': True,
            'document_status': document.status, 'status': 'passed' if satisfied else 'na' if waived else 'pending',
            'version': document.version, 'latest_version_id': version.id if version else None,
            'attachment_id': asset.id if asset else None, 'sha256': asset.sha256 if asset else None,
            'file_size': asset.file_size if asset else None, 'original_available': available, 'retained_by_policy': retained, 'due_is_estimated': document.due_is_estimated,
            'due_at': docs.iso(document.due_at), 'overdue': bool(document.due_at and document.due_at < now and not (satisfied or waived)),
            'confidential': document.confidential, 'waived_reason': document.waived_reason if waived else ''})
    instantiated = {row.definition_id for row in documents}
    for definition in definitions:
        if definition.required and definition.id not in instantiated:
            rows.append({'basis': BASIS, 'id': f'definition:{definition.id}', 'kind': 'definition',
                'definition_id': definition.id, 'code': definition.code, 'name': definition.name,
                'is_required': True, 'blocks_entry': True, 'status': 'pending', 'scope': definition.scope,
                'confidential': definition.confidential_default, 'reason': '资料实例尚未生成，请核对真实车辆和输出时机'})
    missing = [] if definitions or documents else ['未配置第5阶段发车前资料要求，请明确范围，或填写理由批准风险进场。']
    if missing:
        rows.append({'basis': BASIS, 'id': 'missing_scope', 'kind': 'scope', 'status': 'pending', 'name': missing[0], 'is_required': True, 'blocks_entry': True})
    rows.sort(key=lambda row: row['id'])
    token = hashlib.sha256(json.dumps([project.id, rows], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    unmet = [row for row in rows if row['status'] == 'pending' and row['kind'] != 'scope']
    return {'basis': BASIS, 'snapshot': rows, 'met': [row for row in rows if row['status'] == 'passed'],
        'not_applicable': [row for row in rows if row['status'] == 'na'], 'unmet': unmet, 'entry_unmet': unmet,
        'risks': [row for row in unmet if row.get('overdue') or row.get('reason')], 'missing': missing, 'review_token': token}


def _latest(db, project):
    return db.query(ProjectReadinessReview).filter_by(project_id=project.id).order_by(ProjectReadinessReview.reviewed_at.desc().nullslast(), ProjectReadinessReview.id.desc()).populate_existing().first()


def _worsened(current, previous):
    if previous is None or previous.get('status') != 'pending':
        return True
    identity = ('kind', 'code', 'name', 'definition_id', 'vehicle_unit_id', 'period_key', 'scope', 'is_required')
    if any(current.get(key) != previous.get(key) for key in identity):
        return True
    due, old_due = current.get('due_at'), previous.get('due_at')
    return bool(current.get('overdue') and not previous.get('overdue') or due and (not old_due or due < old_due))


def summary(db, project, *, verify_files=False):
    current = manifest(db, project, verify_files=verify_files)
    pending = [row for row in current['snapshot'] if row['status'] == 'pending']
    latest = _latest(db, project)
    canonical = bool(latest and latest.snapshot and all(isinstance(row, dict) and row.get('basis') == BASIS for row in latest.snapshot))
    accepted = {row['id']: row for row in latest.snapshot} if canonical else {}
    risk = bool(latest and latest.conclusion == 'risky' and latest.notes.strip() and canonical
        and not any(_worsened(row, accepted.get(row['id'])) for row in pending))
    confirmed = not pending or risk
    void = bool(pending and latest and latest.conclusion in {'ready', 'risky'} and not risk)
    state = 'ready' if not pending else 'forced_ready' if risk else 'unready'
    return {'basis': BASIS, 'total': len(current['snapshot']), 'done': len(current['met']) + len(current['not_applicable']),
        'required_total': len(current['snapshot']), 'required_done': len(current['met']) + len(current['not_applicable']),
        'entry_unmet': len(current['entry_unmet']), 'unfinished': len(pending), 'blocked': len(pending),
        'overdue': sum(bool(row.get('overdue')) for row in pending), 'late_items': 0,
        'missing': bool(current['missing']), 'entry_confirmed': confirmed, 'void': void,
        'state_key': state, 'state': {'ready': '发车前资料齐备', 'forced_ready': '已批准风险进场', 'unready': '发车前资料待落实'}[state],
        'readiness_state': project.readiness_state, 'confirmed_by': project.prep_confirmed_by,
        'confirmed_at': docs.iso(project.prep_confirmed_at), 'conclusion': '', 'legacy_review': bool(latest and not canonical)}


def visible_manifest(db, project, actor, current):
    result = {key: value for key, value in current.items() if key != 'snapshot'}
    for key in ('met', 'not_applicable', 'unmet', 'entry_unmet', 'risks'):
        visible = []
        for item in current[key]:
            row = db.get(ProjectDocument, item['id']) if item['kind'] == 'document' else db.get(ProjectDocumentDefinition, item.get('definition_id')) if item['kind'] == 'definition' else None
            allowed = bool(row and docs.can_read_document(actor, project, row)) if item['kind'] == 'document' else bool(row and docs.can_read_definition(actor, project, row)) if item['kind']=='definition' else True
            projected = dict(item) if allowed else {'name': '受限资料，请由有查看权限的负责人核对', 'status': item['status'], 'is_required': True, 'restricted': True}
            if allowed and item.get('attachment_id'):
                asset = db.get(Attachment, item['attachment_id'])
                if asset is None or not docs.can_read_file(actor, project, asset):
                    projected.update(attachment_id=None, sha256=None, file_size=None, latest_version_id=None, original_available=None, retained_by_policy=None, file_restricted=True)
            visible.append(projected)
        result[key] = visible
    return result


def confirm(db, project, actor, *, conclusion, notes, review_token):
    current = manifest(db, project)
    if review_token != current['review_token']:
        raise HTTPException(409, '发车前资料及原件已变化，请重新核对后确认')
    if conclusion == 'ready' and (current['entry_unmet'] or current['missing']):
        raise HTTPException(400, '第5阶段必需资料尚未齐备，请补交，或明确批准风险进场并填写理由')
    if conclusion == 'risky' and not notes.strip():
        raise HTTPException(400, '风险进场必须填写理由')
    previous = _latest(db, project)
    now = utcnow()
    if previous and previous.reviewed_at:
        now = max(now, previous.reviewed_at + timedelta(microseconds=1))
    review = ProjectReadinessReview(project_id=project.id, conclusion=conclusion, reviewer_id=actor.id,
        reviewed_at=now, notes=notes.strip(), remaining_risks=current['entry_unmet'], snapshot=[{'basis': BASIS, 'id': 'review_basis', 'kind': 'metadata', 'status': 'na'}] + current['snapshot'])
    db.add(review)
    project.readiness_state = 'ready' if conclusion == 'ready' else 'risky' if conclusion == 'risky' else 'preparing'
    project.prep_confirmed_by = actor.id; project.prep_confirmed_at = now; project.prep_conclusion = '发车前资料确认已记录，具体说明见受权限控制的确认记录'
    log_change(db, project.id, 'project', project.id, 'update', actor.id, '发车前资料确认：' + {'ready': '资料齐备', 'risky': '批准风险进场', 'not_ready': '暂不进场'}[conclusion])
    db.flush()
    return review


def history(db, project, actor):
    result = []
    hidden = any(not docs.can_read_document(actor, project, row) for row in db.query(ProjectDocument).filter_by(project_id=project.id, confidential=True).all())
    for row in db.query(ProjectReadinessReview).filter_by(project_id=project.id).order_by(ProjectReadinessReview.reviewed_at.desc().nullslast(), ProjectReadinessReview.id.desc()).all():
        canonical = bool(row.snapshot and all(isinstance(item, dict) and item.get('basis') == BASIS for item in row.snapshot))
        reviewer = db.get(User, row.reviewer_id)
        historical_hidden = hidden or any(isinstance(item, dict) and item.get('confidential') and item.get('kind') == 'document' and not db.get(ProjectDocument, item.get('id')) and actor.id != project.manager for item in (row.snapshot or []))
        result.append({'id': row.id, 'conclusion': row.conclusion, 'reviewer_name': reviewer.display_name if reviewer else '',
            'reviewed_at': docs.iso(row.reviewed_at), 'notes': '原记录可能含受限资料，说明需由有权限负责人查看' if historical_hidden else row.notes,
            'snapshot_count': sum(isinstance(item, dict) and item.get('kind') != 'metadata' for item in (row.snapshot or [])), 'basis': BASIS if canonical else 'legacy_preparations', 'legacy': not canonical})
    return result
