"""Templates become sections of one-row items; the old template tables become their compiled form.

A template is now an ordered list of sections (free titles, each placed on one company stage 4–9)
holding one row per thing to do: a work item (optionally per vehicle, with checks), a file bundle,
or a purchase, plus template-defined custom fields. Any row may name the files it hands in.

Projects are still generated from phases/tasks/check items/document requirements/vehicle steps and
procurement rows. Those rows are compiled from the items with the same ids, so project documents
that point at a template requirement keep their link.

Every existing template is converted with its content intact: work one row each, documents one row
per document group and per stage. The built-in template is replaced by a merged
version of about twenty rows that still carries every company document code. On installations that
already have projects, the previous built-in content is kept as an ordinary template.

Frozen at this revision: table shapes, stage names and the merged default content below.
"""
from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = 'g3a93b000001'
down_revision = 'g3a92b000001'
branch_labels = None
depends_on = None

STAGE_NAMES = {'4': '内部启动会', '5': '发车前', '6': '实施', '7': '验收', '8': '交付', '9': '全项目周期', 'legacy': '历史待分类'}
STAGE_ORDER = ('4', '5', '6', '7', '8', '9', 'legacy')
REMINDER_ONLY_PHASES = {'项目准备'}
BACKUP_NAME = '通用模板（升级前内容）'
BACKUP_DESCRIPTION = '升级到新版模板时自动保留的原通用模板全部内容；不再需要可以删除。'
FILE_KEYS = ('code', 'name', 'template_no', 'required', 'scope', 'platform', 'timing_type', 'timing_event',
             'timing_offset_hours', 'timing_weekday', 'trigger_type', 'confidential_default',
             'external_visible_default', 'external_never_visible', 'note')

# The merged built-in template: (section, stage, rows). Files are company document codes whose rules
# are taken from the previous built-in definitions. Checks: (name, safety critical).
DEFAULT_CONTENT = [
    ('启动准备', '4', [
        ('work', '内部启动会', {'note': '确认项目风险、人员、定版流程和采购清单', 'files': ['4.1', '4.2', '4.3', '4.4', '4.5']}),
        ('purchase', 'AGV 本体', {'unit': '台', 'spec': '按合同型号与配置'}),
        ('purchase', '自动充电桩', {'unit': '台', 'spec': '按车辆 1:1 选型，含安装底座'}),
    ]),
    ('发车前', '5', [
        ('file', '发车与进场资料', {'files': ['5.1.1', '5.1.2', '5.1.3', '5.1.4', '5.1.5', '5.2.1', '5.2.2', '5.3', '5.4']}),
        ('work', '场地勘测', {'checks': [('场地尺寸与平整度测量', False), ('通道宽度与转弯半径确认', False),
                                     ('网络覆盖与带宽测试', False), ('安全围栏与警示标识检查', True),
                                     ('施工方案各节点签字确认', False)]}),
        ('purchase', '网络设备', {'unit': '套', 'spec': '工业路由器、千兆交换机、网线（按现场需要）', 'optional': True}),
        ('purchase', '安全围栏', {'unit': '米', 'spec': '铝合金围栏 1.2m 高，含立柱', 'optional': True}),
    ]),
    ('到货与单车调试', '6', [
        ('work', '到场点检', {'per_vehicle': True, 'step': 'arrival_inspection',
                           'checks': [('外观检查无损伤', False), ('核对设备清单与配件', False), ('电池电压与充电器功能', True)],
                           'files': ['6.1', '6.10.1']}),
        ('work', '单车调试', {'per_vehicle': True, 'step': 'single_commissioning',
                           'checks': [('机械与导航调试，到点精度≤30mm', False), ('安全激光与停车距离验证', True),
                                      ('额定载荷与过载保护测试', True), ('急停、触边与失速保护', True), ('车辆参数与程序备份', False)],
                           'files': ['6.11.2a', '6.11.2.1', '6.11.2.2', '6.11.2b', '6.10.2']}),
    ]),
    ('系统部署与联调', '6', [
        ('work', '服务器与网络部署', {'checks': [('服务器上架与系统安装', False), ('调度系统与数据库部署', False),
                                            ('防火墙、VLAN 与远程访问', False), ('自动备份与恢复测试', False)],
                                 'files': ['6.11.6a', '6.11.6b', '6.11.6c', '6.11.1a', '6.11.1b']}),
        ('work', '地图与站点', {'checks': [('建图并验证地图精度', False), ('工位与充电站点设置', False),
                                       ('路径规划与交通管制区域', False), ('地图文件备份（本地+云端）', False)],
                             'files': ['6.11.3a', '6.11.3b', '6.11.4']}),
        ('work', '系统联调', {'per_vehicle': True, 'step': 'system_integration',
                           'checks': [('多车任务分配与交通管制', False), ('任务创建→执行→完成全流程', False),
                                      ('断网恢复与故障接管', True), ('紧急情况全系统停止', True), ('满载吞吐与响应延迟达标', False)]}),
        ('work', 'WMS/MES 对接', {'optional': True, 'checks': [('接口字段、鉴权及状态映射确认', False),
                                                            ('下发、执行、完成反馈全流程通过', False),
                                                            ('超时重试、断线恢复及重复订单处理通过', False)]}),
        ('work', '电梯/自动门对接', {'optional': True, 'checks': [('设备安装与信号对接', False), ('联动联调通过', False)]}),
        ('work', 'PLC 对接', {'optional': True, 'checks': [('PLC 信号对接', False), ('联调通过', False)], 'files': ['6.11.5']}),
    ]),
    ('试运行', '6', [
        ('work', '上线运行', {'per_vehicle': True, 'step': 'go_live',
                           'checks': [('连续运行≥7天无重大故障', False), ('异常统计、整改与复测', True), ('试运行报告与运行数据归档', False)],
                           'files': ['6.10.3', '6.11.8']}),
        ('purchase', '备件（坏件更换）', {'unit': '件', 'spec': '现场损坏需更换的零部件，按实际填写', 'optional': True}),
    ]),
    ('培训与验收', '7', [
        ('work', '操作与维护培训', {'checks': [('操作、维护手册交付', False), ('操作与维护人员实操考核', False)], 'files': ['6.10.4']}),
        ('work', '最终验收', {'checks': [('验收标准逐项确认', False), ('客户签字验收', False), ('全部项目文档归档', False)], 'files': ['7.1']}),
    ]),
    ('交付', '8', [
        ('file', '交付资料', {'files': ['8.1', '8.2', '8.3', '8.4']}),
    ]),
    ('过程记录', '6', [
        ('file', '每周资料', {'files': ['6.2', '6.3', '6.4', '6.5', '6.11.7', '6.11.9']}),
        ('file', '发生时提交', {'files': ['6.6', '6.7', '6.8.1', '6.8.2', '6.9.1', '6.9.2', '6.9.3']}),
    ]),
    ('全程记录', '9', [
        ('file', '全程更新资料', {'files': ['9.1', '9.2']}),
    ]),
]

