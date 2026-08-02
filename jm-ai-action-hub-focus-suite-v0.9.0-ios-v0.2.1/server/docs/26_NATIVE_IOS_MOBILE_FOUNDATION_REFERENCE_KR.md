# JM-AI Action Hub Server v0.8.0 — Native iOS Mobile Foundation

- 작성일: 2026-07-31
- 서버 릴리스: `0.8.0`
- 대응 iOS 앱: `JM-AI Action Hub iOS 0.1.0`
- 기준선: Server `0.7.0` Closed-loop Action Control System
- 기본 시간대: `Asia/Seoul`

## 1. 목표

v0.8.0은 기존 PWA를 폐기하지 않고, 별도의 SwiftUI iOS Companion이 안전하게 연결될 수 있는 서버 기반을 추가한다.

```text
Share Extension / 앱 직접 입력 / Siri·Shortcuts
                  │
                  ▼
          iOS App Group Offline Queue
                  │
                  ▼
   기기별 Bearer Token + Batch Capture API
                  │
                  ▼
         Action Hub Review / Approval
                  │
                  ▼
 Todoist / GitHub / Calendar / AI Worker
                  │
                  ▼
          APNs 상태 알림·Delta Sync
```

이 릴리스가 새로 만들지 않는 것:

- 자체 Todo·Calendar·Kanban
- iPhone에 Provider API Token 보관
- Share Extension 내부에서 장시간 분석·외부 등록
- 승인 없는 자동 실행
- APNs 알림 본문에 고객명·원문·작업 제목 포함

## 2. 설계 검증 결론

### 2.1 PWA만으로 부족했던 기능

- iOS Share Sheet에서 즉시 수집
- 네트워크 단절 시 원문 보존
- 앱·Share Extension·Widget 간 최소 상태 공유
- 기기별 연결 해제와 권한 범위
- Face ID/기기 인증, APNs, App Intents, Widget
- 검토·AI 실행·Follow-up 상태의 네이티브 알림

### 2.2 서버에 반드시 있어야 하는 기능

| 기능 | 이유 |
|---|---|
| 1회용 QR 페어링 | 관리자 API Key를 앱에 복사하지 않기 위해 필요 |
| 기기별 Scope | 기기 또는 후속 팀 사용 시 최소권한 적용 |
| 짧은 Access Token | 탈취 시 노출 기간 제한 |
| 회전형 Refresh Token | 장기 세션과 폐기·재사용 탐지 동시 지원 |
| Batch Capture + Idempotency | 앱/Extension 재시도와 네트워크 응답 유실 대응 |
| Optimistic Revision | iPhone·PWA·외부 Webhook의 동시 수정 충돌 탐지 |
| Delta Change Cursor | 모바일 전체 데이터 반복 다운로드 방지 |
| APNs Outbox | 상태 변화와 전송 장애를 분리하고 재시도 |

## 3. API 구조

### 공개 Bootstrap API

```text
GET  /api/v1/mobile/capabilities
POST /api/v1/mobile/pairings/claim
POST /api/v1/mobile/token/refresh
```

### 관리자 API Key 필요

```text
POST   /api/v1/mobile/pairings
GET    /api/v1/mobile/admin/devices
DELETE /api/v1/mobile/admin/devices/{device_id}
```

### 기기 Bearer Token 필요

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
GET    /api/v1/mobile/devices/me/pushes
POST   /api/v1/mobile/devices/me/push-test
DELETE /api/v1/mobile/devices/me
```

## 4. Scope 모델

기본 Scope:

```text
capture:write
plans:read
plans:edit
plans:approve
plans:execute
brief:read
activity:read
devices:write
devices:push
```

규칙:

1. 서버 설정에 존재하지 않는 Scope는 페어링 생성 시 거부한다.
2. Access Token Scope와 현재 Device Scope의 교집합만 유효하다.
3. Dashboard는 `brief:read`만 가진 기기에 Activity 원문을 포함하지 않는다.
4. 기기 이름 수정·자체 폐기는 `devices:write`가 필요하다.
5. APNs Token 등록·알림 설정은 `devices:push`가 필요하다.

## 5. 페어링 흐름

```text
관리자: action-hub mobile-pairing --base-url https://hub.example.com
  → 16자리 1회용 Code 생성
  → DB에는 HMAC Hash만 저장
  → QR JSON / jmactionhub://pair URI 생성
  → iPhone에서 명시적으로 스캔·확인
  → claim API가 Code·TTL·시도횟수 검증
  → Compare-and-set으로 pending→claiming 1회 선점
  → MobileDevice + Refresh Token을 같은 트랜잭션에 생성
  → Access/Refresh Token 반환
