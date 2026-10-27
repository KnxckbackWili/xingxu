"""Shared strict archive validation; implementation also runs in old rollback images."""
from app.services.backup_crypto import (
    ALLOWED_ROOTS, MAX_ARCHIVE_MEMBERS, MAX_MANIFEST_BYTES, MAX_EXPANDED_BYTES,
    safe_members, validate_sqlite_member, copy_project_deletion_backups,
)
