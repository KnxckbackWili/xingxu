#!/usr/bin/env bash
# Installed, trusted helpers shared by both deployment entry points.
# Downloaded source supplies build input only; it never supplies this script.

update_backup_runtime() {
  # Execute the installed trusted codec, including inside an old rollback image
  # that predates the app-side adapter. No passphrase is placed on argv.
  [ -f "$SCRIPT_DIR/backup_runtime.py" ] || { echo "ERROR: Trusted backup codec is missing." >&2; return 1; }
  docker exec -i "$CONTAINER" python - "$@" < "$SCRIPT_DIR/backup_runtime.py"
}

update_backup_passphrase_file() {
  local destination="$1"
  [ -n "${BACKUP_PASSPHRASE_FILE:-}" ] || return 1
  python3 - "$BACKUP_PASSPHRASE_FILE" <<'PY'
import os, stat, sys
fd = os.open(sys.argv[1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
try:
    value = os.fstat(fd)
    if not stat.S_ISREG(value.st_mode) or stat.S_IMODE(value.st_mode) & 0o077:
        raise SystemExit("Backup passphrase file must be private (0600).")
    if value.st_size > 8192:
        raise SystemExit("Backup passphrase file is too large.")
finally:
    os.close(fd)
PY
  update_stream_archive "$BACKUP_PASSPHRASE_FILE" "$destination" "$(sha256_of "$BACKUP_PASSPHRASE_FILE")"
}

update_stream_archive() {
  local archive="$1" target="$2" expected="$3"
  # docker cp writes through the daemon and rejects read-only rootfs even when
  # the destination is tmpfs. An exec process can use the writable mount.
  docker exec -i "$CONTAINER" python -c '
# AGV_STREAM_ARCHIVE
import hashlib, os, re, stat, sys, uuid
target, expected = sys.argv[1:]
assert re.fullmatch(r"[a-f0-9]{64}", expected), "invalid archive checksum"
parent, filename = os.path.split(target)
assert filename and parent, "invalid archive destination"
directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = ".archive-" + uuid.uuid4().hex + ".tmp"
created = False
def regular_or_absent():
    try: info = os.stat(filename, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError: return
    assert stat.S_ISREG(info.st_mode), "archive destination must be a regular file"
try:
    regular_or_absent()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    created = True
    with os.fdopen(fd, "wb") as output:
        digest = hashlib.sha256()
        while chunk := sys.stdin.buffer.read(1024 * 1024):
            digest.update(chunk); output.write(chunk)
        output.flush(); os.fsync(output.fileno())
    assert digest.hexdigest() == expected, "transferred archive checksum mismatch"
    regular_or_absent()
    os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)
finally:
    if created:
        try: os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError: pass
    os.close(directory)
' "$target" "$expected" < "$archive"
}

update_event() {
  local phase="$1" ack
  if [ "${AGV_UPDATE_MANAGED:-0}" = 1 ]; then
    printf 'AGV_UPDATE_PHASE=%s\n' "$phase" >&"${AGV_UPDATE_EVENT_FD:?missing host control pipe}"
  else
    printf 'AGV_UPDATE_PHASE=%s\n' "$phase"
  fi
  if [ "${AGV_UPDATE_MANAGED:-0}" = 1 ]; then
    # The host must persist maintenance before stop/recreate. EOF also prevents
    # a detached child from continuing after its runner has disappeared.
    IFS= read -r ack && [ "$ack" = continue ] || return 1
  fi
}

update_compose() {
  local args=() override="" result=0
  while [ "$#" -gt 0 ] && [ "$1" != -- ]; do args+=("$1"); shift; done
  shift
  if [ -n "${AGV_BUILD_CONTEXT:-}" ]; then
    [ -d "$AGV_BUILD_CONTEXT" ] && [ -f "$AGV_BUILD_CONTEXT/docker/Dockerfile" ] || return 1
    override="$(mktemp "${TMPDIR:-/tmp}/agv-build-context.XXXXXX")" || return 1
    chmod 600 "$override"
    if ! python3 - "$AGV_BUILD_CONTEXT" "${GIT_SHA:-unknown}" "${APP_VERSION:?missing target version}" > "$override" <<'PY'
import json, sys
from pathlib import Path
print(json.dumps({"services": {"agv-pm": {"build": {
    "context": str(Path(sys.argv[1]).resolve()), "dockerfile": "docker/Dockerfile",
    "args": {"GIT_SHA": sys.argv[2], "APP_VERSION": sys.argv[3]}
}}}}))
PY
    then rm -f "$override"; return 1; fi
    args+=(-f "$override")
  fi
  docker compose "${args[@]}" "$@" || result=$?
  [ -z "$override" ] || rm -f "$override"
  return "$result"
}

update_service_status() {
  local output code
  # Parse stdout only. Supervisor/Python warnings on stderr remain in the
  # caller's private deployment log and are not service status records.
  if output="$(docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf status web scheduler healthwatch)"; then
    code=0
  else code=$?; fi
  if { [ "$code" != 0 ] && [ "$code" != 3 ]; } || ! printf '%s\n' "$output" | awk '
    BEGIN { required["web"]=1; required["scheduler"]=1; required["healthwatch"]=1 }
    { if (!($1 in required) || $2 !~ /^[A-Z]+$/ || seen[$1]++) bad=1; else count++ }
    END { exit (count == 3 && !bad) ? 0 : 1 }
  '; then return 1; fi
  printf '%s\n' "$output"
}

update_stop_writes() {
  local statuses
  UPDATE_STOP_ATTEMPTED=1
  statuses="$(update_service_status)" || return 1
  UPDATE_ORIGINAL_RUNNING="$(printf '%s\n' "$statuses" | awk '$2 == "RUNNING" {print $1}' | tr '\n' ' ')"
  docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf stop web scheduler healthwatch || true
  statuses="$(update_service_status)" || return 1
  printf '%s\n' "$statuses" | awk '$2 != "STOPPED" {bad=1} END {exit bad ? 1 : 0}' || return 1
  UPDATE_STOP_VERIFIED=1
}

update_mark_maintenance() {
  # Marker survives a container recreation and is deliberately outside backups.
  UPDATE_STOP_ATTEMPTED=1
  docker exec "$CONTAINER" python -c '
import os
fd = os.open("/app/data/update-maintenance.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as output:
    output.write("{\"protocol\":1}\n"); output.flush(); os.fsync(output.fileno())
' || return 1
  UPDATE_MARKER_OWNED=1
}

update_clear_maintenance() {
  [ "${UPDATE_MARKER_OWNED:-0}" = 1 ] || return 1
  docker exec "$CONTAINER" python -c '
import os, stat
path = "/app/data/update-maintenance.json"
assert stat.S_ISREG(os.lstat(path).st_mode), "invalid maintenance marker"
os.unlink(path)
' || return 1
  UPDATE_MARKER_OWNED=0
}

update_hold_writes() {
  local statuses
  docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf stop web scheduler healthwatch >/dev/null 2>&1 || true
  if statuses="$(update_service_status)" && printf '%s\n' "$statuses" | awk '$2 != "STOPPED" {bad=1} END {exit bad ? 1 : 0}'; then
    return 0
  fi
  # Fail closed if supervisor cannot prove a stop. The persisted managed job
  # keeps maintenance enabled after an administrator starts the container.
  docker stop "$CONTAINER" >/dev/null 2>&1 || true
  return 1
}

update_restore_git_sha() {
  # Compose may override GIT_SHA; restore the original image's value, not the
  # new source commit. Only this non-secret value is read from image metadata.
  local value version
  value="$(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$1" | sed -n 's/^GIT_SHA=//p' | tail -n 1)" || return 1
  version="$(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$1" | sed -n 's/^APP_VERSION=//p' | tail -n 1)" || return 1
  export GIT_SHA="${value:-unknown}"
  [ -z "$version" ] || export APP_VERSION="$version"
}

update_verify_built_image() {
  [ -n "${AGV_BUILD_CONTEXT:-}" ] || return 0
  # Refuse a source whose Dockerfile ignored the pinned build metadata before
  # entering maintenance; /health alone cannot establish source provenance.
  docker image inspect --format '{{json .Config.Env}}' "$AGV_IMAGE" | python3 -c '
import json, sys
values = dict(item.split("=", 1) for item in json.load(sys.stdin) if "=" in item)
assert values.get("APP_VERSION") == sys.argv[1] and values.get("GIT_SHA") == sys.argv[2], "构建版本校验失败"
' "$APP_VERSION" "$GIT_SHA" || return 1
  # A source release may change its Debian base. Never attach an existing PG
  # cluster to another major version, even briefly during a failed activation.
  local current_pg target_pg
  current_pg="$(docker exec "$CONTAINER" python -c '
import os
from pathlib import Path
if os.environ.get("USE_POSTGRES") == "1":
    value = (Path(os.environ.get("PGDATA", "/app/data/pgdata")) / "PG_VERSION").read_text().strip()
    assert value.isdigit(), "invalid installed PostgreSQL version"
    print(value)
')" || return 1
  if [ -n "$current_pg" ]; then
    target_pg="$(docker run --rm --network none --read-only --entrypoint python "$AGV_IMAGE" -c '
from pathlib import Path
versions = sorted(p.name for p in Path("/usr/lib/postgresql").iterdir() if (p / "bin/postgres").is_file())
assert len(versions) == 1 and versions[0].isdigit(), "ambiguous target PostgreSQL version"
print(versions[0])
')" || return 1
    [ "$current_pg" = "$target_pg" ] || { echo "ERROR: PostgreSQL 主版本不兼容，未停止服务或切换数据卷。" >&2; return 1; }
  fi
}

update_persist_runtime() {
  # A later compose up must use the verified image, not stale installation
  # defaults. Persist only after health/recovery succeeds, before maintenance
  # is cleared. Failure leaves the application stopped for administrator review.
  if [ "${AGV_UPDATE_MANAGED:-0}" != 1 ] && [ -z "${AGV_INSTALLED_COMPOSE_FILE:-}" ]; then return 0; fi
  docker inspect --format '{{json .}}' "$CONTAINER" | python3 "$SCRIPT_DIR/persist-update-runtime.py" "$ENV_FILE"
}

update_cleanup() {
  local result=$? outcome=failed
  trap - EXIT
  if [ "${UPDATE_FINISHED:-0}" = 1 ]; then return "$result"; fi
  if [ "${UPDATE_SWITCHED:-0}" = 1 ] || { [ "${UPDATE_STOP_ATTEMPTED:-0}" = 1 ] && [ "${UPDATE_STOP_VERIFIED:-0}" != 1 ]; }; then
    update_hold_writes || true
    outcome=needs_attention
  elif [ "${UPDATE_STOP_VERIFIED:-0}" = 1 ]; then
    if [ -n "${UPDATE_ORIGINAL_RUNNING:-}" ]; then
      # Names come exclusively from validated supervisor status output.
      if ! docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf start $UPDATE_ORIGINAL_RUNNING; then
        update_hold_writes || true
        outcome=needs_attention
      fi
    fi
    if [ "$outcome" = failed ] && ! update_clear_maintenance; then outcome=needs_attention; update_hold_writes || true; fi
  fi
  update_event "$outcome" || true
  return "$result"
}

update_begin() {
  umask 077
  UPDATE_STOP_ATTEMPTED=0 UPDATE_STOP_VERIFIED=0 UPDATE_SWITCHED=0 UPDATE_FINISHED=0 UPDATE_MARKER_OWNED=0
  UPDATE_ORIGINAL_RUNNING=""
  trap update_cleanup EXIT
}

update_finish() {
  # Terminal acknowledgement is followed by process exit before the host
  # publishes success, so an uncompleted script cannot report completion.
  update_persist_runtime || return 1
  update_clear_maintenance || return 1
  update_event "$1" || return 1
  UPDATE_FINISHED=1
}