```

기본 정책:

- Pairing TTL: 300초
- 최대 실패 시도: 5회
- Code: 모호한 문자를 제외한 16자, 약 80bit 엔트로피
- Production Public URL: HTTPS 필수
- Pairing Code 평문 DB 저장 금지
- 동일 Pairing 두 번째 Claim 금지

## 6. Token 모델

### Access Token

- HMAC-SHA256 서명
- `iss`, `aud`, `sub`, `scp`, `ver`, `iat`, `exp`, `jti` 검증
- 기본 수명 15분
- Device `token_version` 변경 시 기존 Token 즉시 무효
- 서버 폐기 Device는 Expiry 전이라도 거부

### Refresh Token

- DB에는 SHA-256 Verifier만 저장
- 기본 수명 30일
- 매 갱신마다 같은 Family 안에서 새 Token으로 회전
- 이전 Token 재사용은 Family 및 Device 전체 폐기
- 네트워크 응답 유실을 고려해 기본 30초 Grace 내에는 이미 발급한 동일 Replacement를 재반환
- Grace 이후 재사용은 탈취로 간주

## 7. Offline Capture

각 iOS Capture는 기기에서 생성한 `client_capture_id`를 가진다.

```text
POST /api/v1/mobile/captures/batch
```

서버 처리 규칙:

1. `(device_id, client_capture_id)` Unique Constraint
2. 동일 ID·동일 Content Hash 재전송은 Duplicate 반환
3. 동일 ID·다른 Content는 충돌로 실패
4. `received/failed → processing → processed` 상태 전이
5. 앱과 Share Extension 동시 업로드는 원자적 Claim으로 한 요청만 Parser 실행
6. 프로세스 중단으로 `processing` Lock이 남으면 Timeout 뒤 재회수
7. 처리 완료 후 Review Plan ID를 Receipt로 반환
8. Review 알림은 Generic APNs 이벤트만 Queue

## 8. Revision 충돌

`action_plans.revision`과 `action_items.revision`을 추가한다.

```text
iPhone이 item revision=5를 수정 요청
서버의 현재 revision=6
→ HTTP 409 revision_conflict
→ iPhone이 최신 Plan 재조회
→ 사용자가 변경사항을 다시 확인
```

승인·거부·실행도 Plan Revision을 검증한다. 마지막 쓰기 우선으로 조용히 덮어쓰지 않는다.

## 9. Delta Sync

`AuditEvent(created_at, id)`를 정렬된 변경 로그로 사용한다.

```text
GET /api/v1/mobile/changes?cursor=...&limit=200
```

- Cursor는 Timestamp와 Audit ID를 Base64URL로 인코딩
- 동시 Timestamp에서는 ID로 안정 정렬
- `has_more`, `next_cursor` 지원
- 삭제 이벤트는 `deleted` 배열에도 제공
- iOS 앱은 한 Foreground 갱신에서 페이지 수를 제한하고 다음 갱신에서 Durable Cursor로 이어받음

## 10. APNs Outbox

APNs 전송은 업무 상태 트랜잭션과 직접 결합하지 않는다.

```text
상태 변화
  → PushNotification Outbox 저장
  → Worker Claim
  → HTTP/2 APNs 요청
  → sent / retry / failed / simulated
