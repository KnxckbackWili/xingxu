"""Default-template vehicle work carries explicit H-2 steps into new projects."""
from tests.template_work import default_work


def test_new_project_vehicle_work_is_bound_to_default_steps(client, pm_headers):
    created = client.post('/api/projects', headers=pm_headers, json={'name': '默认环节', 'start_date': '2026-08-01', 'end_date': '2026-09-30'})
    assert created.status_code == 200, created.text
    pid = created.json()['id']
    generated = client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'work_item_ids': default_work('mod-02', 'mod-03', 'mod-06')})
    assert generated.status_code == 200, generated.text
    from app.db import SessionLocal
    from app.models import Task
    with SessionLocal() as db:
        rows = {t.name: t.vehicle_step_key for t in db.query(Task).filter(Task.project_id == pid, Task.quantity_type == 'per_vehicle')}
    assert rows['到场点检'] == 'arrival_inspection'
    assert rows['单车调试'] == 'single_commissioning'
    assert rows['系统联调'] == 'system_integration'
    assert all(rows.values()), rows


