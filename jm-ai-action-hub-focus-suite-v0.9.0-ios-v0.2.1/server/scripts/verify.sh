#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
PYTEST="${PYTEST:-.venv/bin/pytest}"
RUFF="${RUFF:-.venv/bin/ruff}"
"$RUFF" check .
PYTHONPATH=. "$PYTEST" -W error --cov=action_hub --cov-fail-under=80 --cov-report=term-missing
"$PYTHON" -W error -m compileall -q action_hub tests scripts
"$PYTHON" scripts/export_openapi.py --check
node --check action_hub/web/app.js
node --check action_hub/web/share-target.js
printf 'VERIFY_OK\n'
