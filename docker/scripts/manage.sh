#!/usr/bin/env bash
# Safe lifecycle commands for a single-container NAS deployment.
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
. "$SCRIPT_DIR/update-common.sh"
. "$SCRIPT_DIR/backup-rotation.sh"
COMPOSE_FILE="${AGV_INSTALLED_COMPOSE_FILE:-$PROJECT_DIR/docker/docker-compose.yml}"
ENV_FILE="${AGV_ENV_FILE:-$PROJECT_DIR/.env}"
CONTAINER="${AGV_CONTAINER:-agv-pm}"
BACKUP_DIR="${BACKUP_DIR:-}"
STATE_FILE=""
DATA_DIR=""
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"

die() { echo "ERROR: $*" >&2; exit 1; }

require_env() {
  [ -f "$ENV_FILE" ] || die "Missing $ENV_FILE. Copy .env.example to .env first."
}

env_value() {
  local key="$1"
  sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1
}

load_config() {
  local configured data_path
  require_env
  if [ -z "$BACKUP_DIR" ]; then
    configured="$(env_value BACKUP_DIR)"; configured="${configured:-backups}"
    case "$configured" in
      /*) BACKUP_DIR="$configured" ;;
      *) BACKUP_DIR="$PROJECT_DIR/$configured" ;;
    esac
  fi
  STATE_FILE="$BACKUP_DIR/last-update.env"
  data_path="$(env_value DATA_PATH)"; data_path="${data_path:-../data}"
  case "$data_path" in
    /*) DATA_DIR="$data_path" ;;
    *) DATA_DIR="$PROJECT_DIR/docker/$data_path" ;;
  esac
}

compose() {
  update_compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" -- "$@"
}

set_env_value() {
  local key="$1" value="$2" temp
  temp="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    index($0, key "=") == 1 { print key "=" value; found = 1; next }
    { print }
    END { if (!found) print key "=" value }
  ' "$ENV_FILE" > "$temp"
  mv "$temp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

sync_build_version() {
  local mode version
  mode="$(env_value DEPLOY_MODE)"; mode="${mode:-build}"
  if [ -n "${AGV_BUILD_CONTEXT:-}" ]; then
    version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$AGV_BUILD_CONTEXT/frontend/package.json")"
    export APP_VERSION="${APP_VERSION:-$version}" AGV_IMAGE="${AGV_IMAGE:-agv-pm:$version}"
    return 0
  fi
  [ "$mode" = "build" ] || return 0
  version="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$PROJECT_DIR/frontend/package.json" | head -n 1)"
  [ -n "$version" ] || die "Cannot read the source version from frontend/package.json."
  set_env_value APP_VERSION "$version"
  set_env_value AGV_IMAGE "agv-pm:$version"
}

wait_healthy() {
  local elapsed=0 status
  while [ "$elapsed" -lt "$HEALTH_TIMEOUT" ]; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || true)"
    if [ "$status" = "healthy" ]; then
      return 0
    fi
    if [ "$status" = "exited" ] || [ "$status" = "dead" ]; then
      return 1
    fi
    sleep 3
    elapsed=$((elapsed + 3))
  done
  return 1
}

print_health() {
  local port bind
  port="$(env_value APP_PORT)"; port="${port:-8000}"
  bind="$(env_value BIND_ADDRESS)"; bind="${bind:-127.0.0.1}"
  [ "$bind" = "0.0.0.0" ] && bind="127.0.0.1"
  curl --fail --silent --show-error "http://$bind:$port/health"
  echo
}

deploy_current() {
  local mode image
  mode="$(env_value DEPLOY_MODE)"; mode="${mode:-build}"
  image="$(env_value AGV_IMAGE)"; image="${image:-agv-pm:2.1.2}"
  case "$mode" in
    build)
      compose up -d --build --remove-orphans
      ;;
    registry)
      case "$image" in
        *:latest|*:edge|*:main) die "Refusing floating image tag '$image'; use a released version." ;;
      esac
      compose pull
      compose up -d --no-build --remove-orphans
      ;;
    *) die "DEPLOY_MODE must be 'build' or 'registry'." ;;
  esac
}

prepare_current() {
  local mode image
  if [ -n "${AGV_BUILD_CONTEXT:-}" ]; then compose build; return; fi
  mode="$(env_value DEPLOY_MODE)"; mode="${mode:-build}"
  image="$(env_value AGV_IMAGE)"; image="${image:-agv-pm:2.1.2}"
  case "$mode" in
    build)
      compose build
      ;;
    registry)
      case "$image" in
        *:latest|*:edge|*:main) die "Refusing floating image tag '$image'; use a released version." ;;
      esac
      compose pull
      ;;
    *) die "DEPLOY_MODE must be 'build' or 'registry'." ;;
  esac
}

activate_current() {
  compose up -d --no-build --remove-orphans
}

install_app() {
  load_config
  if docker inspect "$CONTAINER" >/dev/null 2>&1; then
    die "Container '$CONTAINER' already exists; use update instead."
  fi
  sync_build_version
  deploy_current
  if ! wait_healthy; then
    docker logs --tail 120 "$CONTAINER" >&2 || true
    die "Initial deployment did not become healthy."
  fi
  echo "Deployment healthy: $(print_health)"
}

backup_app() {
  BACKUP_DIR="$BACKUP_DIR" AGV_CONTAINER="$CONTAINER" "$SCRIPT_DIR/backup.sh"
}

write_state() {
  local rollback_image="$1" backup_file="$2" previous_ref="$3" target_ref="$4"
  mkdir -p "$BACKUP_DIR"
  {
    printf 'ROLLBACK_IMAGE=%s\n' "$rollback_image"
    printf 'BACKUP_FILE=%s\n' "$backup_file"
    printf 'PREVIOUS_REF=%s\n' "$previous_ref"
    printf 'TARGET_REF=%s\n' "$target_ref"
    printf 'CREATED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$STATE_FILE"
  chmod 600 "$STATE_FILE"
}

rollback_image() {
  local image="$1"
  # Use the preserved rollback reference directly. A previous Config.Image
  # may be a sha256 ID/digest and is not a valid docker tag destination.
  update_restore_git_sha "$image" || return 1
  AGV_IMAGE="$image" compose up -d --no-build --force-recreate
  wait_healthy
}

stage_restore() {
  local archive="$1" expected
  [ -f "$archive.sha256" ] || return 1
  expected="$(awk 'NR==1{print $1}' "$archive.sha256")"
  [ "$expected" = "$(sha256_of "$archive")" ] || return 1
  # Use the existing container's mounted volume; the host need not chown or
  # reach inside a Docker-managed volume. Writers were already stopped.
  local nonce remote result=0
  nonce="$(python3 -c 'from uuid import uuid4; print(uuid4().hex)')"
  remote="/app/data/.rollback-input-$nonce"
  update_stream_archive "$archive" "$remote" "$expected" || result=$?
  if [ "$result" = 0 ]; then
    update_backup_runtime stage --input "$remote" --output /app/data/restore-pending.tar.gz >/dev/null || result=$?
  fi
  if [ "$result" = 0 ]; then
    update_backup_runtime apply >/dev/null || result=$?
  fi
  docker exec "$CONTAINER" python -c 'import sys;from pathlib import Path;Path(sys.argv[1]).unlink(missing_ok=True)' "$remote" >/dev/null 2>&1 || true
  return "$result"
}

update_app() {
  local stamp old_id old_ref target_ref rollback_ref backup_file expected
  load_config
  docker inspect "$CONTAINER" >/dev/null 2>&1 || die "Container is not installed."
  update_begin
  sync_build_version
  stamp="$(date +%Y%m%d-%H%M%S)-$$"
  old_id="$(docker inspect --format '{{.Image}}' "$CONTAINER")"
  old_ref="$(docker inspect --format '{{.Config.Image}}' "$CONTAINER")"
  target_ref="${AGV_IMAGE:-$(env_value AGV_IMAGE)}"
  rollback_ref="agv-pm:rollback-$stamp"

  update_event building
  prepare_current
  update_verify_built_image
  docker image tag "$old_id" "$rollback_ref"
  update_event backing_up
  update_mark_maintenance
  update_stop_writes
  AGV_BACKUP_STAMP="$stamp" backup_app
  backup_file="$BACKUP_DIR/agv-pm-$stamp.tar.gz.agvenc"
  [ -n "$backup_file" ] && [ -f "$backup_file.sha256" ] || die "Backup was not created."
  expected="$(awk 'NR==1{print $1}' "$backup_file.sha256")"
  [ "$expected" = "$(sha256_of "$backup_file")" ] || die "Backup verification failed."
  write_state "$rollback_ref" "$backup_file" "$old_ref" "$target_ref"

  update_event installing
  UPDATE_SWITCHED=1
  if activate_current; then
    update_event verifying
    if wait_healthy; then
      update_finish succeeded
      echo "Update passed its health check."
      return 0
    fi
  fi
  # Even a failed compose call may already have started migrations.
  # Confirm all writers stopped before staging pre-update data for the old image.
  update_hold_writes || die "Cannot confirm maintenance; recovery needs an administrator."
  stage_restore "$backup_file" || die "Cannot apply verified recovery; services remain stopped."
  rollback_image "$rollback_ref" || die "Recovery did not pass health verification."
  # Bootstrap must have consumed the request; /health alone is insufficient.
  docker exec "$CONTAINER" test ! -e /app/data/restore-pending.tar.gz || die "Recovery request was not consumed."
  update_finish rolled_back
  die "Update failed; the original image and pre-update data were restored."
}

load_state() {
  [ -f "$STATE_FILE" ] || die "No update state found at $STATE_FILE."
  ROLLBACK_IMAGE="$(sed -n 's/^ROLLBACK_IMAGE=//p' "$STATE_FILE")"
  BACKUP_FILE="$(sed -n 's/^BACKUP_FILE=//p' "$STATE_FILE")"
  [ -n "$ROLLBACK_IMAGE" ] && [ -n "$BACKUP_FILE" ] || die "Update state is incomplete."
}

rollback_app() {
  load_config
  load_state
  docker image inspect "$ROLLBACK_IMAGE" >/dev/null 2>&1 || die "Rollback image '$ROLLBACK_IMAGE' is missing."
  rollback_image "$ROLLBACK_IMAGE" || die "Rollback image did not become healthy."
  update_persist_runtime || die "Cannot persist the recovered installation version."
  echo "Previous image restored: $(print_health)"
  echo "Data was not overwritten. To restore pre-update data too, run:"
  echo "  $0 restore '$BACKUP_FILE'"
}

restore_data() {
  local archive="${1:-}"
  [ -n "$archive" ] || die "Usage: $0 restore /path/to/agv-pm-backup.tar.gz"
  [ -f "$archive" ] || die "Backup not found: $archive"
  AGV_CONTAINER="$CONTAINER" BACKUP_DIR="$BACKUP_DIR" bash "$SCRIPT_DIR/restore.sh" "$archive" || die "Restore failed; inspect maintenance state before retrying."
  docker restart "$CONTAINER" >/dev/null
  wait_healthy || die "Container did not become healthy after data restore."
  echo "Data restored: $(print_health)"
}

status_app() {
  load_config
  docker ps --filter "name=^/${CONTAINER}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
  print_health
}

case "${1:-}" in
  install) install_app ;;
  update) update_app ;;
  backup) load_config; backup_app ;;
  status) status_app ;;
  rollback) rollback_app ;;
  restore) load_config; restore_data "${2:-}" ;;
  *)
    echo "Usage: $0 {install|update|backup|status|rollback|restore BACKUP_FILE}"
    exit 2
    ;;
esac
