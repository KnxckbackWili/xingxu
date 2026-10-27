#!/usr/bin/env bash
# test-hype52-regression.sh — HYPE-52 最后一轮返工：六项回归断言（永久落库，非临时执行）。
#
# 覆盖（博士 2026-08-27 冻结范围）：
#   ① 缺校验默认拒绝    verify_backup 缺 .sha256 且未显式 SKIP_SHA_CHECK=1 → 拒绝
#   ② 缺校验+人工 skip 放行 缺 .sha256 + SKIP_SHA_CHECK=1 → 放行且打印醒目告警
#   ③ 校验不匹配+skip 仍拒绝 .sha256 存在但不匹配 + SKIP_SHA_CHECK=1 → 仍拒绝
#   ④ 自动回滚不被 skip 放宽  rollback_and_restore 强制 export SKIP_SHA_CHECK=0 且在恢复调用之前
#   ⑤ SQLite stop/start 包含 healthwatch  restore.sh SQLite 分支停止/启动均含 healthwatch
#   ⑥ 无时间戳文件不导致轮转失败且文件保留  rotate_backups 对无时间戳 agv-pm-* 安全跳过
#
# 安全红线（本机承载生产 agv-pm-8002）：
#   · 入口 fail-closed：必须显式设置 AGV_CONTAINER 为隔离容器；拒绝空值与生产容器
#     agv-pm-8002（含子串），禁止依赖默认值。
#   · 本脚本仅对仓库内脚本做函数级/源码级断言，不做任何容器操作；但依然要求
#     AGV_CONTAINER 显式隔离，防止未来扩展测试触碰生产资源。
#
# 用法：
#   AGV_CONTAINER=agvpm-h52r-reg bash docker/scripts/test-hype52-regression.sh
# 依赖：bash + 常见工具（awk/grep/mktemp/find），无需 docker。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY="$SCRIPT_DIR/deploy.sh"
RESTORE="$SCRIPT_DIR/restore.sh"
ROTATION="$SCRIPT_DIR/backup-rotation.sh"

PASS=0; FAIL=0
fail() { echo "❌ FAIL: $*" >&2; FAIL=$((FAIL + 1)); }
ok()   { echo "✅ PASS: $*"; PASS=$((PASS + 1)); }

# ---- 生产红线 fail-closed 入口守卫 ----
AGV_CONTAINER="${AGV_CONTAINER:-}"
if [ -z "$AGV_CONTAINER" ]; then
  echo "FAIL-CLOSED: AGV_CONTAINER 未设置。备份/恢复类测试必须显式设置隔离容器，禁止依赖默认值。" >&2
  exit 1
fi
case "$AGV_CONTAINER" in
  *agv-pm-8002*) echo "FAIL-CLOSED: AGV_CONTAINER 命中生产容器 '$AGV_CONTAINER'，拒绝执行。" >&2; exit 1 ;;
esac
echo "==> 入口守卫通过：AGV_CONTAINER=${AGV_CONTAINER}（与生产隔离）"

# 从 bash 脚本提取顶层函数体（用于对 deploy.sh 内的函数做真实代码断言）。
# 匹配 "name() {" 起始行，输出到下一个列首 "}" 结束；函数体内缩进的 "}" 不受影响。
extract_function() {
  awk -v fn="$1" '
    $0 == fn "() {" || $0 == fn "()" { active = 1; print; next }
    active && /^}/ { print; exit }
    active { print }
  ' "$2"
}

# ── ① 缺校验默认拒绝 ─────────────────────────────────────────────
test_missing_checksum_reject() {
  local dir archive fn
  dir="$(mktemp -d)"
  archive="$dir/backup.tar.gz"
  echo "payload" > "$archive"
  fn="$(extract_function verify_backup "$DEPLOY")"
  [ -n "$fn" ] || fail "无法提取 verify_backup（①）"
  if ( eval "$fn"; SKIP_SHA_CHECK=0 verify_backup "$archive" >/dev/null 2>&1 ); then
    fail "缺校验文件 + 未显式 skip 时 verify_backup 应拒绝"
  else
    ok "缺校验默认拒绝（SKIP_SHA_CHECK 未开启）"
  fi
  rm -rf "$dir"
}

