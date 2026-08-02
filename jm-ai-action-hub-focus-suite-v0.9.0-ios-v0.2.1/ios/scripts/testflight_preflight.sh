#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: TestFlight preflight requires macOS and Xcode." >&2
  exit 2
fi

command -v xcodebuild >/dev/null
command -v xcrun >/dev/null

if [[ ! -f Config/Local.xcconfig ]]; then
  echo "ERROR: Copy Config/Local.xcconfig.example to Config/Local.xcconfig and set your Team/Bundle/App Group." >&2
  exit 3
fi

if grep -q 'YOUR_TEAM_ID' Config/Local.xcconfig; then
  echo "ERROR: DEVELOPMENT_TEAM is not configured." >&2
  exit 4
fi

python3 scripts/generate_xcodeproj.py --check
python3 scripts/verify_openapi_contract.py
python3 scripts/validate_ios_project.py
swift test --package-path Packages/ActionHubCore
xcodebuild \
  -project JM-AI-Action-Hub-iOS.xcodeproj \
  -scheme ActionHubApp \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$PWD/build/ActionHubApp.xcarchive" \
  archive

echo "ARCHIVE_OK: $PWD/build/ActionHubApp.xcarchive"
