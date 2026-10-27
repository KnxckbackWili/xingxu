"""T13 host attestation gates, legacy capability rejection and safe public state."""
import json
import uuid
import pytest

from app import config
from app.services import system_updates as updates
from app.services.system_update_bridge import dispatch


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, '_data_dir', lambda: tmp_path)
    monkeypatch.setattr(config, 'APP_VERSION', '2.3.8')
    monkeypatch.setenv('GIT_SHA', 'a' * 40)
    monkeypatch.setattr(updates.update_source, 'inspect_source', lambda *args: {'commit': 'b' * 40, 'version': '2.4.0'})


def checking():
    updates.save_source({'repository_url': 'https://git.example.com/team/workbench', 'ref': 'v2.4.0',
                         'allow_http': False, 'revision': 0, 'token': 'test-only-private-token'})
    check = updates.check_source(1)['check']
    runner = str(uuid.uuid4())
    updates.heartbeat(runner, 1, trust_protocol=1, trust_configured=True)
    return check, runner


def approved():
    check, runner = checking()
    updates.trust_result(runner, check['id'], 'trusted', method='signed_tag')
    return check, runner


def test_check_stays_pending_and_cannot_install_until_host_attests():
    check, runner = checking()
    assert check['trust']['status'] == 'pending'
    with pytest.raises(updates.UpdateError, match='宿主信任校验'):
        updates.request_install(check['id'], 'admin')
    candidate = dispatch({'action': 'trust-request', 'runner_id': runner})['candidate']
    assert candidate['repository_url'] == 'https://git.example.com/team/workbench'
    assert candidate['commit'] == 'b' * 40 and candidate['check_id'] == check['id']
    assert 'token' not in json.dumps(candidate)
    dispatch({'action': 'trust-result', 'runner_id': runner, 'check_id': check['id'], 'status': 'trusted', 'method': 'signed_tag'})
    job = updates.request_install(check['id'], 'admin')['job']
    assert job['target_commit'] == 'b' * 40


def test_legacy_check_without_trust_is_rejected():
    check, _ = approved()
    state = updates._state(); state['check'].pop('trust'); updates._save(state)
    with pytest.raises(updates.UpdateError, match='宿主信任校验'):
        updates.request_install(check['id'], 'admin')
    assert updates._state().get('job') is None


def test_legacy_runner_downgrade_cannot_claim_prepare_or_advance_old_queued_job():
    check, runner = approved()
    job = updates.request_install(check['id'], 'admin')['job']
    updates.claim(runner)
    updates.heartbeat(runner, 1)  # An old runner cannot advertise trust support.
    assert updates.get_status()['runner']['trust'] == {'configured': False, 'protocol': 0}
    for action in [lambda: updates.claim(runner), lambda: updates.report(runner, job['id'], 'building')]:
        with pytest.raises(updates.UpdateError, match='信任'):
            action()
    updates.report(runner, job['id'], 'failed')  # Failure recovery remains available.


def test_host_rejection_explains_why_and_never_echoes_untrusted_reason():
    check, runner = checking()
    updates.trust_result(runner, check['id'], 'rejected', reason='signature_invalid')
    payload = updates.get_status()
    assert payload['check']['trust']['status'] == 'rejected'
    assert '签名' in payload['check']['trust']['message']
    with pytest.raises(updates.UpdateError):
        updates.request_install(check['id'], 'admin')
    updates.trust_result(runner, check['id'], 'rejected', reason='PRIVATE_DO_NOT_ECHO')
    assert 'PRIVATE_DO_NOT_ECHO' not in json.dumps(updates.get_status())


def test_changed_source_invalidates_inflight_host_attestation_and_credentials():
    check, runner = checking()
    source = updates.get_status()['source']
    updates.save_source({**source, 'ref': 'other', 'clear_token': False})
    with pytest.raises(updates.UpdateError, match='变化'):
        updates.trust_result(runner, check['id'], 'trusted', method='commit')
    with pytest.raises(updates.UpdateError, match='变化'):
        updates.trust_credentials(runner, check_id=check['id'])


def test_wrong_host_cannot_attest_or_read_credentials():
    check, _ = checking()
    other = str(uuid.uuid4())
    with pytest.raises(updates.UpdateError):
        updates.trust_result(other, check['id'], 'trusted', method='commit')
    with pytest.raises(updates.UpdateError):
        updates.trust_credentials(other, check_id=check['id'])


def test_host_only_credentials_never_enter_status_check_or_job():
    check, runner = approved()
    assert updates.trust_credentials(runner, check_id=check['id']) == {'token': 'test-only-private-token'}
    queued = updates.request_install(check['id'], 'admin')
    assert 'test-only-private-token' not in json.dumps(queued)
    claimed = updates.claim(runner)['job']
    assert claimed['check_id'] == check['id'] and claimed['source_revision'] == 1
    assert claimed['repository_url'] == 'https://git.example.com/team/workbench'
    assert 'token' not in json.dumps(claimed)
    assert updates.trust_credentials(runner, job_id=claimed['id'])['token'] == 'test-only-private-token'


def test_expired_check_cannot_receive_a_late_trusted_result():
    check, runner = checking()
    state = updates._state(); state['check']['checked_at'] = '2000-01-01T00:00:00+00:00'; updates._save(state)
    assert updates.trust_request(runner)['candidate'] is None
    with pytest.raises(updates.UpdateError):
        updates.trust_result(runner, check['id'], 'trusted', method='commit')


