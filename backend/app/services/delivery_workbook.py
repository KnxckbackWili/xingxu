"""Six delivery worksheets, with one actor-aware evidence boundary and no mutations."""
import io
import json
import re
import math
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app import models
from app.services.permissions import authorize_project, C_EXPORT
from app.services.scope import ensure_project_visible
from app.services.project_documents import can_read_document, can_read_file
from app.services.report_forms import LIFECYCLE_HEADERS, LIFECYCLE_WIDTHS
from app.services.inventory_time import inventory_time_basis

SHEET_NAMES = ('交付概览', '生命周期表', '问题清单', '物资清单', '收发流水', '交付资料')
INVENTORY_HEADERS = ['物品编码', '名称', '规格', '序列号', '归属', '现存数量', '单位', '位置', '保管人', '说明']
MOVEMENT_HEADERS = ['发生时间（UTC）', '时间依据', '物品', '动作', '数量', '结余', '原位置', '新位置', '经手人', '说明']
_TEXT_CHUNK = 16000  # Below Excel's UTF-16 cell limit, including astral characters.
_XML_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
_KIND = {'hardware': '硬件', 'software': '软件', 'environment': '环境', 'process': '流程', 'safety': '安全', 'other': '其他'}
_STATUS = {'open': '待处理', 'processing': '处理中', 'resolved': '已解决', 'closed': '已关闭', 'cancelled': '已作废'}


def _text(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str):
        return _XML_CONTROL.sub(lambda match: '\\u%04x' % ord(match.group()), value)
    return value


def _iso(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.astimezone(timezone.utc).isoformat()
    return value.isoformat() if value else ''


def _sheet(book, name, headers, *, title=None):
    sheet = book.create_sheet(name)
    if title:
        sheet.append([_text(title)])
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers) + 1)
        sheet.cell(1, 1).fill = PatternFill('solid', fgColor='1677FF')
        sheet.cell(1, 1).font = Font(name='微软雅黑', size=14, bold=True, color='FFFFFF')
        sheet.row_dimensions[1].height = 30
    sheet.append(headers + ['记录分段'])
    header_row = 2 if title else 1
    for cell in sheet[header_row]:
        cell.fill = PatternFill('solid', fgColor='1F4E79')
        cell.font = Font(name='微软雅黑', bold=True, color='FFFFFF')
        cell.alignment = Alignment(vertical='center', wrap_text=True)
        sheet.column_dimensions[cell.column_letter].width = 23 if cell.column <= 5 else 27
    sheet.row_dimensions[header_row].height = 34
    sheet.freeze_panes = f'B{header_row + 1}'
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 90
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth, sheet.page_setup.fitToHeight = 1, 0
    sheet.print_title_rows = f'{header_row}:{header_row}'
    return sheet, header_row


def _append(sheet, values, *, identities=()):
    """Continuation rows preserve long text and do not double-count quantities."""
    values = [_text(value) for value in values]
    pieces = [[value[i:i + _TEXT_CHUNK] for i in range(0, len(value), _TEXT_CHUNK)] or ['']
              if isinstance(value, str) else [value] for value in values]
    total = max(map(len, pieces), default=1)
    for part in range(total):
        row = [chunks[part] if part < len(chunks) else values[index] if index in identities else None
               for index, chunks in enumerate(pieces)]
        sheet.append(row + [f'{part + 1}/{total}' if total > 1 else ''])


def _documents(db, project, actor, assets):
    documents = db.query(models.ProjectDocument).filter_by(project_id=project.id).order_by(models.ProjectDocument.sort_order, models.ProjectDocument.code, models.ProjectDocument.id).all()
    versions = db.query(models.DocumentVersion).filter(models.DocumentVersion.project_document_id.in_([row.id for row in documents])).order_by(models.DocumentVersion.uploaded_at.asc().nullsfirst(), models.DocumentVersion.id).all()
    # Classify against all documents before hiding any of them. A public-file
    # flag must not re-expose a private document's filename as "unclassified".
    classified = {row.attachment_id for row in versions}
    classified.update(getattr(row, 'attachment_id', None) for row in documents if getattr(row, 'attachment_id', None))
    visible = [row for row in documents if can_read_document(actor, project, row)]
    grouped = {}
    for version in versions:
        asset = assets.get(version.attachment_id)
        if asset is not None:
            grouped.setdefault(version.project_document_id, []).append((version, asset))
    for document in visible:
        if document.id not in grouped and getattr(document, 'attachment_id', None) in assets:
            grouped[document.id] = [(None, assets[document.attachment_id])]
    return visible, grouped, classified