meta = sa.MetaData()
templates = sa.Table('templates', meta, sa.Column('id', sa.String), sa.Column('name', sa.String), sa.Column('description', sa.Text),
                     sa.Column('is_system', sa.Boolean), sa.Column('vehicle_type', sa.String), sa.Column('version', sa.Integer),
                     sa.Column('status', sa.String), sa.Column('snapshots', sa.JSON), sa.Column('created_at', sa.DateTime),
                     sa.Column('updated_at', sa.DateTime))
projects = sa.Table('projects', meta, sa.Column('id', sa.String))
phases = sa.Table('phases', meta, sa.Column('id', sa.String), sa.Column('project_id', sa.String), sa.Column('template_id', sa.String),
                  sa.Column('name', sa.String), sa.Column('sort_order', sa.Integer), sa.Column('color', sa.String),
                  sa.Column('entry_criteria', sa.Text), sa.Column('exit_criteria', sa.Text), sa.Column('stage_key', sa.String))
modules = sa.Table('modules', meta, sa.Column('id', sa.String), sa.Column('project_id', sa.String), sa.Column('template_id', sa.String),
                   sa.Column('phase_id', sa.String), sa.Column('name', sa.String))
tasks = sa.Table('tasks', meta, *(sa.Column(name, kind) for name, kind in (
    ('id', sa.String), ('project_id', sa.String), ('template_id', sa.String), ('module_id', sa.String), ('phase_id', sa.String),
    ('group_label', sa.String), ('scope_conditions', sa.JSON), ('legacy_work_snapshot', sa.JSON), ('name', sa.String),
    ('description', sa.Text), ('quantity_type', sa.String), ('target_quantity', sa.Float), ('unit', sa.String),
    ('standard_hours', sa.Float), ('safety_flag', sa.Boolean), ('applicable_vehicle_types', sa.JSON), ('sort_order', sa.Integer),
    ('depends_on', sa.JSON), ('deliverables', sa.JSON), ('reference_docs', sa.JSON), ('version', sa.Integer),
    ('source_task_id', sa.String), ('vehicle_step_key', sa.String), ('manually_completed', sa.Boolean),
    ('manual_completed_reason', sa.Text), ('manual_check_overrides', sa.JSON), ('template_fields', sa.JSON))))
