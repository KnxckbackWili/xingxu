#!/usr/bin/env bash
# 与 .gitea/workflows/ci.yml 等价：Python 3.12、SQLite + PG17 全量、真实行锁、前端、Compose。
# 用法：CI_PG_DATABASE_URL=postgresql+psycopg2://.../agv_ci bash scripts/ci.sh
# PostgreSQL 必须是可清空的专用测试库；pytest 与 pg_gate 都会重建其业务表。
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

: "${CI_PG_DATABASE_URL:?请显式设置可清空的专用 PostgreSQL 17 测试库 CI_PG_DATABASE_URL（库名须含 ci/test/pytest/gate 标记）}"
if [ -x backend/.venv/bin/python ]; then
  CI_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"
else
  CI_PYTHON="${PYTHON_BIN:-python3.12}"
fi
"$CI_PYTHON" - <<'PY'
import os
import re
import sys
from urllib.parse import unquote, urlparse
if sys.version_info[:2] != (3, 12):
    raise SystemExit('CI 必须使用 Python 3.12；请重新创建 backend/.venv 或设置 PYTHON_BIN')
url = urlparse(os.environ['CI_PG_DATABASE_URL'])
if url.scheme not in {'postgresql', 'postgresql+psycopg2'}:
    raise SystemExit('CI_PG_DATABASE_URL 必须指向 PostgreSQL 专用测试库')
name = unquote(url.path.lstrip('/'))
if not re.search(r'(?:^|_)(?:ci|test|tests|pytest|gate|gates)(?:_|$)', name, re.IGNORECASE):
    raise SystemExit('拒绝清空库名不含 ci/test/pytest/gate 标记的数据库')
PY

for tool in pg_dump pg_restore docker npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "缺少必要命令：${tool}" >&2
    exit 1
  fi
done
for tool in pg_dump pg_restore; do
  if ! "$tool" --version | "$CI_PYTHON" -c 'import re,sys; sys.exit(0 if re.search(r"PostgreSQL\) 17\.", sys.stdin.read()) else 1)'; then
    echo "CI 需要 PostgreSQL 17 的 ${tool}；请将对应 bin 目录加入 PATH" >&2
    exit 1
  fi
done
docker compose version >/dev/null

if [ ! -x backend/.venv/bin/python ]; then
  "$CI_PYTHON" -m venv backend/.venv
fi
CI_PYTHON="$PROJECT_ROOT/backend/.venv/bin/python"
"$CI_PYTHON" -m pip install -q --upgrade pip
"$CI_PYTHON" -m pip install -q -r backend/requirements-dev.txt
"$CI_PYTHON" - <<'PY'
import os
from sqlalchemy import create_engine, text
with create_engine(os.environ['CI_PG_DATABASE_URL']).connect() as connection:
    if int(connection.execute(text('SHOW server_version_num')).scalar()) // 10000 != 17:
        raise SystemExit('CI_PG_DATABASE_URL 对应服务器必须为 PostgreSQL 17')
PY

echo "==> [1/6] Python 3.12：SQLite 全量 pytest"
(cd backend && env -u DATABASE_URL "$CI_PYTHON" -m pytest -q)

echo "==> [2/6] Python 3.12：PostgreSQL 17 全量 pytest"
(cd backend && DATABASE_URL="$CI_PG_DATABASE_URL" "$CI_PYTHON" -m pytest -q)

echo "==> [3/6] PostgreSQL 真实行锁并发门禁"
(cd backend && DATABASE_URL="$CI_PG_DATABASE_URL" "$CI_PYTHON" scripts/pg_gate.py)

echo "==> [4/6] 前端依赖、类型检查与构建"
(cd frontend && npm ci --no-audit --no-fund && npm run build)

echo "==> [5/6] 前端 vitest"
(cd frontend && npm test)

echo "==> [6/6] Compose 配置校验"
docker compose -f docker/docker-compose.multica.yml config -q
docker compose -f docker/docker-compose.yml config -q

echo "==> CI 门禁全部通过"