def visible_delivery_files(db, project, actor):
    """File inclusion for the workbook and its complete project package."""
    if actor is None:
        raise ValueError('项目交付导出必须提供当前账号')
    assets = {row.id: row for row in db.query(models.Attachment).filter_by(project_id=project.id) if can_read_file(actor, project, row)}
    documents, grouped, classified = _documents(db, project, actor, assets)
    allowed = {asset.id for document in documents for _, asset in grouped.get(document.id, [])} | (set(assets) - classified)
    return {key: assets[key] for key in allowed}


def _overview(db, book, project, documents, visible_assets, users):
    from app.services.progress import project_progress_tree, execution_tasks, task_progress_maps
    from app.services.project_events import events_for_project
    sheet, header = _sheet(book, SHEET_NAMES[0], ['类别', '项目/指标', '内容', '补充说明'], title=f'{project.name} · 交付概览')
    tasks = execution_tasks(db, project.id)
    _, _, percent = task_progress_maps(db, tasks)
    issues = db.query(models.Issue).filter_by(project_id=project.id).all()
    info = [('项目名称', project.name), ('项目缩写', project.abbreviation), ('客户', project.client),
            ('实施地点', project.location), ('项目状态', project.status), ('开始日期', _iso(project.start_date)),
            ('结束日期', _iso(project.end_date)), ('现场时区', project.timezone), ('调度平台', project.dispatch_platform),
            ('项目负责人', users.get(project.manager, project.manager or '')), ('技术负责人', users.get(project.technical_manager, project.technical_manager or '')),
            ('整体进度 %', project_progress_tree(db, project.id)['percent']), ('执行任务数', len(tasks)),
            ('已完成任务数', sum(percent.get(row.id, 0) >= 100 for row in tasks)),
            ('未闭环问题', sum(row.status not in {'closed', 'cancelled'} for row in issues)),
            ('可见资料项', len(documents)), ('可见附件数', len(visible_assets))]
    for label, value in info:
        _append(sheet, ['项目概况', label, value, ''])
    for event in events_for_project(db, project):
        _append(sheet, ['关键事件', event['label'], event['planned_date'] or '',
                        {'实际发生': (event['actual_date'] if event['derived'] else event['actual_at']) or '',
                         '精度': '项目日期' if event['derived'] else 'UTC时间', '说明': event['note']}])
    from app.services.vehicle_progress import matrix
    progress=matrix(db,project.id)
    _append(sheet,['车辆进度','汇总',progress['summary'],progress['migration_warnings']])
    names={row['key']:row['name'] for row in progress['steps']}
    for step in progress['steps']:
        _append(sheet,['车辆环节定义',step['key'],step['name'],step])
    for unit in progress['units']:
        for key,fact in unit['cells'].items():
            _append(sheet,['车辆环节事实',unit['fleet_no'] or unit['asset_code'],names.get(key,key),
                {'车辆ID':unit['id'],'车辆编号':unit['asset_code'],'环节key':key,**fact}])
    for credit in progress['legacy']:
        _append(sheet,['历史完成凭证',names.get(credit['step_key'],credit['step_key']),credit['unassigned_count'],
            {'状态':'已完成（迁移，车号未知）','总凭证':credit['total_count'],'来源':credit['source_metadata']}])
    if project.portable_unverified_snapshot is not None:
        _append(sheet,['只读导入来源','未核验，不计入本项目完成资格',project.portable_unverified_snapshot,
            '保留来源原字段、日期和操作者；原始事实不会自动应用到新项目。'])
    _append(sheet, ['导出说明', '完整事实与原件', '可在应用导出 JSON 或完整项目包获取全部授权事实与附件。',
                    '长字段按记录分段续行；续行不重复数量。控制字符以可见Unicode转义呈现。'])
    return sheet, header


