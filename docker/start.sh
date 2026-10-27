#!/bin/sh
set -e

# Fail before starting PostgreSQL, scheduler or web with unsafe public settings.
python -m app.services.public_security

# 单容器架构（A1/A2）：USE_POSTGRES=1 时初始化并启用容器内 PostgreSQL，
# 随后由 supervisord 托管 postgres / web / scheduler。
# SQLite 模式（USE_POSTGRES 未设）保持原行为，仅托管其余三个进程。

echo "[start] AGV 项目管理系统 v${APP_VERSION:-unknown} (build ${GIT_SHA:-unknown}, $(date -Is))"

if [ "${USE_POSTGRES:-0}" = "1" ]; then
  PGDATA="${PGDATA:-/app/data/pgdata}"
  PG_BIN="/usr/lib/postgresql/$(ls /usr/lib/postgresql | head -1)/bin"
  export PGDATA

  if [ ! -f "$PGDATA/PG_VERSION" ]; then
    echo "[start] 初始化 PostgreSQL 数据目录：$PGDATA"
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    su postgres -c "$PG_BIN/initdb -D '$PGDATA' -U postgres --auth-local=trust --auth-host=trust -E UTF8 --no-locale"
  fi

  echo "[start] 启动 PostgreSQL 做初始化检查（角色/库幂等创建）..."
  su postgres -c "$PG_BIN/pg_ctl -D '$PGDATA' -o '-c listen_addresses=127.0.0.1 -c port=5432 -c unix_socket_directories=/tmp' -l /tmp/pg-init.log start"

  cleanup_pg() {
    su postgres -c "$PG_BIN/pg_ctl -D '$PGDATA' stop -m fast" >/dev/null 2>&1 || true
  }
  trap cleanup_pg EXIT

  if ! su postgres -c "$PG_BIN/psql -h /tmp -U postgres -tAc \"SELECT 1 FROM pg_roles WHERE rolname='agv'\"" | grep -q 1; then
    su postgres -c "$PG_BIN/psql -h /tmp -U postgres -c \"CREATE ROLE agv LOGIN PASSWORD 'agv'\""
  fi
  if ! su postgres -c "$PG_BIN/psql -h /tmp -U postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='agvpm'\"" | grep -q 1; then
    su postgres -c "$PG_BIN/psql -h /tmp -U postgres -c \"CREATE DATABASE agvpm OWNER agv\""
  fi

  cleanup_pg
  trap - EXIT

  export DATABASE_URL="postgresql+psycopg2://agv:agv@127.0.0.1:5432/agvpm"
  # 日志脱敏（P0-安全）：启动日志只显示 scheme/host/db，口令统一回显为 ***。
  _masked_db_url=$(printf '%s' "$DATABASE_URL" | sed -E 's#://([^:/]+):[^@]*@#://\1:***@#')
  echo "[start] 已启用容器内 PostgreSQL → $_masked_db_url"
fi

exec supervisord -c /app/supervisord.conf
