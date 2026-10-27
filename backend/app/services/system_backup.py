"""Encrypted full-system backups and compatibility helpers."""
from datetime import datetime
from pathlib import Path
import subprocess
from uuid import uuid4

from app.config import DATA_DIR, DATABASE_URL, APP_VERSION
from app.services import backup_crypto as codec

BACKUP_DIR = DATA_DIR / "backups"
PENDING_RESTORE = DATA_DIR / "restore-pending.tar.gz"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
_is_pg = DATABASE_URL.startswith("postgresql")


def _pg_dump(target: Path) -> None:
    codec._module._pg_dump(target, DATABASE_URL)


def validate_archive(path: Path, passphrase: str | None = None) -> dict:
    if codec.is_encrypted(path) and passphrase is None:
        passphrase = codec.get_passphrase(DATA_DIR)
    return codec.validate_archive(path, passphrase, allow_legacy=True, directory=DATA_DIR)


def create_backup(label: str = "manual") -> Path:
    passphrase = codec.get_passphrase(DATA_DIR)
    filename = f"agvpm-{label}-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex}.tar.gz.agvenc"
    return codec.create_archive(DATA_DIR, BACKUP_DIR / filename, DATABASE_URL, passphrase,
                                label=label, app_version=APP_VERSION)
