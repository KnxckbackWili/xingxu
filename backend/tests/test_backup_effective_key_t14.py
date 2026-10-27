"""The encrypted snapshot must preserve the key the running app actually uses."""
import tarfile

import pytest

from app.services import backup_crypto as codec
from .test_backup_encryption import installation, PASSWORD


@pytest.mark.parametrize('state', ['stale', 'missing', 'symlink'])
def test_effective_environment_app_key_in_encrypted_snapshot_without_changing_live_file(tmp_path, monkeypatch, state):
    data = installation(tmp_path / 'source')
    key_file = data / 'secret.key'
    original = key_file.read_bytes()
    key_file.unlink()
    if state == 'stale': key_file.write_bytes(original)
    if state == 'symlink':
        other = tmp_path / 'other'; other.write_bytes(original)
        key_file.symlink_to(other)
    effective = 'isolated-env-app-key-for-backup-t14'
    monkeypatch.setenv('SECRET_KEY', effective)
    destination = tmp_path / 'backup.agvenc'
    if state == 'symlink':
        with pytest.raises(codec.BackupError, match='普通文件'):
            codec.create_archive(data, destination, 'sqlite', PASSWORD)
        assert not destination.exists() and key_file.is_symlink()
        return
    codec.create_archive(data, destination, 'sqlite', PASSWORD)
    assert effective.encode() not in destination.read_bytes()
    with codec.decrypted_file(destination, PASSWORD) as plain, tarfile.open(plain) as archive:
        assert archive.getnames().count('secret.key') == 1
        assert archive.extractfile('secret.key').read() == effective.encode()
        assert archive.getmember('secret.key').mode == 0o600
    if state == 'stale': assert key_file.read_bytes() == original
    else: assert not key_file.exists()
