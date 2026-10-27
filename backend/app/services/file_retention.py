"""Only precise, authorized cleanup evidence can stand in for removed old bytes."""
from datetime import datetime,date,timezone
from sqlalchemy.orm import object_session
from app.models import FileRemovalRecord,ProjectDocument

IDENTITY=('stage_key','code','name','scope','vehicle_unit_id','vehicle_label','period_key','platform','timing_type','timing_weekday','required')


def series(row):
    parts=(row.instance_key or '').split(':')
    definition=row.definition_id or (parts[0] if parts else row.code)
    vehicle=row.vehicle_unit_id or (parts[1] if len(parts)>1 else row.vehicle_label)
    return definition,vehicle,row.platform


def periods_kept(documents,count):
    from collections import defaultdict
    from app.services.document_deadlines import period_start
    grouped=defaultdict(set)
    for row in documents:
        if row.stage_key=='legacy' or row.timing_type!='weekly' or not row.period_key:continue
        try:period_start(row.period_key)
        except Exception:continue
        grouped[series(row)].add(row.period_key)
    return {key:set(sorted(values,reverse=True)[:count]) for key,values in grouped.items()}


def _matching_candidate(receipt,record):
    policy=receipt.policy or {}
    if policy.get('kind')!='weekly_retention_v1' or policy.get('fingerprint')!=receipt.preview_sha256:return None
    for item in policy.get('candidates',[]):
        if item.get('attachment_id')==record.attachment_id and item.get('removal_record_id')==record.id:
            if (item.get('sha256'),item.get('file_size'),item.get('stored_name'),item.get('filename'))==(record.sha256,record.file_size,record.stored_name,record.filename):return item
    return None


def removal_record(asset,db=None):
    record=getattr(asset,'removal_record',None)
    if record is None:return None
    receipt=record.receipt
    if (receipt is None or record.project_id!=asset.project_id or receipt.project_id!=asset.project_id
        or (record.sha256,record.file_size,record.stored_name,record.filename)!=(asset.sha256,asset.file_size,asset.stored_name,asset.filename)
        or not record.reason.strip() or record.reason!=receipt.reason or record.removed_at!=receipt.applied_at
        or _matching_candidate(receipt,record) is None):return None
    return record


def removal_payload(asset):
    record=removal_record(asset)
    if record is None:return {'storage_state':'available','removal':None}
    return {'storage_state':'removed_by_policy','removal':{'receipt_id':record.receipt_id,
        'removed_at':record.removed_at.replace(tzinfo=timezone.utc).isoformat(),
        'removed_by_name':record.removed_by_name,'reason':record.reason}}


def retained_submission(db,project,document,version,asset):
    if document.status!='submitted' or document.stage_key=='legacy' or document.timing_type!='weekly':return False
    record=removal_record(asset,db)
    if record is None or document.project_id!=project.id or asset.project_id!=project.id or version.project_document_id!=document.id:return False
    candidate=_matching_candidate(record.receipt,record)
    proof=next((item for item in candidate.get('versions',[]) if item.get('id')==version.id and item.get('document_id')==document.id),None)
    if proof is None or proof.get('document_status')!='submitted':return False
    if proof.get('identity')!={key:getattr(document,key) for key in IDENTITY}:return False
    documents=db.query(ProjectDocument).filter_by(project_id=project.id,timing_type='weekly').all()
    if document.period_key in periods_kept(documents,record.receipt.keep_periods).get(series(document),set()):return False
    return True


def manifest_removal(snapshot,item):
    """Validate a serialized tombstone before skipping an absent archive entry."""
    if item.get('intentionally_removed') is not True:return False
    records=snapshot.get('records',{})
    by_id={row['id']:row for row in records.get('file_removal_records',[])}
    receipts={row['id']:row for row in records.get('file_cleanup_receipts',[])}
    attachments={row['id']:row for row in records.get('attachments',[])}
    references=item.get('references',[])
    if not references or any(ref.get('table')!='attachments' for ref in references):return False
    for ref in references:
        asset=attachments.get(ref.get('id'))
        record=by_id.get((item.get('removal_record_ids') or {}).get(ref.get('id')))
        receipt=receipts.get(record.get('receipt_id')) if record else None
        if not asset or not record or not receipt:return False
        if (record.get('attachment_id'),record.get('project_id'))!=(asset['id'],asset['project_id']):return False
        for key,manifest_key in (('stored_name','stored_name'),('filename','filename'),('sha256','sha256'),('file_size','size')):
            if record.get(key)!=asset.get(key) or record.get(key)!=item.get(manifest_key):return False
        policy=receipt.get('policy') or {}
        if policy.get('kind')!='weekly_retention_v1' or policy.get('fingerprint')!=receipt.get('preview_sha256'):return False
        proof=next((row for row in policy.get('candidates',[]) if row.get('attachment_id')==asset['id'] and row.get('removal_record_id')==record['id']),None)
        if not proof or any(proof.get(key)!=record.get(key) for key in ('stored_name','filename','sha256','file_size')):return False
        if record.get('reason')!=receipt.get('reason') or record.get('removed_at')!=receipt.get('applied_at'):return False
    return True
