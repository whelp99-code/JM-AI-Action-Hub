# JM-AI Action Hub v0.7.0 테스트 및 인수 기준

## 1. 자동 테스트 범위

| 영역 | 핵심 검증 |
|---|---|
| Parser | 한국어 다중 문장, 상대 날짜·시간, 일정/Todo/GitHub 분류, Action enrichment |
| Approval | 검토 강제, 편집, 선택 승인·거부, 상태 전이 |
| Migration | v0.1 직접 생성 DB → Alembic 최신 Head |
| Outbox | 트랜잭션 기록, 선점, Retry, stale-lock 복구, 중복 방지 |
| Webhook | HMAC 위조 거부, Delivery 중복, stale-lock 복구 |
| Todoist Sync | 완료·미완료·삭제 및 외부 원장 우선 상태 |
| GitHub Sync | Issue close/reopen, Workflow, Check Suite, PR, Merge, 이벤트 순서 역전 |
| Reconciliation | 누락 상태 복구와 비파괴 Conflict |
| OAuth | Refresh Token 캐시, 401 강제 갱신 재시도 |
| Worker | 중복 위임 차단, Workflow→Human Review→Merge 완료 |
| Follow-up | 대기·만료·응답·후속 연락·해결 |
| Planning | 가용시간·Buffer·Overload·Top·Deferred·AI 후보 |
| Fireflies | 서명, Action Item Plan, 중복, 실패 재처리 |
| Personal Rules | 제안·승인·안전 필드 제한·적용 |
| Weekly ROI | 등록·완료·대기·지연·AI 위임·절감시간 |
| API/MCP/CLI | 주요 REST, MCP Adapter, CLI와 Worker entry point |
| PWA/Security | CSP, no-store, URL 비노출 Share Target, 요청 본문 제한, API Key |
| Connectors | dry-run/live mock payload, active probe, ICS 보호 다운로드 |

현재 자동 테스트는 **53개 pytest test function**으로 위 범주를 검증한다.

## 2. 검증 명령

```bash
PYTHONPATH=. python -m pytest -W error \
  --cov=action_hub --cov-fail-under=80 --cov-report=term-missing
python -W error -m compileall -q action_hub tests
node --check action_hub/web/app.js
node --check action_hub/web/share-target.js
git diff --check
```

현재 기준:

```text
54 passed
statement coverage >= 80%
Python compile: PASS
JavaScript syntax: PASS
warnings as errors: PASS
```

현재 실행 환경의 패키지 저장소에는 Ruff가 없어 로컬 실행하지 못했다. `.github/workflows/ci.yml`과 `scripts/verify.sh`에는 `ruff check .`가 포함되어 있으며, 릴리스 판정에서는 실행하지 않은 검사를 실행했다고 주장하지 않는다.

## 3. 핵심 인수 시나리오

### AT-01 입력·승인·등록

```text
내일 오전 10시 고객 미팅,
미팅 전에 GPU 라이선스 확인,
repo:owner/repo 로그인 오류를 codex로 수정
```

통과 조건:

- EVENT, TODO, PROJECT_TASK로 분리
- 서울 시간의 절대 시각
- 검토·승인 전 외부 쓰기 없음
- 승인 후 Outbox에 기록
- dry-run에서 실제 외부 변경 없음

### AT-02 Todoist 폐쇄 루프

통과 조건:

- 등록된 Todoist 작업의 완료 Webhook으로 Action `completed`
- 미완료 이벤트로 Action 재개
- 동일 Delivery는 한 번만 처리
- 누락 이벤트는 Reconciliation으로 복구

### AT-03 GitHub AI 폐쇄 루프

통과 조건:

- Issue 등록 후 승인된 AI Action만 Worker dispatch
- Workflow 성공 시 `human_review`
- Check 실패 시 검증 실패 상태
- PR Merge URL을 완료 증거로 저장
- Merge 후 늦은 Workflow 이벤트가 완료를 되돌리지 않음

### AT-04 Follow-up

통과 조건:

- 응답 대상·예상일·확인일 저장
- 확인일이 지나면 due 목록 표시
- 응답 도착 시 종료
- 후속 연락 후 다음 확인일 설정 가능

### AT-05 Fireflies

통과 조건:

- `meeting.summarized` 서명 검증
- Action Item을 Draft Plan으로 생성
- 즉시 Todoist/GitHub에 쓰지 않음
- 같은 회의 Delivery 중복 방지
- 실패 Intake 재처리 가능

### AT-06 v0.1 업그레이드

통과 조건:

- 백업 후 `./scripts/upgrade.sh`
- 기존 Inbox·Plan·Item 유지
- Alembic Head가 최신 버전
- 새 Outbox/Webhook/Follow-up/Rule 테이블 생성
- `/readiness` ready

### AT-07 보안

통과 조건:

- Production placeholder/짧은 API Key 거부
- 인증 없는 보호 API 401
- 잘못된 Webhook HMAC 401
- Secret 미설정 Production Webhook 503
- 과대 요청 본문 413
- Share 원문 URL query 미사용
- API와 Share 응답 no-store

## 4. 운영 Live 인수

테스트 프로젝트와 테스트 캘린더를 사용해 Provider별 한 항목만 검증한다.

1. dry-run payload 확인
2. Provider 자격증명과 Webhook Secret 등록
3. live 모드에서 하나의 Action 승인·등록
4. 외부 원장의 ID·URL과 Action Hub 기록 비교
5. 외부에서 완료·재오픈·병합하여 상태 회수 확인
6. 같은 Delivery·실행 재전송으로 중복 방지 확인
7. 테스트 항목 정리

## 5. 최종 합격 기준

- 자동 테스트 100% 통과, coverage 80% 이상
- HTTP smoke, Wheel 설치·import, 압축 해제 후 테스트 재통과
- P0 보안 체크리스트 완료
- Provider별 Live smoke 1회 통과
- 실제 스마트폰에서 Capture→Review→Approve 흐름 통과
- 7일 실사용 중 데이터 유실 0건
- 외부 상태 불일치와 충돌이 감사 로그로 추적 가능
