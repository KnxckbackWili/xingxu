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
        for task in phase.get('work_items', []):
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


