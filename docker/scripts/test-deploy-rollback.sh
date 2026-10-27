#!/usr/bin/env bash
# 部署脚本故障注入回归测试（HYPE-51 复评：一审阻塞项 1–3 + 建议项 4）。
#
# 全程使用隔离环境（独立 compose 项目/容器/卷/端口/镜像标签/备份目录），
# 不影响生产 8002 与生产镜像/备份。
#
# 覆盖：
#   T1 自定义镜像版本回滚：AGV_IMAGE 升级后 rollback 精确回到更新前镜像（阻塞项 2）
#   T2 健康检查失败 → 自动回滚+数据恢复成功：退出码非零且仅在此才输出“已自动回滚…已恢复”（阻塞项 1 成功措辞条件）
#   T3 健康检查失败 + 数据恢复失败：退出码非零，【不】误报“已恢复”，保留恢复失败日志（阻塞项 1 失败退出码/措辞）
#   T4 恢复前 SHA-256 校验拒绝：备份损坏 → restore 拒绝执行破坏性操作（建议项 4）
#   T5 容器切换（compose up）失败：仍可能已迁移，必须恢复旧镜像和备份数据，退出码非零
#   T6 旧镜像在新 schema 下不健康 → 先切回旧镜像、恢复已校验备份、再做最终健康检查：
#      证明恢复确实执行且成功措辞/退出码正确（HYPE-51 二审阻塞项——不得以恢复前应用健康为门槛）
#
# 用法：bash docker/scripts/test-deploy-rollback.sh
# 依赖：docker + docker compose；构建走 BuildKit 缓存（首轮稍慢，后续秒级）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY="$SCRIPT_DIR/deploy.sh"
COMPOSE_OVERRIDE="$SCRIPT_DIR/test-compose-override.yml"

# ---- 隔离命名空间（与生产完全分离） ----
RUN_ID="agvpm-h51r"
CONTAINER="$RUN_ID-8002"
APP_PORT=8005
IMG1="$RUN_ID:test1"     # 旧镜像（自定义 AGV_IMAGE 场景）
IMG2="$RUN_ID:test2"     # 新镜像
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/h51r.XXXXXX")"
ENV_FILE="$TMP_DIR/test.env"
BACKUP_DIR="$TMP_DIR/backups"
LOG="$TMP_DIR/run.log"

cat > "$ENV_FILE" <<EOF
INITIAL_ADMIN_PASSWORD=TestAdmin#2026!
SEED_DEMO_USERS=0
TRUSTED_HOSTS=127.0.0.1,localhost
FORWARDED_ALLOW_IPS=
WEB_CONCURRENCY=1
APP_PORT=$APP_PORT
EOF

export COMPOSE_PROJECT_NAME="$RUN_ID"
export AGV_CONTAINER_NAME="$CONTAINER"
export AGV_ENV_FILE="$ENV_FILE"
export BACKUP_DIR="$BACKUP_DIR"
export AGV_ROLLBACK_REF="$RUN_ID"
# 快速 healthcheck override（见 test-compose-override.yml），避免每轮等 40s+。
export AGV_COMPOSE_FILE="$COMPOSE_OVERRIDE"

PASS=0; FAIL=0
fail() { echo "❌ FAIL: $*"; FAIL=$((FAIL + 1)); exit 1; }
ok()   { echo "✅ PASS: $*"; PASS=$((PASS + 1)); }

# 运行期望“非零退出码”的 deploy 子命令；用法：
#   run_expect_fail "描述" <subcommand> VAR=VAL ...
# env 的赋值参数必须位于命令之前，故子命令单独传、排在最前。
run_expect_fail() {
  local desc="$1"; shift
  local cmd="$1"; shift
  echo ""
  echo "──────────────────────────────────────────────"
  echo "▶ $desc"
  echo "──────────────────────────────────────────────"
  set +e
  env "$@" bash "$DEPLOY" "$cmd" >"$LOG" 2>&1
  local rc=$?
  set -e
  echo "  (exit=$rc)"
  [ "$rc" -ne 0 ] || fail "期望非零退出码，实际 0 —— $desc"
  return 0
}

log_has()  { grep -q "$1" "$LOG" || { echo "  输出片段："; cat "$LOG"; fail "输出中未找到：$1"; }; }
log_lacks(){ if grep -q "$1" "$LOG"; then echo "  输出片段："; cat "$LOG"; fail "输出中不应出现：$1"; fi; }

