"""管理视图与导出采用相同的当前进度依据。"""




def _minimal_import():
    return {'type': 'agvpm-project', 'project': {'name': 'round6 import', 'start_date': '2026-01-01', 'end_date': '2026-12-31'},
            'modules': [{'name': 'module', 'phase_name': 'phase', 'tasks': [{'name': 'task', 'quantity_type': 'fixed', 'target_quantity': 1}]}]}


def test_excel_overview_uses_same_weighted_progress_as_project(client, pm_headers):
    from io import BytesIO
    from openpyxl import load_workbook
    from app.db import SessionLocal
    from app.services.progress import project_progress_tree
    payload = _minimal_import()
    payload['modules'][0]['tasks'] = [
        {'name': 'large', 'quantity_type': 'fixed', 'target_quantity': 100},
        {'name': 'small', 'quantity_type': 'fixed', 'target_quantity': 1}]
    payload['progress'] = [{'task_name': 'small', 'work_date': '2026-01-01', 'completed_quantity': 1}]
    pid = client.post('/api/projects/import/json', headers=pm_headers, json=payload).json()['id']
    with SessionLocal() as db: expected = project_progress_tree(db,pid)['percent']
    workbook = load_workbook(BytesIO(client.get(f'/api/projects/{pid}/export/excel', headers=pm_headers).content))
    values = {row[1]: row[2] for row in workbook['交付概览'].iter_rows(values_only=True) if row[0]=='项目概况'}
    assert values['整体进度 %'] == expected
    assert expected != 50
