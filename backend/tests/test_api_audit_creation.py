"""接口认证边界与创建事务回归；只使用隔离测试库。"""
import re
import pytest




def body(client, headers):
    tree = client.get('/api/templates/default/tree', headers=headers).json()
    mid = next(m['id'] for phase in tree if phase['name'] != '项目准备' for m in phase['modules'] if m['tasks'])
    return {'name': '一次完成的项目', 'start_date': '2026-09-15', 'end_date': '2026-10-30', 'status': 'preparing',
            'vehicles': [{'vehicle_type': '潜伏式', 'model_name': 'T6', 'quantity': 3}],
            'module_ids': [mid], 'template_id': 'default', 'client_uuid': 'creation-audit-0001'}


def test_creation_is_atomic_and_replayable(client, pm_headers):
    from app.db import SessionLocal
    from app.models import Project, Vehicle, Task, ProjectCreationReceipt
    data = body(client, pm_headers)
    r = client.post('/api/projects', json=data, headers=pm_headers)
    assert r.status_code == 200, r.text
    result = r.json()
    assert result['initial_generation']['tasks'] > 0
    replay = client.post('/api/projects', json=data, headers=pm_headers)
    assert replay.status_code == 200
    assert replay.json() == result
    with SessionLocal() as db:
        assert db.query(Project).filter_by(id=result['id']).count() == 1
        assert db.query(Vehicle).filter_by(project_id=result['id']).count() == 1
        assert db.query(Task).filter_by(project_id=result['id']).count() == result['initial_generation']['tasks']
        assert db.query(ProjectCreationReceipt).count() == 1
    data['name'] = '请求内容变了'
    assert client.post('/api/projects', json=data, headers=pm_headers).status_code == 409


def test_failed_generation_rolls_back_project_and_vehicles(client, pm_headers, monkeypatch):
    from app.db import SessionLocal
    from app.models import Project, Vehicle, ProjectCreationReceipt
    import app.services.generate_tasks as generator
    data = body(client, pm_headers)
    def fail(*args, **kwargs):
        raise ValueError('模拟生成失败')
    monkeypatch.setattr(generator, 'generate_tasks_for_modules', fail)
    r = client.post('/api/projects', json=data, headers=pm_headers)
    assert r.status_code == 400
    with SessionLocal() as db:
        assert db.query(Project).filter_by(name=data['name']).count() == 0
        assert db.query(Vehicle).filter_by(model_name='T6').count() == 0
        assert db.query(ProjectCreationReceipt).count() == 0


@pytest.mark.parametrize('invalid', [None, 'not-a-list', [None], {'bad': 'id'}])
def test_generate_rejects_malformed_modules(client, pm_headers, invalid):
    data = body(client, pm_headers)
    project = client.post('/api/projects', json=data, headers=pm_headers).json()
    r = client.post(f"/api/projects/{project['id']}/tasks/generate", json={'module_ids': invalid}, headers=pm_headers)
    assert r.status_code == 422


def test_creation_rejects_partially_invalid_module_selection(client, pm_headers):
    data = body(client, pm_headers)
    data['module_ids'].append('missing-module')
    r = client.post('/api/projects', json=data, headers=pm_headers)
    assert r.status_code == 400
    assert '模板' in r.json()['detail']


def test_project_read_routes_do_not_expose_other_projects(client, pm_headers, worker_headers):
    data = body(client, pm_headers)
    pid = client.post('/api/projects', json=data, headers=pm_headers).json()['id']
    failures = []
    for path, methods in client.get('/openapi.json').json()['paths'].items():
        if '{project_id}' not in path or 'get' not in methods:
            continue
        url = re.sub(r'\{[^}]+\}', 'audit-missing-id', path.replace('{project_id}', pid))
        response = client.get(url, headers=worker_headers)
        if response.status_code not in {403, 404, 410, 422}:  # 410: retired route, no project data
            failures.append((path, response.status_code))
    assert failures == []


@pytest.mark.parametrize('fields', [{'status': []}, {'status': 'suspended', 'reason': 123}, {'status': 'archived', 'retrospective': []}])
def test_status_rejects_bad_parameter_types(client, pm_headers, fields):
    pid = client.post('/api/projects', json=body(client, pm_headers), headers=pm_headers).json()['id']
    assert client.post(f'/api/projects/{pid}/status', json=fields, headers=pm_headers).status_code == 422


@pytest.mark.parametrize('value', ['Infinity', '-Infinity', 'NaN'])
def test_numeric_schemas_reject_non_finite_quantities(value):
    from pydantic import ValidationError
    from app.routers.worker import ProgressSubmit
    from app.routers.tasks import GenerateTasksBody
    with pytest.raises(ValidationError):
        ProgressSubmit(task_id='t', work_date='2026-09-16', completed_quantity=value, client_uuid='audit-numeric')
    with pytest.raises(ValidationError):
        GenerateTasksBody(module_ids=['m'], task_quantities={'任务': value})


def test_all_business_operations_require_authentication(client):
    schema = client.get('/openapi.json').json()
    public = {('/api/auth/login', 'post'), ('/api/auth/refresh', 'post'), ('/api/auth/logout', 'post')}
    failures = []
    checked = 0
    for path, methods in schema['paths'].items():
        if not path.startswith('/api/'):
            continue
        for method in methods:
            if method not in {'get', 'post', 'put', 'patch', 'delete'} or (path, method) in public:
                continue
            response = client.request(method.upper(), re.sub(r'\{[^}]+\}', 'audit-missing-id', path))
            checked += 1
            if response.status_code != 401:
                failures.append((method, path, response.status_code))
    assert checked > 200
    assert failures == []
