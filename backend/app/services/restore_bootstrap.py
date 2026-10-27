"""Config-independent staged restore, shared with trusted host rollback tools."""
from app.services.backup_crypto import _module

apply_pending_restore = _module.apply_pending_restore
_install_snapshot = _module._install_snapshot