def _lifecycle(db, book, project, users, assets):
    headers = LIFECYCLE_HEADERS + ['故障部位', '原因判断', '更换配件', '停机小时', '验证结果', '是否关闭', '事件类型',
        '事件后阶段', '事件后状态', '事件后位置', '操作人', '关联附件', '附件ID', '事件ID', '扩展信息',
        '出厂序列号', '当前阶段', '当前状态', '当前位置', '到场日期', '投运日期', '质保到期', '车辆备注', '车辆ID', '升级前九阶段（只读）']
    sheet, header = _sheet(book, SHEET_NAMES[1], headers, title='AGV生命周期表')
    sheet.freeze_panes = 'F3'
    for column, width in LIFECYCLE_WIDTHS.items():
        sheet.column_dimensions[column].width = width
    units = db.query(models.VehicleUnit).filter_by(project_id=project.id).order_by(models.VehicleUnit.asset_code, models.VehicleUnit.id).all()
    vehicles = {row.id: row for row in db.query(models.Vehicle).filter_by(project_id=project.id)}
    by_unit = {}
    for row in db.query(models.VehicleLifecycleEvent).filter(models.VehicleLifecycleEvent.project_id == project.id,
            models.VehicleLifecycleEvent.event_type.in_(('fault', 'repair', 'maintenance', 'inspection', 'other'))).order_by(models.VehicleLifecycleEvent.event_date, models.VehicleLifecycleEvent.created_at, models.VehicleLifecycleEvent.id):
        by_unit.setdefault(row.vehicle_unit_id, []).append(row)
    seq = 0
    rows = [(unit, event) for unit in units for event in (by_unit.get(unit.id) or [None])]
    unit_ids = {unit.id for unit in units}
    rows += [(None, event) for unit_id, events in by_unit.items() if unit_id not in unit_ids for event in events]
    for unit, event in rows:
        vehicle = vehicles.get(unit.vehicle_id) if unit else None
        seq += 1
        extra = (event.extra or {}) if event else {}
        asset = assets.get(event.attachment_id) if event else None
        identity = [seq, project.name, (vehicle.model_name if vehicle else unit.model_name if unit else '') or extra.get('model_name', ''), unit.asset_code if unit else '',
                    (unit.fleet_no if unit else '') or extra.get('fleet_no', ''), event.title if event else '', event.description if event else '',
                    event.action_taken if event else '', event.handler if event else '', _iso(event.event_date) if event else '', extra.get('category', '')]
        fault = [event.fault_part, event.cause, event.replaced_parts, event.downtime_hours, event.verification, '是' if event.is_closed else '否',
                 event.event_type, event.stage_after, event.status_after, event.location_after, users.get(event.operator_id, event.operator_id or ''),
                 asset.filename if asset else '', asset.id if asset else '', event.id, extra] if event else [''] * 15
        archive = [unit.serial_number, unit.current_stage, unit.current_status, unit.location, _iso(unit.arrived_at), _iso(unit.commissioned_at),
                   _iso(unit.warranty_end), unit.note, unit.id, unit.legacy_current_stage] if unit else [''] * 8 + [event.vehicle_unit_id, '']
        _append(sheet, identity + fault + archive, identities=(3, 24, 34))
    return sheet, header


def _issues(db, book, project, users):
    headers = ['项目 Project', '问题类型 Type', '反馈人 Name', '车型 Model', '车辆编号 No.', '问题来源 From', '问题部件 Parts',
        '提交日期 Date', '问题简述（或现象）Description', '标题', '性质', '严重程度', '状态', '状态代码', '已闭环', '负责人',
        '关联任务', '解决方案/关闭或作废说明', '上报时间（UTC）', '解决记录时间（UTC）', '问题ID', '扩展字段', '关联任务ID','原扩展性质']
    sheet, header = _sheet(book, SHEET_NAMES[2], headers, title=f'{project.name} · 问题清单')
    tasks = {row.id: row.name for row in db.query(models.Task).filter_by(project_id=project.id)}
    for row in db.query(models.Issue).filter_by(project_id=project.id).order_by(models.Issue.created_at, models.Issue.id):
        extra = row.extra or {}
        _append(sheet, [project.name, _KIND.get(row.issue_type, row.issue_type), extra.get('reporter_name') or users.get(row.reporter_id, row.reporter_id),
            extra.get('vehicle_model', ''), extra.get('vehicle_no', ''), extra.get('source', ''), extra.get('part', ''),
            extra.get('feedback_date') or (_iso(row.created_at.date()) if row.created_at else ''), row.description, row.title,
            {'normal':'普通','accident':'事故','quality':'质量问题'}.get(row.nature,row.nature), {'critical':'严重','high':'高','medium':'中','low':'低'}.get(row.severity,row.severity),
            _STATUS.get(row.status,row.status), row.status, '是' if row.status in {'closed','cancelled'} else '否', users.get(row.assignee_id,row.assignee_id or ''),
            tasks.get(row.task_id, ''), row.resolution, _iso(row.created_at), _iso(row.resolved_at), row.id, extra, row.task_id or '',extra.get('nature',extra.get('issue_nature',''))], identities=(20,))
    return sheet, header


