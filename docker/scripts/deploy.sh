#!/usr/bin/env bash
# 8002 单容器 PostgreSQL 部署统一入口（Multica 正式部署：首次部署 + 二次部署）。
#
# 用法（与 Makefile 目标等价）：
#   bash docker/scripts/deploy.sh install           首次部署（= make deploy）
#   bash docker/scripts/deploy.sh update            二次部署，自动备份 + 健康检查 + 失败回滚（= make update）
#   bash docker/scripts/deploy.sh status            容器状态 + /health
#   bash docker/scripts/deploy.sh logs              跟踪容器日志
#   bash docker/scripts/deploy.sh ps                容器列表
#   bash docker/scripts/deploy.sh backup            全量备份（pg_dump -Fc → backups/）
#   bash docker/scripts/deploy.sh restore <备份>    恢复备份（同 make restore BACKUP=...）
#   bash docker/scripts/deploy.sh rollback          回滚到上一次 update 前的镜像
#
# 需要配置的变量极少，全部写入 docker/.env 即可（无需 export；无 .env 时走内置默认值）：
#   INITIAL_ADMIN_PASSWORD  首次部署必填（≥8 位）。SEED_DEMO_USERS=0（默认，正式）时未设置会导致首次启动失败。
#   SEED_DEMO_USERS         0=仅创建 admin（正式，默认）；1=额外创建演示账号（评审/演示）。
#   TRUSTED_HOSTS           Host 校验白名单（默认 127.0.0.1,localhost 仅本机回环；通过 IP/域名访问需显式加入，见 docs/deployment.md）。
#   FORWARDED_ALLOW_IPS     反向代理可信地址/网段（默认空=仅回环可信，见 docs/deployment.md T024）。
#   WEB_CONCURRENCY         uvicorn worker 数（默认 2）。
#   AGV_IMAGE / APP_VERSION 镜像标签与版本（默认从 frontend/package.json 自动同步，一般无需改动）。
#   AI_PROVIDER / DEEPSEEK_* / MIMO_* / MINIMAX_*  AI 服务密钥（可选，不配置不影响手工业务）。
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
. "$SCRIPT_DIR/update-common.sh"
# 默认 compose 为 docker/docker-compose.multica.yml；宿主管理员可通过
# AGV_INSTALLED_COMPOSE_FILE 指定完整的本机安装配置（不是下载的源码配置）。高级/测试覆盖：设
# AGV_COMPOSE_FILE 追加一个 override 文件（后加载者覆盖先加载者）。故障注入回归
# 测试用它传入快速 healthcheck，避免每轮容器重建等 40s+ 的 start_period。
COMPOSE_FILES=("${AGV_INSTALLED_COMPOSE_FILE:-$PROJECT_DIR/docker/docker-compose.multica.yml}")
if [ -n "${AGV_COMPOSE_FILE:-}" ] && [ -z "${AGV_INSTALLED_COMPOSE_FILE:-}" ]; then
  COMPOSE_FILES+=("$AGV_COMPOSE_FILE")
fi
ENV_FILE="${AGV_ENV_FILE:-$PROJECT_DIR/docker/.env}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-docker}"
CONTAINER="${AGV_CONTAINER_NAME:-agv-pm-8002}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_DIR/backups}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-240}"
STATE_FILE="$BACKUP_DIR/last-update-multica.env"

APP_PORT=""
if [ -f "$ENV_FILE" ]; then
  APP_PORT="$(sed -n 's/^APP_PORT=//p' "$ENV_FILE" | tail -n 1)"
fi
APP_PORT="${APP_PORT:-8002}"

die() { echo "ERROR: $*" >&2; exit 1; }

