"""开工工作量批量保存：原子性、并发、项目隔离。"""
import pytest


def setup_project(client, headers):
    response = client.post('/api/projects', headers=headers, json={
        'name': '开工安排测试', 'client': '客户', 'start_date': '2026-09-16',
        'end_date': '2026-10-30', 'new_vehicles': False,
        'template_id': 'default', 'module_ids': ['mod-01'],
    })
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    return pid, read_tasks(client, headers, pid)


def read_tasks(client, headers, pid):
    tree = client.get(f'/api/projects/{pid}/tree', headers=headers).json()
    return [task for phase in tree for module in phase['modules'] for task in module['tasks']]


def payload(tasks):
    return {'items': [{'id': task['id'], 'version': task['version'], 'target_quantity': i + 5} for i, task in enumerate(tasks[:2])]}


def test_save_targets_as_one_transaction(client, pm_headers):
    pid, tasks = setup_project(client, pm_headers)
    assert len(tasks) >= 2
    response = client.put(f'/api/projects/{pid}/task-targets', headers=pm_headers, json=payload(tasks))
    assert response.status_code == 200, response.text
    assert response.json()['updated'] == 2
    saved = {task['id']: task for task in read_tasks(client, pm_headers, pid)}
    for i, task in enumerate(tasks[:2]):
        assert saved[task['id']]['target_quantity'] == i + 5
        assert saved[task['id']]['version'] == task['version'] + 1


def test_last_task_conflict_rolls_back_first_task_and_version(client, pm_headers):
    pid, tasks = setup_project(client, pm_headers)
    body = payload(tasks)
    body['items'][1]['version'] += 10
    response = client.put(f'/api/projects/{pid}/task-targets', headers=pm_headers, json=body)
    assert response.status_code == 409
    saved = {task['id']: task for task in read_tasks(client, pm_headers, pid)}
    for task in tasks:
        assert saved[task['id']]['target_quantity'] == task['target_quantity']
        assert saved[task['id']]['version'] == task['version']


def test_cross_project_task_is_rejected_without_partial_save(client, pm_headers):
    pid, tasks = setup_project(client, pm_headers)
    _, other = setup_project(client, pm_headers)
    response = client.put(f'/api/projects/{pid}/task-targets', headers=pm_headers, json=payload([tasks[0], other[0]]))
    assert response.status_code == 404
    assert read_tasks(client, pm_headers, pid)[0]['version'] == tasks[0]['version']


@pytest.mark.parametrize('quantity', [0, -1, None])
def test_invalid_quantity_rejects_whole_request(client, pm_headers, quantity):
    pid, tasks = setup_project(client, pm_headers)
    body = payload(tasks); body['items'][1]['target_quantity'] = quantity
    assert client.put(f'/api/projects/{pid}/task-targets', headers=pm_headers, json=body).status_code == 422
    assert read_tasks(client, pm_headers, pid)[0]['version'] == tasks[0]['version']


def test_field_staff_and_lifecycle_guard(client, pm_headers, worker_headers):
    pid, tasks = setup_project(client, pm_headers)
    # Non-member must not even learn project task contents.
    assert client.put(f'/api/projects/{pid}/task-targets', headers=worker_headers, json=payload(tasks)).status_code in (403, 404)
    from app.db import SessionLocal
    from app.models import Project
    with SessionLocal() as db:
        project = db.get(Project, pid); project.status = 'executing'; db.commit()
    assert client.put(f'/api/projects/{pid}/task-targets', headers=pm_headers, json=payload(tasks)).status_code == 400


def test_duplicate_and_issued_schedule_guard(client, pm_headers):
    pid, tasks = setup_project(client, pm_headers)
    assert client.put(f'/api/projects/{pid}/task-targets', headers=pm_headers, json=payload([tasks[0], tasks[0]])).status_code == 400
    from app.db import SessionLocal
    from app.models import ScheduleEntry
    with SessionLocal() as db:
        from datetime import date
        db.add(ScheduleEntry(project_id=pid, task_id=tasks[0]['id'], work_date=date(2026, 9, 16), planned_quantity=1, is_confirmed=True))
        db.commit()
    assert client.put(f'/api/projects/{pid}/task-targets', headers=pm_headers, json=payload(tasks)).status_code == 400
