# JM-AI Action Hub iOS v0.1.0 상세 개발계획서

## 1. 목표

iPhone에서 “수집까지 3초, 검토까지 한 화면, 실제 실행은 명시적 승인”을 달성한다.

## 2. 비기능 기준

- Remote HTTPS만 허용
- 앱에 Admin/Provider Secret 없음
- Offline Capture 무손실
- Capture 재전송 중복 없음
- Access Token 자동 갱신 1회
- Revision Conflict가 Silent Overwrite를 만들지 않음
- Dynamic Type/Dark Mode/VoiceOver 기본 지원
- Share Extension은 빠르게 종료
- Push는 민감 원문 미포함
- 서버 미연결 상태에서도 Capture 저장 가능

## 3. 단계

### I01 — 프로젝트 기반

- SwiftUI App
- Share Extension
- Widget Extension
- Local Swift Package `ActionHubCore`
- deterministic project generator
- xcconfig signing override
- Privacy Manifest

### I02 — Core Network/Auth

- Pairing Payload JSON/custom URL 파싱
- Capabilities preflight
- Remote HTTP 차단
- Typed API Client
- Bearer Header
- Keychain Credential Store
- Refresh single-flight
- 401 refresh-and-retry
- Minimum version gate

### I03 — Offline Capture

- Capture별 Atomic JSON
- App Group Container
- Data Protection
- Legacy array migration
- Corrupt file quarantine
- Batch upload
- Receipt apply
- 독립 Process 동시 Enqueue 테스트

### I04 — Pairing UX

- QR Scanner
- Camera permission
- Paste fallback
- Service/API/version validation
- Device metadata
- Push permission request

### I05 — Capture UX

- TextEditor
- Explicit Clipboard
- Apple Speech
- Share Extension text/URL
- App Intent capture
- Pending count

### I06 — Review/Approval

- Review list
- Plan detail
- Item editor
- approve/reject/execute
- expected revision
- 409 conflict handling

### I07 — Today/Activity

- Mobile Dashboard
- Top work/overload/risk
- AI running/waiting/failure
- Activity filter
- Deep Link

### I08 — APNs/Background

- Device Token registration
- every-launch re-registration when authorized
- Generic notification routing
- BGAppRefresh
- Foreground full refresh

### I09 — System Integration

- App Shortcuts
- Siri phrases
- Action button eligible Intent
- Today Widget
- Widget snapshot

### I10 — Security/Release

- Face ID/device authentication
- entitlements/plist/privacy static validation
- swift-format
- core tests
- OpenAPI drift
- TestFlight checklist

## 4. 화면

### Today

- 가용시간, 예상 업무량, 초과시간
- Top 3
- Deadline/Follow-up/Reschedule risk
- AI 위임 후보

### Review

- Plan별 Item 수와 검토 상태
- Action Type/Destination/Date/Executor
- 수정·제외·승인·실행

### Activity

- AI 실행
- Follow-up
- 실패
- 최근 외부 상태

### Capture

- Text
- Paste
- Speech
- Offline pending

### Settings

- Device/server status
- sync
- Face ID
- notification preferences
- version
- device revoke

## 5. 데이터

로컬은 원장이 아니다.

```text
Keychain
  └─ StoredMobileSession

App Group
  ├─ captures/<capture-id>.json
  ├─ widget/dashboard.json
  └─ sync/cursor.txt
```

## 6. 테스트

### Core XCTest

- HTTP URL policy
- Bearer Header
- Path segment escaping
- Conflict mapping
- Capability/model decoding
- Capture encoding
- Pairing JSON/URL
- Minimum version
- Unauthorized refresh/retry
- Disconnect local deletion
- Offline Queue persistence/concurrency/migration

### Static

- Xcode Project source/resource inclusion
- Entitlement App Group consistency
- APNs Entitlement
- Usage descriptions
- Privacy Tracking false
- Admin API Header absence
- OpenAPI required operations

### E2E

- Swift executable ↔ live FastAPI
- Pairing→Capture→Edit→Approve→Execute→Sync

## 7. 완료 정의

소스 개발 완료:

- Core tests PASS
- Swift source parse PASS
- format PASS
- static contract PASS
- live FastAPI E2E PASS

Apple 운영 완료:

- macOS Xcode build
- signing/archive
- physical iPhone acceptance
- APNs live
- TestFlight install
