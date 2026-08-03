#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  echo "usage: $0 --archive <absolute-tar.gz> --target-data <absolute-dir>" >&2
  exit 64
}

is_normal_absolute_path() {
  local path="$1"
  [[ "$path" == /* && "$path" != / && "$path" != */ && "$path" != *'//' && "$path" != */./* && "$path" != */../* && "$path" != */. && "$path" != */.. ]]
}

has_only_trusted_symlink_ancestors() {
  python3 - "$1" <<'PY'
import os
import stat
import sys

path = sys.argv[1]

def caller_can_write(path: str, metadata: os.stat_result) -> bool:
    """Avoid treating root's blanket write access as caller control."""
    mode = metadata.st_mode
    if metadata.st_uid == os.geteuid() and mode & stat.S_IWUSR:
        return True
    if metadata.st_gid in os.getgroups() and mode & stat.S_IWGRP:
        return True
    return bool(mode & stat.S_IWOTH)

current = os.sep
for component in path.split(os.sep)[1:]:
    current = os.path.join(current, component)
    try:
        entry = os.lstat(current)
    except FileNotFoundError:
        break
    if stat.S_ISLNK(entry.st_mode):
        parent = os.path.dirname(current) or os.sep
        parent_stat = os.stat(parent)
        # /var -> /private/var on macOS is root-owned and its root parent is
        # not caller-writable, so it remains a permitted system alias.
        if entry.st_uid != 0 or parent_stat.st_uid != 0 or caller_can_write(parent, parent_stat):
            raise SystemExit(1)
PY
}

is_safe_target_path() {
  local path="$1"
  is_normal_absolute_path "$path" && has_only_trusted_symlink_ancestors "$path" && [[ ! -L "$path" ]] && { [[ ! -e "$path" ]] || [[ -d "$path" ]]; } && [[ -d "$(dirname "$path")" && ! -L "$(dirname "$path")" ]]
}

if [[ "$#" -ne 4 || "$1" != "--archive" || "$3" != "--target-data" ]]; then
  usage
fi

archive="$2"
target="$4"
if ! is_normal_absolute_path "$archive" || ! has_only_trusted_symlink_ancestors "$archive" || [[ ! -f "$archive" || -L "$archive" ]] || ! is_safe_target_path "$target"; then
  usage
fi
if [[ ! -x "$ROOT/.venv/bin/action-hub" ]]; then
  echo "action-hub executable is unavailable" >&2
  exit 1
fi

target_parent="$(dirname "$target")"
target_name="$(basename "$target")"
stage="$(mktemp -d "$target_parent/.${target_name}.restore-stage.XXXXXX")"

archive_root="$({
  python3 - "$archive" "$stage" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

archive_path, stage = sys.argv[1:]

def reject(message: str) -> None:
    print(f"restore archive rejected: {message}", file=sys.stderr)
    raise SystemExit(64)

with tarfile.open(archive_path, mode="r:gz") as archive:
    members = archive.getmembers()
    seen: set[str] = set()
    root_name: str | None = None
    root_count = 0
    for member in members:
        name = member.name
        if not name or name.startswith("/") or "\\" in name:
            reject(f"non-normal member {name!r}")
        parts = name.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            reject(f"non-normal member {name!r}")
        normalized = PurePosixPath(*parts).as_posix()
        if normalized != name or normalized in seen:
            reject(f"duplicate or non-normal member {name!r}")
        seen.add(normalized)
        if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
            reject(f"non-regular member {name!r}")
        top = parts[0]
        if root_name is None:
            root_name = top
        if top != root_name:
            reject(f"unexpected root entry {name!r}")
        if len(parts) == 1:
            if not member.isdir():
                reject(f"root must be a directory {name!r}")
            root_count += 1
    if root_name is None or root_count != 1:
        reject("archive must contain exactly one root directory")
    for member in members:
        archive.extract(member, stage)
print(root_name)
PY
} )"

restored_root="$stage/$archive_root"
if [[ ! -d "$restored_root" || -L "$restored_root" ]]; then
  echo "restore archive rejected: extracted root is invalid" >&2
  exit 64
fi

snapshot="$(mktemp -d "$target_parent/.${target_name}.pre-restore.XXXXXX")"
had_target=false
if [[ -e "$target" ]]; then
  mv "$target" "$snapshot/$target_name"
  had_target=true
fi
if ! mv "$restored_root" "$target"; then
  if [[ "$had_target" == true ]]; then
    mv "$snapshot/$target_name" "$target"
  fi
  echo "restore failed before target replacement" >&2
  exit 1
fi

if ! ACTION_HUB_APP_ENV=development ACTION_HUB_MOBILE_ENABLED=false \
  ACTION_HUB_DATABASE_URL="sqlite+pysqlite:///$target/action_hub.db" \
  ACTION_HUB_DATA_DIR="$target" ACTION_HUB_RUN_MIGRATIONS=false \
  "$ROOT/.venv/bin/action-hub" check; then
  mv "$target" "$snapshot/failed-restored"
  if [[ "$had_target" == true ]]; then
    mv "$snapshot/$target_name" "$target"
  fi
  echo "restore check failed; target recovered from snapshot" >&2
  exit 1
fi

printf 'RESTORE_OK target=%s snapshot=%s\n' "$target" "$snapshot"