# ---- 故障注入钩子（仅供 docker/scripts/test-deploy-rollback.sh 回归测试使用；生产不设 FAULT_* 即零影响） ----
#   FAULT_WAIT_HEALTHY=N     N>0：让 wait_healthy 连续失败 N 次（模拟新镜像不健康/恢复后不健康）
#   FAULT_UNTIL_RESTORE=N    N>0：让 wait_healthy 连续失败 N 次，恢复一旦执行即解除（模拟“旧镜像在
#                            新 schema 下不健康、恢复旧数据后才健康”——HYPE-51 二审回归场景）
#   FAULT_COMPOSE_UP=1       让 update 的容器切换（compose up）失败一次（模拟切换命令失败）
#   FAULT_RESTORE=N          N>0：让数据恢复执行阶段失败 N 次（模拟恢复失败，发生在 SHA-256 校验之后）
fault_trigger() {
  case "$1" in
    wait_healthy)
      if [ "${FAULT_UNTIL_RESTORE:-0}" -gt 0 ] 2>/dev/null; then
        FAULT_UNTIL_RESTORE=$((FAULT_UNTIL_RESTORE - 1))
        echo "  [FAULT] 模拟旧镜像在新 schema 下不健康（剩余 $FAULT_UNTIL_RESTORE 次，恢复后解除）" >&2
        return 1
      fi
      if [ "${FAULT_WAIT_HEALTHY:-0}" -gt 0 ] 2>/dev/null; then
        FAULT_WAIT_HEALTHY=$((FAULT_WAIT_HEALTHY - 1))
        echo "  [FAULT] 模拟健康检查失败（剩余 $FAULT_WAIT_HEALTHY 次）" >&2
        return 1
      fi
      ;;
    compose_up)
      if [ "${FAULT_COMPOSE_UP:-0}" -eq 1 ] 2>/dev/null; then
        FAULT_COMPOSE_UP=0
        echo "  [FAULT] 模拟 compose up 切换失败" >&2
        return 1
      fi
      ;;
    restore)
      # 恢复一旦执行，视为 schema 已回退到与旧镜像兼容的状态：解除“恢复前不健康”注入。
      FAULT_UNTIL_RESTORE=0
      if [ "${FAULT_RESTORE:-0}" -gt 0 ] 2>/dev/null; then
        FAULT_RESTORE=$((FAULT_RESTORE - 1))
        echo "  [FAULT] 模拟数据恢复失败（剩余 $FAULT_RESTORE 次）" >&2
        return 1
      fi
      ;;
  esac
  return 0
}

compose() {
  local args=()
  local f
  [ -f "$ENV_FILE" ] && args+=(--env-file "$ENV_FILE")
  for f in "${COMPOSE_FILES[@]}"; do
    args+=(-f "$f")
  done
  update_compose -p "$PROJECT_NAME" "${args[@]}" -- "$@"
}

wait_healthy() {
  local elapsed=0 status
  fault_trigger wait_healthy || return 1
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
  curl --fail --silent --show-error "http://127.0.0.1:$APP_PORT/health"
  echo
}

# 从 frontend/package.json 同步 APP_VERSION / AGV_IMAGE，并从 git 注入 GIT_SHA：
# 版本升级后无需手工改任何变量，镜像标签与构建来源自动跟随源码。
sync_build_version() {
  local version
  version="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${AGV_BUILD_CONTEXT:-$PROJECT_DIR}/frontend/package.json" | head -n 1)"
  [ -n "$version" ] || die "无法读取 frontend/package.json 中的版本号。"
  export APP_VERSION="${APP_VERSION:-$version}"
  export AGV_IMAGE="${AGV_IMAGE:-agv-pm-multica:$version}"
  export GIT_SHA="${GIT_SHA:-$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)}"
}

backup_app() {
  BACKUP_DIR="$BACKUP_DIR" AGV_CONTAINER="$CONTAINER" "$SCRIPT_DIR/backup.sh"
}

