#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python3 scripts/generate_xcodeproj.py --check
python3 scripts/verify_openapi_contract.py
python3 scripts/validate_ios_project.py

if command -v swift-format >/dev/null 2>&1; then
  swift-format lint --strict --recursive \
    ActionHubApp ActionHubShareExtension ActionHubWidgetExtension \
    Packages/ActionHubCore/Sources Packages/ActionHubCore/Tests
fi

swift test --package-path Packages/ActionHubCore

if command -v swiftc >/dev/null 2>&1; then
  find ActionHubApp ActionHubShareExtension ActionHubWidgetExtension \
    Packages/ActionHubCore/Sources Packages/ActionHubCore/Tests \
    -name '*.swift' -print0 | xargs -0 -n1 swiftc -parse
fi

if command -v plutil >/dev/null 2>&1; then
  find Config ActionHubApp/Resources -type f \
    \( -name '*.plist' -o -name '*.entitlements' -o -name '*.xcprivacy' \) \
    -print0 | xargs -0 -n1 plutil -lint
fi

if [[ "${ACTION_HUB_RUN_XCODE:-0}" == "1" ]]; then
  xcodebuild \
    -project JM-AI-Action-Hub-iOS.xcodeproj \
    -scheme ActionHubApp \
    -configuration Debug \
    -destination 'generic/platform=iOS Simulator' \
    CODE_SIGNING_ALLOWED=NO \
    build
fi

echo IOS_RELEASE_SOURCE_CHECK_OK
