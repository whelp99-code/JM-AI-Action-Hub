# JM-AI Action Hub v0.8.0 Mobile Foundation 상세 개발계획서

- 문서 상태: 구현 기준선
- 서버 버전: `0.8.0`
- 대응 iOS 버전: `0.1.0`
- 기준 시간대: `Asia/Seoul`
- 작성일: 2026-07-31

## 1. 목표

v0.7.0의 Closed-loop Action Control Runtime을 iPhone에서 안전하고 빠르게 사용할 수 있도록 **모바일 전용 인증·수집·동기화·알림 계층**을 추가한다.

이 단계는 Todoist, Calendar, GitHub 기능을 iOS 앱에 재구현하지 않는다. iOS는 수집·검토·승인·활동 확인에 집중하고, 외부 원장 및 AI Worker의 제어는 기존 서버가 계속 담당한다.

```text
네이티브 iOS
  ├─ 직접 입력 / 음성 / 붙여넣기
  ├─ Share Extension
  ├─ App Intents
  ├─ Review / Today / Activity
  └─ Widget / APNs
              │
              ▼
Mobile Gateway v1
  ├─ QR Pairing
  ├─ Device-scoped Bearer Auth
  ├─ Offline Capture Idempotency
  ├─ Revision Conflict
  ├─ Delta Sync
  └─ Push Outbox
              │
              ▼
기존 v0.7 Runtime
  ├─ Parser / Approval
  ├─ Transactional Outbox
  ├─ Todoist / GitHub / Calendar
  ├─ Worker Router
  ├─ Follow-up / Planning
  └─ Audit / Reconciliation
```

## 2. 재사용과 개발 경계

| 영역 | 재사용 | 신규 개발 | 판단 |
|---|---|---|---|
| Todo 관리 | Todoist | 없음 | 원장 중복 금지 |
| 일정 | Google/Outlook/ICS | 없음 | 네이티브 Calendar 재개발 금지 |
| 개발 작업 | GitHub | 없음 | 이슈·PR 화면 재개발 금지 |
| 음성 인식 | Apple Speech | 호출·UX만 | 음성 모델 개발 금지 |
| QR | AVFoundation | 페어링 UX만 | QR 엔진 개발 금지 |
| 생체 인증 | LocalAuthentication | 앱 잠금만 | 인증 모델 개발 금지 |
| 공유 | iOS Share Extension | App Group Queue | 메시지 앱별 플러그인 금지 |
| 푸시 | APNs | 서버 Outbox/Provider | 자체 푸시망 금지 |
| 앱–확장 데이터 | App Groups | 원자적 Capture Queue | 별도 로컬 서버 금지 |
| 네트워크 계약 | OpenAPI | 최소 Swift Client | 업무 Schema 이중 설계 금지 |

## 3. 핵심 요구사항

### 3.1 모바일 인증

1. 관리자 API Key를 앱에 저장하지 않는다.
2. 서버 관리자가 1회용 Pairing Session을 생성한다.
3. Pairing Code는 DB에 평문으로 저장하지 않는다.
4. 앱은 Device Scope가 포함된 짧은 Access Token을 사용한다.
5. Refresh Token은 매 사용 시 회전한다.
6. 유예기간 이후 이전 Refresh Token이 재사용되면 토큰 계열과 기기를 폐기한다.
7. 서버 관리자는 기기별로 원격 해제할 수 있다.
8. Production Pairing URL은 HTTPS만 허용한다.

### 3.2 오프라인 수집

1. Share Extension은 네트워크 처리 대신 App Group Queue에 원문을 저장하고 빠르게 종료한다.
2. 각 Capture는 기기에서 UUID를 부여한다.
3. 서버는 `(device_id, client_capture_id)` 유일키로 재전송을 중복 제거한다.
4. 처리 실패 Capture는 동일 ID로 재시도할 수 있다.
5. 하나의 Capture가 하나의 Action Plan으로 연결되고 Receipt를 반환한다.

### 3.3 검토·승인

1. 모바일 앱은 Plan과 Item을 읽는다.
2. Item 수정은 `expected_revision`을 사용한다.
3. 다른 클라이언트가 먼저 수정했다면 `409 revision_conflict`를 반환한다.
4. 승인과 실행을 분리한다.
5. 모바일 Scope가 없는 작업은 서버에서 거부한다.

