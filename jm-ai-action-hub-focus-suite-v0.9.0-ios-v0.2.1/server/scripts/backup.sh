#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

usage() {
  echo "usage: $0 [--source-data <absolute-dir> --output <absolute-tar.gz>]" >&2
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

is_safe_source_directory() {
  is_normal_absolute_path "$1" && has_only_trusted_symlink_ancestors "$1" && [[ -d "$1" && ! -L "$1" ]]
}

is_safe_output_path() {
  is_normal_absolute_path "$1" && has_only_trusted_symlink_ancestors "$1" && [[ ! -e "$1" && ! -L "$1" ]] && [[ -d "$(dirname "$1")" && ! -L "$(dirname "$1")" ]]
}

legacy_backup=false
if [[ "$#" -eq 0 ]]; then
  source_data="$ROOT/data"
  mkdir -p "$ROOT/backups"
  output=""
  legacy_backup=true
elif [[ "$#" -eq 4 && "$1" == "--source-data" && "$3" == "--output" ]]; then
  source_data="$2"
  output="$4"
else
  usage
fi

if ! is_safe_source_directory "$source_data"; then
  usage
fi
if [[ "$legacy_backup" == false ]] && ! is_safe_output_path "$output"; then
  usage
fi

source_parent="$(dirname "$source_data")"
source_name="$(basename "$source_data")"
if [[ "$legacy_backup" == true ]]; then
  output_parent="$ROOT/backups"
  output_name="action-hub-$(date +%Y%m%d-%H%M%S).tar.gz"
else
  output_parent="$(dirname "$output")"
  output_name="$(basename "$output")"
fi
stage="$(mktemp "$output_parent/.${output_name}.backup-stage.XXXXXX")"
cleanup_stage() {
  [[ -z "${stage:-}" ]] || rm -f -- "$stage"
}
trap cleanup_stage EXIT

COPYFILE_DISABLE=1 tar --create --gzip --file "$stage" --directory "$source_parent" \
  --exclude="$source_name/.env" --exclude="$source_name/.env.*" \
  --exclude="*/.env" --exclude="*/.env.*" "$source_name"

if [[ "$legacy_backup" == true ]]; then
  stamp="${output_name#action-hub-}"
  stamp="${stamp%.tar.gz}"
  for attempt in $(seq 0 99); do
    suffix=""
    [[ "$attempt" -eq 0 ]] || suffix="-$attempt"
    candidate="$output_parent/action-hub-$stamp$suffix.tar.gz"
    if ln "$stage" "$candidate" 2>/dev/null; then
      output="$candidate"
      break
    fi
  done
  if [[ -z "$output" ]]; then
    echo "backup output collision limit reached" >&2
    exit 1
  fi
elif ! ln "$stage" "$output" 2>/dev/null; then
  usage
fi
printf '%s\n' "$output"
