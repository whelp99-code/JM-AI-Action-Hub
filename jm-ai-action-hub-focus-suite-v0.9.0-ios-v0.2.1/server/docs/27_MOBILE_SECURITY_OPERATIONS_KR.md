# JM-AI Action Hub Mobile 보안·운영 가이드

- 대상: Server `0.8.0`, iOS `0.1.0`
- 작성일: 2026-07-31

## 1. 보호 대상

1. 원문 메시지·회의·고객 정보
2. Todoist·GitHub·Google·Fireflies 자격증명
3. Action 승인·실행 권한
4. AI Worker 실행 및 PR 상태
5. 모바일 장기 Session
6. APNs Private Key와 Device Token

## 2. 신뢰 경계

```text
iPhone App / Share Extension
  ├─ 신뢰: 기기 Keychain, App Group Container
  └─ 비신뢰: Clipboard, 다른 앱의 Share Payload, Custom URL

Internet
  └─ 비신뢰: Replay, MITM, 지연·중복·순서역전

Action Hub Server
  ├─ 신뢰: Environment Secret, DB, APNs .p8
  └─ 최소권한: 기기 Scope, Provider Token Scope
```

## 3. 위협과 완화

| 위협 | 완화 |
|---|---|
| 관리자 API Key의 iPhone 저장 | QR Claim으로 기기 Token만 발급 |
| Pairing Code DB 유출 | HMAC Hash만 저장, 5분 TTL, 최대 5회 |
| Pairing 중복 Claim | Compare-and-set Single-use Claim |
| Access Token 탈취 | 15분 수명, Device Token Version, Scope |
| Refresh Token 복제 | Rotation Family, Reuse 탐지 시 기기 폐기 |
| 응답 유실 오탐 폐기 | 30초 Lost-response Grace와 동일 Replacement |
| 기기 분실 | 관리자 CLI/API Remote Revoke |
| 앱·Extension 중복 Upload | Client ID + Content Hash + Unique Constraint |
| Parser 도중 서버 중단 | Stale Capture Lock Timeout Recovery |
| 동시 수정 덮어쓰기 | Plan/Item Revision 및 HTTP 409 |
| Push에 민감정보 노출 | Generic Title/Body + 내부 Entity ID만 전송 |
| APNs 장애 | Transactional Push Outbox·Retry·Stale Lock |
| Custom URL 자동 자격증명 Claim | iOS에서 사용자 확인 전 자동 Claim 금지 |
| HTTP 서버 연결 | Remote Host는 HTTPS만 허용, Loopback만 HTTP 예외 |

## 4. Production 필수값

```dotenv
ACTION_HUB_APP_ENV=production
ACTION_HUB_API_KEY=<32자 이상 고엔트로피>
ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET=<API Key와 다른 32자 이상 Secret>
ACTION_HUB_MOBILE_PUBLIC_BASE_URL=https://hub.example.com
ACTION_HUB_ALLOWED_ORIGINS=https://hub.example.com
```

검사:

```bash
action-hub check --json
```

`production_ready=false`이면 운영 트래픽을 받지 않는다.

## 5. Secret 관리

- `.env`를 Git에 Commit하지 않는다.
- APNs `.p8`는 저장소·ZIP·iPhone에 포함하지 않는다.
- Container에서는 Read-only Secret Mount를 사용한다.
- API Key와 Mobile Token Secret을 분리한다.
- Provider Token에는 대상 Repository/Calendar 등 최소 권한만 부여한다.
- 로그에 Authorization, Refresh Token, Pairing Code, APNs Token 평문을 기록하지 않는다.

## 6. HTTPS와 네트워크

권장 순서:

```text
Internet / Tailscale
  → TLS 1.2+ Reverse Proxy
  → Action Hub API
  → PostgreSQL/SQLite는 외부 비공개
```

- 공개 포트를 직접 열기보다 VPN 또는 Zero-trust Access 우선
- Pairing QR의 Server URL과 인증서 Hostname 일치
- Reverse Proxy Request Body 제한 1MiB 이하
- Rate Limit: Pairing Claim, Refresh, Capture Batch를 별도 Bucket으로 제한
- 서버 시계 NTP 동기화: Token `iat/exp`, APNs Provider Token에 필요

