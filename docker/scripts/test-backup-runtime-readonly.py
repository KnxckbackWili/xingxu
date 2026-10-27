#!/usr/bin/env python3
"""Verify trusted backup code in an isolated, read-only container.

Requires a locally available Python 3.12 + cryptography image. No host mount,
application volume, published port, network access or real credential is used.
Example: python test-backup-runtime-readonly.py --base-image LOCAL_IMAGE
"""
import argparse
from pathlib import Path
import subprocess


PROBE = r'''
from pathlib import Path
import sqlite3, os, shutil, sys
sys.modules['app'] = None  # Retained old images need no new app modules.
root = Path('/data')
source = root / 'source'; source.mkdir(mode=0o700)
with sqlite3.connect(source / 'agvpm.db') as db:
    db.executescript("CREATE TABLE users(id,username,password_hash,role,is_active); CREATE TABLE projects(id,name); CREATE TABLE tasks(id,project_id,module_id,name); INSERT INTO users VALUES('admin','admin','retained-hash','admin',1); INSERT INTO projects VALUES('project','retained');")
(source / 'secret.key').write_text('persisted-application-key')
(source / 'uploads').mkdir(mode=0o700)
(source / 'uploads/attachment').write_bytes(os.urandom(8 * 1024 * 1024))
(source / 'migration-exports').mkdir(mode=0o700)
(source / 'migration-exports/evidence.agvr').write_bytes(b'owner-encrypted-evidence')
password = 'test-only-backup-password-2026'
n['set_passphrase'](source, password)
archive = root / 'backup.agvenc'
n['create_archive'](source, archive, 'sqlite', password)
assert not archive.read_bytes().startswith(b'\x1f\x8b')
assert n['validate_archive'](archive, password)['database'] == 'sqlite'
try:
    with n['decrypted_file'](archive, 'wrong-test-only-password'):
        raise AssertionError('Unauthenticated plaintext escaped')
except n['BackupError']:
    pass
destination = root / 'destination'; destination.mkdir(mode=0o700)
n['set_passphrase'](destination, password)
with n['decrypted_file'](archive, password) as plain:
    shutil.copyfile(plain, destination / 'restore-pending.tar.gz')
    (destination / 'restore-pending.tar.gz').chmod(0o600)
assert n['apply_pending_restore'](destination)
for name in ('uploads/attachment', 'migration-exports/evidence.agvr', 'secret.key'):
    assert (destination / name).read_bytes() == (source / name).read_bytes()
assert n['get_passphrase'](destination) == password
assert not (destination / 'restore-pending.tar.gz').exists()
assert not list(root.rglob('.backup-decrypt-*'))
assert all(p.stat().st_mode & 0o777 == 0o600 for p in destination.rglob('*') if p.is_file())
print('readonly rootfs + network none: 8MiB encrypted snapshot/authentication/trusted SQLite apply + migration exports passed')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-image', required=True)
    args = parser.parse_args()
    image = subprocess.run(['docker', 'image', 'inspect', '--format', '{{.Id}}', args.base_image],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert image.startswith('sha256:'), 'Use a locally resolved immutable image'
    runtime = Path(__file__).with_name('backup_runtime.py').read_text()
    program = "n={'__name__':'trusted_backup_probe'}\nexec(" + repr(runtime) + ',n)\n' + PROBE
    result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--read-only',
                             '--tmpfs', '/data:rw,size=128m,mode=0700', '--tmpfs', '/tmp:rw,size=16m,mode=1777',
                             '--entrypoint', 'python3', image, '-'], input=program, text=True, timeout=90)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
