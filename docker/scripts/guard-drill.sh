#!/usr/bin/env bash
# guard-drill.sh — 演练隔离守卫（fail-closed）
#
# 背景：HYPE-19 恢复演练曾以 compose override 叠加到生产 compose（项目名 docker），
# 把生产容器 agv-pm-8002 重建为演练容器、端口与卷错配。本守卫在演练启动前校验
# 演练将使用的 container / volume / port / compose project 均与生产标识隔离；
# 任一命中生产标识即非零退出（FAIL-CLOSED），绝不触碰生产资源。
#
# 生产标识（与 docker/docker-compose.multica.yml 及容器运行时命名一致）：
#   container : agv-pm-8002
#   volume    : agv-pm-multica-data（compose 声明名；运行时 docker_agv-pm-multica-data）
#   port      : 8002（宿主机端口）
#   project   : docker（compose 默认项目名推导）/ agv-pm（仓库名）
#
# 用法：bash guard-drill.sh   （返回 0 且打印 export 行 = 隔离安全；非 0 = FAIL-CLOSED）
set -u

# 演练标识（默认即隔离值；可用环境变量显式覆盖，但覆盖值同样必须通过下面的校验）
AGV_DRILL_CONTAINER="${AGV_DRILL_CONTAINER:-agv-pm-drill}"
AGV_DRILL_VOLUME="${AGV_DRILL_VOLUME:-agvpm-drill-data}"
AGV_DRILL_PORT="${AGV_DRILL_PORT:-8003}"
AGV_DRILL_PROJECT="${AGV_DRILL_PROJECT:-agvpm-drill}"
AGV_DRILL_COMPOSE="${AGV_DRILL_COMPOSE:-$(cd "$(dirname "$0")/.." && pwd)/docker-compose.drill.yml}"

fail() {
  echo "FAIL-CLOSED: $*" >&2
  exit 1
}

# 1) container / volume：生产名作为子串即拒绝（覆盖运行时前缀/后缀变体）
for item in "container:$AGV_DRILL_CONTAINER:agv-pm-8002" "volume:$AGV_DRILL_VOLUME:agv-pm-multica-data"; do
  label="${item%%:*}"; rest="${item#*:}"; value="${rest%%:*}"; banned="${rest#*:}"
  [ -n "$value" ] || fail "$label 为空：演练标识缺失，拒绝继续"
  case "$value" in
    *"$banned"*) fail "$label 命中生产标识：'$value' 含 '$banned'" ;;
  esac
done

# 2) port：必须为纯数字；出现 8002（含 8002-8005 区间写法）即拒绝
[ -n "$AGV_DRILL_PORT" ] || fail "port 为空，拒绝继续"
echo "$AGV_DRILL_PORT" | grep -qE '^[0-9]{1,5}$' || fail "port 非纯数字端口：'$AGV_DRILL_PORT'"
case "$AGV_DRILL_PORT" in
  *8002*) fail "port 命中生产端口：'$AGV_DRILL_PORT' 含 8002" ;;
esac

# 3) compose project：显式项目名不得是 docker / agv-pm（默认推导即生产项目名）
[ -n "$AGV_DRILL_PROJECT" ] || fail "compose project 为空，拒绝继续"
case "$AGV_DRILL_PROJECT" in
  docker|agv-pm) fail "compose project 命中生产项目名：'$AGV_DRILL_PROJECT'" ;;
esac

# 4) 演练 compose 文件本身不得引用任何生产标识（防止后续改动把生产卷/容器/端口抄进来）
[ -f "$AGV_DRILL_COMPOSE" ] || fail "演练 compose 文件不存在：$AGV_DRILL_COMPOSE"
for token in "agv-pm-8002" "agv-pm-multica-data" "8002:8000" "0.0.0.0:8002"; do
  if grep -qF "$token" "$AGV_DRILL_COMPOSE"; then
    fail "演练 compose 引用生产标识：'$token' 出现在 $AGV_DRILL_COMPOSE"
  fi
done

# 全部通过：打印解析后的隔离值（供 drill.sh source 使用）
cat <<EOF
export AGV_DRILL_CONTAINER='$AGV_DRILL_CONTAINER'
export AGV_DRILL_VOLUME='$AGV_DRILL_VOLUME'
export AGV_DRILL_PORT='$AGV_DRILL_PORT'
export AGV_DRILL_PROJECT='$AGV_DRILL_PROJECT'
export AGV_DRILL_COMPOSE='$AGV_DRILL_COMPOSE'
EOF
echo "guard OK：演练标识与生产隔离" >&2
