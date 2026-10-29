"""Templates are edited in place: work items can be deleted, everything can be reordered or moved, and templates renamed."""
from app.db import SessionLocal
from app.models import ChangeLog, CheckItem


def _phases(client, headers, tid='default'):
    response = client.get(f'/api/templates/{tid}/work-items', headers=headers)
    assert response.status_code == 200, response.text
    return response.json()['phases']


def _layout(phases):
    return {'groups': [{'id': phase['id'], 'stage_key': phase['stage_key'], 'item_ids': [item['id'] for item in phase['work_items']]} for phase in phases]}


def test_deleting_a_template_work_item_keeps_existing_projects(client, admin_headers, pm_headers):
    phases = _phases(client, admin_headers)
    victim = next(item for phase in phases for item in phase['work_items'] if item['check_definitions'])
    work_ids = [item['id'] for phase in _phases(client, pm_headers) for item in phase['work_items']]
    project = client.post('/api/projects', headers=pm_headers, json={'name': '删除前项目', 'start_date': '2026-10-01', 'end_date': '2026-12-31',
                                                                     'template_id': 'default', 'work_item_ids': work_ids}).json()
    assert client.delete(f'/api/templates/default/work-items/{victim["id"]}', headers=pm_headers).status_code == 403
    deleted = client.delete(f'/api/templates/default/work-items/{victim["id"]}', headers=admin_headers)
    assert deleted.status_code == 200, deleted.text
    assert victim['id'] not in {item['id'] for phase in _phases(client, admin_headers) for item in phase['work_items']}
    with SessionLocal() as db:
        assert db.query(CheckItem).filter_by(task_id=victim['id']).count() == 0
        assert db.query(ChangeLog).filter_by(entity_id=victim['id'], action='delete').count() == 1
    kept = client.get(f'/api/projects/{project["id"]}/work-items', headers=pm_headers).json()['phases']
    assert victim['name'] in {item['name'] for phase in kept for item in phase['work_items']}
    assert client.delete(f'/api/templates/default/work-items/{victim["id"]}', headers=admin_headers).status_code == 404


def test_layout_reorders_and_moves_items_and_groups(client, admin_headers):
    phases = _phases(client, admin_headers)
    layout = _layout(phases)
    single = next(group for group in layout['groups'] if len(group['item_ids']) > 2)
    single['item_ids'].reverse()
    moved = single['item_ids'].pop()
    target = next(group for group in layout['groups'] if group is not single)
    target['item_ids'].insert(0, moved)
    target['stage_key'] = '8'
    saved = client.put('/api/templates/default/work-layout', headers=admin_headers, json=layout)
    assert saved.status_code == 200, saved.text
    after = {phase['id']: phase for phase in _phases(client, admin_headers)}
    assert [item['id'] for item in after[single['id']]['work_items']] == single['item_ids']
    assert after[target['id']]['work_items'][0]['id'] == moved and after[target['id']]['stage_key'] == '8'
    assert [phase['stage_key'] for phase in _phases(client, admin_headers)][-1] in ('8', '9')


def test_stale_layout_is_refused(client, admin_headers, pm_headers):
    layout = _layout(_phases(client, admin_headers))
    dropped = layout['groups'][0]['item_ids'].pop()
    response = client.put('/api/templates/default/work-layout', headers=admin_headers, json=layout)
    assert response.status_code == 409
    assert dropped in {item['id'] for phase in _phases(client, admin_headers) for item in phase['work_items']}
    layout['groups'][0]['item_ids'] += [dropped, dropped]
    assert client.put('/api/templates/default/work-layout', headers=admin_headers, json=layout).status_code == 409
    assert client.put('/api/templates/default/work-layout', headers=pm_headers, json=_layout(_phases(client, admin_headers))).status_code == 403


def test_template_name_and_description_are_editable_with_a_trail(client, admin_headers):
    created = client.post('/api/templates', headers=admin_headers, json={'name': '待改名模板', 'copy_from': 'default'}).json()
    response = client.put(f'/api/templates/{created["id"]}', headers=admin_headers, json={'name': ' 叉车模板 ', 'description': ''})
    assert response.status_code == 200, response.text
    listed = next(row for row in client.get('/api/templates', headers=admin_headers).json() if row['id'] == created['id'])
    assert listed['name'] == '叉车模板' and listed['description'] == ''
    with SessionLocal() as db:
        assert db.query(ChangeLog).filter_by(entity_id=created['id'], action='update').count() == 1
    assert client.put('/api/templates/default', headers=admin_headers, json={'name': '改系统模板'}).status_code == 400
    assert client.put(f'/api/templates/{created["id"]}', headers=admin_headers, json={'name': '   '}).status_code == 400