```

구현 정책:

- `.p8` Private Key는 서버 파일시스템에만 저장
- ES256 Provider Token 생성·캐시
- Sandbox/Production Device Token 구분
- 민감정보 없는 Generic Alert
- Idempotency Key로 동일 이벤트 중복 방지
- 지수형 재시도와 Max Attempts
- Stale Processing Lock 복구
- `BadDeviceToken` 또는 `Unregistered` 시 Device Token 제거
- `dry_run`에서는 실제 APNs 호출 없이 `simulated`

## 11. 데이터 모델

### MobileDevice

- 기기·OS·앱 버전
- 상태·Scope·Token Version
- APNs Token/환경
- Notification Preferences
- Last Seen·Revoked At

### MobilePairingSession

- HMAC Code Hash
- 요청 Scope
- TTL·Attempt·Max Attempt
- 상태·Claimed Device

### MobileRefreshToken

- Token Hash
- Device/Family
- Expiry·Consumed·Revoked
- Replacement Chain

### MobileCapture

- Device·Client Capture ID
- Content Hash·Plan ID
- 상태·처리 Lock·오류·처리시각

### PushNotification

- Device·Event/Entity
- Privacy-safe Payload
- Idempotency Key
- 상태·시도·다음시도·Lock·오류

## 12. CLI

```bash
# Production readiness
action-hub check --json

# QR 생성
action-hub mobile-pairing \
  --base-url https://hub.example.com \
  --qr-output ./pairing.svg \
  --print-qr

# 연결 기기 확인
action-hub mobile-devices

# 분실·폐기 기기 즉시 해제
action-hub mobile-revoke <device_id>
```

## 13. 환경변수

```dotenv
ACTION_HUB_MOBILE_ENABLED=true
ACTION_HUB_MOBILE_PUBLIC_BASE_URL=https://hub.example.com
ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET=<별도 32자 이상 고엔트로피 Secret>
ACTION_HUB_MOBILE_ACCESS_TOKEN_MINUTES=15
ACTION_HUB_MOBILE_REFRESH_TOKEN_DAYS=30
ACTION_HUB_MOBILE_REFRESH_REUSE_GRACE_SECONDS=30
ACTION_HUB_MOBILE_PAIRING_TTL_SECONDS=300
ACTION_HUB_MOBILE_PAIRING_MAX_ATTEMPTS=5
ACTION_HUB_MOBILE_CAPTURE_BATCH_SIZE=50
ACTION_HUB_MOBILE_CHANGE_BATCH_SIZE=200
ACTION_HUB_MOBILE_MIN_IOS_APP_VERSION=0.1.0
```

APNs:

```dotenv
ACTION_HUB_APNS_TEAM_ID=
ACTION_HUB_APNS_KEY_ID=
ACTION_HUB_APNS_BUNDLE_ID=com.jmactionhub.ios
ACTION_HUB_APNS_PRIVATE_KEY_PATH=/run/secrets/AuthKey_XXXX.p8
ACTION_HUB_APNS_ENVIRONMENT=production
```

## 14. 단계별 완료 기준

| 단계 | 완료 조건 |
|---|---|
| S1 Schema | v0.7 데이터 유지, 0004 Migration 성공 |
| S2 Pairing | Code 평문 미저장, TTL·Attempt·Single-use 검증 |
| S3 Session | Access/Refresh 회전, Reuse 폐기, 기기별 Revoke |
| S4 Capture | Batch·Idempotency·동시성·Stale Lock 복구 |
| S5 Review | Revision 409, Edit·Approve·Reject·Execute |
| S6 Sync | Dashboard·Activity·Cursor Pagination |
| S7 Push | Token 등록·Outbox·Retry·Generic Payload |
| S8 Contract | OpenAPI Export·Swift Client Live Smoke |

## 15. 완료 경계

서버 코드와 자동 검증 범위:

- 구현 완료
- SQLite Migration 및 실제 HTTP E2E 완료
- Swift Core Client와 실제 서버 Contract Smoke 완료
- Production Setting Guard 완료

외부 환경 인수 범위:

- 실제 Apple Developer Team/App ID/App Group 등록
- 실제 APNs `.p8` Key와 Production Device Token
- 인터넷 공개 HTTPS Reverse Proxy
- PostgreSQL/Docker Host의 장시간 동시성 시험