write_state() {
  local rollback_image="$1" backup_file="$2" previous_ref="$3"
  mkdir -p "$BACKUP_DIR"
  {
    printf 'ROLLBACK_IMAGE=%s\n' "$rollback_image"
    printf 'BACKUP_FILE=%s\n' "$backup_file"
    printf 'PREVIOUS_REF=%s\n' "$previous_ref"
    printf 'CREATED_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$STATE_FILE"
  chmod 600 "$STATE_FILE"
}

load_state() {
  [ -f "$STATE_FILE" ] || die "无更新状态（${STATE_FILE}）。"
  ROLLBACK_IMAGE="$(sed -n 's/^ROLLBACK_IMAGE=//p' "$STATE_FILE")"
  BACKUP_FILE="$(sed -n 's/^BACKUP_FILE=//p' "$STATE_FILE")"
  PREVIOUS_REF="$(sed -n 's/^PREVIOUS_REF=//p' "$STATE_FILE")"
  [ -n "$ROLLBACK_IMAGE" ] && [ -n "$BACKUP_FILE" ] || die "更新状态不完整。"
}

# 校验备份 SHA-256（backup.sh 生成 <文件>.sha256）。校验失败返回非零，
# 调用方不得继续执行破坏性恢复（dropdb/createdb/pg_restore）。
# SKIP_SHA_CHECK=1 仅允许「缺少校验文件」时显式跳过（旧版本工具生成的备份无 .sha256），
# 且必须打印醒目告警；校验文件存在但值不匹配时仍必须拒绝，不得绕过篡改检测（HYPE-52 一审阻塞项 1）。
verify_backup() {
  local archive="$1"
  local sum_file="$archive.sha256"
  local expected actual
  [ -f "$archive" ] || { echo "ERROR: 备份文件不存在: $archive" >&2; return 1; }
  if [ ! -f "$sum_file" ]; then
    if [ "${SKIP_SHA_CHECK:-0}" = "1" ]; then
      echo "!!! 警告: 备份缺少校验文件 ${sum_file}，已通过 SKIP_SHA_CHECK=1 显式跳过校验。" >&2
      echo "!!! 风险: 无法确认备份包完整性，仅应在确知来源可靠时使用。" >&2
      return 0
    fi
    echo "ERROR: 缺少校验文件 $sum_file" >&2
    echo "  该备份可能由旧版本工具生成，或校验文件丢失。" >&2
    echo "  如确知备份来源可靠，可设置 SKIP_SHA_CHECK=1 显式跳过校验后继续。" >&2
    return 1
  fi
  expected="$(awk 'NR==1{print $1}' "$sum_file")"
  [ -n "$expected" ] || { echo "ERROR: 校验文件为空: $sum_file" >&2; return 1; }
  if command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$archive" | awk '{print $1}')"
  else
    actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
  fi
  if [ "$expected" != "$actual" ]; then
    echo "ERROR: SHA-256 不匹配：期望 ${expected}，实际 ${actual}（${archive}）" >&2
    return 1
  fi
  echo "==> 备份 SHA-256 校验通过：$archive"
  return 0
}

# 恢复：先校验备份 SHA-256，再执行破坏性恢复（restore.sh：dropdb/createdb/pg_restore）。
# 校验失败或 restore.sh 失败均返回非零，绝不输出“已恢复”之类的成功措辞。
# 第二个参数 logfile 非空时，restore.sh 输出与错误都写入该文件（自动回滚路径保留失败现场）。
restore_with_verify() {
  local archive="${1:-}" logfile="${2:-}"
  local log_err=()
  if [ -n "$logfile" ]; then
    log_err=(echo "ERROR: 数据恢复失败（详见 ${logfile}）。")
  else
    log_err=(echo "ERROR: 数据恢复失败，请检查上方错误。")
  fi
  [ -n "$archive" ] && [ -f "$archive" ] || { echo "ERROR: 备份文件不存在: $archive" >&2; return 1; }
  if ! verify_backup "$archive"; then
    [ -n "$logfile" ] && echo "ERROR: 备份 SHA-256 校验失败，已中止恢复（未执行 dropdb/createdb/pg_restore）。" >>"$logfile"
    echo "ERROR: 已中止恢复（未执行破坏性操作）。" >&2
    return 1
  fi
  fault_trigger restore || { [ -n "$logfile" ] && echo "ERROR: 数据恢复执行失败（故障注入）。" >>"$logfile"; return 1; }
  if [ -n "$logfile" ]; then
    if ! AGV_CONTAINER="$CONTAINER" "$SCRIPT_DIR/restore.sh" "$archive" >"$logfile" 2>&1; then
      "${log_err[@]}"
      return 1
    fi
    cat "$logfile"
    return 0
  fi
  AGV_CONTAINER="$CONTAINER" "$SCRIPT_DIR/restore.sh" "$archive"
}

# 等待回滚后的容器“就绪”而非“健康”：supervisord 已接管、PostgreSQL 可接受连接。
# 恢复已校验备份前不能以应用 /health 为门槛（HYPE-51 二审阻塞项）——迁移令旧版本与新
# schema 不兼容时应用可能不健康，但数据库本身仍应在服务；必须先恢复数据再做最终健康确认。
wait_rollback_ready() {
  local elapsed=0 pg=0
  if docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" 2>/dev/null | grep -q '^USE_POSTGRES=1'; then
    pg=1
  fi
  while [ "$elapsed" -lt 60 ]; do
    if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
      return 1
    fi
    if [ "$pg" -eq 1 ]; then
      # PG 模式：supervisord 已接管 postgres 且可接受连接（dropdb/createdb/pg_restore 可用）。
      if docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf status postgres >/dev/null 2>&1 \
          && docker exec "$CONTAINER" pg_isready -h 127.0.0.1 -p 5432 -U postgres >/dev/null 2>&1; then
        return 0
      fi
    else
      # SQLite 模式：仅需 supervisord 接管（restore.sh 走 staged 流程，不依赖 PG）。
      if docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf status web >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 1
}

# 仅切回旧镜像并重建容器，不做健康检查。
# 用于「新版本健康检查失败」路径：在恢复已校验备份之前不得以旧镜像健康为门槛——
# 若迁移令旧版本与新 schema 不兼容，恢复前健康检查会失败并提前退出，留下旧镜像配新库
# （HYPE-51 二审阻塞项）。健康确认统一放到恢复数据之后。
rollback_image_switch() {
  local rollback_ref="$1" old_ref="$2"
  echo "  -> 切回旧镜像 $old_ref"
  case "$old_ref" in
    sha256:*|*@sha256:*)
      # An immutable image ID/digest is valid for compose up but cannot be a
      # docker tag destination. The pre-update rollback tag already pins it.
      export AGV_IMAGE="$rollback_ref"
      ;;
    *)
      if ! docker tag "$rollback_ref" "$old_ref" >/dev/null 2>&1; then
        echo "ERROR: 回滚镜像 '$rollback_ref' 打 tag 失败，请检查本机镜像与引用。" >&2
        return 1
      fi
      export AGV_IMAGE="$old_ref"
      ;;
  esac
  # 强制 compose 解析到回滚目标：update 期间 AGV_IMAGE 可能已指向新版本（自定义镜像/版本升级），
  # 不覆盖则 compose up 会再次拉起新镜像。
  update_restore_git_sha "$rollback_ref" || return 1
  echo "  -> 用旧镜像重建容器"
  if ! compose up -d --no-build --force-recreate; then
    echo "ERROR: 回滚容器重建失败。请人工介入（docker compose ps 查看状态）。" >&2
    return 1
  fi
  return 0
}

