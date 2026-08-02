# JM-AI Action Hub iOS 아키텍처

## 1. Component

```text
ActionHubApp
  AppModel (@MainActor)
  ├─ MobileSession actor
  ├─ OfflineCaptureQueue actor
  ├─ KeychainCredentialStore actor
  ├─ AppGroupStore
  ├─ NotificationManager
  ├─ BackgroundSyncManager
  ├─ BiometricLock
  ├─ QRScanner
  └─ SpeechCapture

ShareExtension
  └─ OfflineCaptureQueue only

WidgetExtension
  └─ Read-only WidgetSnapshot

App Intents
  └─ OfflineCaptureQueue or Open App
```

## 2. Concurrency

- `AppModel`: `@MainActor`, UI State 단일 소유
- `MobileSession`: Actor, Refresh Task 단일화
- `OfflineCaptureQueue`: Actor + Capture별 파일로 Process 간 Lost Update 방지
- `KeychainCredentialStore`: Actor
- API Model: `Sendable`

## 3. Pairing Sequence

```text
Admin CLI        iOS App          Server DB
   │ QR Payload     │                 │
   ├───────────────>│                 │
   │                │ GET capabilities│
   │                ├────────────────>│
   │                │ POST claim      │
   │                ├────────────────>│
   │                │                 ├─ CAS Pairing
   │                │                 ├─ Device
   │                │                 └─ Refresh Family
   │                │ Access/Refresh  │
   │                │<────────────────┤
   │                └─ Keychain Save  │
```

## 4. Capture Sequence

```text
Share Source
 → Share Extension
 → App Group capture-id.json
 → Main App/BG Refresh
 → MobileSession valid token
 → POST batch
 → Server idempotent receipt
 → processed/duplicate only local delete
 → Review Refresh
```

## 5. Token Refresh Sequence

```text
API 요청 전 Expiry 45초 이내
 → MobileSession.refreshTask 존재? await
 → 없으면 한 Task 생성
 → Refresh Token 회전
 → 새 Session Keychain 원자 저장
 → 대기 중 요청 모두 새 Access Token 사용
```

401 발생 시 한 번 강제 Refresh 후 원 요청을 재시도한다. 두 번째 실패는 상위로 전달한다.

## 6. Sync Sequence

- Dashboard/Review/Activity 병렬 조회
- Widget Snapshot 저장
- Delta Changes 최대 200건/페이지
- Foreground 한 번에 최대 10페이지
- Durable Cursor 저장
- 다음 Refresh에서 이어받기

## 7. Project Generation

`project.yml`은 사람이 읽는 Source of Truth다. `scripts/generate_xcodeproj.py`가 `.pbxproj`와 Shared Scheme을 결정적으로 생성한다.

```bash
python3 scripts/generate_xcodeproj.py --check
```

Drift가 있으면 CI 실패한다.

## 8. OpenAPI Contract

서버 Snapshot:

```text
OpenAPI/action-hub.openapi.json
```

`verify_openapi_contract.py`가 iOS에 필요한 Operation ID와 Mobile API Version을 확인한다. Swift 모델은 Core Test와 실제 Server Contract Smoke로 검증한다.