# ── ② 缺校验 + SKIP_SHA_CHECK=1 放行（含告警） ─────────────────────
test_missing_checksum_skip_allows() {
  local dir archive fn out rc
  dir="$(mktemp -d)"
  archive="$dir/backup.tar.gz"
  echo "payload" > "$archive"
  fn="$(extract_function verify_backup "$DEPLOY")"
  [ -n "$fn" ] || fail "无法提取 verify_backup（②）"
  set +e
  out="$( ( eval "$fn"; SKIP_SHA_CHECK=1 verify_backup "$archive" ) 2>&1 )"
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    fail "缺校验 + SKIP_SHA_CHECK=1 应放行（rc=$rc）"
  else
    ok "缺校验 + SKIP_SHA_CHECK=1 放行"
  fi
  if ! printf '%s' "$out" | grep -q "警告"; then
    fail "缺校验 + SKIP_SHA_CHECK=1 应打印醒目告警"
  else
    ok "放行路径打印醒目告警"
  fi
  rm -rf "$dir"
}

# ── ③ 校验不匹配 + SKIP_SHA_CHECK=1 仍拒绝 ─────────────────────────
test_mismatch_skip_still_rejects() {
  local dir archive fn
  dir="$(mktemp -d)"
  archive="$dir/backup.tar.gz"
  echo "payload" > "$archive"
  printf '%s  %s\n' "0000000000000000000000000000000000000000000000000000000000000000" "$archive" > "$archive.sha256"
  fn="$(extract_function verify_backup "$DEPLOY")"
  [ -n "$fn" ] || fail "无法提取 verify_backup（③）"
  if ( eval "$fn"; SKIP_SHA_CHECK=1 verify_backup "$archive" >/dev/null 2>&1 ); then
    fail "校验不匹配 + SKIP_SHA_CHECK=1 仍应拒绝"
  else
    ok "校验不匹配 + SKIP_SHA_CHECK=1 仍拒绝"
  fi
  rm -rf "$dir"
}

# ── ④ 自动回滚不被 skip 放宽 ──────────────────────────────────────
test_rollback_not_relaxed() {
  local rb exp_line res_line
  rb="$(extract_function rollback_and_restore "$DEPLOY")"
  [ -n "$rb" ] || fail "无法提取 rollback_and_restore（④）"
  if ! printf '%s\n' "$rb" | grep -qE '^\s*export SKIP_SHA_CHECK=0'; then
    fail "rollback_and_restore 必须强制 export SKIP_SHA_CHECK=0"
  fi
  if printf '%s\n' "$rb" | grep -qE '^\s*export SKIP_SHA_CHECK=1'; then
    fail "rollback_and_restore 不应强制 SKIP_SHA_CHECK=1"
  fi
  exp_line="$(printf '%s\n' "$rb" | grep -nE '^\s*export SKIP_SHA_CHECK=0' | head -n1 | cut -d: -f1)"
  res_line="$(printf '%s\n' "$rb" | grep -n 'restore_with_verify' | head -n1 | cut -d: -f1)"
  if [ -z "$exp_line" ] || [ -z "$res_line" ] || [ "$exp_line" -ge "$res_line" ]; then
    fail "export SKIP_SHA_CHECK=0 必须位于 restore_with_verify 调用之前"
  fi
  ok "自动回滚强制强校验（export SKIP_SHA_CHECK=0 在恢复调用前，不受外部 skip 放宽）"
}