## 7. 기기 Lifecycle

### 신규 연결

1. 관리자 화면/CLI에서 Pairing 생성
2. 사용자가 iPhone 앱에서 QR을 직접 스캔
3. Server URL·기기 이름 확인
4. 연결 후 Device List 확인
5. Test Push는 `dry_run`에서 먼저 검증

### 분실 또는 교체

```bash
action-hub mobile-devices
action-hub mobile-revoke <device_id>
```

효과:

- Device 상태 revoked
- `token_version` 증가
- 모든 Refresh Token 폐기
- APNs Token 제거
- 기존 Access Token 즉시 거부

### 앱 연결 해제

앱은 서버 Remote Revoke를 시도한 뒤, 네트워크 실패와 관계없이 로컬 Keychain Session을 제거한다. Remote Revoke가 실패하면 관리자가 Device List에서 잔여 기기를 폐기한다.

## 8. APNs 운영

- Sandbox Build와 Production/TestFlight Token을 혼용하지 않는다.
- `ACTION_HUB_APNS_BUNDLE_ID`는 App Target Bundle ID와 정확히 일치해야 한다.
- `.p8` Key ID와 Team ID를 검증한다.
- Generic Payload 원칙을 유지한다.
- `BadDeviceToken`·`Unregistered` 발생 시 재시도하지 않고 Token 제거
- APNs 5xx/429/일시 오류는 Outbox Retry
- `dry_run`의 `simulated`는 실제 알림 수신을 의미하지 않는다.

## 9. 감사·모니터링

확인 대상:

- Pairing 실패·Lock 횟수
- Device 신규 연결·폐기
- Refresh Reuse 탐지
- Mobile Capture failed/processing 장기 체류
- Revision Conflict 빈도
- Push retry/failed
- Unauthorized/Forbidden 비율
- Server/iOS 최소 버전 불일치

경보 권장:

| 조건 | 경보 |
|---|---|
| Refresh Token Reuse 1건 | 즉시 High |
| 동일 IP Pairing 실패 급증 | High |
| Push Failed 연속 10건 | Medium |
| Processing Lock Timeout 회수 반복 | Medium |
| 401 비율 급증 | Medium |
| DB Migration 불일치 | 배포 차단 |

## 10. Backup과 Migration

```bash
./scripts/backup.sh
./scripts/upgrade.sh
```

v0.8.0 Migration 전후 필수 확인:

```text
inbox_entries count 동일
action_plans count 동일
action_items count 동일
audit_events count 동일
revision 기본값 1
mobile_* / push_notifications 신규 테이블 존재
```

Rollback이 필요하면 DB와 소스를 함께 Backup 시점으로 복구한다. Schema만 Downgrade하고 v0.8 앱을 계속 실행하지 않는다.

## 11. Incident Response

### Refresh Reuse

1. 해당 Device 자동 폐기 여부 확인
2. 관련 IP/로그/시간대 조사
3. Mobile Token Secret 유출 가능성 평가
4. 필요 시 전체 Mobile Secret Rotation
5. 모든 Device 재페어링

### APNs Key 유출

1. Apple Developer Portal에서 Key 폐기
2. 서버 Secret 교체
3. Outbox 재처리 전 새 Key 검증
4. Repository/Artifact에 Key가 포함됐는지 검사

### 원문 유출

1. 해당 Device·Session 폐기
2. Capture/Audit 접근 로그 확인
3. Backup과 로그 보존 정책에 따라 삭제·통지 판단
4. Push Payload에 원문이 포함되지 않았는지 확인

## 12. 현재 보안 경계

구현 완료:

- 기기별 Auth·Scope·Revoke
- Refresh Rotation/Reuse Detection
- HTTPS Guard
- Offline Idempotency/Lock Recovery
- Revision Conflict
- Generic APNs Payload
- Keychain/App Group Protection 정책

운영자가 추가해야 하는 것:

- Reverse Proxy Rate Limit/WAF
- TLS Certificate 자동 갱신
- Secret Manager
- PostgreSQL 암호화·Backup
- 실제 Apple Signing/Provisioning
- 실제 Device MDM/Passcode 정책(팀 배포 시)
