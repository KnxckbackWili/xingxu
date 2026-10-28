"""The actual template HTTP endpoint must not query once per task/checklist."""
from sqlalchemy import event
from app.db import engine


def test_default_template_tree_has_bounded_query_count(client, admin_headers):
    selects = []
    def count_select(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            selects.append(statement)
    event.listen(engine, 'before_cursor_execute', count_select)
    try:
        response = client.get('/api/templates/default/tree', headers=admin_headers)
    finally:
        event.remove(engine, 'before_cursor_execute', count_select)
    assert response.status_code == 200
    phases = response.json()
    tasks = [t for p in phases for m in p['modules'] for t in m['tasks']]
    assert len(tasks) >= 30
    assert any(t['check_items'] for t in tasks)
    assert any(p['name'] == '项目准备' for p in phases)
    # Constant per request (auth, tree levels, work-item rows), independent of task count.
    assert len(selects) <= 10, f'Template tree used {len(selects)} SELECTs for {len(tasks)} tasks'


def test_project_tree_query_count_does_not_grow_with_work_items(client, pm_headers):
    """The project tree (and the overview built on it) batches checks, vehicle steps and work rows."""
    phases = client.get('/api/templates/default/work-items', headers=pm_headers).json()['phases']
    work_ids = [item['id'] for phase in phases if phase['name'] != '项目准备' for item in phase['work_items']]
    created = client.post('/api/projects', headers=pm_headers, json={
        'name': '查询次数项目', 'start_date': '2026-10-01', 'end_date': '2026-12-31', 'template_id': 'default',
        'vehicles': [{'vehicle_type': '潜伏式', 'model_name': 'Q1', 'quantity': 3}], 'work_item_ids': work_ids})
    assert created.status_code == 200, created.text
    pid = created.json()['id']
    selects = []
    def count_select(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            selects.append(statement)
    event.listen(engine, 'before_cursor_execute', count_select)
    try:
        response = client.get(f'/api/projects/{pid}/tree', headers=pm_headers)
    finally:
        event.remove(engine, 'before_cursor_execute', count_select)
    assert response.status_code == 200, response.text
    items = [w for phase in response.json() for w in phase['work_items']]
    assert len(items) >= 30 and any(w['kind'] == 'vehicle' and w['matrix'] for w in items)
    assert len(selects) <= 25, f'Project tree used {len(selects)} SELECTs for {len(items)} work items'
