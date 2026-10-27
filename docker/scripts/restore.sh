#!/usr/bin/env bash
# Restore a full-system backup archive (SQLite or PostgreSQL).
# PostgreSQL 目标：先停 web/scheduler/healthwatch，dropdb+createdb+pg_restore，再拉起。
# SQLite 目标：可信 helper 发布并应用内部 pending，再启动应用。
#
# Authenticate/decode first; encrypted full pre-restore snapshots gate PG writes.
# Preserve checksum, stopped-service proofs and failure maintenance semantics.
set -euo pipefail
umask 077

ARCHIVE="${1:?用法: restore.sh <backup.tar.gz.agvenc>}"
CONTAINER="${AGV_CONTAINER:-agv-pm-8002}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"

# 轮转与 sha256 共享函数（sha256_of / rotate_pre_restore）。
. "$SCRIPT_DIR/backup-rotation.sh"
. "$SCRIPT_DIR/update-common.sh"

[ -f "$ARCHIVE" ] || { echo "备份文件不存在: $ARCHIVE" >&2; exit 1; }

# 改造 2：恢复前 SHA-256 校验（先于任何 docker 改动）。
verify_checksum() {
  local archive="$1"
  local sha_file="$archive.sha256"
  if [ -f "$sha_file" ]; then
    local expected actual
    expected="$(awk 'NR==1 {print $1}' "$sha_file")"
    actual="$(sha256_of "$archive")"
    if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
      echo "ERROR: SHA-256 校验失败: $archive" >&2
      echo "  expected: ${expected:-<空>}" >&2
      echo "  actual:   $actual" >&2
      echo "  备份包可能已损坏或被篡改，拒绝恢复。" >&2
      return 1
    fi
    echo "==> SHA-256 校验通过 ($actual)"
    VERIFIED_ARCHIVE_SHA="$actual"
  elif [ "${SKIP_SHA_CHECK:-0}" = "1" ]; then
    echo "!!! 警告: 备份缺少校验文件 ${sha_file}，已通过 SKIP_SHA_CHECK=1 显式跳过校验。" >&2
    echo "!!! 风险: 无法确认备份包完整性，仅应在确知来源可靠时使用。" >&2
    VERIFIED_ARCHIVE_SHA="$(sha256_of "$archive")"
  else
    echo "ERROR: 未找到校验文件 $sha_file" >&2
    echo "  该备份可能由旧版本工具生成，或校验文件丢失。" >&2
    echo "  如确知备份来源可靠，可设置 SKIP_SHA_CHECK=1 显式跳过校验后继续。" >&2
    return 1
  fi
}
verify_checksum "$ARCHIVE"

docker inspect "$CONTAINER" >/dev/null 2>&1 || {
  echo "Container '$CONTAINER' does not exist or Docker is unavailable." >&2
  exit 1
}

