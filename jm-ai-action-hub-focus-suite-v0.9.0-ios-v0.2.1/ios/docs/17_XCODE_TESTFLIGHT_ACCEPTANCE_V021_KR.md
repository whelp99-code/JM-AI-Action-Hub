# iOS v0.2.1 Xcode·실기기·TestFlight 인수 절차

## 1. 요구 환경

- 최신 안정 Xcode
- Apple Developer Program Team
- iOS 18+ iPhone
- HTTPS Action Hub Server v0.9.0
- App Group·Push Notification Capability
- 필요 시 APNs Auth Key(.p8)는 서버에만 저장

## 2. 설정

```bash
cp Config/Local.xcconfig.example Config/Local.xcconfig
```

```xcconfig
DEVELOPMENT_TEAM = TEAM_ID
ACTION_HUB_BUNDLE_PREFIX = com.example.jmactionhub
ACTION_HUB_APP_GROUP = group.com.example.jmactionhub.shared
```

각 Target의 Bundle ID와 App Group이 Apple Developer Portal과 일치해야 한다.

## 3. Source Gate

```bash
make check
make test
ACTION_HUB_RUN_XCODE=1 bash scripts/verify_release.sh
```

## 4. 실기기 P0

1. QR Pairing
2. Share Extension offline capture
3. Triage 버튼·스와이프·VoiceOver
4. Matrix
5. Human/AI Big3
6. Micro Step
7. Focus 10분 시작
8. Lock Screen/Dynamic Island Live Activity
9. Pause/Resume/Extend/Complete
10. 앱 강제종료·재실행 후 활성 상태 정합성
11. Day Close
12. Widget/App Intents
13. Remote revoke

## 5. Archive

- Release configuration
- Version 0.2.1 / Build 21 이상
- Generic iOS Device
- Product → Archive
- Validate App
- Upload to App Store Connect

## 6. TestFlight 통과 기준

- Crash-free 핵심 Flow
- Pairing/Token rotation
- offline queue 중복 없음
- Focus single-active 보장
- Live Activity 종료 누락 없음
- 민감 Push/Widget/Live Activity 원문 노출 없음
- Dynamic Type/VoiceOver
- 배터리·Background behavior 점검