def _inventory(db, book, project, users):
    sheet, header = _sheet(book, SHEET_NAMES[3], INVENTORY_HEADERS + ['分类', '管理方式', '状态', '供应商/提供方', '到场日期', '预计归还', '最低库存', '扩展字段', '物品ID'])
    items = {row.id:row for row in db.query(models.ProjectInventoryItem).filter_by(project_id=project.id).order_by(models.ProjectInventoryItem.name,models.ProjectInventoryItem.id)}
    for row in items.values():
        _append(sheet, [row.item_code,row.name,row.specification,row.serial_number,row.ownership,row.quantity,row.unit,row.location,row.custodian,row.note,
            row.category,row.tracking_mode,row.status,row.supplier,_iso(row.received_date),_iso(row.expected_return_date),row.minimum_quantity,row.extra,row.id], identities=(0,18))
    history, history_header = _sheet(book, SHEET_NAMES[4], MOVEMENT_HEADERS + ['物品编码','单位','物品ID','流水ID','操作人','记录时间（UTC）','时间依据原值'])
    for row in db.query(models.ProjectInventoryMovement).filter_by(project_id=project.id).order_by(models.ProjectInventoryMovement.occurred_at,models.ProjectInventoryMovement.id):
        item = items.get(row.item_id)
        basis = inventory_time_basis(row)
        occurred = _iso(row.occurred_at) if basis == 'utc' else '原记录：' + (row.occurred_at.isoformat() if row.occurred_at else '')
        _append(history,[occurred,basis if basis=='utc' else '原记录时区未知',item.name if item else row.item_id,row.movement_type,row.quantity,row.balance_after,
            row.from_location,row.to_location,row.handler,row.note,item.item_code if item else '',item.unit if item else '',row.item_id,row.id,
            users.get(row.operator_id,row.operator_id or ''),_iso(row.created_at),row.time_basis or '未声明'],identities=(10,12,13))
    return [(sheet,header),(history,history_header)]


def _evidence(book, project, documents, grouped, classified, assets, users):
    headers = ['记录类型','阶段','资料编号','资料名称','车辆','周次','是否必需','资料状态','截止时间（UTC）','预计截止','不适用说明',
        '文件名','SHA-256','大小（字节）','提交人','提交时间（UTC）','版本说明','审核信息','资料ID','版本ID','附件ID','触发来源ID','触发真实时刻（UTC）']
    sheet, header = _sheet(book, SHEET_NAMES[5], headers, title=f'{project.name} · 交付资料')
    for document in documents:
        versions = grouped.get(document.id) or [(None,None)]
        for version, asset in versions:
            prefix = ['资料版本' if version else '资料项',document.stage_key,document.code,document.name,document.vehicle_label,document.period_key or '',
                '是' if document.required else '否',document.status,_iso(document.due_at),'是' if document.due_is_estimated else '否',document.waived_reason]
            file = [asset.filename,asset.sha256 or '',asset.file_size,users.get(version.uploaded_by if version else asset.uploaded_by,(version.uploaded_by if version else asset.uploaded_by) or ''),_iso(version.uploaded_at if version else asset.uploaded_at),
                version.note if version else '',version.review_metadata if version else None,document.id,version.id if version else '',asset.id] if asset else ['', '', '', users.get(document.submitted_by,document.submitted_by or ''),
                _iso(document.submitted_at),'','',document.id,'','']
            _append(sheet,prefix+file+[document.trigger_ref or '',_iso(document.triggered_at)],identities=(2,18,19,20,21))
    for asset in assets.values():
        if asset.id not in classified:
            _append(sheet,['未归类文件','','','','','','','','','','',asset.filename,asset.sha256 or '',asset.file_size,
                users.get(asset.uploaded_by,asset.uploaded_by or ''),_iso(asset.uploaded_at),'','', '', '',asset.id,'',''],identities=(20,))
    return sheet, header


