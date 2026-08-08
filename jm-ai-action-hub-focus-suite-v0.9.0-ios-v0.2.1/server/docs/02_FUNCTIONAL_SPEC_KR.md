# 기능 명세서 — JM-AI Action Hub v0.7.0

## F-01 AI Inbox

입력:

- `text`: 필수, 기본 최대 30,000자
- `source`: paste, voice, share, email, meeting, api, mcp
- `timezone`: 기본 `Asia/Seoul`
- `reference_time`: 재현 가능한 기준 시각
- `force_new`: 동일 원문을 별도 Plan으로 만들지 여부

처리:

1. 원문 정규화
2. 입력 fingerprint 계산
3. 기존 Plan 재사용 또는 새 Inbox 저장
4. Rules/LLM Parser 실행
5. 승인된 Personal Rule 기본값 적용
6. ActionPlan·ActionItem·감사 이벤트 저장

## F-02 Action 분리·분류

유형:

- `EVENT`: 시간 확정 회의·예약·방문
- `TODO`: 개인 실행 행동
- `PROJECT_TASK`: 개발·코드·테스트·배포 결과물
- `REMINDER`: 단순 알림
- `NOTE`: 참고 정보
- `NO_ACTION`: 인사·설명 등 실행 불필요

문장 분리:

- 줄바꿈, bullet, 세미콜론, 명시적 접속어
- 실행 문장으로 판단되는 경우에만 쉼표 분리
- 날짜 표현 내부 쉼표는 보존
- “미팅 전 확인”, “회의 후 보고”는 일정이 아닌 후속 Action으로 분류
- 최대 100개 fragment

## F-03 날짜·시간·Action Enrichment

추출 필드:

```text
start_at / end_at / due_at / deadline_at
earliest_start_at / latest_finish_at
estimated_minutes / actual_minutes
project / repository / assignee / labels / priority
work_mode / energy_level
executor / preferred_worker
waiting_for / follow_up_at / depends_on
```

규칙:

- EVENT는 날짜와 시각이 있어야 일반 승인 가능
- TODO의 날짜만 있으면 종일 마감
- “다음 주 중”, “오전”, “조만간”은 `needs_review=true`
- DB 저장은 UTC, 응답은 timezone-aware
- Deadline과 예정일은 별도 의미로 보존

## F-04 검토·승인

편집 가능:

- 유형, 목적지, 제목, 설명
- 시작·종료·마감·Deadline
- 프로젝트·저장소·담당자·라벨·우선순위
- 예상시간·Work mode·Energy
- 실행자·Worker
- Waiting-for·Follow-up

행동:

- 수정 저장
- 선택 승인
- 선택 제외
- 검토 항목의 명시적 강제 승인
- 승인된 항목만 등록/위임

서버는 클라이언트가 `needs_review=false`만 보내더라도 구조적 오류를 다시 검증한다.

## F-05 상태 머신

```text
draft → approved → queued → executing → registered
                                  ├→ waiting
                                  ├→ dispatched → running → needs_input
                                  │                         └→ human_review → completed
                                  ├→ blocked
                                  └→ failed → retry

별도 종료: rejected / skipped_duplicate / cancelled
```

Plan 상태:

```text
draft / approved / queued / routed / partial / completed / failed / rejected
```

`registered`는 외부 객체 생성 성공이며 실제 Action 완료가 아니다.

## F-06 Transactional Outbox

- 승인된 등록·Worker 위임 요청을 DB 트랜잭션으로 큐잉
- 목적지·작업·payload 기반 idempotency key
- `pending/retry → processing → completed/failed`
- 지수형 backoff와 최대 시도
- PostgreSQL `FOR UPDATE SKIP LOCKED`
- SQLite WAL·busy timeout
- 처리 중 Worker 종료 시 stale-lock 회수
- API inline drain 또는 별도 `action-hub-worker`

## F-07 Connector

### Todoist

- Task 생성, priority, label, project, due date/time, duration·deadline 지원 범위 반영
- `Action-Hub-ID` 표식으로 응답 유실 후 검색 복구
- 완료·미완료·수정·삭제 Webhook
- 주기적 상태 대조

### GitHub

- 저장소 선택: item repository → project route → optional default
- Issue 생성, label, assignee, Action ID 본문 표식
- Issue close/reopen
- Pull request, Workflow run, Check suite
- PR Merge URL을 완료 증거로 저장

### Google Calendar

- 시간/종일 일정
- 결정적 Event ID와 409 복구
- 단기 Access Token 또는 Refresh Token Broker
- 401 시 한 번 강제 갱신
- Push 대신 현재는 주기적 Reconciliation

### ICS

