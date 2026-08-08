#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REHEARSAL_TMP="$(mktemp -d)"
data_dir="$REHEARSAL_TMP/data"
archive="$REHEARSAL_TMP/backup.tar.gz"
database="$data_dir/action_hub.db"
database_url="sqlite+pysqlite:///$database"
receipt="$ROOT/../evidence/backup-restore-rehearsal.json"

manifest_sha() {
  python3 - "$1" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

directory = Path(sys.argv[1])
manifest = {
    path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(directory.rglob("*"))
    if path.is_file()
}
print(hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
PY
}

mkdir -p "$data_dir"
ACTION_HUB_APP_ENV=development ACTION_HUB_MOBILE_ENABLED=false \
  ACTION_HUB_DATABASE_URL="$database_url" ACTION_HUB_DATA_DIR="$data_dir" \
  "$ROOT/.venv/bin/action-hub" migrate
migrate_exit=$?
if [[ "$migrate_exit" -ne 0 ]]; then
  exit "$migrate_exit"
fi
python3 - "$database" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute("CREATE TABLE rehearsal_marker (value TEXT NOT NULL)")
    connection.execute("INSERT INTO rehearsal_marker (value) VALUES ('restored')")
PY
pre_backup_manifest_sha="$(manifest_sha "$data_dir")"
"$ROOT/scripts/backup.sh" --source-data "$data_dir" --output "$archive" >/dev/null
backup_exit=$?
if [[ "$backup_exit" -ne 0 ]]; then
  exit "$backup_exit"
fi
python3 - "$database" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute("UPDATE rehearsal_marker SET value = 'mutated'")
PY
"$ROOT/scripts/restore.sh" --archive "$archive" --target-data "$data_dir" >/dev/null
restore_exit=$?
if [[ "$restore_exit" -ne 0 ]]; then
  exit "$restore_exit"
fi
post_restore_manifest_sha="$(manifest_sha "$data_dir")"

read -r marker schema < <(python3 - "$database" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    marker = connection.execute("SELECT value FROM rehearsal_marker").fetchone()[0]
    schema = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
print(marker, schema)
PY
)
if [[ "$marker" != restored || "$schema" != 0005_decision_focus_foundation ]]; then
  echo "rehearsal verification failed" >&2
  exit 1
fi
if [[ "$pre_backup_manifest_sha" != "$post_restore_manifest_sha" ]]; then
  echo "rehearsal manifest verification failed" >&2
  exit 1
fi
archive_sha="$(shasum -a 256 "$archive" | awk '{print $1}')"
python3 - "$receipt" "$REHEARSAL_TMP" "$archive_sha" "$migrate_exit" "$backup_exit" "$restore_exit" "$pre_backup_manifest_sha" "$post_restore_manifest_sha" <<'PY'
import json
import sys
from pathlib import Path

(
    receipt,
    temp_path,
    archive_sha,
    migrate_exit,
    backup_exit,
    restore_exit,
    pre_backup_manifest_sha,
    post_restore_manifest_sha,
) = sys.argv[1:]
Path(receipt).write_text(
    json.dumps(
        {
            "schemaVersion": 1,
            "tempPath": temp_path,
            "archiveSha256": archive_sha,
            "marker": "restored",
            "schema": "0005_decision_focus_foundation",
            "commandContracts": [
                {"name": "migrate", "command": "action-hub migrate (temporary SQLite)", "exitCode": int(migrate_exit)},
                {"name": "backup", "command": "backup.sh --source-data <temp>/data --output <temp>/backup.tar.gz", "exitCode": int(backup_exit)},
                {"name": "restore", "command": "restore.sh --archive <temp>/backup.tar.gz --target-data <temp>/data", "exitCode": int(restore_exit)},
            ],
            "preBackupManifestSha256": pre_backup_manifest_sha,
            "postRestoreManifestSha256": post_restore_manifest_sha,
            "manifestsEqual": pre_backup_manifest_sha == post_restore_manifest_sha,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
printf 'BACKUP_RESTORE_OK marker=restored schema=0005_decision_focus_foundation temp=%s\n' "$REHEARSAL_TMP"
