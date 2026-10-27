#!/usr/bin/env bash
# drill.sh — 隔离恢复演练入口（HYPE-19 加固）
#
# 背景：演练曾以 compose override 叠加生产 compose，导致生产容器 agv-pm-8002 被重建、
# 端口与卷错配。本脚本强制：独立 compose project / container / volume / port，
# 启动前由 guard-drill.sh 做 fail-closed 校验；命中任何生产标识立即终止，
# 全程不触碰生产资源。
#
# 用法：
#   bash docker/scripts/drill.sh                 # 用最新备份演练
#   bash docker/scripts/drill.sh backups/xxx.tar.gz   # 指定备份
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GUARD="$REPO_ROOT/docker/scripts/guard-drill.sh"
BACKUP="${1:-}"

# 0) 先决条件：守卫脚本必须存在（防止"守卫文件缺失"被误判为守卫放行）
if [ ! -f "$GUARD" ]; then
  echo "守卫脚本缺失：$GUARD（仓库结构异常，拒绝继续）" >&2
  exit 1
fi

# 1) fail-closed 守卫：命中任何生产标识即终止（此处先于任何 docker 操作）
guard_env="$(mktemp)"
trap 'rm -f "$guard_env"' EXIT
if ! bash "$GUARD" >"$guard_env" 2>"$guard_env.guard.log"; then
  cat "$guard_env.guard.log" >&2
  rm -f "$guard_env.guard.log"
  echo "演练终止：守卫 FAIL-CLOSED，未执行任何容器/卷操作" >&2
  exit 1
fi
rm -f "$guard_env.guard.log"
. "$guard_env"

# 2) 备份包：未指定则取最近一份
if [ -z "$BACKUP" ]; then
  BACKUP="$(ls -t "$REPO_ROOT"/backups/agv-pm-*.tar.gz.agvenc "$REPO_ROOT"/backups/agv-pm-*.tar.gz 2>/dev/null | head -1 || true)"
fi
if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then
  echo "未找到备份包；请指定：$0 <backup.tar.gz>" >&2
  exit 1
fi

# 3) 启动前确认生产容器仍在（仅作环境提示，不做任何改动）
if docker inspect agv-pm-8002 >/dev/null 2>&1; then
  echo "==> 检测到生产容器 agv-pm-8002 运行中（本脚本不会触碰它）"
else
  echo "==> 未检测到生产容器 agv-pm-8002（可能尚未部署或已停止）"
fi

echo "==> 构建并启动隔离演练：project=$AGV_DRILL_PROJECT container=$AGV_DRILL_CONTAINER port=$AGV_DRILL_PORT volume=$AGV_DRILL_VOLUME"
docker compose \
  --project-name "$AGV_DRILL_PROJECT" \
  -f "$AGV_DRILL_COMPOSE" \
  --env-file "$REPO_ROOT/docker/.env" \
  up -d --build

# 4) 等待演练容器健康
echo "==> 等待演练容器健康（最多 120s）"
health="none"
for _ in $(seq 1 24); do
  health="$(docker inspect -f '{{.State.Health.Status}}' "$AGV_DRILL_CONTAINER" 2>/dev/null || echo none)"
  [ "$health" = "unhealthy" ] && { echo "演练容器 unhealthy" >&2; docker logs --tail 40 "$AGV_DRILL_CONTAINER" >&2 || true; exit 1; }
  [ "$health" = "healthy" ] && break
  sleep 5
done
if [ "$health" != "healthy" ]; then
  echo "演练容器超时未健康（当前: $health）" >&2
  docker logs --tail 40 "$AGV_DRILL_CONTAINER" >&2 || true
  exit 1
fi

# 5) 把备份恢复到演练容器（restore.sh 通过 AGV_CONTAINER 指向演练容器，操作全在容器内）
echo "==> 恢复备份到演练容器：$BACKUP"
AGV_CONTAINER="$AGV_DRILL_CONTAINER" bash "$REPO_ROOT/docker/scripts/restore.sh" "$BACKUP"

# 6) 恢复后复验：宿主回环端口 /health 必须 200
echo "==> 恢复后复验 /health"
code="000"
for _ in $(seq 1 12); do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$AGV_DRILL_PORT/health" || echo 000)"
  [ "$code" = "200" ] && break
  sleep 5
done
if [ "$code" != "200" ]; then
  echo "演练 /health 复验失败（HTTP $code）" >&2
  exit 1
fi

cat <<EOF
==> 隔离演练完成
  容器: ${AGV_DRILL_CONTAINER}（宿主回环端口 127.0.0.1:${AGV_DRILL_PORT}）
  卷:   ${AGV_DRILL_VOLUME}
  项目: ${AGV_DRILL_PROJECT}
  备份: ${BACKUP}
生产资源（agv-pm-8002 容器 / 生产数据卷 / 宿主 8002 端口）未被触碰。
清理演练：docker compose --project-name ${AGV_DRILL_PROJECT} -f ${AGV_DRILL_COMPOSE} down -v
EOF