check_items = sa.Table('check_items', meta, *(sa.Column(name, kind) for name, kind in (
    ('id', sa.String), ('task_id', sa.String), ('project_id', sa.String), ('template_id', sa.String), ('name', sa.String),
    ('description', sa.Text), ('is_safety_critical', sa.Boolean), ('is_required', sa.Boolean), ('is_applicable', sa.Boolean),
    ('not_applicable_reason', sa.Text), ('is_done', sa.Boolean), ('failed', sa.Boolean), ('failed_reason', sa.Text),
    ('sort_order', sa.Integer), ('version', sa.Integer))))
requirements = sa.Table('document_requirements', meta, *(sa.Column(name, kind) for name, kind in (
    ('id', sa.String), ('template_id', sa.String), ('stage_key', sa.String), ('code', sa.String), ('name', sa.String),
    ('template_no', sa.String), ('is_group', sa.Boolean), ('parent_id', sa.String), ('required', sa.Boolean), ('scope', sa.String),
    ('platform', sa.String), ('timing_type', sa.String), ('timing_event', sa.String), ('timing_offset_hours', sa.Integer),
    ('timing_weekday', sa.Integer), ('trigger_type', sa.String), ('confidential_default', sa.Boolean),
    ('external_visible_default', sa.Boolean), ('external_never_visible', sa.Boolean), ('blank_file_id', sa.String),
    ('sort_order', sa.Integer), ('note', sa.Text), ('source_metadata', sa.JSON), ('created_at', sa.DateTime), ('updated_at', sa.DateTime))))
vehicle_steps = sa.Table('vehicle_steps', meta, sa.Column('id', sa.String), sa.Column('template_id', sa.String), sa.Column('key', sa.String),
                         sa.Column('name', sa.String), sa.Column('sort_order', sa.Integer))
procurements = sa.Table('template_procurement_items', meta, *(sa.Column(name, kind) for name, kind in (
    ('id', sa.String), ('template_id', sa.String), ('name', sa.String), ('unit', sa.String), ('spec', sa.String),
    ('due_weeks', sa.Integer), ('condition', sa.String), ('is_required', sa.Boolean), ('owner_party', sa.String),
    ('risk', sa.String), ('sort_order', sa.Integer))))
template_docs = sa.Table('template_docs', meta, sa.Column('id', sa.String), sa.Column('template_id', sa.String), sa.Column('task_id', sa.String))


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _id():
    return str(uuid4())


def _is(column, value):
    return column.is_(None) if value is None else column == value


def _sections_table():
    return sa.Table('template_sections', meta, sa.Column('id', sa.String), sa.Column('template_id', sa.String),
                    sa.Column('title', sa.String), sa.Column('stage_key', sa.String), sa.Column('sort_order', sa.Integer),
                    sa.Column('created_at', sa.DateTime), sa.Column('updated_at', sa.DateTime), extend_existing=True)


def _items_table():
    return sa.Table('template_items', meta, *(sa.Column(name, kind) for name, kind in (
        ('id', sa.String), ('template_id', sa.String), ('section_id', sa.String), ('kind', sa.String), ('name', sa.String),
        ('note', sa.Text), ('optional', sa.Boolean), ('per_vehicle', sa.Boolean), ('step_key', sa.String), ('checks', sa.JSON),
        ('files', sa.JSON), ('quantity', sa.Float), ('unit', sa.String), ('spec', sa.String), ('fields', sa.JSON),
        ('extra', sa.JSON), ('sort_order', sa.Integer), ('version', sa.Integer), ('created_at', sa.DateTime),
        ('updated_at', sa.DateTime))), extend_existing=True)


def _fields_table():
    return sa.Table('template_fields', meta, sa.Column('id', sa.String), sa.Column('template_id', sa.String),
                    sa.Column('name', sa.String), sa.Column('field_type', sa.String), sa.Column('options', sa.JSON),
                    sa.Column('sort_order', sa.Integer), extend_existing=True)


def _file_from(row):
    data = {key: row[key] for key in FILE_KEYS}
    data.update(id=row['id'], scope=row['scope'] or 'project', template_no=row['template_no'] or '', note=row['note'] or '',
                blank_file_id=row['blank_file_id'], source_metadata=row['source_metadata'])
    return data


