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


def test_a_fresh_install_has_one_standard_template(client, pm_headers):
    names = [template['name'] for template in client.get('/api/templates', headers=pm_headers).json()]
    assert names == ['系统默认模板']


def test_merging_adds_only_missing_content_and_removes_the_source(client, admin_headers, pm_headers):
    from app.db import SessionLocal
    from app.models import Phase, Task, CheckItem, DocumentRequirement, Template, VehicleStep
    copy = client.post('/api/templates', headers=admin_headers, json={'name': '叉车模板', 'copy_from': 'default'}).json()['id']
    with SessionLocal() as db:
        default_tasks = db.query(Task).filter(Task.template_id.is_(None), Task.project_id.is_(None)).count()
        default_docs = db.query(DocumentRequirement).filter_by(template_id=None).count()
        phase = db.query(Phase).filter_by(template_id=copy).filter(Phase.stage_key == '6').first()
        extra = Task(template_id=copy, phase_id=phase.id, name='叉车货叉校准', group_label='叉车', applicable_vehicle_types=['叉车式'],
                     quantity_type='fixed', unit='项', sort_order=999)
        db.add(extra); db.flush()
        db.add(CheckItem(template_id=copy, task_id=extra.id, name='货叉水平', is_required=True, is_safety_critical=False, sort_order=0))
        db.add(DocumentRequirement(template_id=copy, stage_key='6', code='6.99', name='叉车点检表', template_no='', is_group=False, required=True,
                                   scope='project', timing_type='on_demand', sort_order=999, note=''))
        db.add(VehicleStep(template_id=copy, key='fork_check', name='货叉检查', sort_order=99))
        db.commit()
    merged = client.post(f'/api/templates/{copy}/merge', headers=admin_headers)
    assert merged.status_code == 200, merged.text
    assert merged.json()['added'] == {'work_items': 1, 'documents': 1, 'vehicle_steps': 1, 'procurement_items': 0}
    with SessionLocal() as db:
        assert db.get(Template, copy) is None
        assert db.query(Task).filter(Task.template_id.is_(None), Task.project_id.is_(None)).count() == default_tasks + 1
        added = db.query(Task).filter(Task.template_id.is_(None), Task.name == '叉车货叉校准').one()
        assert added.applicable_vehicle_types == ['叉车式'] and added.group_label == '叉车'
        assert [check.name for check in db.query(CheckItem).filter_by(task_id=added.id)] == ['货叉水平']
        assert db.query(DocumentRequirement).filter_by(template_id=None).count() == default_docs + 1
        assert db.query(VehicleStep).filter_by(template_id='default', key='fork_check').count() == 1
    assert client.post('/api/templates/default/merge', headers=admin_headers).status_code == 400
    assert client.post(f'/api/templates/{copy}/merge', headers=pm_headers).status_code == 403


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