- RFC 5545 파일 생성
- API Key 보호 다운로드
- `Cache-Control: private, no-store`

## F-08 Signed Webhook Inbox

지원 Provider:

```text
todoist / github / fireflies
```

처리:

1. 요청 본문 크기 확인
2. Provider Secret 설정 확인
3. HMAC/Provider 서명 검증
4. Provider + Delivery ID unique 저장
5. 202를 빠르게 반환
6. inline 또는 Worker에서 비동기 처리
7. 실패·stale lock 재처리

동일 Delivery는 duplicate로 수락하되 두 번 적용하지 않는다.

## F-09 External State·Reconciliation

External State는 다음을 보존한다.

```text
provider / external_id / external_state
external_updated_at / last_synced_at
source_version / metadata / sync_error
```

Reconciliation:

- Webhook 누락·지연 보완
- Todoist/GitHub/Calendar 상태 조회
- 외부 최신 시각과 로컬 상태 비교
- 404는 삭제로 단정하지 않고 Sync Conflict 생성
- PR Merge 후 늦은 Workflow/Check 이벤트는 완료 하향 금지

## F-10 Human–AI Worker Router

실행자:

```text
human / ai / hybrid / external
```

Worker 후보:

```text
codex / claude / copilot / orca / hermes / master-worker
```

Action Hub는 Worker를 재개발하지 않고 설정된 GitHub `workflow_dispatch`를 호출한다.

상태:

```text
ready / queued / running / needs_input / plan_ready
pr_ready / verification_failed / human_review
approved / merged / completed / failed / cancelled
```

안전 규칙:

- 승인된 AI/Hybrid Action만 dispatch
- 활성 실행 중복 차단
- Workflow 성공은 완료가 아니라 `human_review`
- Action ID 상관관계가 불명확하면 `unmatched`
- 자동 Merge·운영 배포 금지

## F-11 Waiting-for·Follow-up

필드:

```text
waiting_for / channel / waiting_since
expected_by / follow_up_at / template
reminder_count / response_received_at / resolved_at
```

상태:

```text
waiting / follow_up_due / followed_up
response_received / resolved / expired / cancelled
```

Worker는 기한이 지난 항목을 `follow_up_due`로 전환하고 Today Decision에 노출한다.

## F-12 Daily Decision

입력:

- 대상 날짜
- 가용시간
- 최대 표시 항목
- AI 후보 포함 여부

출력:

- 가용시간
- 보호 Buffer
- 실제 계획 가능 시간
- 예정 작업시간
- 초과시간
- Top items
- Deferred items
- AI delegation candidates
- Overdue, Deadline, Dependency, Follow-up 위험

Calendar 시간표를 직접 수정하지 않는다.

## F-13 Fireflies Meeting Intake

- V2 Webhook 서명 검증
- `meeting.summarized` 처리
- GraphQL Transcript/summary 조회
- Action Item 정규화
- Draft Action Plan 생성
- Provider Delivery와 meeting ID 중복 방지
- 실패 Intake 재처리
- 승인 전 외부 원장 쓰기 금지

## F-14 Personal Rule

- 반복 수정값을 Project 단위로 관찰
- 최소 관찰 횟수와 안정 비율 확인
- `proposed` 상태로 생성
- 사용자 승인 후 `active`
- 안전 allowlist 필드만 적용
- 승인·외부 삭제·Token/API URL은 규칙으로 변경 불가

## F-15 Weekly ROI

보고 항목:

- 수집 원문, 생성 Action, 승인·등록·완료·지연
- Waiting-for와 Follow-up due
- AI 위임, Worker 성공·실패, PR Merge
- 중복 방지 건수
- Parser 수정·Rule 적용
- 추정 Human Touch Minutes와 절감시간
- 개선 권고

## F-16 REST·MCP·CLI

REST는 입력·승인·등록·상태·Worker·Follow-up·Planning·Meeting·Rule·Report·운영 제어를 제공한다.

MCP는 `parse → approve → execute/dispatch`를 분리한다.

CLI:

```text
action-hub serve
action-hub parse
action-hub migrate
action-hub check
action-hub worker-once
action-hub worker-sync
action-hub-worker [--once] [--reconcile]
```

`worker-sync`는 `master-worker` Worker(로컬 JM-AI Master Worker intake dispatch)의 `dispatched` 상태 Execution만 대상으로, MW 감사 로그(`GET /audit?objectType=intake&objectId=...`)를 조회해 상태를 갱신한다. Owner가 명시적으로 실행할 때만 동작하며 `worker-once`/`action-hub-worker`의 자동 루프에는 포함되지 않는다. 자세한 매핑과 한계는 §17을 참고.
