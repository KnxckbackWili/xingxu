"""Canonical real-file fixtures for lifecycle/security tests after T22."""
import json


def documents(client, headers, project_id):
    result = client.get(f'/api/projects/{project_id}/documents', headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


def upload_documents(client, headers, project_id, document_ids=(), *, content=b'fixture evidence', name='evidence.txt', **fields):
    result = client.post(f'/api/projects/{project_id}/documents/files', headers=headers,
        files={'file': (name, content, 'application/octet-stream')},
        data={'document_ids': json.dumps(list(document_ids)), **fields})
    assert result.status_code == 200, result.text
    return result.json()


def complete_documents(client, headers, project_id):
    rows = documents(client, headers, project_id)['documents']
    ids = [row['id'] for row in rows if row['required'] and row['applicable'] and row['status'] != 'submitted']
    if ids:
        upload_documents(client, headers, project_id, ids)


def complete_checks_and_documents(client, headers, project_id):
    tree = client.get(f'/api/projects/{project_id}/tree', headers=headers).json()
    for phase in tree:
        for module in phase.get('modules', []):
            for task in module.get('tasks', []):
                for check in task.get('check_items', []):
                    if check.get('is_applicable', True) and (check.get('is_required') or check.get('is_safety_critical')):
                        response = client.put(f'/api/projects/{project_id}/check-items/{check["id"]}',
                            headers=headers, json={'is_done': True, 'version': check['version']})
                        assert response.status_code == 200, response.text
    complete_documents(client, headers, project_id)


def requirement(client, headers, project_id, *, name='资料要求', code='6.99', required=True, note=''):
    result = client.post(f'/api/projects/{project_id}/documents/requirements', headers=headers,
        json={'stage_key': '6', 'code': code, 'name': name, 'scope': 'project',
              'timing_type': 'on_demand', 'required': required, 'note': note})
    assert result.status_code == 200, result.text
    definition = result.json()
    row = next(row for row in documents(client, headers, project_id)['documents'] if row['definition_id'] == definition['id'])
    return row


def legacy_document(client, headers, project_id, task_id, *, name='原交付物', code='6.99'):
    """Construct a migrated source snapshot, never create legacy via a new HTTP write."""
    from app.db import SessionLocal
    from app.models import ProjectDocument, ProjectDocumentDefinition, Task
    row = requirement(client, headers, project_id, name=name, code=code)
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        source = {'kind': 'task_deliverable', 'task': {'id': task_id, 'version': task.version or 0},
                  'original': {'name': name, 'required': True, 'done': False}}
        for entity in (db.get(ProjectDocument, row['id']), db.get(ProjectDocumentDefinition, row['definition_id'])):
            entity.stage_key = 'legacy'
            entity.code = 'legacy.' + row['id'].replace('-', '')
            entity.timing_type = 'on_demand'; entity.timing_event = None; entity.timing_offset_hours = None
            entity.source_metadata = source
        db.commit()
    return row['id']
