from app.services import system_backup
from app.routers import system


def test_pg_dump_uses_supported_environment_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(system_backup, 'DATABASE_URL', 'postgresql://agv:test-only-password@localhost:5432/demo')
    monkeypatch.setenv('AGV_BACKUP_TEST', 'preserved')
    calls = []
    monkeypatch.setattr(system_backup.subprocess, 'run', lambda cmd, **kwargs: calls.append((cmd, kwargs)))
    system_backup._pg_dump(tmp_path / 'snapshot.dump')
    cmd, options = calls[0]
    assert cmd[0] == 'pg_dump'
    assert options['env']['AGV_BACKUP_TEST'] == 'preserved'
    assert options['env']['PGPASSWORD'] == 'test-only-password'
    assert 'test-only-password' not in ' '.join(cmd)
    assert options['check'] is True


def test_backup_capabilities_disclose_pg_restore_limit(client, admin_headers, monkeypatch):
    monkeypatch.setattr(system, 'DATABASE_URL', 'postgresql://localhost/demo')
    r = client.get('/api/system/backups', headers=admin_headers)
    assert r.status_code == 200
    assert r.json()['database'] == 'postgresql'
    assert r.json()['web_restore_supported'] is False
