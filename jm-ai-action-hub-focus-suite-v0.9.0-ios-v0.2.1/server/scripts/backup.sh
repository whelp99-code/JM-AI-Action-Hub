#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
tar -czf "backups/action-hub-$STAMP.tar.gz" data .env 2>/dev/null || tar -czf "backups/action-hub-$STAMP.tar.gz" data
printf 'backups/action-hub-%s.tar.gz\n' "$STAMP"
