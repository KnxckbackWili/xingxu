#!/usr/bin/env bash
# Create and verify an encrypted, consistent full-system backup.
set -euo pipefail
umask 077
CONTAINER="${AGV_CONTAINER:-agv-pm-8002}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
NONCE="$(python3 -c 'from uuid import uuid4; print(uuid4().hex)')"
STAMP="${AGV_BACKUP_STAMP:-$(date +%Y%m%d-%H%M%S)-$NONCE}"
PREFIX="${AGV_BACKUP_PREFIX:-agv-pm}"
[[ "$STAMP" =~ ^[0-9a-f-]+$ ]] || { echo "Invalid backup identifier." >&2; exit 1; }
[[ "$PREFIX" = agv-pm || "$PREFIX" = agvpm-pre-restore ]] || { echo "Invalid backup prefix." >&2; exit 1; }
ARCHIVE="$PREFIX-$STAMP.tar.gz.agvenc"
PARTIAL="$BACKUP_DIR/.$ARCHIVE.$NONCE.partial"
REMOTE="/app/data/backups/.host-transfer-$NONCE.agvenc"
PASSWORD_FILE="/tmp/.backup-passphrase-$NONCE"
. "$SCRIPT_DIR/backup-rotation.sh"
. "$SCRIPT_DIR/update-common.sh"
mkdir -p "$BACKUP_DIR"
[ ! -e "$BACKUP_DIR/$ARCHIVE" ] && [ ! -L "$BACKUP_DIR/$ARCHIVE" ] || { echo "Backup destination already exists; refusing to overwrite." >&2; exit 1; }
docker inspect "$CONTAINER" >/dev/null 2>&1 || { echo "Container '$CONTAINER' is unavailable." >&2; exit 1; }
cleanup_backup() {
  local code=$?
  rm -f "$PARTIAL"
  docker exec "$CONTAINER" python -c 'import sys;from pathlib import Path;[Path(name).unlink(missing_ok=True) for name in sys.argv[1:]]' "$REMOTE" "$PASSWORD_FILE" >/dev/null 2>&1 || true
  return "$code"
}
trap cleanup_backup EXIT
password_args=(--data-dir /app/data)
configured="$(update_backup_runtime status | python3 -c 'import json,sys; print(int(json.load(sys.stdin)["configured"]))')"
if [ "$configured" != 1 ] && [ -n "${BACKUP_PASSPHRASE_FILE:-}" ]; then
  update_backup_passphrase_file "$PASSWORD_FILE"
  password_args+=(--passphrase-file "$PASSWORD_FILE")
fi
update_backup_runtime create --output "$REMOTE" "${password_args[@]}"
update_backup_runtime inspect --input "$REMOTE" "${password_args[@]}" >/dev/null
if [ "$configured" != 1 ]; then
  update_backup_runtime configure "${password_args[@]}" >/dev/null
fi
remote_sha="$(docker exec "$CONTAINER" python -c 'import hashlib,sys;h=hashlib.sha256();f=open(sys.argv[1],"rb");[h.update(b) for b in iter(lambda:f.read(1048576),b"")];print(h.hexdigest())' "$REMOTE")"
docker exec "$CONTAINER" python -c 'import shutil,sys;from pathlib import Path;f=Path(sys.argv[1]).open("rb");shutil.copyfileobj(f,sys.stdout.buffer,1048576)' "$REMOTE" > "$PARTIAL"
[ "$(sha256_of "$PARTIAL")" = "$remote_sha" ] || { echo "Encrypted backup transfer checksum failed." >&2; exit 1; }
ln "$PARTIAL" "$BACKUP_DIR/$ARCHIVE"
rm "$PARTIAL"
printf '%s  %s\n' "$remote_sha" "$ARCHIVE" > "$BACKUP_DIR/$ARCHIVE.sha256"
echo "Backup created: $BACKUP_DIR/$ARCHIVE"
echo "Checksum: $BACKUP_DIR/$ARCHIVE.sha256"
rotate_backups "$BACKUP_DIR"
rotate_pre_restore "$BACKUP_DIR"
