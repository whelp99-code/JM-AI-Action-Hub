# JM-AI Action Hub for iOS

> iPhone 어디에서든 업무를 수집하고, Action Hub 서버가 해석한 일정·Todo·GitHub 작업을 검토·승인하며, 사람·AI·외부 응답의 실제 완료 상태를 확인하는 네이티브 Companion App.

## 릴리스

| 항목 | 값 |
|---|---|
| iOS 앱 | `0.2.1` Focus Matrix + Live Focus |
| 요구 서버 | JM-AI Action Hub Server `0.9.0+` |
| 최소 OS | iOS/iPadOS 18.0 |
| UI | SwiftUI, Swift 6 |
| 앱 구조 | Main App + Share Extension + Widget + App Intents |
| 로컬 자격증명 | Action Hub Device Refresh Token만 Keychain 저장 |
| 외부 서비스 토큰 | iPhone에 저장하지 않음 |
| 원장 | Todoist, Calendar, GitHub는 서버가 계속 관리 |

## 제품 경계

이 앱은 Todoist·Calendar·GitHub를 대체하지 않는다.

```text
수집·검토·승인·상태 확인      → Action Hub iOS
업무 해석·라우팅·감사·동기화  → Action Hub Server
개인 Todo 원장                → Todoist
일정 원장                     → Google/Outlook/ICS
개발 원장                     → GitHub
AI 작업 실행                  → Codex/Claude/Copilot/Orca/Hermes
```

Focus 계층도 새로운 Todo 원장을 만들지 않는다. `execution_state`와 독립된 `attention_state`만 관리하며, Q4 분류는 삭제가 아니라 보류 판단이다. 위임·외부 실행·이월·완료는 각각 명시적 사용자 동작을 요구한다.

## 구현 기능

### 입력

- SwiftUI 빠른 입력
- 사용자가 누를 때만 Clipboard 읽기
- Apple Speech 전사
- Share Extension 텍스트·URL 수집
- App Intents / Siri / Shortcuts 입력
- 네트워크 없이 App Group 오프라인 Queue 저장

### 검토와 실행

- Review Queue
- Plan Detail
- Item 수정
- 승인·제외
- 실행 요청
- Revision 충돌 감지
- 등록 상태와 실제 완료 상태 구분

### 의사결정과 집중

- 설명 가능한 중요도·긴급도 사전 평가
- 스와이프와 명시적 버튼을 함께 제공하는 Q1/Q2/Q3/Q4 Triage
- 2×2 Eisenhower Matrix
- 사람 Big3와 AI Big3를 분리한 Dual Big3
- 오늘 가용시간 대비 과부하 검사
- 3~5개 Micro Step과 단계별 Human/AI/Hybrid/External 실행자
- 10·25·50·90분 Focus Session
- Green·Yellow·Red 시간 신호등
- Pause·Resume·Extend·Complete·Abandon
- 승인형 Day Close와 이월 사유 기록
- 잠금화면·Dynamic Island Live Activity

### 운영

- Today Dashboard와 Focus Summary
- 과부하·Top 업무·위험
- AI Worker 상태
- Waiting/Follow-up
- Activity Feed
- Cursor 기반 Delta Sync
- APNs 알림
- Focus 중심 Home Screen Widget
- Siri·Shortcuts·App Intents의 Capture/Focus 진입점
- Face ID/기기 인증 잠금

## 아키텍처

```text
ActionHubApp
  ├─ SwiftUI Features
  │   ├─ Today
  │   ├─ Focus (Triage / Matrix / Big3 / Session)
  │   ├─ Review
  │   ├─ Activity
  │   ├─ Capture
  │   └─ Settings
  ├─ Infrastructure
  │   ├─ KeychainCredentialStore
  │   ├─ AppGroupStore
  │   ├─ BackgroundSyncManager
  │   ├─ NotificationManager
  │   ├─ QRScannerView
  │   └─ SpeechCaptureService
  └─ ActionHubCore Package
      ├─ MobileSession
      ├─ Typed API Client
      ├─ OfflineCaptureQueue
      ├─ PairingPayload
      └─ Models / JSON / Version Gate

ActionHubShareExtension
  └─ App Group Atomic Capture Queue

ActionHubWidgetExtension
  └─ Privacy-minimized Dashboard Snapshot
```

## 빌드 준비

### 1. 로컬 Signing 설정

