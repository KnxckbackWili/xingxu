"""Frozen T22 data conversion. Never imports current app ORM or business services."""
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL
import sqlalchemy as sa
from functools import lru_cache

RULE_KEYS = ('stage_key', 'code', 'name', 'template_no', 'required', 'scope', 'platform', 'timing_type',
             'timing_event', 'timing_offset_hours', 'timing_weekday', 'trigger_type', 'blank_file_id', 'sort_order', 'note', 'source_metadata')
TABLE_COLUMNS = {
 'users': 'id', 'projects': 'id template_id dispatch_platform timezone',
 'tasks': 'id project_id template_id module_id name deliverables source_task_id version',
 'modules': 'id project_id phase_id name', 'phases': 'id name sort_order',
 'attachments': 'id project_id entity_type entity_id filename stored_name file_size content_type uploaded_by uploaded_at confidential sha256',
 'archive_checklists': 'id project_id category item_name is_required is_done done_by done_at attachment_id requirements sort_order',
 'project_preparation_items': 'id project_id category name task_id is_required blocks_entry status owner_id owner_party required_date committed_date forecast_date planned_date actual_date risk affected_phase_id affected_task_id completed_by completed_at note extra sort_order created_at updated_at',
 'template_preparation_items': 'id template_id name category is_required blocks_entry owner_party risk condition sort_order',
 'document_requirements': 'id template_id stage_key code name template_no is_group parent_id required scope platform timing_type timing_event timing_offset_hours timing_weekday trigger_type confidential_default external_visible_default external_never_visible blank_file_id sort_order note source_metadata created_at updated_at',
}
JSON_COLUMNS = {'deliverables', 'requirements', 'extra', 'source_metadata'}
DATE_COLUMNS = {'required_date', 'committed_date', 'forecast_date', 'planned_date', 'actual_date'}
DATETIME_COLUMNS = {'uploaded_at', 'done_at', 'completed_at', 'created_at', 'updated_at'}
BOOL_COLUMNS = {'is_required', 'is_done', 'blocks_entry', 'confidential', 'required', 'is_group', 'confidential_default', 'external_visible_default', 'external_never_visible'}


@lru_cache(maxsize=None)
def table(name):
    def column(key):
        kind = sa.JSON() if key in JSON_COLUMNS else sa.Date() if key in DATE_COLUMNS else sa.DateTime() if key in DATETIME_COLUMNS else sa.Boolean() if key in BOOL_COLUMNS else sa.Integer() if key in {'sort_order', 'timing_offset_hours', 'timing_weekday', 'file_size', 'version'} else sa.String()
        return sa.column(key, kind)
    return sa.table(name, *(column(key) for key in TABLE_COLUMNS[name].split()))


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_value(item) for item in value]
    return value


