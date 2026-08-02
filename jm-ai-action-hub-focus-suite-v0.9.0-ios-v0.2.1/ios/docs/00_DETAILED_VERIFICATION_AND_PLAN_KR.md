# JM-AI Action Hub iOS v0.1.0 상세 검증 및 개발 계획서

- 작성일: 2026-07-31
- 프로젝트: `jm-ai-action-hub-ios`
- 앱 버전: `0.1.0`
- 필수 서버: `JM-AI Action Hub Server 0.8.0+`
- 개발 기준: Swift 6, SwiftUI, iOS/iPadOS 18+
- 상태: 소스 구현 및 비-Apple SDK 검증 완료, Xcode/실기기 인수 대기

## 1. Executive Summary

JM-AI Action Hub iOS는 Todoist·Calendar·GitHub의 모바일 대체 앱이 아니다. 기존 Action Hub 서버의 고유 기능인 자연어 Action 분석, 승인, 사람/AI 실행자, Waiting-for, PR·CI·Merge 상태, 외부 원장 완료 증거를 iPhone에서 가장 빠르게 통제하는 네이티브 Companion이다.

제품 가설:

> 사용자는 카카오톡·문자·메일·웹에서 발견한 업무를 두세 번의 동작으로 잃지 않고 수집하고, 이후 한 화면에서 Action Hub의 분석 결과만 검토·승인한다.

최소 성공 기준:

- Share Sheet 수집 성공률 99% 이상
- 오프라인 Capture 유실 0건
- 동일 Capture 중복 Plan 생성 0건
- Capture→Review 도달 중앙값 10초 이하(정상 네트워크)
- 승인 전 외부 시스템 쓰기 0건
- 앱 내 Provider Credential 저장 0건
- 원격 기기 폐기 후 Access/Refresh 재사용 성공 0건

## 2. 기존 앱·오픈소스 재사용 판단

| 영역 | 재사용 | 개발하지 않는 이유 |
|---|---|---|
| 개인 Todo | Todoist | 모바일·알림·완료·프로젝트가 이미 존재 |
| 일정 | Apple/Google/Outlook Calendar | 일정 원장과 초대·알림을 재구현할 이유 없음 |
| 개발 작업 | GitHub Issues/Projects | Issue→PR→CI→Merge가 실제 개발 원장 |
| AI 코딩 | Codex·Claude Code·Copilot·Orca·Hermes | Worker를 새로 만들지 않고 서버가 Adapter로 호출 |
| 음성 인식 | Apple Speech | 자체 음성 모델 불필요 |
| QR | AVFoundation | 자체 Scanner 불필요 |
| 앱 잠금 | LocalAuthentication | Face ID/Passcode를 직접 구현하지 않음 |
| Push | APNs/UserNotifications | 플랫폼 표준 사용 |
| 공유 | iOS Share Extension | 카카오톡·메일·Safari 진입점 재사용 |
| 단축 명령 | App Intents | Siri·Shortcuts·Spotlight 진입점 재사용 |
| Widget | WidgetKit | 홈/잠금화면 상태 요약 재사용 |
| API 원장 | Action Hub Server | Parser·Approval·Execution 로직 중복 금지 |

독자 개발이 필요한 공백:

1. Action Hub 전용 보안 페어링
2. App Group 기반 Process-safe Offline Capture
3. 검토·승인·실행 UX
4. 사람/AI/Waiting 상태의 모바일 통합 화면
5. Server Revision Conflict와 Delta Sync 처리
6. 민감정보 없는 상태 Push 라우팅

## 3. Apple 플랫폼 설계 검증

### App Group

Main App, Share Extension, Widget은 별도 Process이므로 같은 App Group Container를 사용한다. 공유 상태는 전체 DB가 아니라 다음 최소 데이터만 둔다.

```text
captures/<capture-id>.json
widget/dashboard.json
sync/cursor.txt
```

### Share Extension

Share Extension은 실행시간과 자원 제약이 있으므로 다음만 한다.

```text
입력 Provider에서 Text/URL 추출
→ Trim·Join
→ App Group에 원자적 파일 저장
→ 성공 메시지
→ 종료
```

하지 않는 것:

- Keychain Token 조회
- Server API 호출
- LLM 분석
- 외부 Todo/Issue/Calendar 등록

### APNs와 BackgroundTasks

- APNs: 서버 상태 변경의 즉시 신호
- BGAppRefreshTask: 시스템이 허용할 때 큐 업로드·변경분 동기화
- Foreground 진입: 즉시 Refresh/Flush

Background Task는 정확한 실행시각을 보장하지 않으므로 업무 Deadline 알림의 단일 원천으로 사용하지 않는다.

