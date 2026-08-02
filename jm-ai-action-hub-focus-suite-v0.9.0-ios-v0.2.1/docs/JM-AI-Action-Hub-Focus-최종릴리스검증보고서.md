# JM-AI Action Hub Focus Control Suite
## 최종 릴리스 검증 보고서

- Server: v0.9.0
- iOS: v0.2.1
- 검증일: 2026-08-01

# 1. 판정표

| 대상 | 결과 |
|---|---|
| Server source/runtime | GO |
| SQLite/PostgreSQL model/migration | GO |
| v0.8.0 → v0.9.0 upgrade | GO |
| OpenAPI contract | GO |
| HTTP focus flow | GO |
| Swift Core/API contract | GO |
| Native iOS source release | GO |
| Xcode iOS SDK build/signing | Apple 환경 인수 필요 |
| 실기기 Live Activity | Apple 환경 인수 필요 |
| APNs Live/TestFlight | Apple 환경 인수 필요 |

# 2. Server 검증

## Tests

```text
86 passed
warnings-as-errors passed
```

## Coverage

```json
{
  "files": 60,
  "statements": 6301,
  "missing": 1089,
  "coverage_percent": 82.717,
  "gate_percent": 80.0,
  "gate_passed": true
}
```

## Static/Contract

- Python compileall: PASS
- JavaScript app.js: PASS
- JavaScript share-target.js: PASS
- OpenAPI export/check: PASS
- Paths: 77
- Operations: 80
- Unique operation IDs: PASS
- SHA-256: `b5ae0361a4b4b1cf22f29ff4742d927f6fa839e2faebca7a1a805842eaa10fbc`

# 3. Focus 기능 검증

- suggested assessment
- user classification
- terminal action rejection
- Q4 non-destructive behavior
- revision conflict
- Matrix grouping
- Human/AI Big3 limit/duplicate/capacity
- Micro Step generate/update
- single active focus at service and DB level
- pause/resume/extend
- actual-time calculation
- traffic state
- complete/abandon
- optional action completion evidence
- all Day Close decisions
- weekly analytics
- mobile scope and API

# 4. 실제 HTTP E2E

검증 Flow:

```text
Pairing
→ Device Token
→ Capture
→ Plan edit
→ Approval/Execution
→ Q1 classify
→ Human Big3
→ 4 Micro Steps
→ Focus start
→ pause
→ resume
→ complete
→ Matrix
→ Weekly report
→ Push dry-run
→ Device revoke
```

핵심 결과:

```text
server_version          0.9.0
classified              q1
human_big3              1
microsteps              4
focus_state             completed
stale_revision          409
push                     simulated
revoked_access          401
revoked_refresh         401
```

# 5. Swift E2E

실제 Swift ActionHubCore client가 FastAPI v0.9.0에 연결해 다음을 완료했다.

```text
Pairing/Capabilities
Capture/Plan
Classify Q1
Human Big3
5 Micro Steps
Focus session complete
Weekly report
```

# 6. iOS Source Gate

```text
XCODEPROJ_CHECK_OK
OpenAPI contract OK
IOS_PROJECT_STATIC_OK sources=30
36 XCTest passed
1 Swift Testing smoke passed
swift-format strict passed
53 Swift files parsed
Plist/Entitlement/Privacy Manifest lint passed
IOS_RELEASE_SOURCE_CHECK_OK
```

검증된 호환성:

- server v0.9.0 contract
- Dynamic path encoding
- HTTP loopback only exception
- Remote HTTP rejection
- Pairing payload validation
- refresh/retry
- offline queue concurrency/migration
- Focus Codable
- Focus API paths
- Widget v0.1 cache compatibility

# 7. Migration 검증

실제 v0.8.0 코드를 사용해 Plan 1개·Action 2개가 있는 SQLite DB를 생성한 뒤 v0.9.0으로 업그레이드했다.

결과:

- Alembic Head: `0005_decision_focus_foundation`
- Plan count/ID 보존
- Action count/ID/title 보존
- attention_state=untriaged
- 신규 Focus 테이블 6개
- 기존 Plan API 200
- Triage total 2

# 8. 보안·안전 검증

- Q4는 삭제하지 않음
- Q3는 자동 Worker Dispatch 없음
- Focus Complete는 기본적으로 외부 Action Complete 아님
- stale revision 409
- single active focus DB unique
- App Intent 직접 승인/실행 없음
- Widget/Live Activity privacy-sensitive
- Push 원문 없음
- remote HTTP 거부
- device revoke 후 access/refresh 거부

# 9. 정확한 미검증 경계

현재 실행환경에는 Xcode와 Apple iOS SDK가 없다. 따라서 다음을 완료했다고 주장하지 않는다.

- iOS Simulator/Device target 실제 Xcode build
- Apple code signing
- Archive/IPA
- Lock Screen/Dynamic Island 실기기 배치
- Siri/App Intents 실제 등록
- Widget timeline 실기기
- APNs Sandbox/Production
- TestFlight 설치

이 항목은 제공된 Xcode·TestFlight 인수 절차로 macOS/Apple 계정에서 수행한다.

Ruff 실행파일도 현재 환경에 없어 로컬 Ruff 실행은 하지 못했다. Python tests, warnings-as-errors, compileall, OpenAPI, coverage는 통과했다.
