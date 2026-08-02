# JM-AI Action Hub v0.9.0 — Decision & Focus Foundation 상세 검증·개발계획서

- 기준 버전: Server v0.8.0 / Native iOS v0.1.0
- 목표 버전: Server v0.9.0 / Native iOS v0.2.0·v0.2.1
- 기준 시간대: Asia/Seoul
- 작성·구현 기준일: 2026-08-01

## 1. 목적

Action Hub v0.8.0은 입력을 일정·Todo·GitHub 작업으로 바꾸고, 승인 후 외부 원장에 등록한 다음 실제 완료 상태까지 회수한다. 그러나 사용자가 매일 겪는 다음 의사결정은 아직 외부 앱에 흩어져 있었다.

1. 무엇이 중요하고 긴급한가.
2. 지금 실행할 일, 계획할 일, 위임할 일, 하지 않을 일은 무엇인가.
3. 오늘 사람이 직접 책임질 세 가지와 AI가 처리할 세 가지는 무엇인가.
4. 큰 일을 실제 시작 가능한 단계로 어떻게 나눌 것인가.
5. 예상시간을 넘긴 일을 연장·분할·위임·중단 중 무엇으로 처리할 것인가.
6. 미완료 작업을 왜 이월했는지 어떻게 기록하고 학습할 것인가.

v0.9.0의 목적은 새로운 Todo 앱이나 Calendar를 만드는 것이 아니라, 기존 원장 위에 **Action Focus Control Loop**를 추가하는 것이다.

```text
외부 원장의 실제 작업
        ↓
설명 가능한 우선순위 제안
        ↓
사용자 Triage(Q1/Q2/Q3/Q4)
        ↓
사람 Big3 / AI Big3
        ↓
Micro Steps
        ↓
Focus Session
        ↓
완료 증거 또는 승인형 Day Close
        ↓
주간 Focus 분석
```

## 2. 기존 앱·TRIX 기능 검증과 재사용 결정

TRIX에서 검증된 핵심 행동 흐름은 브레인 덤프, 스와이프 아이젠하워 분류, Big3, 집중 타이머, 마이크로 스텝, 신호등, Live Activity, 이월과 회고다. Action Hub는 이 흐름을 그대로 복제하지 않고 기존 구조에 다음처럼 흡수한다.

| 기능 | 판단 | Action Hub 적용 |
|---|---|---|
| 브레인 덤프·음성·공유 | 이미 보유 | 기존 Capture/Share/Speech 재사용 |
| 스와이프 분류 | 적용 | AI 제안 + 사용자 확인, 명시적 버튼·VoiceOver 병행 |
| Eisenhower Matrix | 적용 | 저장 원장이 아닌 의사결정 View |
| Big3 | 확장 적용 | Human Big3와 AI Big3 분리 |
| Pomodoro/Focus | 적용 | Action·실제시간·완료증거와 연결 |
| 마이크로 스텝 | 적용 | 단계별 Human/AI/Hybrid/External 실행자 |
| 신호등 | 적용 | 예정시간 대비 Green/Yellow/Red |
| 자동 이월 | 그대로 적용하지 않음 | 사유가 있는 명시적 Day Close |
| Calendar | 개발하지 않음 | 기존 Calendar 원장 유지 |
| Todo DB | 개발하지 않음 | Todoist/GitHub/Calendar 원장 유지 |
| Reminders Bridge | 후속 선택 기능 | 단일 원장 원칙 검증 후 도입 |
| 온디바이스 AI | 후속 | Foundation Models 지원 기기에서 v0.3 후보 |

### 고정 제품 경계

```text
Action Hub가 관리하는 것
- 원문의 출처와 승인 이력
- 우선순위 판단과 사용자 수정
- 오늘의 Commitments
- Focus Session과 실제시간
- 사람/AI 실행 배정
- 이월 사유와 완료 증거

기존 앱이 계속 관리하는 것
- Todoist 개인 업무 원장
- Calendar 일정 원장
- GitHub 개발 작업 원장
- Codex/Claude/Copilot/Orca/Hermes 실제 Worker
```

## 3. 핵심 설계 결정

### 3.1 실행 상태와 주의 상태 분리

등록·실행·완료 상태와 사용자의 오늘 집중 판단을 하나의 필드에 섞지 않는다.

```text
execution state
  draft → approved → queued → registered → running → completed/failed

attention state
  untriaged → classified → committed → focusing/paused
             → carried_over/skipped/completed
```

따라서 Q4로 분류해도 외부 작업을 삭제하지 않고, Focus를 끝내도 외부 완료로 자동 전환하지 않는다. `mark_action_completed=true`라는 명시적 요청이 있을 때만 완료 증거와 함께 Action을 완료한다.

### 3.2 설명 가능한 우선순위

규칙 엔진은 다음 신호를 0~100의 중요도·긴급도 점수와 근거로 변환한다.