# 仅切回旧镜像并等待健康，保留供显式的镜像回滚操作使用。
rollback_image_only() {
  local rollback_ref="$1" old_ref="$2"
  if ! rollback_image_switch "$rollback_ref" "$old_ref"; then
    return 1
  fi
  echo "  -> 等待健康检查"
  if ! wait_healthy; then
    docker logs --tail 120 "$CONTAINER" >&2 || true
    echo "ERROR: 回滚后容器未通过健康检查。请人工介入。" >&2
    return 1
  fi
  return 0
}

# 新版本已运行但未通过健康检查：先切回旧镜像（不做健康门槛）→ 恢复已校验备份 → 再做最终健康确认。
# 任一关键步骤失败都返回非零并保留失败日志；只有 restore 成功且最终健康检查通过才输出“数据已恢复”。
rollback_and_restore() {
  local rollback_ref="$1" old_ref="$2" backup_file="$3" stamp="$4"
  local restore_log="$BACKUP_DIR/failed-restore-$stamp.log"
  : > "$restore_log"   # 预创建，保证失败时一定有日志可看
  # 自动回滚路径保持强校验：不受 SKIP_SHA_CHECK 影响（HYPE-52 一审阻塞项 1）。
  # 更新流程生成的备份必带 .sha256，这里显式置 0 覆盖任何外部传入的跳过意图，
  # 确保回滚的数据恢复绝不因校验缺失/被跳过而恢复一个未验证的备份。
  export SKIP_SHA_CHECK=0
  rollback_image_switch "$rollback_ref" "$old_ref" || return 1
  if ! wait_rollback_ready; then
    echo "ERROR: 切回旧镜像后容器未就绪（supervisord/PostgreSQL 未在 60s 内就绪），中止恢复。请人工介入。" >&2
    return 1
  fi
  echo "  -> 恢复更新前数据（${backup_file}）"
  if ! restore_with_verify "$backup_file" "$restore_log"; then
    echo "ERROR: 数据恢复失败（镜像已回滚，但数据未恢复）。详见 ${restore_log}。请人工介入。" >&2
    return 1
  fi
  echo "  -> 等待恢复数据后的最终健康检查"
  if ! wait_healthy; then
    echo "ERROR: 数据恢复后容器未通过健康检查。请人工介入。" >&2
    return 1
  fi
  echo "  -> 数据已恢复：$(print_health)"
  return 0
}

install_app() {
  if docker inspect "$CONTAINER" >/dev/null 2>&1; then
    die "容器 '$CONTAINER' 已存在。二次部署（更新到当前代码）请用 make update（deploy.sh update）。"
  fi
  sync_build_version
  echo "==> 首次部署：构建镜像并启动单容器（PostgreSQL 在容器内，端口 ${APP_PORT}）"
  compose up -d --build
  if ! wait_healthy; then
    docker logs --tail 120 "$CONTAINER" >&2 || true
    die "首次部署未通过健康检查。"
  fi
  echo "==> 部署健康：$(print_health)"
  echo "==> 访问：http://127.0.0.1:$APP_PORT"
  echo "==> 首次登录：admin / docker/.env 中的 INITIAL_ADMIN_PASSWORD（演示部署 SEED_DEMO_USERS=1 时为 admin/admin123）"
}