def _place(sections, title, stage, template_id):
    """First section on this stage, else a new one after the last section of an earlier stage."""
    for section in sections:
        if section['stage_key'] == stage:
            return section
    new = {'id': _id(), 'template_id': template_id, 'title': title, 'stage_key': stage}
    rank = STAGE_ORDER.index(stage) if stage in STAGE_ORDER else len(STAGE_ORDER)
    position = 0
    for index, section in enumerate(sections):
        if (STAGE_ORDER.index(section['stage_key']) if section['stage_key'] in STAGE_ORDER else len(STAGE_ORDER)) <= rank:
            position = index + 1
    sections.insert(position, new)
    return new


def _convert(connection, template_id):
    """One template's phases, work, document rules, vehicle steps and procurement as sections and items."""
    sections = []
    for row in connection.execute(sa.select(phases).where(_is(phases.c.template_id, template_id), phases.c.project_id.is_(None))
                                  .order_by(phases.c.sort_order, phases.c.id)).mappings():
        if (row['name'] or '').strip() in REMINDER_ONLY_PHASES:
            continue
        sections.append({'id': row['id'], 'template_id': template_id, 'title': row['name'] or '工作', 'stage_key': row['stage_key'] or '6'})
    known = {section['id'] for section in sections}
    module_rows = {row['id']: row for row in connection.execute(sa.select(modules).where(
        _is(modules.c.template_id, template_id), modules.c.project_id.is_(None))).mappings()}
    checks = {}
    for row in connection.execute(sa.select(check_items).where(_is(check_items.c.template_id, template_id), check_items.c.project_id.is_(None))
                                  .order_by(check_items.c.sort_order, check_items.c.id)).mappings():
        checks.setdefault(row['task_id'], []).append({'id': row['id'], 'name': row['name'], 'description': row['description'] or '',
                                                      'required': row['is_required'] is not False, 'safety': bool(row['is_safety_critical'])})
    items = {section['id']: [] for section in sections}
    for row in connection.execute(sa.select(tasks).where(_is(tasks.c.template_id, template_id), tasks.c.project_id.is_(None))
                                  .order_by(tasks.c.sort_order, tasks.c.id)).mappings():
        module = module_rows.get(row['module_id'])
        section_id = row['phase_id'] or (module['phase_id'] if module else None)
        if section_id not in known:
            continue
        title = next(section['title'] for section in sections if section['id'] == section_id)
        group = row['group_label'] or (module['name'] if module else '')
        extra = {'group_label': group if group and group != title else None,
                 'scope_conditions': row['scope_conditions'] or None,
                 'applicable_vehicle_types': row['applicable_vehicle_types'] or None,
                 'standard_hours': row['standard_hours'], 'safety_flag': row['safety_flag'] or None,
                 'depends_on': row['depends_on'] or None, 'legacy_work_snapshot': row['legacy_work_snapshot']}
        per_vehicle = row['quantity_type'] == 'per_vehicle'
        if not per_vehicle and (row['quantity_type'] not in (None, 'fixed') or row['target_quantity'] is not None):
            extra.update(quantity_type=row['quantity_type'], target_quantity=row['target_quantity'], unit=row['unit'])
        items[section_id].append({'id': row['id'], 'kind': 'work', 'name': row['name'], 'note': row['description'] or '',
                                  'per_vehicle': per_vehicle, 'step_key': row['vehicle_step_key'] if per_vehicle else None,
                                  'checks': checks.get(row['id'], []), 'files': [],
                                  'extra': {key: value for key, value in extra.items() if value is not None}})
    used = {item['step_key'] for rows in items.values() for item in rows if item['step_key']}
    for row in connection.execute(sa.select(vehicle_steps).where(vehicle_steps.c.template_id == (template_id or 'default'))
                                  .order_by(vehicle_steps.c.sort_order, vehicle_steps.c.key)).mappings():
        if row['key'] in used:
            continue
        section = _place(sections, '车辆环节', '6', template_id)
        items.setdefault(section['id'], []).append({'id': _id(), 'kind': 'work', 'name': row['name'], 'note': '', 'per_vehicle': True,
                                                    'step_key': row['key'], 'checks': [], 'files': [], 'extra': {}})
        used.add(row['key'])
    docs = list(connection.execute(sa.select(requirements).where(_is(requirements.c.template_id, template_id))
                                   .order_by(requirements.c.sort_order, requirements.c.code)).mappings())
    groups = {row['id']: row for row in docs if row['is_group']}
    bundles = {}
    for row in docs:
        if row['is_group']:
            continue
        stage = row['stage_key'] if row['stage_key'] in STAGE_NAMES else '6'
        group = groups.get(row['parent_id'])
        grouped = group is not None and group['stage_key'] == row['stage_key']
        # One row per document group, and one row for the remaining documents of each stage.
        key = group['id'] if grouped else f'stage:{stage}'
        if key not in bundles:
            section = _place(sections, f"{STAGE_NAMES[stage]}资料", stage, template_id)
            bundle = {'id': _id(), 'kind': 'file', 'name': (group['name'].replace('（分组）', '').strip() or group['name']) if grouped else f"{STAGE_NAMES[stage]}资料",
                      'note': '', 'per_vehicle': False, 'step_key': None, 'checks': [], 'files': [], 'extra': {}}
            bundles[key] = bundle
            items.setdefault(section['id'], []).append(bundle)
        bundles[key]['files'].append(_file_from(row))
    for row in connection.execute(sa.select(procurements).where(_is(procurements.c.template_id, template_id))
                                  .order_by(procurements.c.sort_order, procurements.c.id)).mappings():
        section = next((s for s in sections if s['stage_key'] == '5'), None) or next((s for s in sections if s['stage_key'] == '4'), None) \
            or _place(sections, '采购', '5', template_id)
        extra = {'risk': row['risk'], 'due_weeks': row['due_weeks'] or None, 'condition': row['condition'] if row['condition'] not in (None, 'default') else None,
                 'owner_party': row['owner_party'] if row['owner_party'] not in (None, 'procurement') else None}
        items.setdefault(section['id'], []).append({'id': row['id'], 'kind': 'purchase', 'name': row['name'], 'note': '',
                                                    'optional': row['is_required'] is False, 'unit': row['unit'] or '', 'spec': row['spec'] or '',
                                                    'per_vehicle': False, 'step_key': None, 'checks': [], 'files': [],
                                                    'extra': {key: value for key, value in extra.items() if value is not None}})
    _write(connection, template_id, sections, items)