- 작업 우선순위
- 전략·고객·매출·보안·운영 라벨
- 프로젝트·Repository 연결
- Deep Work 여부
- Deadline/Due/Start까지 남은 시간
- 후속 확인 시각 도래
- 재조정 횟수
- 실패 복구 필요
- 선행 작업 존재
- 사용자 검토 필요
- AI 위임 가능성

기본 임계값은 중요도 60, 긴급도 60이다.

```text
Q1 importance ≥ 60 and urgency ≥ 60
Q2 importance ≥ 60 and urgency < 60
Q3 importance < 60 and urgency ≥ 60
Q4 importance < 60 and urgency < 60
```

AI/규칙 제안은 자동 확정이 아니다. 사용자가 분류하면 source=user, confidence=1.0, user_overridden=true로 기록한다.

### 3.3 Dual Big3

- Human Big3: 사람이 직접 수행하거나 최종 검토해야 하는 최대 세 개
- AI Big3: AI Worker가 수행하고 사람이 결과를 확인할 최대 세 개
- 날짜별 가용시간과 선택 작업의 예상시간을 저장
- 초과분과 경고를 계산하되 선택을 강제로 차단하지 않음
- 동일 Action을 Human/AI 양쪽에 동시에 넣지 않음

### 3.4 Micro Steps

- 기본 3~5단계
- 단계별 executor: human / ai / hybrid / external
- preferred_worker와 estimated_minutes 선택 지원
- 자동 생성은 결정적 기본 분해로 제공하고, 사용자가 명시한 Steps가 있으면 이를 우선
- 복잡한 DAG/범용 Workflow Builder는 범위에서 제외

### 3.5 단일 활성 Focus Session

- running 또는 paused 세션은 시스템 전체에 하나만 허용
- 서비스 레벨 검사와 DB unique active_slot을 함께 적용
- 10/25/50/90분 preset, 서버 허용 최대 240분
- pause 중 시간은 실제 집중시간에서 제외
- extend는 명시적 분 단위 연장
- complete와 abandon을 구분

신호등 기준:

```text
Green  실제 경과 < 계획시간의 80%
Yellow 계획시간의 80% 이상, 100% 미만
Red    계획시간 이상
```

### 3.6 승인형 Day Close

지원 결정:

- reschedule: 다음 날짜로 이동하고 재조정 횟수 증가
- split: Micro Steps 생성
- delegate: executor를 AI 등으로 변경
- deadline_change: 명시적 최종기한 변경
- cancel: 외부 삭제가 아니라 Action 취소 기록
- waiting: 상대방·후속 시각을 지정하고 Follow-up 엔진 연결

모든 결정은 `CarryOverDecision`과 Audit Log에 남는다.

## 4. 데이터 모델

### PriorityAssessment

```text
id
ActionItem 1:1
importance_score
urgency_score
quadrant
source(rule/user/ai)
confidence
reasons_json
user_overridden
created_at / updated_at
```

### DailyFocusPlan

```text
focus_date unique
available_minutes
created_at / updated_at
```

### DailyCommitment

```text
commitment_date
ActionItem
owner_type(human/ai)
rank(1..3)
committed_minutes
state(active/released)
unique(date, item)
unique(date, owner_type, rank)
```

### MicroStep

```text
ActionItem
position
name/title
executor
preferred_worker
estimated_minutes
state
completion_note
unique(action, position)
```

### FocusSession

```text
ActionItem
state(running/paused/completed/abandoned)
planned_minutes
extension_minutes
started_at / paused_at / ended_at
paused_seconds
actual_minutes
traffic_state
completion_note
revision
active_slot unique nullable
```

### CarryOverDecision

```text
ActionItem
from_date / to_date
decision
reason
actor
result_json
created_at
```

## 5. API

관리자 API와 모바일 Bearer Scope API를 동일 도메인 서비스에 연결한다.

| 기능 | 관리자 API | 모바일 API |
|---|---|---|
| Triage | `GET /api/v1/focus/triage` | `GET /api/v1/mobile/triage` |
| 분류 | `POST /api/v1/focus/actions/{id}/classify` | `POST /api/v1/mobile/actions/{id}/classify` |
| Matrix | `GET /api/v1/focus/matrix` | `GET /api/v1/mobile/matrix` |
| Big3 조회/설정 | `GET/POST /api/v1/focus/commitments` | `GET/POST /api/v1/mobile/commitments` |
| 분해 | `POST /api/v1/focus/actions/{id}/decompose` | `POST /api/v1/mobile/actions/{id}/decompose` |
| Micro Step 수정 | `PATCH /api/v1/focus/microsteps/{id}` | `PATCH /api/v1/mobile/microsteps/{id}` |
| 활성 Focus | `GET /api/v1/focus/sessions/active` | `GET /api/v1/mobile/focus-sessions/active` |
| Focus 시작 | `POST /api/v1/focus/sessions` | `POST /api/v1/mobile/focus-sessions` |
| Focus 변경 | `PATCH /api/v1/focus/sessions/{id}` | `PATCH /api/v1/mobile/focus-sessions/{id}` |
| Day Close | `POST /api/v1/focus/day-close` | `POST /api/v1/mobile/day-close` |
| 주간 보고서 | `GET /api/v1/focus/reports/weekly` | `GET /api/v1/mobile/focus-reports/weekly` |