# Work lives on the private data volume, not the bounded /tmp tmpfs. Never
# expose decrypted contents until the complete GCM tag and archive are checked.
NONCE="$(python3 -c 'from uuid import uuid4; print(uuid4().hex)')"
REMOTE_ARCHIVE="/app/data/.restore-input-$NONCE"
REMOTE_PLAIN="/app/data/.restore-plain-$NONCE.tar.gz"
RESTORE_WORK="/app/data/.restore-work-$NONCE"
PASSWORD_FILE="/tmp/.restore-passphrase-$NONCE"
password_args=(--data-dir /app/data)
RESTORE_MUTATION_STARTED=0
RESTORE_STOPPED=0
RESTORE_START_ATTEMPTED=0
ORIGINAL_RUNNING_SERVICES=""
PRE_RESTORE_SNAPSHOT=""
restore_cleanup() {
  local exit_status=$?
  docker exec "$CONTAINER" python -c 'import shutil,sys;from pathlib import Path
for name in sys.argv[1:]:
 p=Path(name)
 if p.is_dir() and not p.is_symlink(): shutil.rmtree(p)
 else: p.unlink(missing_ok=True)' "$REMOTE_ARCHIVE" "$REMOTE_PLAIN" "$RESTORE_WORK" "$PASSWORD_FILE" >/dev/null 2>&1 || true
  if [ "$exit_status" != 0 ] && [ "$RESTORE_START_ATTEMPTED" = 1 ]; then
    # A nonzero start may have started only part of the writer set. Establish
    # real maintenance again rather than merely claiming the services stopped.
    docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf stop web scheduler healthwatch >/dev/null 2>&1 || true
    stopped_status="$(read_service_status)" || stopped_status=""
    if [ -z "$stopped_status" ] || ! printf '%s\n' "$stopped_status" | awk '$2 != "STOPPED" { invalid=1 } END { exit invalid ? 1 : 0 }'; then
      echo "ERROR: 恢复失败后无法确认停写，正在停止整个容器。" >&2
      docker stop "$CONTAINER" >/dev/null || echo "ERROR: 容器也无法停止；请立即人工隔离写入。" >&2
    fi
  fi
  if [ "$exit_status" != 0 ] && [ "$RESTORE_MUTATION_STARTED" = 1 ]; then
    echo "ERROR: 恢复未完成，web/scheduler/healthwatch 服务保持停止（维护停写）。" >&2
    echo "  数据库或文件可能只恢复了一部分；不要直接重启容器或应用服务。" >&2
    echo "  恢复前加密快照: $PRE_RESTORE_SNAPSHOT" >&2
    echo "  保留原完整备份和失败日志，排除故障后用已校验完整备份重新执行恢复。" >&2
  elif [ "$exit_status" != 0 ] && [ "$RESTORE_STOPPED" = 1 ]; then
    if [ -n "$ORIGINAL_RUNNING_SERVICES" ]; then
      docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf start $ORIGINAL_RUNNING_SERVICES || true
    else
      echo "==> 原处维护停写或原状态未知，服务保持停止。" >&2
    fi
  fi
  return "$exit_status"
}
trap restore_cleanup EXIT
if [ -n "${BACKUP_PASSPHRASE_FILE:-}" ]; then
  update_backup_passphrase_file "$PASSWORD_FILE"
  password_args+=(--passphrase-file "$PASSWORD_FILE")
fi
update_stream_archive "$ARCHIVE" "$REMOTE_ARCHIVE" "$VERIFIED_ARCHIVE_SHA"
MANIFEST="$(update_backup_runtime decrypt --input "$REMOTE_ARCHIVE" --output "$REMOTE_PLAIN" "${password_args[@]}")"
DB_KIND="$(printf '%s' "$MANIFEST" | python3 -c 'import json,sys; print(json.load(sys.stdin)["database"])')"
# On a fresh recovery installation the operator's private file also configures
# future/pre-restore encryption, after the imported archive has authenticated.
TARGET_STATUS="$(update_backup_runtime status)"
TARGET_DATABASE="$(printf '%s' "$TARGET_STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["database"])')"
if [ "$DB_KIND" != "$TARGET_DATABASE" ]; then
  echo "ERROR: 备份与目标数据库类型不一致；数据和服务未改动。" >&2
  exit 1
fi
supported="$(printf '%s' "$TARGET_STATUS" | python3 -c 'import json,sys; print(int(json.load(sys.stdin)["host_restore_supported"]))')"
if [ "$supported" != 1 ]; then
  echo "ERROR: 此入口仅恢复 SQLite 或 USE_POSTGRES=1 容器内 PostgreSQL；外部数据库须由数据库管理员隔离恢复。" >&2
  exit 1
fi
configured="$(printf '%s' "$TARGET_STATUS" | python3 -c 'import json,sys; print(int(json.load(sys.stdin)["configured"]))')"
if [ "$configured" != 1 ]; then
  update_backup_runtime configure "${password_args[@]}" >/dev/null
fi
update_backup_runtime extract --input "$REMOTE_PLAIN" --output "$RESTORE_WORK" >/dev/null
echo "==> 口令及完整性验证通过；备份数据库类型: $DB_KIND"

