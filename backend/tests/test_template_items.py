"""Templates as titled sections of one-row items: editing, compiling, copying, Excel and project creation."""
import io

import sqlalchemy as sa
from alembic import command
from openpyxl import load_workbook

from app.db import SessionLocal
from app.models import (ChangeLog, CheckItem, DocumentRequirement, Phase, ProjectDocumentDefinition, ProjectPreparationItem,
                        Task, TemplateItem, VehicleStep)
from tests.test_vehicle_progress_migration import config


def tree(client, headers, tid='default'):
    response = client.get(f'/api/templates/{tid}/items', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def rows(data):
    return {item['name']: item for section in data['sections'] for item in section['items']}


def new_template(client, headers, name='新事项模板', copy_from='default'):
    response = client.post('/api/templates', headers=headers, json={'name': name, 'copy_from': copy_from})
    assert response.status_code == 200, response.text
    return response.json()['id']


def body(item, **changes):
    keep = ('section_id', 'kind', 'name', 'note', 'optional', 'per_vehicle', 'checks', 'files', 'quantity', 'unit', 'spec', 'version')
    data = {key: item[key] for key in keep}
    data['files'] = [{key: value for key, value in file.items() if key != 'blank_file'} for file in item['files']]
    return {**data, **changes}


def test_default_is_about_twenty_rows_with_every_company_document(client, pm_headers):
    data = tree(client, pm_headers)
    items = rows(data)
    assert 18 <= len(items) <= 26 and len(data['sections']) >= 6
    assert {item['kind'] for item in items.values()} == {'work', 'file', 'purchase'}
    assert sum(len(item['files']) for item in items.values()) == 53
    assert items['到场点检']['per_vehicle'] and [f['code'] for f in items['到场点检']['files']] == ['6.1', '6.10.1']
    assert all(items[name]['optional'] for name in ('WMS/MES 对接', '电梯/自动门对接', 'PLC 对接', '备件（坏件更换）'))
    # A purchase can sit in a later section too: spare parts once the site runs.
    trial = next(section for section in data['sections'] if any(item['name'] == '备件（坏件更换）' for item in section['items']))
    assert trial['stage_key'] == '6' and trial['title'] == '试运行'
    with SessionLocal() as db:
        steps = [row.key for row in db.query(VehicleStep).filter_by(template_id='default').order_by(VehicleStep.sort_order)]
        assert steps == ['arrival_inspection', 'single_commissioning', 'system_integration', 'go_live']
        assert db.query(Task).filter(Task.template_id.is_(None), Task.project_id.is_(None)).count() == sum(item['kind'] == 'work' for item in items.values())


def test_sections_are_free_titles_on_a_stage_and_rows_follow_their_stage(client, admin_headers, pm_headers):
    tid = new_template(client, admin_headers)
    data = tree(client, admin_headers, tid)
    first = data['sections'][0]
    added = client.post(f'/api/templates/{tid}/sections', headers=admin_headers, json={'title': ' 客户现场培训 ', 'stage_key': '7', 'after_id': first['id']})
    assert added.status_code == 200, added.text
    section = next(row for row in added.json()['sections'] if row['id'] == added.json()['id'])
    assert section['title'] == '客户现场培训' and added.json()['sections'][1]['id'] == section['id']
    item = client.post(f'/api/templates/{tid}/items', headers=admin_headers, json={
        'section_id': section['id'], 'kind': 'file', 'name': '培训照片', 'files': [{'name': '培训签到照片'}]})
    assert item.status_code == 200, item.text
    created = rows(item.json())['培训照片']
    assert created['files'][0]['code'].startswith('7.')
    renamed = client.put(f'/api/templates/{tid}/sections/{section["id"]}', headers=admin_headers, json={'title': '交付培训', 'stage_key': '8'})
    assert renamed.status_code == 200, renamed.text
    with SessionLocal() as db:
        assert db.get(Phase, section['id']).name == '交付培训' and db.get(Phase, section['id']).stage_key == '8'
        assert db.get(DocumentRequirement, created['files'][0]['id']).stage_key == '8'
    assert client.put(f'/api/templates/{tid}/sections/{section["id"]}', headers=pm_headers, json={'title': '无权修改'}).status_code == 403
    removed = client.delete(f'/api/templates/{tid}/sections/{section["id"]}', headers=admin_headers)
    assert removed.status_code == 200 and all(row['id'] != section['id'] for row in removed.json()['sections'])
    with SessionLocal() as db:
        assert db.get(DocumentRequirement, created['files'][0]['id']) is None and db.get(Phase, section['id']) is None
        assert db.query(ChangeLog).filter_by(entity_type='template', entity_id=tid).filter(ChangeLog.detail.like('%删除段落%')).count() == 1


def test_a_row_compiles_to_work_checks_files_and_its_own_vehicle_step(client, admin_headers):
    tid = new_template(client, admin_headers)
    section = tree(client, admin_headers, tid)['sections'][2]['id']
    created = client.post(f'/api/templates/{tid}/items', headers=admin_headers, json={
        'section_id': section, 'kind': 'work', 'name': '激光雷达标定', 'per_vehicle': True,
        'checks': [{'name': '标定板放置正确', 'safety': True}, {'name': '记录标定参数', 'required': False}],
        'files': [{'name': '标定记录', 'scope': 'vehicle', 'timing_type': 'after_event', 'timing_event': 'vehicle_arrival', 'timing_offset_hours': 48}]})
    assert created.status_code == 200, created.text
    item = rows(created.json())['激光雷达标定']
    with SessionLocal() as db:
        task = db.get(Task, item['id'])
        assert task.quantity_type == 'per_vehicle' and task.vehicle_step_key == item['step_key'] and task.phase_id == section
        assert [(c.name, c.is_safety_critical, c.is_required) for c in db.query(CheckItem).filter_by(task_id=task.id).order_by(CheckItem.sort_order)] == [
            ('标定板放置正确', True, True), ('记录标定参数', False, False)]
        assert db.query(VehicleStep).filter_by(template_id=tid, key=item['step_key']).one().name == '激光雷达标定'
        rule = db.get(DocumentRequirement, item['files'][0]['id'])
        assert rule.scope == 'vehicle' and rule.timing_event == 'vehicle_arrival' and rule.stage_key == '6'
    changed = client.put(f'/api/templates/{tid}/items/{item["id"]}', headers=admin_headers, json=body(item, per_vehicle=False, name='激光雷达复核'))
    assert changed.status_code == 200, changed.text
    stale = client.put(f'/api/templates/{tid}/items/{item["id"]}', headers=admin_headers, json=body(item, name='旧页面'))
    assert stale.status_code == 409
    other = rows(changed.json())['到场点检']
    duplicate = client.put(f'/api/templates/{tid}/items/{other["id"]}', headers=admin_headers,
                           json=body(other, files=[{**{k: v for k, v in other['files'][0].items() if k != 'blank_file'}, 'code': item['files'][0]['code']}]))
    assert duplicate.status_code == 409 and '已被' in duplicate.json()['detail']
    with SessionLocal() as db:
        assert db.get(Task, item['id']).quantity_type == 'fixed'
        assert db.query(VehicleStep).filter_by(template_id=tid, key=item['step_key']).count() == 0
    bad = client.post(f'/api/templates/{tid}/items', headers=admin_headers, json={'section_id': section, 'kind': 'file', 'name': '空资料'})
    assert bad.status_code == 422
    deleted = client.delete(f'/api/templates/{tid}/items/{item["id"]}', headers=admin_headers)
    assert deleted.status_code == 200 and '激光雷达复核' not in rows(deleted.json())
    with SessionLocal() as db:
        assert db.get(Task, item['id']) is None and db.get(DocumentRequirement, item['files'][0]['id']) is None


def test_drag_layout_moves_rows_and_refuses_a_stale_page(client, admin_headers):
    tid = new_template(client, admin_headers)
    data = tree(client, admin_headers, tid)
    layout = [{'id': s['id'], 'item_ids': [i['id'] for i in s['items']]} for s in data['sections']]
    moved = layout[0]['item_ids'].pop(0)
    layout[-1]['item_ids'].insert(0, moved)
    layout.reverse()
    saved = client.put(f'/api/templates/{tid}/layout', headers=admin_headers, json={'sections': layout})
    assert saved.status_code == 200, saved.text
    assert saved.json()['sections'][0]['items'][0]['id'] == moved
    with SessionLocal() as db:
        assert db.get(TemplateItem, moved).section_id == layout[0]['id']
    layout[0]['item_ids'].pop(0)
    assert client.put(f'/api/templates/{tid}/layout', headers=admin_headers, json={'sections': layout}).status_code == 409


def test_rows_copy_between_templates_with_their_blank_forms(client, admin_headers):
    from tests.template_work import upload_template_blank
    assert upload_template_blank(client, admin_headers, '6.1', {'file': ('点检表.xlsx', b'blank check sheet')}).status_code == 200
    target = client.post('/api/templates', headers=admin_headers, json={'name': '空白起点', 'copy_from': 'default'}).json()['id']
    data = tree(client, admin_headers, target)
    for section in data['sections']:
        assert client.delete(f'/api/templates/{target}/sections/{section["id"]}', headers=admin_headers).status_code == 200
    assert tree(client, admin_headers, target)['sections'] == []
    source = rows(tree(client, admin_headers))
    copied = client.post(f'/api/templates/{target}/items/copy', headers=admin_headers, json={
        'source_template_id': 'default', 'item_ids': [source['到场点检']['id'], source['AGV 本体']['id']]})
    assert copied.status_code == 200, copied.text
    result = rows(copied.json())
    assert set(result) == {'到场点检', 'AGV 本体'}
    check = result['到场点检']
    assert check['per_vehicle'] and [f['code'] for f in check['files']] == ['6.1', '6.10.1']
    assert check['files'][0]['blank_file']['filename'] == '点检表.xlsx'
    assert check['files'][0]['blank_file']['id'] != source['到场点检']['files'][0]['blank_file']['id']
    again = client.post(f'/api/templates/{target}/items/copy', headers=admin_headers, json={'source_template_id': 'default', 'item_ids': [source['到场点检']['id']]})
    codes = [f['code'] for item in again.json()['sections'][0]['items'] for f in item['files']]
    assert len(codes) == len(set(codes)) == 4  # a second copy gets free codes
    assert client.post(f'/api/templates/{target}/items/copy', headers=admin_headers, json={'source_template_id': target, 'item_ids': [check['id']]}).status_code == 400


def test_excel_roundtrip_replaces_content_and_keeps_files_by_code(client, admin_headers):
    from tests.template_work import upload_template_blank
    tid = new_template(client, admin_headers, 'Excel 模板')
    assert upload_template_blank(client, admin_headers, '7.1', {'file': ('验收单.docx', b'blank acceptance')}, tid).status_code == 200
    before = rows(tree(client, admin_headers, tid))
    exported = client.get(f'/api/templates/{tid}/excel', headers=admin_headers)
    assert exported.status_code == 200 and exported.content[:2] == b'PK'
    book = load_workbook(io.BytesIO(exported.content))
    sheet = book['事项']
    names = [row[3].value for row in sheet.iter_rows(min_row=2)]
    survey = names.index('场地勘测') + 2
    sheet.cell(survey, 4, '场地复勘')
    sheet.cell(survey, 7, '[安全]围栏完整\n[选做]拍照存档')
    sheet.append(['新增段落', '验收', '采购', '验收礼品', '是', '', '', '', 3, '份', '定制', ''])
    buffer = io.BytesIO(); book.save(buffer)
    imported = client.post(f'/api/templates/{tid}/excel', headers=admin_headers, files={'file': ('t.xlsx', buffer.getvalue())})
    assert imported.status_code == 200, imported.text
    after = rows(imported.json())
    assert '场地勘测' not in after and after['场地复勘']['checks'] == [
        {'id': after['场地复勘']['checks'][0]['id'], 'name': '围栏完整', 'description': '', 'required': True, 'safety': True},
        {'id': after['场地复勘']['checks'][1]['id'], 'name': '拍照存档', 'description': '', 'required': False, 'safety': False}]
    assert after['验收礼品']['kind'] == 'purchase' and after['验收礼品']['optional'] and after['验收礼品']['quantity'] == 3
    acceptance = after['最终验收']
    assert acceptance['id'] == before['最终验收']['id'] and acceptance['files'][0]['id'] == before['最终验收']['files'][0]['id']
    assert acceptance['files'][0]['blank_file']['filename'] == '验收单.docx'
    assert imported.json()['sections'][-1]['title'] == '新增段落' and imported.json()['sections'][-1]['stage_key'] == '7'
    wrong = client.post(f'/api/templates/{tid}/excel', headers=admin_headers, files={'file': ('bad.xlsx', b'not a workbook')})
    assert wrong.status_code == 400
    assert rows(tree(client, admin_headers, tid)) == after


def test_new_project_takes_required_rows_and_only_the_optional_ones_chosen(client, admin_headers, pm_headers):
    items = rows(tree(client, pm_headers))
    payload = {'name': '按事项建项目', 'start_date': '2026-11-01', 'end_date': '2027-01-31', 'template_id': 'default'}
    assert client.post('/api/projects', headers=pm_headers, json={**payload, 'optional_item_ids': [items['场地勘测']['id']]}).status_code == 400
    created = client.post('/api/projects', headers=pm_headers, json={**payload, 'optional_item_ids': [items['PLC 对接']['id'], items['备件（坏件更换）']['id']]})
    assert created.status_code == 200, created.text
    pid = created.json()['id']
    with SessionLocal() as db:
        names = {row.name for row in db.query(Task).filter_by(project_id=pid)}
        assert {'场地勘测', '到场点检', 'PLC 对接'} <= names and 'WMS/MES 对接' not in names and '电梯/自动门对接' not in names
        codes = {row.code for row in db.query(ProjectDocumentDefinition).filter_by(project_id=pid)}
        assert '6.11.5' in codes and len(codes) == 53
        purchases = {row.name: row for row in db.query(ProjectPreparationItem).filter_by(project_id=pid, category='procurement')}
        assert set(purchases) == {'AGV 本体', '自动充电桩', '备件（坏件更换）'}
        assert purchases['AGV 本体'].extra['unit'] == '台' and purchases['备件（坏件更换）'].required_date is None
    without = client.post('/api/projects', headers=pm_headers, json={**payload, 'name': '不要PLC', 'optional_item_ids': []}).json()['id']
    with SessionLocal() as db:
        assert '6.11.5' not in {row.code for row in db.query(ProjectDocumentDefinition).filter_by(project_id=without)}
        assert 'PLC 对接' not in {row.name for row in db.query(Task).filter_by(project_id=without)}


def test_template_name_and_description_are_editable_with_a_trail(client, admin_headers):
    tid = new_template(client, admin_headers, '待改名模板')
    response = client.put(f'/api/templates/{tid}', headers=admin_headers, json={'name': ' 叉车模板 ', 'description': ''})
    assert response.status_code == 200, response.text
    listed = next(row for row in client.get('/api/templates', headers=admin_headers).json() if row['id'] == tid)
    assert listed['name'] == '叉车模板' and listed['summary']['work'] >= 10 and listed['summary']['files'] == 53
    assert client.put('/api/templates/default', headers=admin_headers, json={'name': '改系统模板'}).status_code == 400


def test_upgrade_converts_templates_keeps_project_document_links_and_the_old_default(monkeypatch, tmp_path):
    url = 'sqlite:///' + str(tmp_path / 'items.db')
    monkeypatch.setattr('app.config.DATABASE_URL', url)
    cfg = config()
    command.upgrade(cfg, 'g3a92b000001')
    engine = sa.create_engine(url)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO projects (id,name,start_date,end_date,status,members) VALUES ('p','既有项目','2026-01-01','2026-03-01','executing','[]')"))
        c.execute(sa.text("INSERT INTO phases (id,project_id,template_id,name,sort_order,stage_key) VALUES ('ph',NULL,NULL,'进场准备',1,'5')"))
        c.execute(sa.text("INSERT INTO modules (id,project_id,template_id,phase_id,name,sort_order) VALUES ('m',NULL,NULL,'ph','进场准备',1)"))
        c.execute(sa.text("INSERT INTO tasks (id,project_id,template_id,module_id,name,quantity_type,manually_completed,sort_order) VALUES ('old-task',NULL,NULL,'m','原勘测','fixed',false,1)"))
        c.execute(sa.text("INSERT INTO check_items (id,task_id,template_id,project_id,name,is_required,is_safety_critical,sort_order) VALUES ('old-check','old-task',NULL,NULL,'原检查',true,false,0)"))
        rule = c.execute(sa.text("SELECT id FROM document_requirements WHERE template_id IS NULL AND code='6.1'")).scalar()
        c.execute(sa.text("INSERT INTO project_document_definitions (id,project_id,requirement_id,source_key,stage_key,code,name,required,scope,timing_type,confidential_default,external_visible_default,external_never_visible,sort_order) "
                          "VALUES ('pd','p',:rule,'template:'||:rule,'6','6.1','车辆到场点检表',true,'vehicle','on_demand',false,false,false,0)"), {'rule': rule})
    command.upgrade(cfg, 'head')
    with engine.connect() as c:
        backup = c.execute(sa.text("SELECT id FROM templates WHERE name='通用模板（升级前内容）'")).scalar()
        assert backup
        assert c.execute(sa.text("SELECT template_id FROM tasks WHERE id='old-task'")).scalar() == backup
        assert c.execute(sa.text("SELECT name FROM template_items WHERE id='old-task'")).scalar() == '原勘测'
        assert c.execute(sa.text("SELECT requirement_id FROM project_document_definitions WHERE id='pd'")).scalar() == rule
        assert c.execute(sa.text("SELECT template_id FROM document_requirements WHERE id=:rule"), {'rule': rule}).scalar() == backup
        assert c.execute(sa.text("SELECT count(*) FROM template_items WHERE template_id IS NULL")).scalar() >= 18
        assert c.execute(sa.text("SELECT count(*) FROM document_requirements WHERE template_id IS NULL")).scalar() == 53
        assert c.execute(sa.text("SELECT count(*) FROM tasks WHERE template_id IS NULL AND project_id IS NULL AND module_id IS NOT NULL")).scalar() == 0
    command.downgrade(cfg, 'g3a92b000001')
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM tasks WHERE project_id IS NULL AND module_id IS NULL")).scalar() == 0
    engine.dispose()
