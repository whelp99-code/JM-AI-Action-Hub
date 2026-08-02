#!/usr/bin/env bash
set -euo pipefail
BASE_URL="${ACTION_HUB_URL:-http://127.0.0.1:8787}"
KEY="${ACTION_HUB_API_KEY:-change-me}"
HEADERS=(-H "Content-Type: application/json" -H "X-Action-Hub-Key: $KEY")
PLAN=$(curl -fsS "${HEADERS[@]}" -X POST "$BASE_URL/api/v1/inbox/parse" -d '{
  "text":"내일 오전 10시 고객 미팅\n금요일까지 제안서 작성\nrepo:whelp99-code/Proof-Graph 로그인 버그 수정",
  "source":"curl",
  "timezone":"Asia/Seoul"
}')
echo "$PLAN"
PLAN_ID=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$PLAN")
curl -fsS "${HEADERS[@]}" -X POST "$BASE_URL/api/v1/plans/$PLAN_ID/approve" -d '{"actor":"curl"}'
curl -fsS "${HEADERS[@]}" -X POST "$BASE_URL/api/v1/plans/$PLAN_ID/execute" -d '{"actor":"curl"}'