def _write(connection, template_id, sections, items):
    section_table, item_table = _sections_table(), _items_table()
    now = _now()
    for index, section in enumerate(sections):
        connection.execute(section_table.insert().values(id=section['id'], template_id=template_id, title=section['title'][:200],
                                                         stage_key=section['stage_key'], sort_order=index, created_at=now, updated_at=now))
        for position, item in enumerate(items.get(section['id'], [])):
            connection.execute(item_table.insert().values(
                id=item['id'], template_id=template_id, section_id=section['id'], kind=item['kind'], name=item['name'][:200],
                note=item.get('note') or '', optional=bool(item.get('optional')), per_vehicle=bool(item.get('per_vehicle')),
                step_key=item.get('step_key'), checks=item.get('checks') or [], files=item.get('files') or [],
                quantity=item.get('quantity'), unit=item.get('unit') or '', spec=item.get('spec') or '', fields={},
                extra=item.get('extra') or {}, sort_order=position, version=0, created_at=now, updated_at=now))


def _default_content(connection, previous):
    """The merged built-in template; document rules come from the previous built-in definitions by code."""
    sections, items = [], {}
    for title, stage, rows in DEFAULT_CONTENT:
        section = {'id': _id(), 'template_id': None, 'title': title, 'stage_key': stage}
        sections.append(section)
        items[section['id']] = []
        for kind, name, spec in rows:
            files = []
            for code in spec.get('files', []):
                source = previous.get(code)
                if source is not None:
                    files.append({**_file_from(source), 'id': _id(), 'source_metadata': None})
            items[section['id']].append({
                'id': _id(), 'kind': kind, 'name': name, 'note': spec.get('note', ''), 'optional': spec.get('optional', False),
                'per_vehicle': spec.get('per_vehicle', False), 'step_key': spec.get('step'), 'unit': spec.get('unit', ''),
                'spec': spec.get('spec', ''), 'files': files, 'extra': {},
                'checks': [{'id': _id(), 'name': check, 'description': '', 'required': True, 'safety': safety}
                           for check, safety in spec.get('checks', [])]})
    _write(connection, None, sections, items)


def _upsert(connection, table, condition, wanted, keep=()):
    existing = {row[0] for row in connection.execute(sa.select(table.c.id).where(condition))}
    for key, values in wanted.items():
        if key in existing:
            connection.execute(table.update().where(table.c.id == key).values(**{k: v for k, v in values.items() if k not in keep and k != 'id'}))
        else:
            connection.execute(table.insert().values(**values))
    return existing - set(wanted)


