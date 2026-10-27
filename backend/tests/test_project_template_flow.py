"""从方案选范围、确认工作量，到后续模板修改的使用契约。"""
from app.db import SessionLocal
from app.models import Template, Phase, Module, Task, DocumentRequirement


def make_template():
    with SessionLocal() as db:
        tpl = Template(name='窄巷道现场方案', is_system=False, version=3)
        db.add(tpl); db.flush()
        phase = Phase(template_id=tpl.id, name='现场安装', sort_order=1)
        db.add(phase); db.flush()
        module = Module(template_id=tpl.id, phase_id=phase.id, name='站点部署')
        db.add(module); db.flush()
        a = Task(template_id=tpl.id, module_id=module.id, name='站点确认', quantity_type='manual', unit='个')
        b = Task(template_id=tpl.id, module_id=module.id, name='单车检查', quantity_type='per_vehicle', unit='台')
        db.add_all([a, b, DocumentRequirement(template_id=tpl.id, stage_key='6', code='6.99', name='窄巷道净宽确认', scope='project', timing_type='on_demand')])
        db.commit()
        return tpl.id, phase.id, module.id, a.id, b.id


def test_custom_solution_scope_and_snapshot_survive_template_deletion(client, admin_headers, pm_headers):
    tid, phase_id, mid, manual, vehicle = make_template()
    result = client.post('/api/projects', headers=pm_headers, json={
        'name': '真实窄巷道项目', 'start_date': '2026-09-16', 'end_date': '2026-12-31',
        'template_id': tid, 'module_ids': [mid],
        'vehicles': [{'vehicle_type': '潜伏式', 'model_name': 'T6', 'quantity': 3}],
    })
    assert result.status_code == 200, result.text
    pid = result.json()['id']
    details = client.get(f'/api/projects/{pid}', headers=pm_headers).json()
    assert details['source_template'] == {'id': tid, 'name': '窄巷道现场方案', 'version': 3, 'available': True}
    preps = client.get(f'/api/projects/{pid}/documents', headers=pm_headers).json()['definitions']
    assert {item['name'] for item in preps} == {'窄巷道净宽确认'}
    tree = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    assert tree[0]['id'] != phase_id
    tasks = tree[0]['modules'][0]['tasks']
    assert {task['name'] for task in tasks} == {'站点确认', '单车检查'}
    assert client.delete(f'/api/templates/{tid}', headers=admin_headers).status_code == 200
    assert client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json() == tree
    progress = client.get(f'/api/projects/{pid}/progress', headers=pm_headers).json()
    assert progress['phases'][0]['name'] == '现场安装'


def test_excluded_work_can_be_added_later_from_same_source(client, pm_headers):
    tid, _, mid, manual, vehicle = make_template()
    result = client.post('/api/projects', headers=pm_headers, json={
        'name': '分批实施', 'start_date': '2026-09-16', 'end_date': '2026-12-31',
        'template_id': tid, 'module_ids': [mid], 'exclude_task_ids': [vehicle],
    })
    assert result.status_code == 200, result.text
    pid = result.json()['id']
    tree = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    assert len(tree[0]['modules'][0]['tasks']) == 1
    added = client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'module_ids': [mid]})
    assert added.status_code == 200, added.text
    assert added.json()['tasks'] == 1
    after = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    assert len(after[0]['modules'][0]['tasks']) == 2
    assert {task['source_task_id'] for task in after[0]['modules'][0]['tasks']} == {manual, vehicle}


def test_stale_scope_rolls_back_creation(client, pm_headers):
    tid, _, mid, _, _ = make_template()
    result = client.post('/api/projects', headers=pm_headers, json={
        'name': '失效方案', 'start_date': '2026-09-16', 'end_date': '2026-12-31',
        'template_id': tid, 'module_ids': [mid], 'exclude_task_ids': ['not-in-template'],
    })
    assert result.status_code == 400
    assert not any(project['name'] == '失效方案' for project in client.get('/api/projects', headers=pm_headers).json())


def test_presets_have_real_content_and_selection(client, pm_headers):
    templates = client.get('/api/templates', headers=pm_headers).json()
    simple = next(template for template in templates if template['name'] == '潜伏式简版模板')
    phases = client.get(f"/api/templates/{simple['id']}/tree", headers=pm_headers).json()
    selected = {module['name'] for phase in phases for module in phase['modules'] if module['is_selected']}
    assert selected == {'到货检查', '单车调试', '系统联调', '培训验收'}
    assert sum(len(module['tasks']) for phase in phases for module in phase['modules']) > 20


def test_template_edit_keeps_identity_documents_and_project_customization(client, admin_headers, pm_headers):
    tid, phase_id, mid, manual, vehicle = make_template()
    doc = client.post(f'/api/templates/{tid}/tasks/{manual}/reference-docs', headers=admin_headers,
                      files={'file': ('现场规范.txt', b'field guide', 'text/plain')})
    assert doc.status_code == 200
    tree = client.get(f'/api/templates/{tid}/tree', headers=pm_headers).json()
    pid = client.post('/api/projects', headers=pm_headers, json={
        'name': '方案更新前项目', 'start_date': '2026-09-16', 'end_date': '2026-12-31',
        'template_id': tid, 'module_ids': [mid],
    }).json()['id']
    project_tree = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    tree[0]['name'] = '新现场安装标准'
    tree[0]['modules'][0]['is_selected'] = False
    tree[0]['modules'][0]['tasks'][0]['name'] = '新版站点确认'
    saved = client.put(f'/api/templates/{tid}/tree', headers=admin_headers, json={'phases': tree, 'replace_missing_phases': True})
    assert saved.status_code == 200, saved.text
    new_tree = client.get(f'/api/templates/{tid}/tree', headers=pm_headers).json()
    assert new_tree[0]['id'] == phase_id
    assert new_tree[0]['modules'][0]['id'] == mid
    assert new_tree[0]['modules'][0]['is_selected'] is False
    assert next(task for task in new_tree[0]['modules'][0]['tasks'] if task['id'] == manual)['ref_docs'][0]['filename'] == '现场规范.txt'
    assert client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json() == project_tree
    preps = client.get(f'/api/templates/{tid}/document-requirements', headers=pm_headers).json()
    assert {item['name'] for item in preps} == {'窄巷道净宽确认'}
    # 编辑器明确删除的阶段不会保存后又被自动恢复。
    assert client.put(f'/api/templates/{tid}/tree', headers=admin_headers, json={'phases': [], 'replace_missing_phases': True}).status_code == 200
    assert client.get(f'/api/templates/{tid}/tree', headers=pm_headers).json() == []
    assert client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json() == project_tree


def test_clone_keeps_project_scope_and_local_edits(client, pm_headers):
    tid, _, mid, manual, vehicle = make_template()
    response = client.post('/api/projects', headers=pm_headers, json={
        'name': '一期方案', 'start_date': '2026-09-16', 'end_date': '2026-12-31',
        'template_id': tid, 'module_ids': [mid], 'exclude_task_ids': [vehicle],
    })
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    with SessionLocal() as db:
        task = db.query(Task).filter_by(project_id=pid).one()
        task.name = '现场定制站点'
        task.manually_completed = True
        db.commit()
    result = client.post(f'/api/projects/{pid}/clone', headers=pm_headers, json={'name': '二期'})
    assert result.status_code == 200, result.text
    new_id = result.json()['id']
    with SessionLocal() as db:
        copied = db.query(Task).filter_by(project_id=new_id).one()
        assert copied.name == '现场定制站点'
        assert copied.source_task_id == manual
        assert not copied.manually_completed
