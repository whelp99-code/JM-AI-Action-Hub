#!/usr/bin/env bash
set -uo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
MODE="${1:---local}"
TMP_ROOT="$(mktemp -d)"
SERVER_PID=""
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
CRITERIA_JSON="$TMP_ROOT/criteria.json"

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

fail() {
  echo "ACCEPTANCE_FAILED: $*" >&2
  return 1
}

record_criterion() {
  local number="$1" command="$2" evidence="$3"
  shift 3
  local output exit_code stdout_sha
  if output="$("$@" 2>&1)"; then
    exit_code=0
  else
    exit_code=$?
  fi
  printf '%s\n' "$output"
  if ! stdout_sha="$(printf '%s' "$output" | "${SHA256_BIN:-shasum}" -a 256 | awk '{print $1}')" || [[ ! "$stdout_sha" =~ ^[0-9a-f]{64}$ ]]; then
    echo "ACCEPTANCE_FAILED: stdout SHA-256 is unavailable or invalid" >&2
    python3 - "$CRITERIA_JSON" "$number" "$command" "$exit_code" "$evidence" <<'PY'
import json
import sys
from pathlib import Path

path, number, command, exit_code, evidence = sys.argv[1:]
criteria = json.loads(Path(path).read_text()) if Path(path).exists() else {}
criteria[number] = {
    "command": command,
    "exitCode": int(exit_code),
    "stdoutSha256": None,
    "evidence": f"{evidence}; stdout SHA-256 unavailable",
    "status": "FAIL",
}
Path(path).write_text(json.dumps(criteria, sort_keys=True), encoding="utf-8")
PY
    return 1
  fi
  python3 - "$CRITERIA_JSON" "$number" "$command" "$exit_code" "$stdout_sha" "$evidence" <<'PY'
import json
import sys
from pathlib import Path

path, number, command, exit_code, stdout_sha, evidence = sys.argv[1:]
criteria = json.loads(Path(path).read_text()) if Path(path).exists() else {}
criteria[number] = {
    "command": command,
    "exitCode": int(exit_code),
    "stdoutSha256": stdout_sha,
    "evidence": evidence,
    "status": "PASS" if exit_code == "0" else "FAIL",
}
Path(path).write_text(json.dumps(criteria, sort_keys=True), encoding="utf-8")
PY
  local receipt_rc=$?
  if [[ "$receipt_rc" -ne 0 ]]; then
    return "$receipt_rc"
  fi
  return "$exit_code"
}

start_server() {
  local api_key="$1"
  local webhook_secret="$2"
  local port="$3"
  local data_dir="$TMP_ROOT/data-$port"
  mkdir -p "$data_dir" || return $?
  ACTION_HUB_APP_ENV=development ACTION_HUB_API_KEY="$api_key" ACTION_HUB_MOBILE_ENABLED=false \
    ACTION_HUB_GITHUB_WEBHOOK_SECRET="$webhook_secret" ACTION_HUB_DATABASE_URL="sqlite+pysqlite:///$data_dir/action_hub.db" \
    ACTION_HUB_DATA_DIR="$data_dir" ACTION_HUB_EXECUTION_MODE=dry_run \
    "$ROOT/.venv/bin/uvicorn" action_hub.main:app --host 127.0.0.1 --port "$port" >"$TMP_ROOT/server-$port.log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 50); do
    if python3 - "$port" <<'PY'
import sys
from urllib.request import urlopen
try:
    urlopen(f"http://127.0.0.1:{sys.argv[1]}/health", timeout=0.2)
except Exception:
    raise SystemExit(1)
PY
    then return 0; fi
    sleep 0.1
  done
  fail "loopback server did not become ready"
}

stop_server() {
  cleanup
  SERVER_PID=""
}

