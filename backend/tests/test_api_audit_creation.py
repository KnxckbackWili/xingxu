"""接口认证边界与创建事务回归；只使用隔离测试库。"""
import re
import pytest




def body(client, headers):
    from tests.template_work import default_work
    return {'name': '一次完成的项目', 'start_date': '2026-09-15', 'end_date': '2026-10-30', 'status': 'preparing',
            'vehicles': [{'vehicle_type': '潜伏式', 'model_name': 'T6', 'quantity': 3}],
            'work_item_ids': default_work('mod-01'), 'template_id': 'default', 'client_uuid': 'creation-audit-0001'}


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
    import app.services.work_items as generator
    data = body(client, pm_headers)
    def fail(*args, **kwargs):
        raise ValueError('模拟生成失败')
    monkeypatch.setattr(generator, 'generate', fail)
    r = client.post('/api/projects', json=data, headers=pm_headers)
    assert r.status_code == 400
    with SessionLocal() as db:
        assert db.query(Project).filter_by(name=data['name']).count() == 0
        assert db.query(Vehicle).filter_by(model_name='T6').count() == 0
        assert db.query(ProjectCreationReceipt).count() == 0


@pytest.mark.parametrize('invalid', [None, 'not-a-list', [None], {'bad': 'id'}])
def test_generate_rejects_malformed_work_items(client, pm_headers, invalid):
    data = body(client, pm_headers)
    project = client.post('/api/projects', json=data, headers=pm_headers).json()
    r = client.post(f"/api/projects/{project['id']}/tasks/generate", json={'work_item_ids': invalid}, headers=pm_headers)
    assert r.status_code == 422


def test_creation_rejects_partially_invalid_work_selection(client, pm_headers):
    data = body(client, pm_headers)
    data['work_item_ids'].append('missing-work')
    r = client.post('/api/projects', json=data, headers=pm_headers)
    assert r.status_code == 400
    assert '模板' in r.json()['detail']


@pytest.mark.parametrize('fields', [{'status': []}, {'status': 'suspended', 'reason': 123}, {'status': 'archived', 'retrospective': []}])
def test_status_rejects_bad_parameter_types(client, pm_headers, fields):
    pid = client.post('/api/projects', json=body(client, pm_headers), headers=pm_headers).json()['id']
    assert client.post(f'/api/projects/{pid}/status', json=fields, headers=pm_headers).status_code == 422


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