모바일 Scope:

- read: plans:read / brief:read / activity:read
- classify·microstep edit: plans:edit
- commitments·day-close: plans:approve
- focus 시작·변경: plans:execute

## 6. iOS UX

### Focus 탭

```text
Focus Home
├── Triage
├── Matrix
├── Human Big3 / AI Big3
├── Active Focus Session
└── Day Close
```

### Swipe Triage

- 위: Q1 실행
- 오른쪽: Q2 계획
- 왼쪽: Q3 위임
- 아래: Q4 보류
- 모든 제스처에 대응하는 보이는 버튼 제공
- VoiceOver Custom Action 제공
- 중요도·긴급도·신뢰도·판단 근거 표시
- 자동 삭제·자동 위임 없음

### Matrix

2×2 View에서 각 사분면 수와 작업을 조회하고 상세 행동으로 이동한다. Matrix는 저장 원장이 아니라 Attention View다.

### Focus Session

- preset: 10/25/50/90
- Micro Step 체크
- Pause/Resume/Extend
- 종료 메모
- Action 완료 여부 별도 Toggle
- Live Activity: 잠금화면/Dynamic Island 상태 표시

## 7. 구현 순서

| PR | 내용 | 완료 기준 |
|---|---|---|
| F01 | 모델·Alembic 0005 | v0.8 데이터 보존, 신규 테이블 생성 |
| F02 | 설명 가능한 분류 | 근거·점수·Q 제안, 사용자 override |
| F03 | Triage·Matrix API | 관리자·모바일 계약 |
| F04 | Dual Big3 | 3+3, capacity/overload, 순위 고유성 |
| F05 | Micro Steps | 3~5 단계, 실행자·예상시간 |
| F06 | Focus Session | single active, timer, traffic, revision |
| F07 | Day Close | 이월·분할·위임·취소·Waiting 감사 |
| F08 | Weekly analytics | Focus/Big3/Q2/이월/정확도 |
| I01 | iOS Focus Core/API | Codable·API Client·cache compatibility |
| I02 | Triage/Matrix | gesture+button+accessibility |
| I03 | Dual Big3 | human/AI selection, overload |
| I04 | Focus Session | timer/control/microsteps |
| I05 | Widget/App Intents | safe navigation only |
| I06 | Live Activity | ActivityKit UI, privacy minimization |
| V01 | E2E·migration·release | Python/Swift/HTTP/DB/package evidence |

## 8. 안전·보안 기준

1. Q4는 삭제가 아니다.
2. AI 제안은 확정이 아니다.
3. Q3 분류가 곧 Worker Dispatch는 아니다.
4. Focus complete가 기본적으로 외부 Action complete는 아니다.
5. Day Close는 silent carry-over를 하지 않는다.
6. 오래된 revision은 HTTP 409로 거부한다.
7. Live Activity와 Widget은 privacy-sensitive로 표시한다.
8. App Intents는 Capture와 화면 열기만 제공하고 승인·실행 Intent를 제공하지 않는다.
9. Push에는 업무 원문을 포함하지 않는다.
10. Todoist·Calendar·GitHub의 단일 원장 원칙을 유지한다.

## 9. 테스트 계획

- 모델·마이그레이션
- 분류 점수·사용자 override·terminal 거부
- Q4 비파괴
- Big3 최대 3개·중복·capacity
- Micro Step 생성·수정
- 단일 활성 세션·DB 경쟁조건
- pause/resume/extend/complete/abandon
- revision conflict
- traffic state
- Day Close 전 결정 분기
- 주간 리포트
- 관리자/모바일 Scope
- OpenAPI operation ID 고유성
- v0.8.0 실데이터 보존 Migration
- FastAPI HTTP E2E
- FastAPI–Swift E2E
- Swift Codable·API Client·Widget cache compatibility
- Swift source parse·format·Plist·Entitlement·Privacy Manifest

## 10. 제외·후속

이번 릴리스에서 제외:

- Apple Reminders 양방향 Bridge
- Foundation Models 온디바이스 분류
- OCR/PDF Private Capture
- 복잡한 스케줄 최적화
- 다중 동시 Focus
- 자동 Worker Dispatch/자동 Merge
- TRIX 화면·색상·브랜드 복제

후속 후보:

- iOS v0.3.0 Private Multimodal
- Apple Foundation Models 기반 사전 분류·민감정보 제거
- 단방향 Reminders Focus Bridge
- 실제 Focus 패턴 기반 예상시간 개인화
