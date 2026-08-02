#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[dev]'
if [ ! -f .env ]; then
  cp .env.example .env
  KEY="$(.venv/bin/python scripts/generate_api_key.py)"
  MOBILE_SECRET="$(.venv/bin/python scripts/generate_api_key.py)"
  .venv/bin/python - "$KEY" "$MOBILE_SECRET" <<'PYKEY'
from pathlib import Path
import sys

path = Path('.env')
key = sys.argv[1]
mobile_secret = sys.argv[2]
lines = path.read_text().splitlines()
updated = []
for line in lines:
    if line.startswith('ACTION_HUB_API_KEY='):
        updated.append(f'ACTION_HUB_API_KEY={key}')
    elif line.startswith('ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET='):
        updated.append(f'ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET={mobile_secret}')
    else:
        updated.append(line)
path.write_text('\n'.join(updated) + '\n')
PYKEY
fi
mkdir -p data/exports backups
printf '\n설치 완료. ./scripts/run.sh 실행 후 API 키는 관리자용으로만 보관하고, iOS 앱은 QR 페어링을 사용하세요.\n'
