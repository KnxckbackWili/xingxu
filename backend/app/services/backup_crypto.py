"""Load the one trusted backup implementation used by the app and host tools."""
import importlib.util
from pathlib import Path
import sys

_name = "xingxu_backup_runtime"
if _name not in sys.modules:
    _runtime = Path("/app/backup_runtime.py")
    if not _runtime.is_file():
        _runtime = Path(__file__).resolve().parents[3] / "docker/scripts/backup_runtime.py"
    _spec = importlib.util.spec_from_file_location(_name, _runtime)
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_name] = _module
    _spec.loader.exec_module(_module)
else:
    _module = sys.modules[_name]

BackupError = _module.BackupError
encrypted_writer = _module.encrypted_writer
encrypt_file = _module.encrypt_file
decrypted_file = _module.decrypted_file
plain_archive = _module.plain_archive
is_encrypted = _module.is_encrypted
get_passphrase = _module.get_passphrase
set_passphrase = _module.set_passphrase
passphrase_update = _module.passphrase_update
passphrase_status = _module.passphrase_status
validate_passphrase = _module.validate_passphrase
create_archive = _module.create_archive
validate_archive = _module.validate_archive
safe_members = _module.safe_members
validate_sqlite_member = _module.validate_sqlite_member
copy_project_deletion_backups = _module.copy_project_deletion_backups
ALLOWED_ROOTS = _module.ALLOWED_ROOTS
MAX_ARCHIVE_MEMBERS = _module.MAX_ARCHIVE_MEMBERS
MAX_MANIFEST_BYTES = _module.MAX_MANIFEST_BYTES
MAX_EXPANDED_BYTES = _module.MAX_EXPANDED_BYTES
