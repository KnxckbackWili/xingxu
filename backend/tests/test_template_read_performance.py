"""The actual template HTTP endpoint must not query once per task/checklist."""
from sqlalchemy import event
from app.db import engine


def test_default_template_rows_have_bounded_query_count(client, admin_headers):
    selects = []
    def count_select(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            selects.append(statement)
    event.listen(engine, 'before_cursor_execute', count_select)
    try:
        response = client.get('/api/templates/default/items', headers=admin_headers)
    finally:
        event.remove(engine, 'before_cursor_execute', count_select)
    assert response.status_code == 200
    rows = [item for section in response.json()['sections'] for item in section['items']]
    assert len(rows) >= 15 and any(item['checks'] for item in rows)
    # Constant per request (auth, sections, rows, fields, references, blank forms), independent of row count.
    assert len(selects) <= 10, f'Template rows used {len(selects)} SELECTs for {len(rows)} rows'


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
    assert len(items) >= 10 and any(w['kind'] == 'vehicle' and w['matrix'] for w in items)
    assert len(selects) <= 25, f'Project tree used {len(selects)} SELECTs for {len(items)} work items'