assert_healthy() {
  curl --fail --silent --max-time 10 "http://127.0.0.1:$APP_PORT/health" >/dev/null \
    || fail "容器未通过健康检查（${CONTAINER}）"
  ok "容器健康"
}
container_image() { docker inspect --format '{{.Config.Image}}' "$CONTAINER" 2>/dev/null; }

cleanup() {
  echo ""
  echo "==> 清理隔离环境..."
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker volume rm "${RUN_ID}_agv-pm-multica-data" >/dev/null 2>&1 || true
  for img in "$IMG1" "$IMG2"; do docker rmi "$img" >/dev/null 2>&1 || true; done
  docker images --format '{{.Repository}}:{{.Tag}}' | grep "^${RUN_ID}:rollback-" | xargs -I{} docker rmi {} >/dev/null 2>&1 || true
  rm -rf "$TMP_DIR"
  echo "==> 清理完成（测试中途失败也保留容器现场，可 docker ps -a 排查）"
}
trap cleanup EXIT

# ──────────────────────────────
echo "==> 隔离安装（旧镜像 $IMG1, GIT_SHA=testA）..."
env AGV_IMAGE="$IMG1" GIT_SHA=testA bash "$DEPLOY" install >"$LOG" 2>&1 || { cat "$LOG"; fail "隔离首次部署失败"; }
assert_healthy
[ "$(container_image)" = "$IMG1" ] || fail "安装后容器镜像应为 ${IMG1}，实际 $(container_image)"
ok "初始部署镜像 = $IMG1"

# ── T2：健康检查失败 → 自动回滚 + 恢复成功 ─────────────────────────
echo ""
echo "==================== T2 健康检查失败→自动回滚+恢复成功 ===================="
run_expect_fail "T2 update（FAULT_WAIT_HEALTHY=1，GIT_SHA=testB）" update \
  FAULT_WAIT_HEALTHY=1 AGV_IMAGE="$IMG1" GIT_SHA=testB
log_has "已恢复原镜像和更新前数据"
log_has "数据已恢复"
assert_healthy
[ "$(container_image)" = "$IMG1" ] || fail "T2 回滚后镜像应为 ${IMG1}，实际 $(container_image)"
ok "T2 回滚后镜像 = ${IMG1}（回到更新前镜像）"

# ── T6：旧镜像在新 schema 下不健康 → 先恢复数据再做最终健康确认（二审阻塞项） ─────────
echo ""
echo "==================== T6 旧镜像新库不健康（先恢复再做最终健康确认） ===================="
# FAULT_UNTIL_RESTORE=2：切到新镜像后的健康检查失败一次；回滚路径若不先恢复数据，
# 对旧镜像做健康检查会再失败一次（模拟迁移令旧版本与新 schema 不兼容）；恢复一旦执行
# 注入即解除，最终健康检查通过。旧代码在恢复前以旧镜像健康为门槛会提前退出（不恢复），
# 新代码必须：切回旧镜像 → 恢复已校验备份 → 再做最终健康检查。
run_expect_fail "T6 update（FAULT_UNTIL_RESTORE=2，GIT_SHA=testF）" update \
  FAULT_UNTIL_RESTORE=2 AGV_IMAGE="$IMG1" GIT_SHA=testF
log_has "已恢复原镜像和更新前数据"
log_has "备份 SHA-256 校验通过"
log_has "pg_restore 完成"
log_lacks "自动恢复未完成"
assert_healthy
[ "$(container_image)" = "$IMG1" ] || fail "T6 回滚后镜像应为 ${IMG1}，实际 $(container_image)"
ok "T6 恢复确实执行且最终健康确认通过（成功措辞/退出码正确）"

# ── T5：容器切换失败 → 恢复旧镜像与更新前数据 ─────────────────────────
echo ""
echo "==================== T5 容器切换失败（可能部分启动，完整恢复数据） ===================="
# 清空此前日志，断言 compose 错误路径仍然完成了经过校验的数据恢复。
rm -f "$BACKUP_DIR"/failed-restore-*.log
run_expect_fail "T5 update（FAULT_COMPOSE_UP=1，GIT_SHA=testD）" update \
  FAULT_COMPOSE_UP=1 AGV_IMAGE="$IMG1" GIT_SHA=testD