### App Intents·Widget

- App Intent: Text Capture와 앱 열기
- Widget: Review/Waiting/AI Count와 Top 3 요약
- Widget/Shortcut에서 승인·실행 금지

## 4. 최종 아키텍처

```text
┌────────────────────────────────────────────┐
│ ActionHubApp                               │
│  SwiftUI                                   │
│  ├─ Today                                  │
│  ├─ Review                                 │
│  ├─ Activity                               │
│  ├─ Settings                               │
│  ├─ Pairing                                │
│  └─ Capture                                │
│                                            │
│ Infrastructure                             │
│  ├─ KeychainCredentialStore                │
│  ├─ AppGroupStore                          │
│  ├─ NotificationManager                    │
│  ├─ BackgroundSyncManager                  │
│  ├─ BiometricLock                          │
│  ├─ QRScannerView                          │
│  └─ SpeechCaptureService                   │
├────────────────────────────────────────────┤
│ ActionHubShareExtension                    │
│  └─ Text/URL → Offline Capture Queue       │
├────────────────────────────────────────────┤
│ ActionHubWidgetExtension                   │
│  └─ Privacy-safe Dashboard Snapshot        │
├────────────────────────────────────────────┤
│ ActionHubCore (local Swift Package)         │
│  ├─ Typed Models/API Client                │
│  ├─ MobileSession / Token Refresh          │
│  ├─ PairingPayload                         │
│  ├─ OfflineCaptureQueue                    │
│  ├─ SemanticVersion                        │
│  └─ Live Contract Smoke                    │
└──────────────────┬─────────────────────────┘
                   │ HTTPS Bearer
                   ▼
        Action Hub Server v0.8.0
```

## 5. 화면 계획

### Today

- 가용시간·계획시간·초과시간
- Top 업무
- AI 위임 후보
- Deadline/Follow-up 위험
- 외부 원장 Deep Link

### Review

- Plan 목록과 Review Count
- Action 유형·Destination·신뢰도·일정·예상시간
- Item Edit
- Item Reject
- Plan Approve
- Plan Execute
- Revision Conflict 안내

### Activity

- AI Worker 상태
- Follow-up Due
- Connector 실패
- 최근 등록·완료·PR/CI 상태
- 외부 URL 열기

### Capture

- 직접 입력
- Clipboard 버튼(사용자 명시 동작)
- 한국어 Speech
- 저장 직후 Offline Queue Count

### Settings

- 연결 기기·서버 버전
- Sync·Offline Count
- Biometric Lock
- Push Preferences
- Connection Revoke
- 개인정보 원칙

## 6. 데이터·보안 설계

### Keychain

저장:

- Server URL
- Access Token와 Expiry
- Refresh Token와 Expiry
- Device Metadata

속성:

```text
kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
```

이유:

- BG Upload가 첫 잠금해제 후 작동 가능
- 다른 Device/Backup으로 이동 금지

### App Group Queue

- Capture마다 별도 JSON 파일
- Atomic Write
- Complete File Protection Until First Authentication
- Malformed 파일은 `corrupt/`로 격리
- 과거 배열형 Queue 자동 Migration
- 성공/중복 Receipt만 삭제
- 실패 Capture는 재시도 가능

### Network

- Remote는 HTTPS만 허용
- `localhost`, `127.0.0.1`, `::1`만 HTTP 개발 예외
- Ephemeral URLSession
- 30초 Request/60초 Resource Timeout
- Bearer Token만 Mobile API에 사용
- 관리자 `X-Action-Hub-Key` 금지 검사

### Pairing User Intent

- 앱 내부 QR Scanner는 사용자가 명시적으로 실행했으므로 Scan 후 Claim 가능
- 외부 `jmactionhub://pair`는 다른 앱/웹에서 열 수 있으므로 자동 Claim 금지
- Pairing 화면에 값을 채운 뒤 사용자가 연결 버튼을 눌러야 함

## 7. 순차 개발 계획과 구현 결과

### Phase I0 — 기준선·Research

검증:

- Server v0.7.0 API와 상태 모델
- Apple App Groups/Extensions/APNs/App Intents/Widget/BackgroundTasks/Speech/LocalAuthentication
- 기존 앱 재사용 경계

결과: 완료

### Phase S1 — Server Mobile Foundation

구현:

- Mobile Schema/Migration
- Capabilities
- QR Pairing
- Device Scope
- Access/Refresh Token
- Remote Revoke

결과: 완료

### Phase S2 — Offline/Sync/Push

구현:

- Capture Batch Idempotency
- Concurrent Claim
- Stale Lock Recovery
- Plan/Item Revision
- Dashboard·Activity·Changes Cursor
- APNs Token/Outbox/Retry

