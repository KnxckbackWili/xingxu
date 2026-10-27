#!/bin/sh
# A2：supervisord 托管的 PostgreSQL 入口。
# USE_POSTGRES != 1 → 立即退出 0（expected），保持纯 SQLite 单容器模式兼容。
set -e

if [ "${USE_POSTGRES:-0}" != "1" ]; then
  echo "$(date -Is) USE_POSTGRES != 1，跳过容器内 PostgreSQL（SQLite 模式）" >> /tmp/pg-entry.log
  exit 0
fi

PG_VERSION="$(ls /usr/lib/postgresql | head -1)"
PGDATA="${PGDATA:-/app/data/pgdata}"

exec "/usr/lib/postgresql/$PG_VERSION/bin/postgres" \
  -D "$PGDATA" \
  -c listen_addresses=127.0.0.1 \
  -c port=5432 \
  -c unix_socket_directories=/tmp
