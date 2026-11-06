"""工作快照及原日程填报来源保全。"""
from tests.lifecycle_helpers import versioned
from tests.template_work import default_work



def _project_with_member(client, pm_headers, worker_headers):
    r = client.post('/api/projects', headers=pm_headers, json={'name': '工作快照保全项目', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'})
    pid = r.json()['id']
    client.post(f'/api/projects/{pid}/vehicles', headers=pm_headers, json={'vehicle_type': '潜伏式', 'model_name': 'AGV-500', 'quantity': 2})
    client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'work_item_ids': default_work('mod-03')})
    wid = client.get('/api/auth/me', headers=worker_headers).json()['id']
    r = client.get(f'/api/projects/{pid}', headers=pm_headers)
    return pid

def test_generate_preserves_project_snapshot_no_duplicate(client, pm_headers):
    """C2-6：模板改名后再次带入 → 保留项目任务原名，不覆盖现场计划也不重复。"""
    pid = client.post('/api/projects', headers=pm_headers, json={'name': '改名幂等项目', 'start_date': '2026-08-10', 'new_vehicles': False, 'end_date': '2026-09-30'}).json()['id']
    client.post(f'/api/projects/{pid}/vehicles', headers=pm_headers, json={'vehicle_type': '潜伏式', 'model_name': 'AGV-500', 'quantity': 2})
    client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'work_item_ids': default_work('mod-03')})
    tree = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    names_before = {t['name'] for ph in tree for m in ph['modules'] for t in m['tasks']}
    assert '单车调试' in names_before
    from app.db import SessionLocal
    from app.models import Task
    db = SessionLocal()
    try:
        tpl_task = db.get(Task, default_work('mod-03')[0])
        assert tpl_task is not None
        tpl_task.name = '单车调试（改名后）'
        db.commit()
    finally:
        db.close()
    client.post(f'/api/projects/{pid}/tasks/generate', headers=pm_headers, json={'work_item_ids': default_work('mod-03')})
    tree2 = client.get(f'/api/projects/{pid}/tree', headers=pm_headers).json()
    names_after = {t['name'] for ph in tree2 for m in ph['modules'] for t in m['tasks']}
    assert '单车调试（改名后）' not in names_after
    assert '单车调试' in names_after, '项目快照应保留，不随模板改名'
    count_after = sum((1 for ph in tree2 for m in ph['modules'] for t in m['tasks']))
    assert count_after == 1
