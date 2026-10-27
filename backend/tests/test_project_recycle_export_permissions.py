"""Delete/restore authority never silently includes project backup export."""
from tests.test_project_recycle_bin import _project, _policy, _delete


def test_owner_export_denial_blocks_backup_but_keeps_delete_and_restore(client, admin_headers, pm_headers):
    project = _project(client, pm_headers)
    _policy(client, admin_headers, 'user-pm-001', {'project.export': False, 'project.delete': True})
    assert client.get(f"/api/projects/{project['id']}/export/json", headers=pm_headers).status_code == 403
    deleted = _delete(client, pm_headers, project)
    assert deleted.status_code == 200, deleted.text
    path = f"/api/project-recycle-bin/projects/{project['id']}"
    row = client.get(path, headers=pm_headers).json()
    assert row['delete_backup_available'] and row['can_restore']
    assert row['can_download_backup'] is False
    listed = client.get('/api/project-recycle-bin/projects', headers=pm_headers).json()
    assert next(item for item in listed if item['id'] == project['id'])['can_download_backup'] is False
    assert client.get(path + '/backup', params={'deletion_id': row['deletion_id']}, headers=pm_headers).status_code == 403
    restored = client.post(path + '/restore', headers=pm_headers,
                           json={'version': row['version'], 'deletion_id': row['deletion_id']})
    assert restored.status_code == 200, restored.text
    assert client.get(f"/api/projects/{project['id']}", headers=pm_headers).json()['id'] == project['id']


def test_worker_delete_grant_does_not_grant_backup_download(client, admin_headers, pm_headers, worker_headers):
    project = _project(client, pm_headers, members=['user-worker-001'])
    _policy(client, admin_headers, 'user-worker-001', {'project.delete': True})
    deleted = _delete(client, worker_headers, project)
    assert deleted.status_code == 200, deleted.text
    path = f"/api/project-recycle-bin/projects/{project['id']}"
    row = client.get(path, headers=worker_headers).json()
    assert row['can_restore'] and row['can_download_backup'] is False
    assert client.get(path + '/backup', params={'deletion_id': row['deletion_id']}, headers=worker_headers).status_code == 403
    restored = client.post(path + '/restore', headers=worker_headers,
                           json={'version': row['version'], 'deletion_id': row['deletion_id']})
    assert restored.status_code == 200, restored.text


def test_owner_default_export_permission_still_downloads_verified_project_backup(client, pm_headers):
    from io import BytesIO
    from zipfile import ZipFile
    import json
    project = _project(client, pm_headers)
    deleted = _delete(client, pm_headers, project)
    assert deleted.status_code == 200, deleted.text
    path = f"/api/project-recycle-bin/projects/{project['id']}"
    row = client.get(path, headers=pm_headers).json()
    assert row['can_restore'] and row['can_download_backup'] is True
    response = client.get(path + '/backup', params={'deletion_id': row['deletion_id']}, headers=pm_headers)
    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as bundle:
        assert bundle.testzip() is None
        assert json.loads(bundle.read('project-backup.json'))['project']['id'] == project['id']