def execution_evidence(db, project_id):
    """Read-only source facts; project import must never apply these states."""
    from sqlalchemy import or_
    users = dict(db.query(models.User.id, models.User.display_name))
    tasks = db.query(models.Task).filter_by(project_id=project_id).order_by(models.Task.sort_order, models.Task.id).all()
    checks = db.query(models.CheckItem).filter(models.CheckItem.task_id.in_([task.id for task in tasks]),
        or_(models.CheckItem.project_id == project_id, models.CheckItem.project_id.is_(None))).order_by(models.CheckItem.sort_order, models.CheckItem.id).all()
    operations = {}
    for log in db.query(models.ChangeLog).filter(models.ChangeLog.project_id == project_id,
            models.ChangeLog.entity_id.in_([check.id for check in checks]),
            models.ChangeLog.entity_type.in_(('task', 'check_item'))).order_by(models.ChangeLog.created_at.desc(), models.ChangeLog.id.desc()):
        if log.entity_type == 'check_item' or (log.detail or '').startswith('检查项'):
            operations.setdefault(log.entity_id, {'id': log.id, 'action': log.action, 'recorded_at': _iso(log.created_at),
                'actor_id': log.operator_id, 'actor_name': users.get(log.operator_id, '原操作人未记录')})
    by_task = {}
    for check in checks:
        row = {column.key: _iso(getattr(check, column.key)) if isinstance(getattr(check, column.key), datetime) else getattr(check, column.key)
               for column in check.__table__.columns}
        row.update(done_by_name=users.get(check.done_by, '原操作人未记录') if check.done_by else '',
            not_applicable_set_by_name=users.get(check.not_applicable_set_by, '原操作人未记录') if check.not_applicable_set_by else '',
            last_operation=operations.get(check.id))
        by_task.setdefault(check.task_id, []).append(row)
    fields = ('phase_id','group_label','scope_conditions','legacy_work_snapshot','vehicle_step_key', 'manually_completed', 'manual_completed_by', 'manual_completed_role', 'manual_completed_at', 'manual_completed_reason', 'manual_check_overrides')
    from app.services.vehicle_progress import matrix
    return {'read_only': True, 'meaning': '来源执行事实，仅供核对；便携导入不继承完成、检查或验收资格。',
        'vehicle_progress_matrix':{**matrix(db,project_id),'read_only':True},
        'vehicle_check_definitions':[{c.key:getattr(d,c.key) for c in d.__table__.columns} for d in db.query(models.VehicleCheckDefinition).filter_by(project_id=project_id).order_by(models.VehicleCheckDefinition.id)],
        'tasks': [{'source_id': task.id, 'name': task.name,
            **{key: _iso(getattr(task, key)) if isinstance(getattr(task, key), datetime) else getattr(task, key) for key in fields},
            'manual_completed_by_name': users.get(task.manual_completed_by, '原操作人未记录') if task.manual_completed_by else '',
            'check_items': by_task.get(task.id, [])} for task in tasks]}


def build_delivery_workbook(db, project_id, *, actor):
    if actor is None or not getattr(actor, 'id', None):
        raise ValueError('项目交付导出必须提供当前账号')
    actor = db.get(models.User, actor.id, populate_existing=True)
    if actor is None or not actor.is_active:
        raise ValueError('项目交付导出账号不可用')
    project = ensure_project_visible(db, project_id, actor)
    authorize_project(actor, project, C_EXPORT)
    users = dict(db.query(models.User.id,models.User.display_name))
    assets = {row.id:row for row in db.query(models.Attachment).filter_by(project_id=project.id) if can_read_file(actor,project,row)}
    documents, grouped, classified = _documents(db,project,actor,assets)
    visible_asset_ids = {asset.id for document in documents for _,asset in grouped.get(document.id, [])} | (set(assets) - classified)
    book = Workbook();book.remove(book.active)
    layouts = [_overview(db,book,project,documents,visible_asset_ids,users), _lifecycle(db,book,project,users,{key:assets[key] for key in visible_asset_ids}), _issues(db,book,project,users)]
    layouts += _inventory(db,book,project,users)
    layouts.append(_evidence(book,project,documents,grouped,classified,assets,users))
    for sheet, header_row in layouts:
        sheet.auto_filter.ref = f'A{header_row}:{get_column_letter(sheet.max_column)}{max(header_row,sheet.max_row)}'
        for cells in sheet.iter_rows(min_row=header_row+1):
            lines = max((sum(max(1, math.ceil((len(line) + sum(ord(char) > 127 for char in line)) / max(8, sheet.column_dimensions[cell.column_letter].width - 2))) for line in str(cell.value or '').splitlines()) for cell in cells), default=1)
            sheet.row_dimensions[cells[0].row].height = min(240, max(30, lines * 15))
            for cell in cells:
                if isinstance(cell.value,str):cell.data_type='s'
                cell.alignment = Alignment(vertical='top',wrap_text=True)
                cell.font = Font(name='微软雅黑',size=11)
                if cell.row % 2:cell.fill = PatternFill('solid',fgColor='F2F6FC')
        for cells in sheet:
            for cell in cells:
                if isinstance(cell.value,str):cell.data_type='s'
    book.active = 0
    output = io.BytesIO();book.save(output)
    from app.services.project_documents import audit_access
    audit_access(db,project,actor,documents=documents,files=[assets[key] for key in visible_asset_ids],action='confidential_export')
    db.commit()
    return output.getvalue()