snapshot_pg_before_restore() {
  local dir="$1" stamp
  stamp="$(date +%Y%m%d-%H%M%S)-$NONCE"
  PRE_RESTORE_SNAPSHOT="$dir/agvpm-pre-restore-$stamp.tar.gz.agvenc"
  echo "==> 恢复前加密快照: $PRE_RESTORE_SNAPSHOT"
  if ! BACKUP_DIR="$dir" AGV_BACKUP_PREFIX=agvpm-pre-restore AGV_BACKUP_STAMP="$stamp" bash "$SCRIPT_DIR/backup.sh"; then
    echo "ERROR: 恢复前快照失败，中止恢复（当前数据库未被改动）" >&2
    return 1
  fi
}

read_service_status() {
  local service_status status_code
  # Stderr warnings belong in the restore log, not the strict status parser.
  if service_status="$(docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf status web scheduler healthwatch)"; then
    status_code=0
  else
    status_code=$?
  fi
  # STOPPED/EXITED 等状态返回 3；连接错误、缺项和重复行均不能作为状态证明。
  if { [ "$status_code" != "0" ] && [ "$status_code" != "3" ]; } || ! printf '%s\n' "$service_status" | awk '
    BEGIN { required["web"]=1; required["scheduler"]=1; required["healthwatch"]=1 }
    { if (!($1 in required) || $2 !~ /^[A-Z]+$/ || seen[$1]++) invalid=1; else count++ }
    END { exit (count == 3 && !invalid) ? 0 : 1 }
  '; then
    return 1
  fi
  printf '%s\n' "$service_status"
}

stop_restore_services() {
  local original_status stopped_status
  ORIGINAL_RUNNING_SERVICES=""
  if original_status="$(read_service_status)"; then
    # Canonical service names only. Never resume a pre-existing maintenance stop.
    ORIGINAL_RUNNING_SERVICES="$(printf '%s\n' "$original_status" | awk '$2 == "RUNNING" { print $1 }' | tr '\n' ' ')"
  else
    echo "==> 原服务状态无法确认；前置失败时不会自动启动服务。" >&2
  fi
  # stop 对已停止服务也可返回非零，以随后查询的确切状态为准。
  if ! docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf stop web scheduler healthwatch; then
    echo "==> 停止命令未全部成功，正在核实服务停止状态..." >&2
  fi
  # EXITED/BACKOFF 等状态仍可能被 supervisord 自动拉起，只接受 STOPPED。
  if ! stopped_status="$(read_service_status)" || ! printf '%s\n' "$stopped_status" | awk '$2 != "STOPPED" { invalid=1 } END { exit invalid ? 1 : 0 }'; then
    echo "ERROR: 无法确认 web/scheduler/healthwatch 服务停止状态，中止恢复（数据和文件未改动）。" >&2
    echo "  请排查 supervisord 连接与进程状态；本次不会自动启动任何服务。" >&2
    return 1
  fi
}

