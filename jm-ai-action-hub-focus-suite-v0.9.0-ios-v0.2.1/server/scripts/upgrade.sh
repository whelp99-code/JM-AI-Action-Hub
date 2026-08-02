#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo '.venv가 없습니다. 먼저 ./scripts/bootstrap.sh를 실행하세요.' >&2
  exit 2
fi
./scripts/backup.sh >/dev/null
.venv/bin/pip install --upgrade -e '.[dev]'
.venv/bin/action-hub migrate
.venv/bin/action-hub check
printf 'UPGRADE_OK\n'