security_check() {
  local port=18787
  start_server "" "" "$port" || return $?
  python3 - "$port" <<'PY'
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
port = sys.argv[1]
try:
    urlopen(Request(f"http://127.0.0.1:{port}/api/v1/connectors/status"), timeout=2)
    raise SystemExit("missing configured key did not fail")
except HTTPError as exc:
    if exc.code != 503: raise
PY
  local check_rc=$?
  if [[ "$check_rc" -ne 0 ]]; then
    stop_server
    return "$check_rc"
  fi
  stop_server

  local key="local-acceptance-api-key-0123456789abcdef"
  local secret="local-acceptance-webhook-secret"
  start_server "$key" "$secret" "$port" || return $?
  python3 - "$port" "$key" "$secret" "$TMP_ROOT/data-$port/action_hub.db" <<'PY'
import hashlib
import hmac
import json
import sqlite3
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

port, key, secret, database = sys.argv[1:]
base = f"http://127.0.0.1:{port}"
def request(path, body=None, headers=None):
    req = Request(base + path, data=body, headers=headers or {}, method="POST" if body is not None else "GET")
    return urlopen(req, timeout=3)
for headers, expected in (({}, 401), ({"X-Action-Hub-Key": "wrong"}, 401)):
    try:
        request("/api/v1/connectors/status", headers=headers)
        raise SystemExit("missing/wrong key did not fail")
    except HTTPError as exc:
        if exc.code != expected: raise
assert request("/api/v1/connectors/status", headers={"X-Action-Hub-Key": key}).status == 200
payload = json.dumps({"action": "opened", "issue": {"number": 1}, "repository": {"full_name": "owner/repo"}}, separators=(",", ":")).encode()
signature = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
headers = {"X-Hub-Signature-256": signature, "X-GitHub-Event": "issues", "X-GitHub-Delivery": "local-valid", "Content-Type": "application/json"}
assert request("/api/v1/webhooks/github", payload, headers).status == 202
with sqlite3.connect(database) as connection:
    valid_count = connection.execute("SELECT COUNT(*) FROM webhook_deliveries WHERE signature_valid = 1").fetchone()[0]
assert valid_count == 1
headers["X-GitHub-Delivery"] = "local-invalid"
headers["X-Hub-Signature-256"] = signature[:-1] + ("0" if signature[-1] != "0" else "1")
try:
    request("/api/v1/webhooks/github", payload, headers)
    raise SystemExit("invalid signature did not fail")
except HTTPError as exc:
    if exc.code != 401: raise
with sqlite3.connect(database) as connection:
    assert connection.execute("SELECT COUNT(*) FROM webhook_deliveries").fetchone()[0] == 1
PY
  check_rc=$?
  if [[ "$check_rc" -ne 0 ]]; then
    stop_server
    return "$check_rc"
  fi
  stop_server
  printf 'ACCEPTANCE_SECURITY_OK loopback=127.0.0.1\n'
}

smoke_check() {
  local port=18788
  local key="local-acceptance-api-key-0123456789abcdef"
  start_server "$key" "" "$port" || return $?
  python3 - "$port" "$key" "$TMP_ROOT/data-$port/action_hub.db" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

port, key, database = sys.argv[1:]
base = f"http://127.0.0.1:{port}"
headers = {"X-Action-Hub-Key": key, "Content-Type": "application/json"}
def post(path, payload):
    request = Request(base + path, data=json.dumps(payload).encode(), headers=headers, method="POST")
    return urlopen(request, timeout=3)
plan = json.loads(post("/api/v1/inbox/parse", {"text": "내일 오전 10시 합성 회의 준비", "timezone": "Asia/Seoul", "force_new": True}).read())
assert plan["items"]
assert urlopen(Request(base + "/api/v1/focus/matrix?limit_per_quadrant=1", headers={"X-Action-Hub-Key": key}), timeout=3).status == 200
item_id = plan["items"][0]["id"]
database = Path(database)
with sqlite3.connect(database) as connection:
    item_before = connection.execute(
        "SELECT state, attention_state, revision, reschedule_count, follow_up_at FROM action_items WHERE id = ?", (item_id,)
    ).fetchone()
    decision_before = connection.execute("SELECT COUNT(*) FROM carry_over_decisions WHERE action_item_id = ?", (item_id,)).fetchone()[0]
    audit_before = connection.execute("SELECT COUNT(*) FROM audit_events WHERE entity_id = ?", (item_id,)).fetchone()[0]
assert item_before is not None
try:
    post(f"/api/v1/focus/day-close", {"decisions": [{"action_item_id": item_id, "decision": "reschedule"}, {"action_item_id": "missing-local-item", "decision": "cancel"}]})
    raise SystemExit("atomic close-day did not reject missing item")
except HTTPError as exc:
    if exc.code != 404: raise
with sqlite3.connect(database) as connection:
    assert connection.execute(
        "SELECT state, attention_state, revision, reschedule_count, follow_up_at FROM action_items WHERE id = ?", (item_id,)
    ).fetchone() == item_before
    assert connection.execute("SELECT COUNT(*) FROM carry_over_decisions WHERE action_item_id = ?", (item_id,)).fetchone()[0] == decision_before
    assert connection.execute("SELECT COUNT(*) FROM audit_events WHERE entity_id = ?", (item_id,)).fetchone()[0] == audit_before
PY
  local check_rc=$?
  if [[ "$check_rc" -ne 0 ]]; then
    stop_server
    return "$check_rc"
  fi
  stop_server
  printf 'ACCEPTANCE_SMOKE_OK synthetic_capture=true bounded_matrix=true atomic_close_day=true\n'
}