### 3.4 변경분 동기화

1. 전체 DB를 반복 다운로드하지 않는다.
2. `GET /mobile/changes?cursor=`로 Audit Log 기반 변경분을 조회한다.
3. Cursor는 HMAC으로 위·변조를 검출한다.
4. 클라이언트는 최대 페이지 수를 제한하고 다음 Foreground Sync에서 이어받는다.

### 3.5 APNs

1. Push Token은 기기별 저장한다.
2. Push 본문에 원문·고객명·작업 제목을 넣지 않는다.
3. 이벤트 종류와 내부 Entity ID만 전송한다.
4. APNs Provider Token은 서버에서 생성·캐시한다.
5. Push Queue는 재시도, 최대 시도, stale-lock 복구, idempotency를 갖는다.
6. APNs 미설정 상태에서도 앱 핵심 기능은 동작한다.

## 4. 단계별 구현

### PR-M01 — API Contract와 Capability

- 모든 모바일 Endpoint에 고정 `operationId` 부여
- `/api/v1/mobile/capabilities`
- 서버 버전, Mobile API 버전, 최소 iOS 앱 버전 제공
- OpenAPI JSON을 저장소에 고정

완료 기준:

- OpenAPI drift 검사
- iOS 앱이 Pairing 전 호환성을 확인
- 최소 버전 미달 시 Claim 요청 차단

### PR-M02 — 데이터 모델과 Migration

신규 테이블:

```text
mobile_devices
mobile_pairing_sessions
mobile_refresh_tokens
mobile_captures
push_notifications
```

기존 테이블 변경:

```text
action_plans.revision
 action_items.revision
```

완료 기준:

- v0.7.0 DB를 데이터 손실 없이 `0004_mobile_foundation`으로 업그레이드
- 기존 Plan·Item ID와 제목 보존
- Revision 기본값 1

### PR-M03 — QR Pairing과 Device Auth

- 5분 기본 TTL
- 16자 사람이 읽을 수 있는 Pairing Code
- HMAC Code Hash 저장
- 시도 횟수 제한
- 기기 정보와 Scope 저장
- 15분 기본 Access Token
- 30일 기본 Refresh Token
- Refresh Rotation과 Family Revocation
- 기기 원격 해제

완료 기준:

- Pairing 단일 사용
- 동시 Claim 중 하나만 성공
- Token 변조·만료·미지원 Scope 거부
- Access Token 즉시 무효화 가능한 Token Version

### PR-M04 — Capture Gateway

- Batch Upload
- Capture ID 유효성 검증
- 기기별 Idempotency
- 처리 중 충돌 처리
- 실패 후 동일 ID 재시도
- Plan 생성 후 Review Push Queue

완료 기준:

- 동일 Capture를 여러 번 보내도 Plan 하나
- 동시 재전송이 HTTP 500을 만들지 않음
- 성공 Receipt 수신 후 iOS 로컬 Queue 삭제

### PR-M05 — Mobile Read/Write API

- Dashboard
- Review Queue
- Plan Detail
- Item Patch
- Approve / Reject / Execute
- Activity
- Device Preferences

완료 기준:

- Scope마다 접근 분리
- Revision 충돌 응답
- 승인되지 않은 Item 실행 방지
- 기존 v0.7 서비스 계층 재사용

### PR-M06 — Delta Sync

- Audit 기반 Changed Entity
- Cursor 서명
- Page Limit
- Deleted/Changed 목록

완료 기준:

- 잘못된 Cursor 400
- 다음 Cursor로 연속 조회
- iOS의 중단 후 재개

### PR-M07 — APNs

- Push Token 등록
- Notification Preferences
- APNs Provider JWT
- Sandbox/Production Host 구분
- Queue Worker 통합
- Generic Payload

완료 기준:

- Dry-run 전송 성공 처리
- 중복 Push Queue 방지
- 잘못된 Token Wrapper 거부
- APNs 영구/일시 오류 분류

### PR-M08 — 운영 도구

- `mobile-pairing`
- `mobile-devices`
- `mobile-revoke`
- QR SVG 및 Terminal QR
- Mobile HTTP Smoke
- Connector/Readiness 확장