update_app() {
  local stamp old_id old_ref rollback_ref backup_file switch_ok
  docker inspect "$CONTAINER" >/dev/null 2>&1 || die "容器未安装，请先执行 install。"
  update_begin
  sync_build_version
  stamp="$(date +%Y%m%d-%H%M%S)-$$"
  old_id="$(docker inspect --format '{{.Image}}' "$CONTAINER")"
  old_ref="$(docker inspect --format '{{.Config.Image}}' "$CONTAINER")"
  rollback_ref="${AGV_ROLLBACK_REF:-agv-pm-multica}:rollback-$stamp"

  update_event building
  compose build
  update_verify_built_image
  # Preserve the exact old image before stopping any service.
  docker tag "$old_id" "$rollback_ref"

  update_event backing_up
  update_mark_maintenance
  update_stop_writes
  # No application/scheduler writes between this snapshot and final verification.
  AGV_BACKUP_STAMP="$stamp" backup_app
  backup_file="$BACKUP_DIR/agv-pm-$stamp.tar.gz.agvenc"
  [ -n "$backup_file" ] || die "备份文件未生成。"
  SKIP_SHA_CHECK=0 verify_backup "$backup_file" || die "备份校验失败，中止更新。"
  write_state "$rollback_ref" "$backup_file" "$old_ref"

  update_event installing
  UPDATE_SWITCHED=1
  switch_ok=0
  fault_trigger compose_up || switch_ok=1
  if [ "$switch_ok" -eq 0 ]; then compose up -d --no-build || switch_ok=1; fi
  if [ "$switch_ok" -eq 0 ]; then
    update_event verifying
    if wait_healthy; then
      update_finish succeeded
      echo "==> 更新通过健康检查。"
      return 0
    fi
    docker logs --tail 160 "$CONTAINER" > "$BACKUP_DIR/failed-update-$stamp.log" 2>&1 || true
  fi
  # A nonzero compose result can still mean the new process migrated data.
  # Both activation errors and health failures require image AND data recovery.
  if rollback_and_restore "$rollback_ref" "$old_ref" "$backup_file" "$stamp"; then
    update_finish rolled_back
    die "更新失败，已恢复原镜像和更新前数据。"
  fi
  die "自动恢复未完成，保持维护停写；请检查本机日志。"
}

rollback_app() {
  load_state
  docker image inspect "$ROLLBACK_IMAGE" >/dev/null 2>&1 || die "回滚镜像 '$ROLLBACK_IMAGE' 不存在。"
  sync_build_version
  # Use the same immutable-reference handling as automatic recovery.
  rollback_image_switch "$ROLLBACK_IMAGE" "${PREVIOUS_REF:-$AGV_IMAGE}" || die "回滚镜像切换失败。"
  wait_healthy || die "回滚镜像未通过健康检查。"
  update_persist_runtime || die "无法保存回滚后的安装版本。"
  echo "==> 已回滚：$(print_health)"
  echo "==> 数据未覆盖。如需同时恢复更新前数据：bash docker/scripts/deploy.sh restore '$BACKUP_FILE'"
}

restore_data() {
  local archive="${1:-}"
  [ -n "$archive" ] || die "用法: deploy.sh restore /path/to/agv-pm-backup.tar.gz"
  [ -f "$archive" ] || die "备份文件不存在: $archive"
  tar -tzf "$archive" >/dev/null || die "备份文件无效。"
  restore_with_verify "$archive" || die "数据恢复失败，请检查上方错误。"
  wait_healthy || die "恢复后容器未通过健康检查。"
  echo "==> 已恢复：$(print_health)"
}

status_app() {
  docker ps --filter "name=^/${CONTAINER}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
  print_health
}

case "${1:-}" in
  install) install_app ;;
  update) update_app ;;
  status) status_app ;;
  logs) compose logs -f --tail=200 ;;
  ps) compose ps ;;
  backup) backup_app ;;
  restore) restore_data "${2:-}" ;;
  rollback) rollback_app ;;
  *)
    echo "用法: $0 {install|update|status|logs|ps|backup|restore BACKUP|rollback}"
    exit 2
    ;;
esac
