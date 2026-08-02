# Server v0.9.0 릴리스 검증 보고서

## 자동 검증

- Python 테스트: 86 passed
- Coverage.py statement 분석: 82.72%
- 기준 Gate: 80%
- Python compileall: PASS
- OpenAPI export/check: PASS
- OpenAPI paths: 77
- OpenAPI operations: 80, operation_id 중복 없음
- OpenAPI SHA-256: `b5ae0361a4b4b1cf22f29ff4742d927f6fa839e2faebca7a1a805842eaa10fbc`

## HTTP E2E

다음 실제 Uvicorn 경로를 검증했다.

```text
QR Pairing
→ Device Token
→ Offline Capture
→ Plan 수정
→ 승인·실행
→ Q1 분류
→ Human Big3
→ 4 Micro Steps
→ Focus Start/Pause/Resume/Complete
→ Matrix/Weekly Report
→ Push dry-run
→ Device Revoke
```

안전 검증:

- stale Action revision: HTTP 409
- tampered cursor: HTTP 400
- revoke 후 access/refresh: HTTP 401
- push: simulated, 원문 없음

## Swift E2E

Swift ActionHubCore가 실제 v0.9.0 FastAPI에 연결해 다음을 통과했다.

- Pairing/Token
- Capture/Plan
- 분류
- Dual Big3
- 5 Micro Steps
- Focus complete
- Weekly report

## Migration E2E

실제 v0.8.0 코드로 생성한 SQLite DB를 0005로 업그레이드했다.

- 기존 Plan 수·ID 보존
- 기존 Action 수·ID·Title 보존
- attention_state=untriaged 초기화
- 신규 Focus 테이블 6개 생성
- 업그레이드 후 기존 Plan API 200
- Triage에서 기존 Action 2개 조회

## 미실행 경계

- Linux 환경에 Xcode/iOS SDK가 없어 iOS Archive/Signing 미실행
- Apple Developer 계정·APNs 키·실기기가 없어 Live Activity/APNs/TestFlight 실환경 미실행
- Ruff 실행 파일이 제공되지 않아 Ruff 로컬 실행 미실행; CI 설정과 pyproject 규칙은 유지