archive_check() {
  local first="$TMP_ROOT/first.tar.gz"
  local second="$TMP_ROOT/second.tar.gz"
  SOURCE_RELEASE_OUTPUT="$first" make -C "$ROOT" source-release >/dev/null || return $?
  SOURCE_RELEASE_OUTPUT="$second" make -C "$ROOT" source-release >/dev/null || return $?
  local first_sha second_sha
  first_sha="$(shasum -a 256 "$first" | awk '{print $1}')" || return $?
  second_sha="$(shasum -a 256 "$second" | awk '{print $1}')" || return $?
  if [[ "$first_sha" != "$second_sha" ]]; then
    fail "source archive is not deterministic"
    return 1
  fi
  SOURCE_RELEASE_INPUT="$second" make -C "$ROOT" verify-source-release >/dev/null || return $?
  mkdir "$TMP_ROOT/extracted" || return $?
  tar -xzf "$second" -C "$TMP_ROOT/extracted" || return $?
  local extracted="$TMP_ROOT/extracted/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/server"
  python3 -m venv "$extracted/.venv" || return $?
  "$extracted/.venv/bin/pip" install -e "$extracted" >/dev/null || return $?
  ACTION_HUB_APP_ENV=development ACTION_HUB_MOBILE_ENABLED=false ACTION_HUB_DATA_DIR="$TMP_ROOT/install-data" \
    ACTION_HUB_DATABASE_URL="sqlite+pysqlite:///$TMP_ROOT/install-data/action_hub.db" "$extracted/.venv/bin/action-hub" migrate >/dev/null || return $?
  ACTION_HUB_APP_ENV=development ACTION_HUB_MOBILE_ENABLED=false ACTION_HUB_DATA_DIR="$TMP_ROOT/install-data" \
    ACTION_HUB_DATABASE_URL="sqlite+pysqlite:///$TMP_ROOT/install-data/action_hub.db" "$extracted/.venv/bin/action-hub" check >/dev/null || return $?
  printf 'ACCEPTANCE_ARCHIVE_OK sha256=%s\n' "$first_sha"
}

write_receipt() {
  local exit_code="$1"
  local timestamp receipt
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  receipt="${ACCEPTANCE_RECEIPT_PATH:-$REPO_ROOT/evidence/production-acceptance-$timestamp.json}"
  case "$receipt" in
    "$REPO_ROOT"/evidence/production-acceptance-*.json) ;;
    *) fail "receipt path must be under evidence/production-acceptance-*.json"; return 64 ;;
  esac
  python3 - "$receipt" "$CRITERIA_JSON" "$STARTED_AT" "$TMP_ROOT" "$exit_code" <<'PY'
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

receipt, criteria_path, started_at, temp_root, exit_code = sys.argv[1:]
root = Path(receipt).parents[1]
criteria = json.loads(Path(criteria_path).read_text(encoding="utf-8"))
external_status = "LOCAL_PASS_EXTERNAL_PENDING" if exit_code == "0" else "LOCAL_FAIL_EXTERNAL_PENDING"
Path(receipt).write_text(json.dumps({
    "schemaVersion": 1,
    "repoHead": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
    "planSha256": hashlib.sha256((root / "docs" / "IMPROVEMENT_PLAN_V1.md").read_bytes()).hexdigest(),
    "startedAt": started_at,
    "finishedAt": datetime.now(timezone.utc).isoformat(),
    "tempRoot": temp_root,
    "criteria": criteria,
    "externalStatus": external_status,
    "blockers": [{"code": "LIVE_ACCEPTANCE_PENDING", "message": "LIVE-ACCEPTANCE PENDING (사용자 인프라 필요)"}],
    "redactions": [{"field": "auth headers", "method": "not serialized"}, {"field": "capture text", "method": "synthetic and not serialized"}],
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(receipt)
PY
}

case "$MODE" in
  --security) security_check ;;
  --smoke) smoke_check ;;
  --local)
    overall_exit=0
    record_criterion 1 "make acceptance-security" "loopback auth and signed-webhook boundary" security_check || overall_exit=1
    record_criterion 2 "deterministic source archive install/check" "two-build SHA, verifier, isolated install/check" archive_check || overall_exit=1
    record_criterion 3 "make acceptance-smoke" "loopback synthetic capture, bounded matrix, 404 mixed close-day with item state and decision/audit counts unchanged" smoke_check || overall_exit=1
    record_criterion 4 "make rehearse-backup-restore" "isolated deterministic restore rehearsal" make -C "$ROOT" rehearse-backup-restore || overall_exit=1
    record_criterion 5 "make docs-check" "documentation validation and shell syntax" make -C "$ROOT" docs-check || overall_exit=1
    if ! receipt="$(write_receipt "$overall_exit")"; then
      echo "ACCEPTANCE_FAILED: unable to write receipt" >&2
      exit 1
    fi
    if [[ "$overall_exit" -eq 0 ]]; then
      printf 'LOCAL_ACCEPTANCE_OK receipt=%s externalStatus=LOCAL_PASS_EXTERNAL_PENDING\n' "$receipt"
    else
      printf 'LOCAL_ACCEPTANCE_FAILED receipt=%s externalStatus=LOCAL_FAIL_EXTERNAL_PENDING\n' "$receipt" >&2
    fi
    exit "$overall_exit"
    ;;
  *) echo "usage: $0 [--security|--smoke|--local]" >&2; exit 64 ;;
esac