# ── ⑤ SQLite stop/start 包含 healthwatch ──────────────────────────
test_sqlite_healthwatch() {
  local branch stop_function
  # 提取 restore.sh 的 else（SQLite）分支：首个列首 else 到其后的列首 fi。
  branch="$(awk '/^else$/{a=1; print; next} a && /^fi$/{print; exit} a{print}' "$RESTORE")"
  [ -n "$branch" ] || fail "无法定位 restore.sh SQLite 分支（⑤）"
  stop_function="$(extract_function stop_restore_services "$RESTORE")"
  if ! printf '%s\n' "$branch" | grep -q 'stop_restore_services' || ! printf '%s\n' "$stop_function" | grep -q 'stop web scheduler healthwatch'; then
    fail "SQLite 分支恢复前未调用包含 healthwatch 的统一停写校验"
  fi
  if ! printf '%s\n' "$branch" | grep -q 'start web scheduler healthwatch'; then
    fail "SQLite 分支恢复后未启动 healthwatch"
  fi
  ok "SQLite 分支 stop/start 均包含 healthwatch"
}

# ── ⑥ 无时间戳文件不导致轮转失败且文件保留 ─────────────────────────
test_rotation_timestampless() {
  local dir keep_manual
  dir="$(mktemp -d)"
  for f in \
    agv-pm-20260101-000000.tar.gz.agvenc agv-pm-20260102-000000.tar.gz.agvenc \
    agv-pm-20260103-000000.tar.gz.agvenc agv-pm-20260104-000000.tar.gz.agvenc \
    agv-pm-manual-a.tar.gz.agvenc agv-pm-manual-b.tar.gz.agvenc agv-pm-manual-c.tar.gz.agvenc; do
    touch "$dir/$f" "$dir/$f.sha256"
  done
  touch "$dir/agv-pm-20000101-000000.tar.gz"
  keep_manual="$(find "$dir" -maxdepth 1 -name 'agv-pm-manual-*.tar.gz.agvenc' | wc -l | tr -d ' ')"
  [ "$keep_manual" -eq 3 ] || fail "前置条件：应创建 3 个无时间戳文件"
  # keep_daily=2：若把无时间戳文件计入保留名额，将挤掉真实日备并可能误删无时间戳文件。
  # 注意用 export（macOS bash 3.2 不保留对特殊内建 . 的前缀赋值）。
  if ! ( export BACKUP_KEEP_DAILY=2 BACKUP_KEEP_MONTHLY=12; . "$ROTATION"; rotate_backups "$dir" >/dev/null 2>&1 ); then
    fail "存在无时间戳文件时 rotate_backups 应正常完成（不中止）"
  fi
  [ "$(find "$dir" -maxdepth 1 -name 'agv-pm-manual-*.tar.gz.agvenc' | wc -l | tr -d ' ')" -eq "$keep_manual" ] \
    || fail "无时间戳文件被轮转误删"
  [ -f "$dir/agv-pm-20260103-000000.tar.gz.agvenc" ] && [ -f "$dir/agv-pm-20260104-000000.tar.gz.agvenc" ] \
    || fail "最新日备未保留（日轮转被无时间戳文件干扰）"
  [ ! -f "$dir/agv-pm-20260101-000000.tar.gz.agvenc" ] && [ ! -f "$dir/agv-pm-20260102-000000.tar.gz.agvenc" ] \
    || fail "超窗日备未按规则删除"
  [ -f "$dir/agv-pm-20000101-000000.tar.gz" ] || fail "历史明文备份不得自动删除"
  ok "无时间戳文件安全跳过（不中止、不误删），日/月轮转结果正确"
  rm -rf "$dir"
}

# ──────────────────────────────
echo "==> ① 缺校验默认拒绝"
test_missing_checksum_reject
echo "==> ② 缺校验 + SKIP_SHA_CHECK=1 放行（含告警）"
test_missing_checksum_skip_allows
echo "==> ③ 校验不匹配 + SKIP_SHA_CHECK=1 仍拒绝"
test_mismatch_skip_still_rejects
echo "==> ④ 自动回滚强制 SKIP_SHA_CHECK=0"
test_rollback_not_relaxed
echo "==> ⑤ SQLite 分支 stop/start 含 healthwatch"
test_sqlite_healthwatch
echo "==> ⑥ 无时间戳文件安全跳过（不中止、不误删）"
test_rotation_timestampless

# ──────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "HYPE-52 回归断言完成：PASS=$PASS FAIL=$FAIL"
echo "════════════════════════════════════════"
[ "$FAIL" -eq 0 ] || exit 1