결과: 완료

### Phase I1 — ActionHubCore

구현:

- Typed API Models
- HTTPS Client
- Session Restore/Refresh Serialization
- Pairing Parser
- Semantic Version Guard
- Offline Queue
- Cross-platform Tests

결과: 완료

### Phase I2 — Native App Shell

구현:

- SwiftUI App Lifecycle
- Today/Review/Activity/Settings
- Pairing/QR
- Capture/Clipboard/Speech
- Biometric Lock

결과: 소스 완료

### Phase I3 — Extensions

구현:

- Share Extension
- App Group Storage
- Widget
- App Intents/Shortcuts
- APNs Deep Link Routing
- BGAppRefreshTask

결과: 소스 완료

### Phase I4 — Hardening

구현:

- Remote Revoke 실패 시 Local Keychain 강제 삭제
- Pairing Custom URL 사용자 확인
- Delta Pagination
- Camera Permission 상태 처리
- Speech AudioSession Cleanup
- Project/Plist/Entitlement/Privacy Manifest 정적검증

결과: 완료

### Phase I5 — Release Verification

완료:

- Swift Core Unit Tests
- Swift Release Build
- Swift Format Strict
- 모든 Swift 파일 Parse
- OpenAPI Contract Check
- Deterministic Xcode Project Check
- Live Swift→Server E2E

남음:

- Apple SDK Xcode Compile
- Simulator UI Test
- 실제 iPhone Share/QR/Face ID/Speech/APNs
- Signing/TestFlight

## 8. 테스트 전략

### 자동 테스트

| 계층 | 내용 |
|---|---|
| Server Unit/Integration | Auth, Pairing, Refresh, Scope, Capture, Revision, Push |
| Swift Core | URL Guard, Models, Session, Refresh, Queue, Pairing, Version |
| Contract | OpenAPI Operation ID와 Swift Client Endpoint |
| Live E2E | Pair→Capture→Review→Edit→Approve→Execute→Changes→Revoke |
| Migration | v0.7 Sample DB→v0.8, Count/Revision/Table 보존 |
| Static iOS | pbxproj, Scheme, Plist, Entitlement, Privacy Manifest, Source Inclusion |
| CI | macOS Xcode Simulator Build |

### 수동 실기기

- 카카오톡 Text Share
- Safari URL Share
- Mail Share
- Airplane Mode Capture 후 복구
- 앱과 Share Extension 연속 수집
- QR 만료·오코드
- Face ID 실패/Passcode Fallback
- Korean Speech
- APNs Sandbox/TestFlight Production
- Device Remote Revoke

## 9. 릴리스 Gate

### Gate A — Server

- 모든 Test Pass
- Coverage 80% 이상
- Migration 보존
- OpenAPI 고정
- Production Secret Guard
- HTTP E2E

### Gate B — Swift Core

- `swift test`
- `swift build -c release`
- Format Strict
- Live Contract Smoke

### Gate C — Xcode

- macOS/Xcode Build
- Simulator Launch
- No Signing Build
- Extension Embed 확인
- Privacy Manifest/Entitlement 확인

### Gate D — Device

- App Group Provisioning
- Share Extension
- Keychain/Face ID
- Speech/Camera
- APNs Sandbox/Production
- Offline Recovery

### Gate E — TestFlight

- Archive/Validate
- Internal Test Group
- Crash/Metric 확인
- 실제 서버 Production TLS

## 10. 버전 로드맵

### iOS 0.1.0

- Text/Share/Speech Capture
- Review/Approval/Execution
- Today/Activity
- Push/Widget/App Intent
- Secure Pairing

### iOS 0.2.0

기존 프레임워크 우선:

- VisionKit DataScanner OCR
- Photos/스크린샷 OCR
- PDF Text Extraction
- Attachment Upload

### iOS 0.3.0

- Live Activity: AI Worker 장기 실행만
- Apple Watch Quick Capture/Counts
- iPad Multicolumn UI

### iOS 0.4.0

- On-device Classification Assist
- 개인정보 민감도 자동 표시
- Personal Rule 제안 Review

## 11. 최종 판정 기준

현 환경에서 판정 가능한 상태:

> Server v0.8.0과 Swift Core/iOS Xcode Source는 구현 완료. 실제 Server와 Swift Client의 네트워크 Contract 및 데이터 Migration은 검증 완료.

Apple 환경에서만 판정 가능한 상태:

> iOS Binary, Extension Embed, Entitlement/Provisioning, 실제 APNs, Face ID, Siri, Widget, TestFlight는 macOS/Xcode 및 물리 기기 인수가 완료되어야 Release Candidate로 판정한다.
