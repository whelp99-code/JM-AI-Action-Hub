# JM-AI Action Hub Mobile 보안·운영 가이드

- 대상: Server `0.9.0`, native iOS `0.2.1`
- 작성일: 2026-08-03

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

### unsigned webhook 플래그

`ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS=false`가 기본값이다. Provider signing secret이 없는 수신을 허용해야 한다면 development/test에서만 명시적으로 `true`를 설정한다. production은 플래그 값과 무관하게 unsigned webhook을 거부하며, 이미 queue에 든 unsigned delivery도 처리 직전에 현재 정책을 다시 검사한다.

## 5. Secret 관리

- `.env`를 Git에 Commit하지 않는다.
- APNs `.p8`는 저장소·ZIP·iPhone에 포함하지 않는다.
- Container에서는 Read-only Secret Mount를 사용한다.
- API Key와 Mobile Token Secret을 분리한다.
- Mobile Token Secret은 API Key와 다른 32자 이상 고엔트로피 값이어야 한다. 같은 값이면 모바일 인증은 차단된다.
- Development에서 Mobile Token Secret이 비어 있고 안전한 API Key만 있으면, 서버는 versioned HKDF-SHA256으로 domain-separated 32-byte 모바일 서명 키를 파생한다. API Key 원문은 모바일 서명 키로 사용하지 않는다.
- HKDF fallback을 사용한 상태에서 API Key 또는 Mobile Token Secret을 바꾸면 기존 Access/Refresh Token은 무효가 될 수 있으므로 모든 기기를 재페어링한다. Production에서는 항상 독립된 Mobile Token Secret을 설정한다.
- Mobile Token Secret이 누락되었거나 template placeholder이거나 API Key와 같으면 Claim, Refresh, Bearer API 모두 credential 검사 전에 503으로 차단되며 기기·토큰 상태는 변경하지 않는다.
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

## 10. iOS dead-letter 운영

iOS App Group queue는 `captures/` 아래 pending, dead-letter, corrupt record를 분리한다. 서버 `failed` receipt가 같은 Capture에 5회 누적될 때만 dead-letter가 생성되며, network/transport 예외는 attempt count를 증가시키지 않는다.

복구 절차:

1. iOS Settings > 오프라인 수집 진단에서 Dead Letter 건수와 오류를 확인한다.
2. `모두 복원`을 실행하면 각 record가 retry metadata 없이 pending으로 돌아간다. pending에 같은 client capture ID가 있으면 해당 복원은 중단되므로 원인을 먼저 확인한다.
3. 원문 보존 필요성을 확인한 뒤에만 `모두 삭제`를 선택하고, 표시되는 복구 불가 확인 대화상자를 승인한다. 자동 purge는 없다.

이 절차는 기기 내 queue의 수동 조치다. 서버의 capture API 또는 DB를 직접 삭제해 dead-letter를 해결하지 않는다.

## 11. Backup과 Migration

```bash
./scripts/backup.sh
./scripts/upgrade.sh
```

v0.9.0 배포 또는 migration 전후 필수 확인:

```text
inbox_entries count 동일
action_plans count 동일
action_items count 동일
audit_events count 동일
revision 기본값 1
mobile_* / push_notifications 신규 테이블 존재
```

Rollback이 필요하면 DB와 소스를 함께 Backup 시점으로 복구한다. Schema만 Downgrade하고 v0.8 앱을 계속 실행하지 않는다.

## 12. Incident Response

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

## 13. 현재 보안·검증 경계

구현 완료:

- 기기별 Auth·Scope·Revoke
- Refresh Rotation/Reuse Detection
- HTTPS Guard
- Offline Idempotency/Lock Recovery
- Revision Conflict
- Generic APNs Payload
- Keychain/App Group Protection 정책
- iOS dead-letter 수동 복구·확정 삭제 UI
- iOS full refresh 경로 (server Delta API는 호환성 유지)

운영자가 추가해야 하는 것:

- Reverse Proxy Rate Limit/WAF
- TLS Certificate 자동 갱신
- Secret Manager
- PostgreSQL 암호화·Backup
- 실제 Apple Signing/Provisioning
- 실제 Device MDM/Passcode 정책(팀 배포 시)
- Full Xcode XCTest, App Target/Extension build, simulator/실기기 Share Sheet·Widget·APNs·background refresh 인수

현재 iOS-XCTEST는 Full Xcode 필요 상태다. 서버 코드·문서 gate 또는 iOS 정적 검증만으로 device/build 인수가 완료됐다고 주장하지 않는다.
