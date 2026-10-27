#!/usr/bin/env bash
# 真正执行 restore.sh，使用本测试创建的 Docker 替身，不接触任何容器/数据库。
# 依赖 Python 3.12+；PYTHON 可指定解释器。输出目录必须全新，证据不会被覆盖。
# 用法：PYTHON=backend/.venv/bin/python bash docker/scripts/test-restore-maintenance.sh [全新输出目录]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON:-python3}" "$SCRIPT_DIR/test-restore-maintenance.py" "$@"
