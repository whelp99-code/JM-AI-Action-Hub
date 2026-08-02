#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${ACTION_HUB_URL:-http://127.0.0.1:8787}"
HEADER=()
if [ -n "${ACTION_HUB_API_KEY:-}" ]; then HEADER=(-H "X-Action-Hub-Key: ${ACTION_HUB_API_KEY}"); fi
curl -fsS "$BASE_URL/health" | grep -q '"status":"ok"'
PLAN=$(curl -fsS "${HEADER[@]}" -H 'Content-Type: application/json' -d '{"text":"내일 오전 10시 테스트 미팅","source":"smoke","timezone":"Asia/Seoul"}' "$BASE_URL/api/v1/inbox/parse")
printf '%s\n' "$PLAN" | grep -q '"items"'
printf 'SMOKE_OK\n'