```bash
cp Config/Local.xcconfig.example Config/Local.xcconfig
```

수정:

```xcconfig
DEVELOPMENT_TEAM = YOUR_TEAM_ID
ACTION_HUB_BUNDLE_PREFIX = com.yourcompany.jmactionhub
ACTION_HUB_APP_GROUP = group.com.yourcompany.jmactionhub.shared
```

`Config/Local.xcconfig`는 Git에서 제외된다. 여기에 API Key나 `.p8`를 넣지 않는다.

### 2. 프로젝트 확인

```bash
make check
make test
```

macOS/Xcode:

```bash
make xcode-build
```

### 3. 앱 연결

서버에서:

```bash
action-hub mobile-pairing \
  --base-url https://YOUR_ACTION_HUB \
  --qr-output pairing.svg \
  --print-qr
```

앱에서 QR을 스캔한다. Remote HTTP는 거부되며, Localhost 개발만 HTTP를 허용한다.

## 테스트

Linux에서 실행 가능한 검증:

```text
36 XCTest
1 Swift Testing smoke
53 Swift source parse
swift-format strict lint
Xcode project deterministic check
OpenAPI contract check
Privacy/Entitlement/Plist static check
FastAPI–Swift live E2E
```

macOS/Apple 환경에서 추가해야 하는 인수:

```text
Xcode Simulator build
Code signing and archive
Share Extension host-app test
Camera QR
Microphone/Speech
Face ID
Widget/App Intents
APNs Sandbox/Production
Background refresh
TestFlight install
```

자세한 절차는 `docs/09_TESTFLIGHT_DEVICE_ACCEPTANCE_KR.md`를 참조한다.

## 보안 원칙

- 관리자 `X-Action-Hub-Key` 앱 저장 금지
- Todoist·GitHub·Google Token 앱 저장 금지
- Remote HTTPS 강제
- Keychain `AfterFirstUnlockThisDeviceOnly`
- 회전형 Refresh Token
- 기기별 Scope와 원격 해제
- Push에 원문 미포함
- Share Extension에서 네트워크 호출 금지
- 오프라인 파일 Data Protection
- Clipboard 자동 읽기 금지
- 승인과 실행 분리

## 저장소 검증

```bash
bash scripts/verify_release.sh
```

macOS Release Archive:

```bash
bash scripts/testflight_preflight.sh
```


## 문서

- [상세 검증 및 통합 계획](docs/00_DETAILED_VERIFICATION_AND_PLAN_KR.md)
- [제품·기존 솔루션 재사용 검증](docs/01_PRODUCT_AND_REUSE_VALIDATION_KR.md)
- [PRD·기능명세](docs/02_PRD_AND_FUNCTIONAL_SPEC_KR.md)
- [상세 개발계획](docs/03_DETAILED_DEVELOPMENT_PLAN_KR.md)
- [앱 아키텍처](docs/04_ARCHITECTURE_KR.md)
- [Process·보안 아키텍처](docs/05_ARCHITECTURE_SECURITY_KR.md)
- [보안·개인정보](docs/06_SECURITY_PRIVACY_KR.md)
- [릴리스 검증](docs/07_RELEASE_VERIFICATION_KR.md)
- [단계별 완료 보고](docs/08_PHASE_COMPLETION_REPORT_KR.md)
- [TestFlight·실기기 인수](docs/09_TESTFLIGHT_DEVICE_ACCEPTANCE_KR.md)
- [Xcode 인수 참조](docs/10_XCODE_TESTFLIGHT_ACCEPTANCE_REFERENCE_KR.md)
- [수동 시험 케이스](docs/11_MANUAL_TEST_CASES_KR.md)
- [알려진 제한](docs/12_KNOWN_LIMITATIONS_KR.md)
- [Focus Matrix 제품·기능 명세](docs/13_FOCUS_MATRIX_PRODUCT_SPEC_KR.md)
- [Focus UX·접근성·안전](docs/14_FOCUS_UX_AND_ACCESSIBILITY_KR.md)
- [Live Activity·Widget·App Intents](docs/15_LIVE_ACTIVITY_APP_INTENTS_KR.md)
- [iOS v0.2.1 릴리스 검증](docs/16_RELEASE_VERIFICATION_V021_KR.md)
- [Xcode·실기기·TestFlight v0.2.1 인수](docs/17_XCODE_TESTFLIGHT_ACCEPTANCE_V021_KR.md)
