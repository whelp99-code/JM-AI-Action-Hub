#!/usr/bin/env bash
set -euo pipefail
if [ "$#" -ne 1 ]; then echo "usage: $0 backups/action-hub-YYYYmmdd-HHMMSS.tar.gz" >&2; exit 2; fi
cd "$(dirname "$0")/.."
mkdir -p data
cp -a data "data.pre-restore.$(date +%s)" 2>/dev/null || true
tar -xzf "$1"
echo "복구 완료"
