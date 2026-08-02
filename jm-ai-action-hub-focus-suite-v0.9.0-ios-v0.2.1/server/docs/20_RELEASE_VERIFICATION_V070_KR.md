# JM-AI Action Hub v0.7.0 릴리스 검증 보고서

- 검증일: 2026-07-29
- 검증 대상: 소스 트리, 설치 Wheel, 배포 ZIP
- 기준 시간대: Asia/Seoul
- 검증 환경: Linux x86_64, Python 3.13.5, Node.js 22.16.0
- 지원 Python: 3.12 이상

## 1. 자동 테스트

실행:

```bash
PYTHONPATH=. python -m pytest -W error \
  --cov=action_hub --cov-fail-under=80 --cov-report=term-missing
```

결과:

```text
54 passed
warnings treated as errors
TOTAL statement coverage 80.59%
coverage threshold 80% PASS
```

검증 범주:

| 범주 | 결과 |
|---|---|
| Parser·날짜·Action enrichment | 통과 |
| 승인·거부·구조적 재검증 | 통과 |
| 입력·Action·Outbox 중복 방지 | 통과 |
| Todoist/GitHub/Google/ICS Connector | 통과 |
| v0.1 DB Migration | 통과 |
| Outbox Claim·Retry·Stale Lock | 통과 |
| Webhook HMAC·Delivery 중복·Stale Lock | 통과 |
| Todoist 완료·미완료 상태 전환 | 통과 |
| GitHub Issue close/reopen | 통과 |
| Workflow·Check Suite·PR·Merge | 통과 |
| 이벤트 순서 역전 시 완료 보존 | 통과 |
| Reconciliation·Sync Conflict | 통과 |
| Google OAuth refresh·401 retry | 통과 |
| Follow-up lifecycle | 통과 |
| Daily Decision·Overload | 통과 |
| Fireflies Intake·재처리 | 통과 |
| Personal Rule 안전 필드 | 통과 |
| Weekly ROI | 통과 |
| REST·MCP·CLI Entry Point | 통과 |
| CSP·Cache·Share Target·본문 제한 | 통과 |
| Connector active probe | 통과 |

## 2. 정적 검증

```bash
python -W error -m compileall -q action_hub tests
node --check action_hub/web/app.js
node --check action_hub/web/share-target.js
git diff --check
```

결과:

```text
PYTHON_COMPILE_OK
JS_APP_SYNTAX_OK
JS_SHARE_TARGET_SYNTAX_OK
GIT_DIFF_WHITESPACE_OK
```

현재 실행 환경의 내부 Python Package Index에는 Ruff 배포본이 없어 로컬 Ruff 실행은 불가능했다. `.github/workflows/ci.yml`과 `scripts/verify.sh`에는 `ruff check .`가 포함되어 있다. 릴리스 결과에는 Ruff를 실행했다고 기재하지 않는다.

## 3. 실제 HTTP 통합 Smoke

별도 Uvicorn 프로세스를 Production 설정·안전한 API Key·임시 SQLite DB·별도 Worker 모드로 기동했다.

검증 Endpoint:

```text
GET  /health
GET  /readiness
POST /api/v1/inbox/parse
POST /api/v1/plans/{id}/approve
POST /api/v1/plans/{id}/execute
POST /api/v1/control/run-once
GET  /api/v1/plans/{id}
GET  /api/v1/exports/{id}.ics
POST /api/v1/planning/decision
GET  /api/v1/brief/today
GET  /api/v1/reports/weekly
GET  /api/v1/connectors/status?probe=true
POST /share-target  — 과대 본문
```

결과:

```json
{
  "health": 200,
  "readiness": 200,
  "parsed_items": 2,
  "outbox_processed": 2,
  "ics": 200,
  "decision": 200,
  "brief": 200,
  "weekly": 200,
  "connectors": 5,
  "oversized": 413
}
```

추가 확인:

- 인증 없는 보호 API 401
- Production HSTS Header
- Outbox 처리 후 두 Action 모두 `registered`
- 보호된 ICS에 `BEGIN:VCALENDAR`
- ICS `Cache-Control: private, no-store`
- 1MiB 초과 Share 요청 413과 no-store

## 4. Wheel 검증

격리 빌드가 아닌 현재 환경의 검증된 Setuptools로 다음을 실행한다.

```bash
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
```

검증 항목:

- Wheel metadata version `0.7.0`
- PWA 파일 포함
- `share-target.js` 포함
- Alembic env·template·0001/0002/0003 revision 포함
- 임시 target 설치
- 설치된 Wheel에서 SQLite Migration
- 설치된 Wheel에서 한국어 복합 문장 Parse

결과:

```text
WHEEL_BUILD_OK
WHEEL_CONTENT_OK
WHEEL_IMPORT_MIGRATE_PARSE_OK
```

## 5. 보안 검증

- Production placeholder·짧은 API Key 거부
- 인증 없는 보호 API 401
- Webhook Secret 미설정 Production 503
- 잘못된 HMAC 401
- 동일 Delivery 중복 적용 차단
- 요청 본문 기본 1MiB 제한과 413
- 원문을 GET query로 받는 Share Target 405
- POST 공유 원문 URL 비노출
- API/Share `Cache-Control: no-store`
- CSP `script-src 'self'`
- Frame 차단, nosniff, referrer 차단
- Production HSTS
- ICS 보호 다운로드
- Token·Secret DB 저장 금지
- AI 실행·Merge·배포의 Human Approval Gate

## 6. 배포 ZIP 검증 절차

릴리스 생성 시 다음을 수행한다.

```text
불필요 파일과 Secret 제외
RELEASE_MANIFEST.sha256 생성
ZIP 생성
ZIP 별도 디렉터리에 압축 해제
Manifest 전체 검증
압축 해제본에서 54개 테스트 재실행
Python/JavaScript 구문 재검사
Wheel과 ZIP SHA-256 생성
```

최종 파일 Hash는 외부 `SHA256SUMS-jm-ai-action-hub-v0.7.0.txt`에 기록한다.

## 7. 운영 계정 인수 제외

다음은 소프트웨어 결함 때문이 아니라 사용자 계정·외부 환경이 없어 실행하지 않았다.

| 항목 | 릴리스 검증 범위 | 운영 인수 |
|---|---|---|
| Todoist Live | Mock·Payload·Signed Fixture·Reconciliation | 테스트 Project 생성·완료·미완료 |
| GitHub Live | Mock·Payload·Signed Event·Worker Loop | 테스트 Repo Issue·Workflow·PR·Merge |
| Google Live | OAuth Broker Mock·Calendar Payload·ICS | 실제 Consent·Refresh Token·Calendar |
| Fireflies Live | Signed Event·GraphQL Mock·Reprocess | 실제 Workspace Webhook·Transcript |
| Docker daemon | Dockerfile·Compose 정적 검토·CI build 정의 | 대상 Host 실제 build/up |
| PostgreSQL server | SQLAlchemy·Alembic 경로·Compose 정의 | 대상 DB Migration·부하 확인 |
| 실제 스마트폰 | Responsive PWA·Share Target 코드 | HTTPS 주소에서 홈 화면·공유 시트 |
| Ruff local | CI와 Verify script 정의 | 네트워크 가능한 CI에서 실행 |

## 8. 릴리스 판정

```text
JM-AI Action Hub v0.7.0 개인용 Closed-loop 소프트웨어 릴리스 가능
외부 Provider는 사용자 계정별 1회 Live 인수 후 활성화
Production API+Worker 다중 프로세스는 PostgreSQL 권장
자동 Merge·운영 배포·고객 발송은 의도적으로 제외
```
