"""Delete/restore authority never silently includes project backup export."""
from tests.test_project_recycle_bin import _project, _policy, _delete


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
    # 下载的是加密备份（不发布明文）；用系统备份口令解密后核对内容。
    from app import config
    from app.services import backup_crypto as codec
    encrypted = config.DATA_DIR / 'downloaded-project-backup.zip.agvenc'
    encrypted.write_bytes(response.content)
    try:
        assert codec.is_encrypted(encrypted)
        with codec.decrypted_file(encrypted, codec.get_passphrase(config.DATA_DIR)) as plain:
            with ZipFile(plain) as bundle:
                assert bundle.testzip() is None
                assert json.loads(bundle.read('project-backup.json'))['project']['id'] == project['id']
    finally:
        encrypted.unlink()