if [ "$DB_KIND" = "postgres" ]; then
  echo "==> 恢复 PostgreSQL（先停 web/scheduler/healthwatch 避免活动连接与自愈干扰）"
  stop_restore_services
  RESTORE_STOPPED=1
  snapshot_pg_before_restore "$BACKUP_DIR"

  # 还原 secret.key、uploads 与项目回收站的独立备份
  # 从第一处文件替换起就可能不再是原始完整状态，后续失败不得恢复写服务。
  RESTORE_MUTATION_STARTED=1
  docker exec "$CONTAINER" sh -c '
    set -e
    work="$1"
    if [ -f "$work/secret.key" ]; then
      [ ! -L /app/data/secret.key ]
      cp "$work/secret.key" /app/data/secret.key
      chmod 600 /app/data/secret.key
    fi
    if [ -e "$work/system-update-config.json" ] || [ -L "$work/system-update-config.json" ]; then
      [ -f "$work/system-update-config.json" ] && [ ! -L "$work/system-update-config.json" ]
      [ ! -L /app/data/system-update-config.json ]
      config_tmp="$(mktemp /app/data/.update-config-restore.XXXXXX)"
      cp "$work/system-update-config.json" "$config_tmp"
      chmod 600 "$config_tmp"
      mv "$config_tmp" /app/data/system-update-config.json
    else
      # Legacy snapshots carry no updater configuration; do not keep a token
      # encrypted with a different restored secret.key.
      [ ! -d /app/data/system-update-config.json ]
      rm -f /app/data/system-update-config.json
    fi
    # Ordinary restore invalidates requests queued against pre-restore data.
    # Automatic rollback keeps its managed job so the host can report recovery.
    if [ ! -e /app/data/update-maintenance.json ] && [ ! -L /app/data/update-maintenance.json ]; then
      [ ! -L /app/data/system-updates ]
      rm -f /app/data/system-updates/state.json
    fi
    rm -rf /app/data/uploads
    if [ -d "$work/uploads" ]; then
      cp -r "$work/uploads" /app/data/uploads
    else
      mkdir -p /app/data/uploads
    fi
    rm -rf /app/data/project-deletion-backups
    if [ -d "$work/project-deletion-backups" ]; then
      cp -r "$work/project-deletion-backups" /app/data/project-deletion-backups
    else
      mkdir -p /app/data/project-deletion-backups
    fi
    chmod 700 /app/data/project-deletion-backups
    find /app/data/project-deletion-backups -type f -exec chmod 600 {} \;
    [ ! -L /app/data/migration-exports ]
    rm -rf /app/data/migration-exports
    if [ -d "$work/migration-exports" ]; then
      cp -r "$work/migration-exports" /app/data/migration-exports
    else
      mkdir -m 700 /app/data/migration-exports
    fi
    chmod 700 /app/data/migration-exports
    find /app/data/migration-exports -type f -exec chmod 600 {} \;
  ' sh "$RESTORE_WORK"

  docker exec "$CONTAINER" sh -c '
    set -e
    work="$1"
    # dropdb/createdb 用 postgres 超级用户（trust auth，无密码）；pg_restore 用应用角色 agv。
    dropdb -h 127.0.0.1 -U postgres agvpm --if-exists
    createdb -h 127.0.0.1 -U postgres -O agv agvpm
    PGPASSWORD=agv pg_restore -h 127.0.0.1 -U agv -d agvpm --no-owner --role=agv "$work/agvpm.dump"
    echo "pg_restore 完成"
  ' sh "$RESTORE_WORK"
  RESTORE_START_ATTEMPTED=1
  docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf start web scheduler healthwatch
else
  echo "==> 恢复 SQLite（可信 helper 验证并应用，再启动应用）"
  # 与 PG 分支一致：一并停止 healthwatch，避免看门狗在 web 停止窗口内误判
  # restart/shutdown 干扰 staged restore（HYPE-52 一审阻塞项 2）。
  stop_restore_services
  RESTORE_STOPPED=1
  # The trusted helper stages an authenticated/validated private archive for
  # both the new bootstrap and retained rollback images.
  RESTORE_MUTATION_STARTED=1
  if update_backup_runtime stage --input "$REMOTE_PLAIN" --output /app/data/restore-pending.tar.gz >/dev/null; then
    :
  else
    stage_status=$?
    echo "ERROR: 恢复请求提交失败，服务保持停止；请排除拷贝错误后重试。" >&2
    exit "$stage_status"
  fi
  # Apply using the installed trusted code before any retained old image starts.
  # Its bootstrap need not understand the new migration-exports archive root.
  update_backup_runtime apply >/dev/null
  RESTORE_START_ATTEMPTED=1
  docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf start web scheduler healthwatch
fi

if [ "$DB_KIND" = "postgres" ]; then
  echo "==> 恢复完成：$ARCHIVE"
else
  echo "==> 恢复完成：${ARCHIVE}（SQLite）；请检查 /health、项目和附件。"
fi
