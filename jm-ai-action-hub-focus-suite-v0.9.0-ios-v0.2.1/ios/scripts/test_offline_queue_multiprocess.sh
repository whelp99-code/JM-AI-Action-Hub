#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE="$ROOT/Packages/ActionHubCore"
swift build --package-path "$PACKAGE" --product offline-capture-queue-probe >/dev/null
PROBE="$PACKAGE/.build/debug/offline-capture-queue-probe"
TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT

LEGACY_FILE="$TEMP_ROOT/captures/pending.json"
mkdir -p "$(dirname "$LEGACY_FILE")"

"$PROBE" enqueue --legacy-file "$LEGACY_FILE" --prefix alpha --count 50 &
first_enqueue=$!
"$PROBE" enqueue --legacy-file "$LEGACY_FILE" --prefix bravo --count 50 &
second_enqueue=$!
wait "$first_enqueue"
wait "$second_enqueue"

"$PROBE" apply-failed --legacy-file "$LEGACY_FILE" --prefix alpha --count 50 --rounds 5 &
first_failed=$!
"$PROBE" apply-failed --legacy-file "$LEGACY_FILE" --prefix bravo --count 50 --rounds 5 &
second_failed=$!
wait "$first_failed"
wait "$second_failed"

before_recovery="$("$PROBE" inventory --legacy-file "$LEGACY_FILE" --prefix all --count 100)"
[[ "$before_recovery" == *"pending=0 dlq=100 corrupt=0"* ]]

restore_output="$TEMP_ROOT/restore.out"
purge_output="$TEMP_ROOT/purge.out"
"$PROBE" restore --legacy-file "$LEGACY_FILE" --prefix all --count 100 >"$restore_output" &
restore_pid=$!
"$PROBE" purge --legacy-file "$LEGACY_FILE" --prefix all --count 100 >"$purge_output" &
purge_pid=$!
wait "$restore_pid"
wait "$purge_pid"
grep -qx 'PURGED count=50' "$purge_output"

inventory="$("$PROBE" inventory --legacy-file "$LEGACY_FILE" --prefix all --count 100)"
[[ "$inventory" == *"pending=50 dlq=0 corrupt=0"* ]]

COLLISION_FILE="$TEMP_ROOT/collision/captures/pending.json"
mkdir -p "$(dirname "$COLLISION_FILE")"
"$PROBE" enqueue --legacy-file "$COLLISION_FILE" --prefix collision --count 1
"$PROBE" apply-failed --legacy-file "$COLLISION_FILE" --prefix collision --count 1 --rounds 5
"$PROBE" enqueue --legacy-file "$COLLISION_FILE" --prefix collision --count 1
if "$PROBE" apply-failed --legacy-file "$COLLISION_FILE" --prefix collision --count 1 --rounds 5; then
  echo "expected pending-to-DLQ collision to fail" >&2
  exit 1
fi
collision_inventory="$("$PROBE" inventory --legacy-file "$COLLISION_FILE" --prefix collision --count 1)"
[[ "$collision_inventory" == "INVENTORY pending=1 dlq=1 corrupt=0 unique=1" ]]
echo "$collision_inventory"

LOCK_FILE="$TEMP_ROOT/contention/captures/pending.json"
mkdir -p "$(dirname "$LOCK_FILE")"
lock_output="$TEMP_ROOT/hold-lock.out"
"$PROBE" hold-lock --legacy-file "$LOCK_FILE" --prefix same --count 1 --milliseconds 2000 >"$lock_output" &
holder_pid=$!
for _ in $(seq 1 100); do
  if grep -qx 'LOCK_HELD' "$lock_output" 2>/dev/null; then break; fi
  sleep 0.05
done
grep -qx 'LOCK_HELD' "$lock_output"
started_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"
"$PROBE" enqueue --legacy-file "$LOCK_FILE" --prefix same --count 1
finished_ms="$(python3 -c 'import time; print(int(time.time() * 1000))')"
wait "$holder_pid"
lock_wait_ms=$((finished_ms - started_ms))
(( lock_wait_ms >= 1500 ))

contention_inventory="$("$PROBE" inventory --legacy-file "$LOCK_FILE" --prefix same --count 1)"
[[ "$contention_inventory" == *"pending=1 dlq=0 corrupt=0 unique=1"* ]]

echo "OFFLINE_QUEUE_MULTIPROCESS_OK pending=50 dlq=0 purged=50 corrupt=0 lock_wait_ms>=1500 same_record_unique=1"
