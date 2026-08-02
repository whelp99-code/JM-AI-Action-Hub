# Changelog

## 0.2.1 — 2026-08-01

### Live Focus and system surfaces

- Added ActivityKit Live Activity for the single active human Focus Session on the Lock Screen and Dynamic Island.
- Added Focus-aware Widget snapshots with privacy-sensitive task titles and counts.
- Added Siri/Shortcuts App Intents for Capture, Focus, Triage, and Matrix navigation without direct approval or execution.
- Added backward-compatible WidgetSnapshot decoding so v0.1 cached data remains readable after upgrade.
- Added route handoff through the App Group container and foreground-safe pending-route consumption.

### Verification

- 36 XCTest cases and 1 Swift Testing smoke test pass.
- All Swift sources parse with Swift 6.2.1 on Linux and swift-format strict checks pass.
- A live Swift client completes classify → Dual Big3 → Micro Steps → Focus pause/resume/complete → weekly report against Server v0.9.0.
- Xcode iOS SDK build, code signing, physical-device ActivityKit behavior, APNs live delivery, and TestFlight remain Apple-environment acceptance items.

## 0.2.0 — 2026-08-01

### Focus Matrix

- Added Focus tab with explainable Swipe Triage and equivalent visible buttons/VoiceOver actions.
- Added Eisenhower Matrix with Q1 execute, Q2 plan, Q3 delegate, and Q4 hold semantics.
- Added human Big3 and AI Big3 with capacity and overload feedback.
- Added Micro Steps with per-step human/AI/hybrid/external ownership.
- Added 10/25/50/90-minute Focus Session controls, traffic-light progress, pause/resume/extend/complete/abandon, and completion notes.
- Added explicit Day Close decisions instead of silent automatic carry-over.
- Extended Today, Settings, API client, cache models, and OpenAPI contract for Server v0.9.0.

## 0.1.0 — 2026-07-31

### Final hardening

- Made device disconnect delete local Keychain credentials even when remote revoke fails.
- Required explicit user confirmation for externally opened custom pairing URLs.
- Added paginated delta sync, camera permission handling, and deterministic Speech audio-session cleanup.
- Marked Widget task titles and operational counts as privacy-sensitive.
- Kept silent-push background mode disabled until `content-available` processing exists.


### Native companion

- Added SwiftUI Today, Review, Activity, Capture, and Settings experiences.
- Added one-time QR pairing with capability/version preflight.
- Added Keychain session storage and rotating refresh-token support.
- Added typed mobile API client with one automatic refresh-and-retry path.
- Added process-safe, per-capture App Group offline queue shared by the app, Share Extension, and App Intents.
- Added Share Extension text/URL intake, explicit clipboard paste, and Apple Speech capture.
- Added plan item edit, approve, reject, and execute flows with optimistic revision handling.
- Added APNs registration, notification routing, foreground sync, and background refresh.
- Added Today widget, Siri/Shortcuts App Intents, and Face ID/device-authentication lock.
- Added minimum app-version enforcement and remote cleartext HTTP rejection.
- Added deterministic Xcode project generation, OpenAPI contract checks, privacy manifest, CI, and release scripts.

### Verification

- 30 XCTest cases pass for the cross-platform ActionHubCore package.
- 1 Swift Testing package smoke test passes.
- 42 Swift source files parse with Swift 6.2.1 on Linux.
- The Swift smoke client completes a live end-to-end flow against Server v0.8.0.
- Xcode signing, simulator/device build, APNs live delivery, and TestFlight remain macOS/Apple operational acceptance items.