## 5. API 요약

### Public

```text
GET  /api/v1/mobile/capabilities
POST /api/v1/mobile/pairings/claim
POST /api/v1/mobile/token/refresh
```

### Administrator

```text
POST   /api/v1/mobile/pairings
GET    /api/v1/mobile/admin/devices
DELETE /api/v1/mobile/admin/devices/{device_id}
```

### Device Bearer

```text
GET    /api/v1/mobile/dashboard
GET    /api/v1/mobile/changes
GET    /api/v1/mobile/activity
POST   /api/v1/mobile/captures/batch
GET    /api/v1/mobile/review
GET    /api/v1/mobile/plans/{plan_id}
PATCH  /api/v1/mobile/plans/{plan_id}/items/{item_id}
POST   /api/v1/mobile/plans/{plan_id}/approve
POST   /api/v1/mobile/plans/{plan_id}/reject
POST   /api/v1/mobile/plans/{plan_id}/execute
PATCH  /api/v1/mobile/devices/me
POST   /api/v1/mobile/devices/me/push-token
PATCH  /api/v1/mobile/devices/me/notification-preferences
POST   /api/v1/mobile/devices/me/push-test
GET    /api/v1/mobile/devices/me/pushes
DELETE /api/v1/mobile/devices/me
```

## 6. 위협 모델

| 위협 | 대응 |
|---|---|
| 앱 바이너리에서 관리자 키 유출 | 관리자 키를 앱에 제공하지 않음 |
| QR 사진 유출 | 짧은 TTL, 단일 사용, 시도 횟수 제한 |
| Pairing Code DB 유출 | HMAC Hash만 저장 |
| Access Token 탈취 | 짧은 수명, Device Token Version, Scope |
| Refresh Token 탈취 | 회전, 계열 추적, 유예 이후 재사용 시 전체 폐기 |
| 정상 회전 응답 유실 | 짧은 유예기간에 동일 후속 토큰 재반환 |
| 모바일 중복 전송 | Client Capture ID + DB Unique Constraint |
| 동시에 수정 | Revision 기반 Optimistic Concurrency |
| Push로 민감정보 노출 | Generic Alert + Entity ID만 전송 |
| 공유 확장 시간 제한 | 네트워크 없이 원자적 로컬 저장 후 종료 |
| HTTP MITM | Remote Server HTTPS 강제 |
| APNs 장애 | Outbox Retry + Foreground/Background Sync 유지 |

## 7. 테스트 전략

### 서버 자동화

- Mobile Migration/Capabilities
- Pairing Code Hash
- Pairing TTL/Lock
- Claim Concurrency
- Refresh Lost-response Retry
- Late Reuse Revocation
- Refresh Concurrency
- Scope Enforcement
- Token Tamper/Oversize/Claim Validation
- Capture Idempotency/Concurrency/Retry
- Revision Conflict
- Approval/Execution
- Cursor/Activity
- Push Queue/Dry-run/Token Validation
- Remote Revoke
- Production HTTPS
- QR SVG/ASCII

### 통합

```text
FastAPI 실제 Uvicorn
→ Swift Client Capability
→ QR Pairing
→ Capture Batch
→ Plan 조회/수정
→ 승인
→ 실행
→ Activity/Changes/Dashboard
```

### 운영 인수

macOS·Apple 계정·실기기가 필요한 다음 항목은 별도 인수한다.

- Xcode Simulator Build
- Signing/Provisioning
- Share Extension 실제 앱 간 공유
- Camera QR
- Speech/Microphone
- Face ID
- Widget/App Intent
- APNs Sandbox/Production
- Background Refresh
- TestFlight

## 8. 릴리스 판정

서버 소스의 완료 조건:

- Python 78 tests 통과
- Coverage 81.27%
- v0.7→v0.8 Migration 보존 검증
- OpenAPI Contract 검증
- 실제 FastAPI–Swift E2E 통과
- Production 보안 설정 검사

Apple 운영 인수는 서버 개발 완료와 구분한다. Apple 서명과 물리 기기가 필요한 검증을 수행하지 않은 상태에서 “App Store 배포 완료”라고 판정하지 않는다.
