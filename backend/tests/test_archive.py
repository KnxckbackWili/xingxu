"""T22 archive material evidence uses the canonical document stream."""
from tests.document_helpers import documents, upload_documents


def project(client, headers):
    result = client.post('/api/projects', headers=headers, json={'name': '归档资料测试', 'start_date': '2026-08-01', 'end_date': '2026-09-30'})
    assert result.status_code == 200, result.text
    return result.json()['id']


def test_document_list_has_stable_identity_and_no_automatic_submission(client, pm_headers):
    pid = project(client, pm_headers)
    first = documents(client, pm_headers, pid)
    second = documents(client, pm_headers, pid)
    assert [row['id'] for row in first['documents']] == [row['id'] for row in second['documents']]
    assert len([row for row in first['definitions'] if row['stage_key'] != 'legacy']) == 53
    assert all(row['status'] == 'pending' and not row['versions'] for row in first['documents'])


def test_archive_material_requires_real_file(client, pm_headers):
    pid = project(client, pm_headers)
    row = documents(client, pm_headers, pid)['documents'][0]
    result = client.post(f'/api/projects/{pid}/documents/submit', headers=pm_headers, json={'document_ids': [row['id']]})
    assert result.status_code == 422
    submitted = upload_documents(client, pm_headers, pid, [row['id']])['documents'][0]
    assert submitted['status'] == 'submitted' and submitted['versions'][0]['attachment_id']


def test_nonmember_cannot_write_archive_material(client, pm_headers, worker_headers):
    pid = project(client, pm_headers)
    row = documents(client, pm_headers, pid)['documents'][0]
    result = client.put(f'/api/projects/{pid}/documents/{row["id"]}', headers=worker_headers,
        json={'status': 'waived', 'reason': '越权不适用', 'version': row['version']})
    assert result.status_code == 404