def _compile(connection, template_id):
    """Regenerate the project-generation rows of one template from its sections and items, ids unchanged."""
    section_table, item_table, field_table = _sections_table(), _items_table(), _fields_table()
    now = _now()
    section_rows = list(connection.execute(sa.select(section_table).where(_is(section_table.c.template_id, template_id))
                                           .order_by(section_table.c.sort_order, section_table.c.id)).mappings())
    order = {row['id']: index for index, row in enumerate(section_rows)}
    stage_of = {row['id']: row['stage_key'] for row in section_rows}
    item_rows = sorted(connection.execute(sa.select(item_table).where(_is(item_table.c.template_id, template_id))).mappings(),
                       key=lambda row: (order.get(row['section_id'], 1 << 30), row['sort_order'] or 0, row['id']))
    names = {row['id']: row['name'] for row in connection.execute(sa.select(field_table).where(_is(field_table.c.template_id, template_id))).mappings()}
    wanted_phases = {row['id']: {'id': row['id'], 'project_id': None, 'template_id': template_id, 'name': row['title'][:100],
                                 'sort_order': index, 'color': '#1890ff', 'entry_criteria': '', 'exit_criteria': '',
                                 'stage_key': row['stage_key']} for index, row in enumerate(section_rows)}
    template_rows = sa.and_(_is(phases.c.template_id, template_id), phases.c.project_id.is_(None))
    stale_phases = _upsert(connection, phases, template_rows, wanted_phases)
    wanted_tasks, wanted_checks, wanted_docs, wanted_procs, steps = {}, {}, {}, {}, {}
    doc_order = 0
    for position, row in enumerate(item_rows):
        extra = row['extra'] or {}
        fields = [{'name': names[key], 'value': value} for key, value in (row['fields'] or {}).items()
                  if key in names and value not in (None, '', [])]
        if row['kind'] == 'work':
            per_vehicle = bool(row['per_vehicle'])
            wanted_tasks[row['id']] = {
                'id': row['id'], 'project_id': None, 'template_id': template_id, 'module_id': None, 'phase_id': row['section_id'],
                'group_label': extra.get('group_label') or '', 'scope_conditions': extra.get('scope_conditions') or [],
                'legacy_work_snapshot': extra.get('legacy_work_snapshot'), 'name': row['name'], 'description': row['note'] or '',
                'quantity_type': 'per_vehicle' if per_vehicle else extra.get('quantity_type') or 'fixed',
                'target_quantity': None if per_vehicle else extra.get('target_quantity'),
                'unit': '台' if per_vehicle else extra.get('unit') or '项', 'standard_hours': extra.get('standard_hours'),
                'safety_flag': bool(extra.get('safety_flag')), 'applicable_vehicle_types': extra.get('applicable_vehicle_types') or [],
                'sort_order': position, 'depends_on': extra.get('depends_on') or [], 'deliverables': [], 'reference_docs': [],
                'version': 0, 'source_task_id': None, 'vehicle_step_key': row['step_key'] if per_vehicle else None,
                'manually_completed': False, 'manual_completed_reason': '', 'manual_check_overrides': [],
                'template_fields': fields or None}
            for index, check in enumerate(row['checks'] or []):
                wanted_checks[check['id']] = {
                    'id': check['id'], 'task_id': row['id'], 'project_id': None, 'template_id': template_id, 'name': check['name'],
                    'description': check.get('description') or '', 'is_safety_critical': bool(check.get('safety')),
                    'is_required': check.get('required', True) is not False, 'is_applicable': True, 'not_applicable_reason': '',
                    'is_done': False, 'failed': False, 'failed_reason': '', 'sort_order': index, 'version': 0}
            if per_vehicle and row['step_key'] and row['step_key'] not in steps:
                steps[row['step_key']] = row['name']
        if row['kind'] == 'purchase':
            wanted_procs[row['id']] = {'id': row['id'], 'template_id': template_id, 'name': row['name'], 'unit': row['unit'] or '件',
                                       'spec': row['spec'] or '', 'due_weeks': extra.get('due_weeks') or 0,
                                       'condition': extra.get('condition') or 'default', 'is_required': not row['optional'],
                                       'owner_party': extra.get('owner_party') or 'procurement', 'risk': extra.get('risk') or 'low',
                                       'sort_order': position}
        for document in row['files'] or []:
            metadata = dict(document.get('source_metadata') or {})
            metadata['template_item_id'] = row['id']
            wanted_docs[document['id']] = {
                'id': document['id'], 'template_id': template_id, 'stage_key': stage_of.get(row['section_id'], '6'),
                **{key: document.get(key) for key in FILE_KEYS}, 'template_no': document.get('template_no') or '',
                'note': document.get('note') or '', 'scope': document.get('scope') or 'project', 'is_group': False, 'parent_id': None,
                'required': document.get('required', True) is not False,
                'confidential_default': bool(document.get('confidential_default')),
                'external_visible_default': bool(document.get('external_visible_default')),
                'external_never_visible': bool(document.get('external_never_visible')),
                'blank_file_id': document.get('blank_file_id'), 'sort_order': doc_order, 'source_metadata': metadata,
                'created_at': now, 'updated_at': now}
            doc_order += 1
    task_rows = sa.and_(_is(tasks.c.template_id, template_id), tasks.c.project_id.is_(None))
    stale_tasks = _upsert(connection, tasks, task_rows, wanted_tasks, keep=('version',))
    check_rows = sa.and_(_is(check_items.c.template_id, template_id), check_items.c.project_id.is_(None))
    stale_checks = _upsert(connection, check_items, check_rows, wanted_checks, keep=('version',))
    if stale_checks:
        connection.execute(check_items.delete().where(check_items.c.id.in_(stale_checks)))
    if stale_tasks:
        connection.execute(template_docs.delete().where(template_docs.c.task_id.in_(stale_tasks)))
        connection.execute(check_items.delete().where(check_items.c.task_id.in_(stale_tasks)))
        connection.execute(tasks.delete().where(tasks.c.id.in_(stale_tasks)))
    connection.execute(modules.delete().where(_is(modules.c.template_id, template_id), modules.c.project_id.is_(None)))
    if stale_phases:
        connection.execute(phases.delete().where(phases.c.id.in_(stale_phases)))
    doc_rows = _is(requirements.c.template_id, template_id)
    connection.execute(requirements.update().where(doc_rows).values(parent_id=None))
    stale_docs = _upsert(connection, requirements, doc_rows, wanted_docs, keep=('created_at',))
    if stale_docs:
        connection.execute(requirements.delete().where(requirements.c.id.in_(stale_docs)))
    step_key = template_id or 'default'
    connection.execute(vehicle_steps.delete().where(vehicle_steps.c.template_id == step_key))
    for index, (key, name) in enumerate(steps.items()):
        connection.execute(vehicle_steps.insert().values(id=_id(), template_id=step_key, key=key, name=name[:200], sort_order=index))
    stale_procs = _upsert(connection, procurements, _is(procurements.c.template_id, template_id), wanted_procs)
    if stale_procs:
        connection.execute(procurements.delete().where(procurements.c.id.in_(stale_procs)))


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError('模板事项需要逐条读取并转换现有模板内容；请在线事务运行')
    op.create_table(
        'template_sections',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('template_id', sa.String(36), sa.ForeignKey('templates.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('stage_key', sa.String(8), nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime), sa.Column('updated_at', sa.DateTime),
    )
    op.create_table(
        'template_items',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('template_id', sa.String(36), sa.ForeignKey('templates.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('section_id', sa.String(36), sa.ForeignKey('template_sections.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('kind', sa.String(12), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('note', sa.Text, nullable=False),
        sa.Column('optional', sa.Boolean, nullable=False),
        sa.Column('per_vehicle', sa.Boolean, nullable=False),
        sa.Column('step_key', sa.String(80), nullable=True),
        sa.Column('checks', sa.JSON, nullable=False),
        sa.Column('files', sa.JSON, nullable=False),
        sa.Column('quantity', sa.Float, nullable=True),
        sa.Column('unit', sa.String(20), nullable=False),
        sa.Column('spec', sa.String(300), nullable=False),
        sa.Column('fields', sa.JSON, nullable=False),
        sa.Column('extra', sa.JSON, nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime), sa.Column('updated_at', sa.DateTime),
    )
    op.create_table(
        'template_fields',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('template_id', sa.String(36), sa.ForeignKey('templates.id', ondelete='CASCADE'), nullable=True, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('field_type', sa.String(12), nullable=False),
        sa.Column('options', sa.JSON, nullable=False),
        sa.Column('sort_order', sa.Integer, nullable=False),
    )
    op.add_column('tasks', sa.Column('template_fields', sa.JSON, nullable=True))

    connection = op.get_bind()
    previous = {row['code']: dict(row) for row in connection.execute(
        sa.select(requirements).where(requirements.c.template_id.is_(None), requirements.c.is_group.is_(False))).mappings()}
    has_projects = connection.execute(sa.select(sa.func.count()).select_from(projects)).scalar() > 0
    # A database whose built-in template has no work yet (a new installation) gets the merged
    # template at startup (app/seed/default_template.py); only existing content is converted here.
    has_default = connection.execute(sa.select(sa.func.count()).select_from(tasks).where(
        tasks.c.template_id.is_(None), tasks.c.project_id.is_(None))).scalar() > 0
    if has_projects and has_default:
        backup = _id()
        now = _now()
        connection.execute(templates.insert().values(id=backup, name=BACKUP_NAME, description=BACKUP_DESCRIPTION, is_system=False,
                                                     vehicle_type=None, version=1, status='published', snapshots=[],
                                                     created_at=now, updated_at=now))
        for table in (phases, modules, tasks, check_items):
            connection.execute(table.update().where(table.c.template_id.is_(None), table.c.project_id.is_(None)).values(template_id=backup))
        for table in (requirements, procurements):
            connection.execute(table.update().where(table.c.template_id.is_(None)).values(template_id=backup))
        connection.execute(template_docs.update().where(template_docs.c.template_id.is_(None)).values(template_id=backup))
        connection.execute(vehicle_steps.update().where(vehicle_steps.c.template_id == 'default').values(template_id=backup))
    elif has_default:
        default_tasks = sa.select(tasks.c.id).where(tasks.c.template_id.is_(None), tasks.c.project_id.is_(None))
        connection.execute(template_docs.delete().where(template_docs.c.task_id.in_(default_tasks)))
        connection.execute(check_items.delete().where(check_items.c.template_id.is_(None), check_items.c.project_id.is_(None)))
        connection.execute(tasks.delete().where(tasks.c.template_id.is_(None), tasks.c.project_id.is_(None)))
        connection.execute(modules.delete().where(modules.c.template_id.is_(None), modules.c.project_id.is_(None)))
        connection.execute(phases.delete().where(phases.c.template_id.is_(None), phases.c.project_id.is_(None)))
        connection.execute(requirements.update().where(requirements.c.template_id.is_(None)).values(parent_id=None))
        connection.execute(requirements.delete().where(requirements.c.template_id.is_(None)))
        connection.execute(vehicle_steps.delete().where(vehicle_steps.c.template_id == 'default'))
        connection.execute(procurements.delete().where(procurements.c.template_id.is_(None)))
    template_ids = [row[0] for row in connection.execute(sa.select(templates.c.id).where(
        sa.or_(templates.c.is_system.is_(False), templates.c.is_system.is_(None))).order_by(templates.c.created_at, templates.c.id))]
    for template_id in template_ids:
        _convert(connection, template_id)
        _compile(connection, template_id)
    if has_default:
        _default_content(connection, previous)
        _compile(connection, None)


def downgrade():
    # The compiled phases/tasks/requirements/steps/procurement rows stay valid on their own. Earlier
    # revisions keep template work under modules, so module-less template work gets one per group.
    connection = op.get_bind()
    module_rows = sa.Table('modules', sa.MetaData(), *(sa.Column(name, kind) for name, kind in (
        ('id', sa.String), ('project_id', sa.String), ('template_id', sa.String), ('phase_id', sa.String), ('name', sa.String),
        ('category', sa.String), ('is_selected', sa.Boolean), ('sort_order', sa.Integer), ('description', sa.Text),
        ('applies_to_all_vehicles', sa.Boolean), ('source_module_id', sa.String), ('preparation_conditions', sa.JSON))))
    groups = {}
    for row in connection.execute(sa.select(tasks.c.id, tasks.c.template_id, tasks.c.phase_id).where(
            tasks.c.project_id.is_(None), tasks.c.module_id.is_(None), tasks.c.phase_id.isnot(None))).mappings():
        key = (row['template_id'], row['phase_id'])
        if key not in groups:
            name = connection.execute(sa.select(phases.c.name).where(phases.c.id == row['phase_id'])).scalar() or '工作'
            groups[key] = _id()
            connection.execute(module_rows.insert().values(id=groups[key], project_id=None, template_id=row['template_id'],
                                                           phase_id=row['phase_id'], name=name, category='core', is_selected=True,
                                                           sort_order=0, description='', applies_to_all_vehicles=True,
                                                           source_module_id=None, preparation_conditions=[]))
        connection.execute(tasks.update().where(tasks.c.id == row['id']).values(module_id=groups[key]))
    op.drop_column('tasks', 'template_fields')
    op.drop_table('template_fields')
    op.drop_table('template_items')
    op.drop_table('template_sections')
