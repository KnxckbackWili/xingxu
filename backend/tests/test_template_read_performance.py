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
