#!/usr/bin/env bash
# Verify that a release is internally consistent and buildable.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

VERSION="$(node -p "require('./frontend/package.json').version")"
expect() {
  local file="$1" pattern="$2"
  grep -Fq "$pattern" "$file" || {
    echo "Version mismatch: expected '$pattern' in $file" >&2
    exit 1
  }
}

case "$VERSION" in
  ""|*latest*|*edge*|*main*) echo "Invalid release version: $VERSION" >&2; exit 1 ;;
esac

expect frontend/package-lock.json "\"version\": \"$VERSION\""
expect frontend/src/pages/LoginPage.tsx "行序 · 项目工作台 · {APP_VERSION}"
expect backend/app/config.py "APP_VERSION = os.getenv(\"APP_VERSION\", \"$VERSION\")"
expect docker/Dockerfile "ARG APP_VERSION=$VERSION"
expect docker/docker-compose.yml "APP_VERSION: \${APP_VERSION:-$VERSION}"
expect docker/docker-compose.yml "image: \${AGV_IMAGE:-agv-pm:$VERSION}"
expect .env.example "APP_VERSION=$VERSION"
expect .env.example "AGV_IMAGE=agv-pm:$VERSION"

git diff --check
bash -n docker/scripts/*.sh
docker compose --env-file .env.example -f docker/docker-compose.yml config --quiet

if [ "${FAST:-0}" != "1" ]; then
  (cd frontend && npm run build)
  grep -Fq 'agvpm-pages' frontend/dist/sw.js || {
    echo "Service worker must use the network-first navigation cache." >&2
    exit 1
  }
  if grep -Fq 'NavigationRoute' frontend/dist/sw.js; then
    echo "Service worker must not restore cache-first SPA navigation." >&2
    exit 1
  fi
  if [ "${SKIP_AUDIT:-0}" != "1" ]; then
    (cd frontend && npm audit --audit-level=high --registry=https://registry.npmjs.org)
  fi
  if [ -n "${AGV_TEST_PYTHON:-}" ]; then
    PYTHON="$AGV_TEST_PYTHON"
  elif [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/.venv/bin/python"
  elif [ -x "$PROJECT_DIR/backend/.venv/bin/python" ]; then
    PYTHON="$PROJECT_DIR/backend/.venv/bin/python"
  elif python3 -m pytest --version >/dev/null 2>&1; then
    PYTHON=python3
  else
    echo "pytest is unavailable. Run: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt" >&2
    exit 1
  fi
  "$PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
  (cd backend && "$PYTHON" -m pytest -q)
fi

echo "Release checks passed for v$VERSION"
