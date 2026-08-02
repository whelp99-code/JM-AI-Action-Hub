#!/usr/bin/env python3
"""Static release checks that do not require Xcode or code signing."""
from __future__ import annotations

import json
import plistlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        ERRORS.append(message)


def load_plist(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            return plistlib.load(stream)
    except Exception as exc:  # pragma: no cover - script boundary
        ERRORS.append(f"Invalid plist {path.relative_to(ROOT)}: {exc}")
        return {}


def main() -> int:
    project = ROOT / "JM-AI-Action-Hub-iOS.xcodeproj" / "project.pbxproj"
    text = project.read_text(encoding="utf-8") if project.exists() else ""
    check(bool(text), "Xcode project is missing")

    swift_files = sorted(
        path.relative_to(ROOT).as_posix()
        for folder in ("ActionHubApp", "ActionHubShareExtension", "ActionHubWidgetExtension")
        for path in (ROOT / folder).rglob("*.swift")
    )
    for source in swift_files:
        check(f'path = "{source}";' in text, f"Xcode project does not include {source}")

    for required in (
        "ActionHubShareExtension.appex in Embed App Extensions",
        "ActionHubWidgetExtension.appex in Embed App Extensions",
        "ActionHubCore in Frameworks",
        "PrivacyInfo.xcprivacy in Resources",
        "Assets.xcassets in Resources",
    ):
        check(required in text, f"Xcode project missing {required}")

    app_info = load_plist(ROOT / "Config" / "ActionHubApp-Info.plist")
    share_info = load_plist(ROOT / "Config" / "ShareExtension-Info.plist")
    widget_info = load_plist(ROOT / "Config" / "WidgetExtension-Info.plist")
    privacy = load_plist(ROOT / "ActionHubApp" / "Resources" / "PrivacyInfo.xcprivacy")
    app_ent = load_plist(ROOT / "Config" / "ActionHubApp.entitlements")
    share_ent = load_plist(ROOT / "Config" / "ActionHubShareExtension.entitlements")
    widget_ent = load_plist(ROOT / "Config" / "ActionHubWidgetExtension.entitlements")

    for key in (
        "NSCameraUsageDescription",
        "NSFaceIDUsageDescription",
        "NSMicrophoneUsageDescription",
        "NSSpeechRecognitionUsageDescription",
    ):
        check(bool(app_info.get(key)), f"App Info.plist missing {key}")
    registered_schemes = {
        scheme
        for url_type in app_info.get("CFBundleURLTypes", [])
        for scheme in url_type.get("CFBundleURLSchemes", [])
    }
    check("jmactionhub" in registered_schemes, "Dedicated jmactionhub URL scheme is missing")
    check(
        "actionhub" not in registered_schemes,
        "Legacy generic actionhub URL scheme must not be registered",
    )
    check("processing" not in app_info.get("UIBackgroundModes", []), "Unused background processing mode enabled")
    check("fetch" in app_info.get("UIBackgroundModes", []), "Background fetch mode missing")
    check(
        "remote-notification" not in app_info.get("UIBackgroundModes", []),
        "Silent push background mode must remain disabled until content-available delivery is implemented",
    )
    check(bool(app_info.get("BGTaskSchedulerPermittedIdentifiers")), "BG task identifier missing")
    check(app_info.get("NSSupportsLiveActivities") is True, "Live Activities support is not declared")
    check(
        share_info.get("NSExtension", {}).get("NSExtensionPointIdentifier") == "com.apple.share-services",
        "Share Extension point is invalid",
    )
    share_rule = (
        share_info.get("NSExtension", {})
        .get("NSExtensionAttributes", {})
        .get("NSExtensionActivationRule", {})
    )
    check(share_rule.get("NSExtensionActivationSupportsText") is True, "Share text intake is disabled")
    check(
        int(share_rule.get("NSExtensionActivationSupportsWebURLWithMaxCount", 0)) >= 1,
        "Share URL intake is disabled",
    )
    check(
        "NSExtensionActivationSupportsFileWithMaxCount" not in share_rule,
        "v0.1 must not advertise unsupported file intake",
    )
    check(
        widget_info.get("NSExtension", {}).get("NSExtensionPointIdentifier")
        == "com.apple.widgetkit-extension",
        "Widget Extension point is invalid",
    )

    app_groups = app_ent.get("com.apple.security.application-groups", [])
    check(app_groups == share_ent.get("com.apple.security.application-groups", []), "App and Share App Groups differ")
    check(app_groups == widget_ent.get("com.apple.security.application-groups", []), "App and Widget App Groups differ")
    check(app_ent.get("aps-environment") == "$(ACTION_HUB_PUSH_ENVIRONMENT)", "APNs entitlement missing")
    check(privacy.get("NSPrivacyTracking") is False, "Privacy manifest must disable tracking")

    all_swift = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in swift_files)
    check("X-Action-Hub-Key" not in all_swift, "Admin API key header must never be embedded in iOS source")
    check(
        "registerIfAuthorized()" in all_swift,
        "APNs token must be re-registered on connected app launches",
    )
    check("ActivityConfiguration(for: FocusActivityAttributes.self)" in all_swift, "Focus Live Activity configuration missing")
    check("FocusHomeView()" in all_swift, "Focus tab is not wired into the app")
    check("OpenTriageIntent" in all_swift and "OpenMatrixIntent" in all_swift, "Focus App Intents missing")
    check("markActionCompleted" in all_swift, "Focus completion evidence bridge missing")
    check("Todoist" not in all_swift or "토큰" in all_swift, "Review direct provider credentials in iOS source")
    check(not re.search(r'http://(?!localhost|127\\.0\\.0\\.1|\\[::1\\])', all_swift), "Non-local cleartext server URL embedded")

    openapi = ROOT / "OpenAPI" / "action-hub.openapi.json"
    try:
        document = json.loads(openapi.read_text(encoding="utf-8"))
        check(document.get("info", {}).get("version") == "0.9.0", "OpenAPI version is not 0.9.0")
        operations = {
            operation.get("operationId")
            for methods in document.get("paths", {}).values()
            for operation in methods.values()
            if isinstance(operation, dict)
        }
        for operation in (
            "claimMobilePairing",
            "refreshMobileToken",
            "uploadMobileCaptures",
            "getMobileDashboard",
            "updateMobileActionItem",
            "executeMobilePlan",
            "revokeCurrentMobileDevice",
            "listMobileFocusTriage",
            "classifyMobileFocusAction",
            "getMobileFocusMatrix",
            "getMobileBig3",
            "setMobileBig3",
            "startMobileFocusSession",
            "updateMobileFocusSession",
            "closeMobileFocusDay",
            "getMobileFocusWeeklyReport",
        ):
            check(operation in operations, f"OpenAPI operation missing: {operation}")
    except Exception as exc:
        ERRORS.append(f"OpenAPI validation failed: {exc}")

    generated = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_xcodeproj.py"), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    check(generated.returncode == 0, generated.stderr.strip() or generated.stdout.strip())

    if ERRORS:
        for error in ERRORS:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"IOS_PROJECT_STATIC_OK sources={len(swift_files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
