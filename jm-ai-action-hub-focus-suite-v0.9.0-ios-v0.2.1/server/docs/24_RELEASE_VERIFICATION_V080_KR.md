# JM-AI Action Hub Server v0.8.0 릴리스 검증 보고서

검증 기준일: **2026-07-31 (Asia/Seoul)**

## 1. 판정

> 서버 v0.8.0의 소스, Alembic Migration, 모바일 인증·동기화 API, APNs Outbox, Python→HTTP→Swift 계약 흐름은 **Release Candidate 통과**로 판정한다.

운영 계정이 필요한 APNs Live와 Apple Signing/TestFlight는 iOS 운영 인수 범위이며, 서버 기능 미완료로 보지 않는다.

## 2. Python 자동 테스트

```text
78 passed
warnings treated as errors
statement coverage 81.27%
required threshold 80% PASS
```

검증 영역:

- 기존 v0.7 Parser, Approval, Transactional Outbox, Webhook, Worker, Follow-up 회귀
- 1회용 QR Pairing, 기기별 Scope, Access Token
- Refresh Token Rotation, 응답 유실 유예, 재사용 탐지와 기기 폐기
- Offline Capture Idempotency, Content Hash Conflict, 동시 요청 보호
- 처리 중 서버 중단 후 Stale Capture Lock 회수
- Plan/Item Optimistic Revision과 HTTP 409
- 모바일 Approval/Execution
- HMAC-SHA256 서명 Delta Cursor와 변조 거부
- APNs Push Outbox, Retry, Privacy-safe Payload
- 원격 기기 해제, Production HTTPS·Secret·Public URL Guard

## 3. OpenAPI 계약

```text
version: 0.8.0
operations: 56
sha256: ac795ac1fdc685cebd0cff041c50773d5156187e8912f838cd313ed65b4a96d8
```

서버에서 재생성한 계약과 저장소 Snapshot이 일치한다. iOS 저장소의 Snapshot도 같은 SHA-256을 사용한다.

## 4. v0.7.0 → v0.8.0 Migration

검증 절차:

```text
원본 v0.7.0 코드로 샘플 Inbox/Plan/Action/Audit 생성
→ v0.8.0 migration 0004_mobile_foundation 적용
→ ID, 제목, 개수, Alembic Head 비교
```

결과:

```text
Data preserved: YES
Inbox: 1 → 1
Plan: 1 → 1
Action Item: 2 → 2
Audit: 1 → 1
Plan revision: 1
Item revisions: 1, 1
New mobile tables: 5
Head: 0004_mobile_foundation
```

기존 업무 데이터는 보존되고 revision 및 모바일 전용 테이블만 추가됐다.

## 5. 실제 HTTP 통합 검증

실제 Uvicorn 서버에서 Python 모바일 클라이언트가 다음을 수행했다.

```text
Capabilities
→ Pairing Claim
→ Dashboard
→ Offline Capture Upload
→ Stale Revision Update
→ 정상 Revision Update
→ Approve
→ Execute
→ Changes/Activity
→ Push Token/Test Outbox
→ Device Revoke
→ 폐기 Access/Refresh Token 재사용
```

결과:

```text
capture_status: processed
stale_revision_status: 409
execution_completed: 2
execution_failed: 0
push_processed: 1
push_state: simulated
revoked_access_status: 401
revoked_refresh_status: 401
server_version: 0.8.0
```

## 6. Swift Client ↔ FastAPI E2E

Linux Swift 6.2.1에서 빌드한 `ActionHubMobileSmoke`가 실제 FastAPI 서버에서 다음을 완료했다.

```text
Capabilities
→ QR Payload Parse
→ Pairing Claim
→ Bearer Dashboard
→ Capture
→ Plan Fetch
→ Revisioned Item Patch
→ Approve
→ Execute
→ Activity
→ Delta Changes
```

결과:

```text
capture_status: processed
execution_completed: 1
execution_failed: 0
activity_count: 10
change_count: 10
server_version: 0.8.0
```

## 7. Delta Cursor·Refresh 적대적 검증

```text
Delta Change limit=1
→ HMAC 서명 Cursor 반환
→ 정상 Cursor로 다음 페이지 조회
→ 마지막 문자를 변조한 Cursor 재전송
```

결과:

```text
signed_cursor_contains_separator: true
tampered_cursor_status: 400
second_page_changes: 1
```

Refresh 응답 유실 시나리오:

```text
R1로 Refresh → R2 발급 → 응답 유실 가정 → 유예기간 안에 R1 재전송
```

결과:

```text
refresh_retry_status: 200
refresh_retry_same_successor: true
```

유예기간을 벗어난 이전 Refresh Token 재사용은 Token Family와 기기를 폐기한다.

## 8. Production QR URL 보안

Production에서는 요청의 `Host` Header로 Pairing QR 목적지를 추론하지 않는다.

허용 경로:

```text
관리자가 요청 Payload에 public_base_url 명시
또는
ACTION_HUB_MOBILE_PUBLIC_BASE_URL 구성
```

둘 다 없으면 Pairing 생성이 실패한다. Host Header Injection으로 악성 Pairing URL이 만들어지는 경로를 차단한다.

## 9. 정적 검증

- Python `compileall` with warnings-as-errors
- JavaScript syntax
- OpenAPI Drift
- Git whitespace/error check
- Production readiness guard
- QR SVG/terminal renderer
- Secret exclusion and scope tests

## 10. 미실행 경계

현재 Linux 검증 환경에서는 다음을 실행할 수 없다.

- Xcode iOS App/Share/Widget Target SDK Build
- Apple Code Signing/Provisioning
- 실제 카메라, 마이크, Face ID
- 실제 Share Sheet Host App 동작
- Widget/App Intents 시스템 등록
- APNs Sandbox/Production Live
- TestFlight Upload/Install

이 항목은 iOS 저장소의 `docs/09_TESTFLIGHT_DEVICE_ACCEPTANCE_KR.md` 순서로 macOS와 실제 iPhone에서 인수한다.


## 11. 최종 iOS 페어링 계약 재검증

```text
Server claim_uri scheme      jmactionhub
Swift Client Pairing Parse   PASS
Swift → FastAPI E2E          PASS
QR scan automatic claim      disabled
Duplicate query rejection    PASS
```

서버가 발급하는 Custom URL을 프로젝트 전용 `jmactionhub://pair`로 변경하고, iOS 앱이 QR 스캔 직후 자동 Claim하지 않도록 최종 계약을 다시 검증했다.