def test_http_source_cannot_change_host_roots(client, admin_headers):
    source = {'repository_url': 'https://git.example.com/team/workbench', 'ref': 'main', 'allow_http': False, 'revision': 0}
    for field, value in [('allowed_commits', ['b' * 40]), ('ssh_allowed_signers', '/host/keys'), ('trust', {'status': 'trusted'})]:
        response = client.put('/api/system/updates/source', headers=admin_headers, json={**source, field: value})
        assert response.status_code == 422
    assert client.put('/api/system/updates/trust', headers=admin_headers, json={'allowed_commits': ['b' * 40]}).status_code in {404, 405}


def test_trust_failure_job_message_uses_only_known_public_reasons():
    check, runner = approved()
    job = updates.request_install(check['id'], 'admin')['job']; updates.claim(runner)
    result = updates.report(runner, job['id'], 'failed', reason='policy_changed')
    assert '宿主信任配置已变化' in result['job']['message']


def test_capable_host_can_reject_a_queued_job_after_policy_revocation():
    check, runner = approved()
    job = updates.request_install(check['id'], 'admin')['job']
    updates.heartbeat(runner, 1, trust_protocol=1, trust_configured=False)
    assert updates.claim(runner)['job']['id'] == job['id']
    with pytest.raises(updates.UpdateError):
        updates.report(runner, job['id'], 'building')
    result = updates.report(runner, job['id'], 'failed', reason='not_configured')
    assert result['job']['status'] == 'failed' and '宿主尚未配置' in result['job']['message']


def test_local_bridge_never_consumes_a_pending_restore_while_writers_may_be_running(tmp_path):
    import os
    import sqlite3
    import subprocess
    import sys
    from pathlib import Path
    from app.services import backup_crypto as codec
    data, source = tmp_path / 'running', tmp_path / 'snapshot'
    for directory, label in [(data, 'running data'), (source, 'restored data')]:
        directory.mkdir(mode=0o700)
        with sqlite3.connect(directory / 'agvpm.db') as database:
            database.executescript("CREATE TABLE users(id,username,password_hash,role,is_active); CREATE TABLE projects(id,name); CREATE TABLE tasks(id,project_id,module_id,name);")
            database.execute("INSERT INTO projects VALUES('project',?)", (label,))
        (directory / 'secret.key').write_text(label + '-key')
        (directory / 'uploads').mkdir(mode=0o700)
        (directory / 'uploads/file.txt').write_text(label + '-attachment')
    password = 'test-only-private-backup-password'
    codec.set_passphrase(data, password)
    sealed = tmp_path / 'backup.agvenc'
    codec.create_archive(source, sealed, 'sqlite', password)
    pending = data / 'restore-pending.tar.gz'
    with codec.decrypted_file(sealed, password) as plaintext:
        pending.write_bytes(plaintext.read_bytes()); pending.chmod(0o600)
    pending_bytes = pending.read_bytes()
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1]), 'DATA_DIR': str(data),
           'DATABASE_URL': 'sqlite:///' + str(data / 'agvpm.db'), 'SECRET_KEY': ''}
    result = subprocess.run([sys.executable, '-m', 'app.services.system_update_bridge'],
                            input=json.dumps({'action': 'heartbeat', 'runner_id': str(uuid.uuid4()), 'protocol': 1}),
                            env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0 and json.loads(result.stdout)['ok']
    imported = subprocess.run([sys.executable, '-c', 'import app.services.system_update_bridge'], env=env, capture_output=True, timeout=30)
    assert imported.returncode == 0
    assert pending.read_bytes() == pending_bytes
    assert (data / 'secret.key').read_text() == 'running data-key'
    with sqlite3.connect(data / 'agvpm.db') as database:
        assert database.execute('SELECT name FROM projects').fetchone()[0] == 'running data'
    # A normal new web process must still apply the valid staged snapshot.
    startup = subprocess.run([sys.executable, '-c', 'import app.config'], env=env, capture_output=True, timeout=30)
    assert startup.returncode == 0 and not pending.exists()
    assert (data / 'secret.key').read_text() == 'restored data-key'
    assert (data / 'uploads/file.txt').read_text() == 'restored data-attachment'
    with sqlite3.connect(data / 'agvpm.db') as database:
        assert database.execute('SELECT name FROM projects').fetchone()[0] == 'restored data'
    snapshots = list((data / 'backups').glob('*.agvenc'))
    assert len(snapshots) == 1 and codec.validate_archive(snapshots[0], password)['label'] == 'pre-restore'


def test_forged_capability_state_cannot_reenable_the_old_runner_package_protocol(monkeypatch):
    check, runner = approved()
    job = updates.request_install(check['id'], 'admin')['job']
    updates.heartbeat(runner, 1)  # Old runner, no host trust implementation.
    state = updates._state()
    state['runner'].update(trust_protocol=1, trust_configured=True)  # App data is not a trust root.
    updates._save(state)
    updates.claim(runner)
    calls = []
    monkeypatch.setattr(updates.update_source, 'download_source', lambda *args: calls.append(args))
    with pytest.raises(updates.UpdateError, match='旧版压缩包更新协议已停用'):
        dispatch({'action': 'prepare', 'runner_id': runner, 'job_id': job['id']})
    assert calls == [] and not (updates._directory() / 'packages').exists()
