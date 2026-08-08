#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
RUFF="${RUFF:-.venv/bin/ruff}"
"$RUFF" check .
PYTHONPATH=. "$PYTHON" -W error - <<'PY'
import warnings

from starlette.exceptions import StarletteDeprecationWarning

warnings.filterwarnings(
    "ignore",
    message=r"^Using `httpx` with `starlette\.testclient` is deprecated; install `httpx2` instead\.$",
    category=StarletteDeprecationWarning,
)

import pytest

raise SystemExit(
    pytest.main(["--cov=action_hub", "--cov-fail-under=80", "--cov-report=term-missing"])
)
PY
"$PYTHON" -W error -m compileall -q action_hub tests scripts
"$PYTHON" scripts/export_openapi.py --check
node --check action_hub/web/app.js
node --check action_hub/web/share-target.js
printf 'VERIFY_OK\n'