log_has "已恢复原镜像和更新前数据"
log_has "pg_restore 完成"
[ -n "$(ls "$BACKUP_DIR"/failed-restore-*.log 2>/dev/null | tail -n 1)" ] || fail "T5 应留下实际数据恢复日志"
ok "T5 旧镜像与数据均已恢复"
assert_healthy
[ "$(container_image)" = "$IMG1" ] || fail "T5 后镜像应为 ${IMG1}，实际 $(container_image)"
ok "T5 容器镜像 = ${IMG1}（已切回旧镜像）"

# ── T4：恢复前 SHA-256 校验拒绝 ─────────────────────────
echo ""
echo "==================== T4 损坏备份 → restore 拒绝（SHA-256） ===================="
latest="$(ls "$BACKUP_DIR"/agv-pm-*.tar.gz.agvenc | sort | tail -n 1)"
corrupt="$TMP_DIR/corrupt.tar.gz"
cp "$latest" "$corrupt"
echo "0000000000000000000000000000000000000000000000000000000000000000  $corrupt" > "$corrupt.sha256"
set +e
env AGV_IMAGE="$IMG1" bash "$DEPLOY" restore "$corrupt" >"$LOG" 2>&1
rc=$?
set -e
echo "  (exit=$rc)"
[ "$rc" -ne 0 ] || fail "T4 损坏备份 restore 应拒绝并返回非零"
log_has "SHA-256"
log_has "中止恢复"
ok "T4 restore 因 SHA-256 校验失败被拒绝（未执行破坏性恢复）"
assert_healthy
rm -f "$corrupt" "$corrupt.sha256"

# ── T1：自定义镜像版本升级 → rollback 精确回到旧镜像 ─────────────────────────
echo ""
echo "==================== T1 自定义镜像版本升级 + rollback ===================="
echo "==> 升级到新镜像 ${IMG2}（GIT_SHA=testE），应成功..."
env AGV_IMAGE="$IMG2" GIT_SHA=testE bash "$DEPLOY" update >"$LOG" 2>&1 || { cat "$LOG"; fail "T1 update 到 $IMG2 失败"; }
[ "$(container_image)" = "$IMG2" ] || fail "T1 update 后镜像应为 ${IMG2}，实际 $(container_image)"
ok "T1 升级后镜像 = $IMG2"
assert_healthy

echo "==> rollback 回到 ${IMG1}（依据 PREVIOUS_REF，不依赖写死的 2.1.0）..."
env bash "$DEPLOY" rollback >"$LOG" 2>&1 || { cat "$LOG"; fail "T1 rollback 失败"; }
[ "$(container_image)" = "$IMG1" ] || fail "T1 rollback 后镜像应为 ${IMG1}，实际 $(container_image)"
ok "T1 rollback 后镜像 = ${IMG1}（精确回到更新前自定义镜像）"
assert_healthy

# ── T3：健康检查失败 + 恢复失败 → 不误报成功 ─────────────────────────
echo ""
echo "==================== T3 健康检查失败+恢复失败（不误报成功） ===================="
run_expect_fail "T3 update（FAULT_WAIT_HEALTHY=1 FAULT_RESTORE=1，GIT_SHA=testC）" update \
  FAULT_WAIT_HEALTHY=1 FAULT_RESTORE=1 AGV_IMAGE="$IMG1" GIT_SHA=testC
log_lacks "已恢复原镜像和更新前数据"
log_has "自动恢复未完成"
log_has "数据恢复失败"
restore_log="$(ls "$BACKUP_DIR"/failed-restore-*.log 2>/dev/null | tail -n 1)"
[ -n "$restore_log" ] && [ -s "$restore_log" ] || fail "应保留恢复失败日志 failed-restore-*.log"
ok "恢复失败日志已保留：$restore_log"
# Restore failure must remain in maintenance; never mistake old-image health for recovered data.
docker exec "$CONTAINER" test -f /app/data/update-maintenance.json || fail "T3 必须保留维护标记"
services="$(docker exec "$CONTAINER" supervisorctl -c /app/supervisord.conf status web scheduler healthwatch || true)"
printf '%s\n' "$services" | awk 'NF {count++; if ($2 != "STOPPED") bad=1} END {exit count == 3 && !bad ? 0 : 1}' || fail "T3 写服务必须保持停止"
[ "$(container_image)" = "$IMG1" ] || fail "T3 回滚后镜像应为 ${IMG1}，实际 $(container_image)"
ok "T3 镜像已回滚，但恢复未完成；保留维护标记与停写状态"

# ──────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "测试完成：PASS=$PASS FAIL=$FAIL"
echo "════════════════════════════════════════"
[ "$FAIL" -eq 0 ] || exit 1