def instant(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    return None


def legacy_code(kind, identity):
    return 'legacy.' + uuid5(NAMESPACE_URL, 'xingxu-t22:' + kind + ':' + identity).hex


def migrate_legacy_documents(connection, definitions, documents, versions):
    rows = {name: [dict(row) for row in connection.execute(sa.select(table(name))).mappings()] for name in TABLE_COLUMNS}
    users = {row['id'] for row in rows['users']}
    modules = {row['id']: row for row in rows['modules']}
    phases = {row['id']: row for row in rows['phases']}
    projects = {row['id']: row for row in rows['projects']}
    attachments = {row['id']: row for row in rows['attachments']}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    uploads = Path(os.getenv('DATA_DIR', str(Path(__file__).resolve().parents[1] / 'data'))) / 'uploads'
    file_state = {}
    for asset in attachments.values():
        stored = asset['stored_name']
        path = uploads / stored
        safe = isinstance(stored, str) and stored == Path(stored).name and '\\' not in stored and not path.is_symlink() and path.resolve().parent == uploads.resolve()
        digest = None
        if safe and path.is_file():
            sha = hashlib.sha256()
            with path.open('rb') as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                    sha.update(chunk)
            digest = sha.hexdigest()
        file_state[asset['id']] = ('available' if path.stat().st_size==asset['file_size'] else 'file_size_mismatch') if digest else 'missing_or_unsafe_file'
        connection.execute(table('attachments').update().where(table('attachments').c.id == asset['id']).values(sha256=digest))

    def rule(name, identity, source, required=True, stage='legacy', code=None, order=0):
        return {'stage_key': stage, 'code': code or legacy_code(source['kind'], identity), 'name': str(name or '未命名旧资料')[:300],
            'template_no': '', 'required': bool(required), 'scope': 'project', 'platform': None,
            'timing_type': 'on_demand', 'timing_event': None, 'timing_offset_hours': None, 'timing_weekday': None,
            'trigger_type': None, 'blank_file_id': None, 'sort_order': order or 0,
            'note': '旧资料待明确分类，原完成与审核事实保留在来源记录中' if stage == 'legacy' else '', 'source_metadata': json_value(source)}

    def add_project_record(project_id, source_key, values, candidates=(), claimed=False, actor=None, when=None, waived_reason=''):
        if project_id not in projects:
            raise RuntimeError('旧资料所属项目缺失，拒绝丢弃来源记录')
        definition_id, document_id = str(uuid4()), str(uuid4())
        connection.execute(definitions.insert().values(id=definition_id, project_id=project_id, requirement_id=None,
            source_key=source_key, **values, confidential_default=False, external_visible_default=False,
            external_never_visible=False, created_by=actor if actor in users else None, created_at=now))
        evidence = []
        invalid = []
        for attachment_id in dict.fromkeys(candidates):
            asset = attachments.get(attachment_id)
            if asset and asset['project_id'] == project_id:
                evidence.append(asset)
            else:
                invalid.append(attachment_id)
        metadata = dict(values['source_metadata'] or {})
        metadata['evidence'] = [{'attachment_id': asset['id'], 'file_state': file_state[asset['id']]} for asset in evidence]
        metadata['invalid_attachment_refs'] = invalid
        valid_evidence = any(file_state[asset['id']] == 'available' for asset in evidence)
        status = 'waived' if waived_reason.strip() else 'submitted' if claimed and valid_evidence else 'pending'
        connection.execute(documents.insert().values(id=document_id, project_id=project_id, definition_id=definition_id, requirement_id=None,
            instance_key=source_key, **{**values, 'source_metadata': metadata}, vehicle_unit_id=None, vehicle_label='',
            period_key=None, trigger_ref=None, due_at=None, due_is_estimated=False, status=status, waived_reason=waived_reason,
            confidential=False, external_visible=False, external_never_visible=False,
            submitted_by=actor if status == 'submitted' and actor in users else None,
            submitted_at=instant(when) if status == 'submitted' else None, version=1, created_at=now))
        for asset in evidence:
            connection.execute(versions.insert().values(id=str(uuid4()), project_document_id=document_id, attachment_id=asset['id'],
                uploaded_by=actor if actor in users else asset['uploaded_by'] if asset['uploaded_by'] in users else None,
                uploaded_at=instant(when) or asset['uploaded_at'], note='旧资料附件保留', review_metadata=json_value(metadata)))

    # Each old row/item retains a stable source position; no name-based collapsing.
    for task in rows['tasks']:
        module = modules.get(task['module_id']) or {}
        phase = phases.get(module.get('phase_id')) or {}
        old = task['deliverables'] or []
        if not isinstance(old, list):
            raise RuntimeError(f"任务{task['id']}的旧交付物不是数组，迁移拒绝猜测")
        for index, original in enumerate(old):
            item = original if isinstance(original, dict) else {'name': str(original)}
            source = {'kind': 'task_deliverable', 'task': {key: task[key] for key in ('id','name','module_id','source_task_id','version')},
                      'module': module, 'phase': phase, 'index': index, 'original': original}
            identity = f"{task['id']}:{index}"
            values = rule(item.get('name'), identity, source, item.get('required', True), order=index)
            if task['project_id'] is None:
                requirement = {key: value for key, value in values.items() if key != 'blank_file_id'}
                connection.execute(table('document_requirements').insert().values(id=str(uuid4()), template_id=task['template_id'],
                    **requirement, is_group=False, parent_id=None, blank_file_id=None, confidential_default=False,
                    external_visible_default=False, external_never_visible=False, created_at=now, updated_at=now))
            else:
                candidate = item.get('attachment_id')
                add_project_record(task['project_id'], 'task:' + identity, values, [candidate] if isinstance(candidate, str) and candidate else [],
                    claimed=(bool(item.get('done')) or item.get('status') in ('submitted','approved')) and item.get('status') != 'rejected',
                    actor=item.get('submitted_by') or item.get('done_by'), when=item.get('submitted_at') or item.get('done_at'))
        if old:
            connection.execute(table('tasks').update().where(table('tasks').c.id == task['id']).values(deliverables=[]))

    for row in rows['archive_checklists']:
        stage = '7' if row['category'] == '验收文件' and row['item_name'] != '备件与工具移交记录' else '8'
        values = rule(row['item_name'], row['id'], {'kind':'archive_checklist','original':row}, row['is_required'], stage=stage,
                      code=stage + '.legacy.' + uuid5(NAMESPACE_URL, row['id']).hex[:16], order=row['sort_order'])
        candidate = row['attachment_id']
        add_project_record(row['project_id'], 'archive:' + row['id'], values, [candidate] if candidate else [],
                           claimed=row['is_done'], actor=row['done_by'], when=row['done_at'])

    # Only exact company-list names (and the explicit CAD synonym) are classified.
    frozen_company_rows = json.loads(Path(__file__).with_name('v3_document_requirements_seed.json').read_text())
    company_names = {row['name']: row for row in frozen_company_rows if row['stage_key'] in ('4','5') and not row['is_group']}
    if 'CAD 布局图' in company_names:
        company_names['现场布局图'] = company_names['CAD 布局图']
    for row in rows['project_preparation_items']:
        if row['category'] == 'procurement':
            continue
        matched = company_names.get(row['name'])
        source = {'kind':'preparation_item','original':row, 'classification':'exact_company_name' if matched else 'unclassified'}
        stage = matched['stage_key'] if matched else 'legacy'
        code = stage + '.legacy.' + uuid5(NAMESPACE_URL, row['id']).hex[:16] if matched else None
        values = rule(row['name'], row['id'], source, row['is_required'], stage=stage, code=code, order=row['sort_order'])
        candidates = [asset['id'] for asset in attachments.values() if asset['project_id'] == row['project_id']
                      and asset['entity_type'] in ('preparation_item','preparation') and asset['entity_id'] == row['id']]
        extra = row['extra'] if isinstance(row['extra'], dict) else {}
        reason = next((extra.get(key) for key in ('not_applicable_reason', 'waived_reason', 'na_reason')
                       if isinstance(extra.get(key), str) and extra[key].strip()), '') if row['status'] == 'na' else ''
        add_project_record(row['project_id'], 'preparation:' + row['id'], values, candidates,
                           claimed=row['status'] == 'passed', actor=row['completed_by'], when=row['completed_at'], waived_reason=reason)
    for row in rows['template_preparation_items']:
        if row['category'] == 'procurement':
            continue
        identity = row['id']
        values = rule(row['name'], identity, {'kind':'template_preparation_item','original':row}, row['is_required'], order=row['sort_order'])
        connection.execute(table('document_requirements').insert().values(id=str(uuid4()), template_id=row['template_id'],
            **values, is_group=False, parent_id=None, confidential_default=False, external_visible_default=False,
            external_never_visible=False, created_at=now, updated_at=now))
