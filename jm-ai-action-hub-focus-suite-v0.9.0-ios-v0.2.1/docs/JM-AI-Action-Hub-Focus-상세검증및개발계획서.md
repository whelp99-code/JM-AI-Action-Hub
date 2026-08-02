# JM-AI Action Hub Focus Control Suite
## 상세 검증 및 개발 계획서

**대상 릴리스**

- JM-AI Action Hub Server `v0.9.0`
- JM-AI Action Hub Native iOS `v0.2.0` Focus Matrix
- JM-AI Action Hub Native iOS `v0.2.1` Live Focus
- 기준일: 2026-08-01
- 기준 시간대: Asia/Seoul

---

# 1. 프로젝트 목적

기존 JM-AI Action Hub는 자연어·음성·공유 입력을 Action으로 바꾸고, 사용자가 검토·승인한 뒤 Todoist·Calendar·GitHub로 등록하며, 외부 상태와 AI Worker 결과를 실제 완료까지 추적한다.

이번 릴리스는 그 다음 공백을 해결한다.

> 수집된 업무 중 무엇을 지금 실행하고, 무엇을 계획하고, 무엇을 사람 또는 AI에게 위임하며, 무엇을 하지 않을지 결정한 뒤 실제 집중과 완료까지 연결한다.

최종 흐름은 다음과 같다.

```text
자연어·음성·공유 입력
        ↓
Action Parser / Approval
        ↓
Todoist·Calendar·GitHub 등록 및 상태 동기화
        ↓
설명 가능한 중요도·긴급도 제안
        ↓
Swipe Triage / Eisenhower Matrix
        ↓
Human Big3 + AI Big3
        ↓
Micro Steps
        ↓
Human Focus / AI Execution
        ↓
완료 증거 또는 승인형 Day Close
        ↓
주간 Focus·위임·이월 분석
```

# 2. 기존 앱·솔루션 검증

## 2.1 TRIX에서 확인한 가치

TRIX가 제공하는 행동 흐름 중 Action Hub에 가치가 높은 부분은 다음이다.

- 브레인 덤프
- 스와이프 아이젠하워 분류
- Big3
- 10·25·50·90분 집중
- 마이크로 스텝
- 집중시간 신호등
- Widget·Live Activity
- 이월·완료 기록·주간 분석

그러나 Action Hub가 이를 그대로 복제하면 자체 Todo·Calendar·Pomodoro 앱으로 변질된다. 따라서 다음처럼 결정했다.

| TRIX/기존 기능 | 결정 | 이유 |
|---|---|---|
| 브레인 덤프·음성·공유 | 기존 Action Hub 기능 재사용 | 중복 개발 금지 |
| Eisenhower Matrix | 의사결정 View로 도입 | 외부 원장을 대체하지 않음 |
| Big3 | Human/AI Dual Big3로 확장 | Action Hub만의 실행자 구조 활용 |
| Focus Timer | Action과 실제시간·완료 증거에 연결 | 단순 Pomodoro보다 높은 가치 |
| Micro Steps | 단계별 실행자·Worker 지정 | 사람/AI 협업 차별화 |
| 신호등 | 예정시간 초과 제어 | 과집중과 범위 증가 감지 |
| 자동 이월 | 그대로 도입하지 않음 | 쌓이는 미완료 업무 방지 |
| Calendar | 개발하지 않음 | 기존 Calendar 원장 유지 |
| Todo DB | 개발하지 않음 | Todoist/GitHub 유지 |
| Reminders 양방향 | 이번 릴리스 제외 | 다중 원장 충돌 방지 |
| 온디바이스 AI | 후속 후보 | 지원 기기·Apple SDK 인수 필요 |

## 2.2 고정 제품 경계

### Action Hub가 담당

- 우선순위 제안과 근거
- 사용자 Triage
- Human Big3·AI Big3
- 가용시간·과부하
- Micro Steps
- Focus Session과 실제시간
- 사람·AI 실행자 연결
- 이월·분할·위임·취소·Waiting 결정
- 완료 증거·주간 분석

### 기존 앱이 담당

- Todoist: 개인 업무 최종 원장
- Calendar: 일정 최종 원장
- GitHub: 개발 업무·PR·CI·Merge 최종 원장
- Codex·Claude·Copilot·Orca·Hermes: 실제 AI Worker
- Fireflies: 회의 전사·요약

# 3. 제품 원칙

1. **Build Less, Integrate More**
2. Matrix는 저장 원장이 아니라 Decision View다.
3. AI의 추천은 자동 확정하지 않는다.
4. Q4는 삭제가 아니라 보류다.
5. Q3는 자동 AI Dispatch가 아니다.
6. Focus Complete와 Action Complete를 분리한다.
7. 미완료 업무는 자동 이월하지 않는다.
8. 제스처만으로 기능을 숨기지 않는다.
9. Live Activity·Widget에는 민감한 원문을 최소화한다.
10. 외부 실행·Merge·배포·고객 발송은 계속 사람 승인 뒤에 둔다.

# 4. 제품 요구사항

## FR-01 설명 가능한 Priority Assessment

입력:

- priority
- project/repository
- work_mode
- labels
- due/deadline/start
- follow_up_at
- reschedule_count
- failed/needs_review/depends_on
- executor

출력:

```json
{
  "importance_score": 85,
  "urgency_score": 72,
  "quadrant": "q1",
  "confidence": 0.84,
  "reasons_json": ["우선순위 4/4", "고객 영향", "24시간 이내"]
}
```

## FR-02 Swipe Triage

- Q1 실행
- Q2 계획
- Q3 위임
- Q4 보류
- Swipe + 버튼 + VoiceOver Action
- 사용자 수정은 source=user, confidence=1.0으로 보존
- stale revision 거부

## FR-03 Matrix

- 2×2 사분면
- 사분면별 Count와 Action
- Untriaged Count
- Matrix에서 Focus/Big3/위임/Day Close 연결

## FR-04 Dual Big3

- Human 최대 3개
- AI 최대 3개
- 순위 1~3
- 동일 Action 중복 금지
- 날짜별 available_minutes
- committed_minutes·overload_minutes·warning

## FR-05 Micro Steps

- 3~5개 권장
- human/ai/hybrid/external
- preferred_worker
- estimated_minutes
- completion state/note

## FR-06 Focus Session

- 하나의 활성 세션만 허용
- 10/25/50/90분 preset
- pause/resume/extend/complete/abandon
- revision conflict
- green/yellow/red
- 실제시간에서 pause 제외
- 종료 메모
- Action 완료는 별도 선택

## FR-07 승인형 Day Close

- reschedule
- split
- delegate
- deadline_change
- cancel
- waiting
- reason 저장
- Audit·CarryOverDecision 저장
- silent auto-carry 금지

## FR-08 Weekly Focus Analytics

- Focus session 수·완료 수·총 시간
- traffic 분포
- Q1~Q4 시간
- Human/AI Big3 완료율
- Q2 투자시간
- 이월 결정 수
- 예상시간 정확도

## FR-09 iOS Native Surface

- Focus 전용 탭
- Today Focus Summary
- Triage/Matrix/Big3/Session/Day Close
- Widget
- Siri/Shortcuts/App Intents
- Lock Screen/Dynamic Island Live Activity
- backward-compatible cache

# 5. 상태 아키텍처

## 5.1 실행 상태

기존 `ActionItem.state`는 외부 실행의 실제 상태다.

```text
draft → approved → queued → registered
      → dispatched/running/human_review
      → completed/failed/cancelled
```

## 5.2 주의·집중 상태

신규 `ActionItem.attention_state`는 사용자의 판단 상태다.

```text
untriaged
→ classified
→ committed
→ focusing / paused
→ carried_over / skipped / completed
```

두 축을 분리하면 다음이 가능하다.

- GitHub Issue는 open이지만 오늘 Q2로 계획
- Todoist 작업은 registered이지만 Human Big3에 포함
- AI Worker는 running이고 AI Big3에 포함
- Q4로 보류해도 외부 작업은 유지
- Focus 종료 후 실제 Action은 아직 미완료로 유지

# 6. 데이터 모델

## PriorityAssessment

- action_item_id 1:1
- importance_score
- urgency_score
- quadrant
- source
- confidence
- reasons_json
- user_overridden

## DailyFocusPlan

- focus_date unique
- available_minutes

## DailyCommitment

- commitment_date
- action_item_id
- owner_type(human/ai)
- rank
- committed_minutes
- state
- unique(date, item)
- unique(date, owner, rank)

## MicroStep

- action_item_id
- position
- title
- executor
- preferred_worker
- estimated_minutes
- state
- completion_note

## FocusSession

- action_item_id
- state
- planned_minutes
- extension_minutes
- started_at/paused_at/ended_at
- paused_seconds
- actual_minutes
- traffic_state
- completion_note
- revision
- active_slot unique nullable

## CarryOverDecision

- action_item_id
- from_date/to_date
- decision
- reason
- actor
- result_json

# 7. API 계약

```text
GET  /api/v1/focus/triage
POST /api/v1/focus/actions/{id}/classify
GET  /api/v1/focus/matrix
GET  /api/v1/focus/commitments
POST /api/v1/focus/commitments
POST /api/v1/focus/actions/{id}/decompose
PATCH /api/v1/focus/microsteps/{id}
GET  /api/v1/focus/sessions/active
POST /api/v1/focus/sessions
PATCH /api/v1/focus/sessions/{id}
POST /api/v1/focus/day-close
GET  /api/v1/focus/reports/weekly
```

동일 기능의 모바일 Bearer API를 `/api/v1/mobile` 아래에 제공한다.

모바일 API Scope:

- 조회: plans:read, brief:read, activity:read
- 분류·Step 수정: plans:edit
- Big3·Day Close: plans:approve
- Focus 시작·변경: plans:execute

# 8. iOS UX 상세

## Focus Home

```text
미분류 업무
Matrix 요약
Human Big3
AI Big3
활성 Focus Session
Day Close
```

## Swipe Triage

```text
위      Q1 실행
오른쪽  Q2 계획
왼쪽    Q3 위임
아래    Q4 보류
```

동일한 버튼과 VoiceOver Action을 제공한다.

## Dual Big3

```text
Human Big3
1. 고객 제안서       120분
2. 고객 미팅          60분
3. PR 최종 검토       30분

AI Big3
1. 회귀 테스트        Codex
2. 운영문서           Claude
3. 경쟁조사           Master Worker
```

## Focus Mode

```text
작업명
계획시간 / 경과시간
Traffic State
Micro Steps
Pause / Resume / +10분
Complete / Abandon
Action 완료 선택
```

## Day Close

모든 미완료 항목에 사유와 다음 행동을 요구한다. 자동 이월을 사용하지 않는다.

# 9. 보안·안전·개인정보

- 관리자 API Key iOS 저장 금지
- Device-scoped Bearer 사용
- HTTPS 강제
- Q4 비파괴
- Intent·Widget·Live Activity에서 승인/실행 금지
- Live Activity/Widget privacySensitive
- Push 원문 미포함
- stale revision HTTP 409
- 단일 활성 Focus를 DB unique로 보장
- 외부 Provider 삭제 없음
- Worker Dispatch 별도 승인

# 10. 순차 구현 계획

| 단계 | 버전 | 내용 |
|---|---|---|
| 1 | Server 0.9.0 | 모델·Alembic 0005 |
| 2 | Server 0.9.0 | Priority·Triage·Matrix |
| 3 | Server 0.9.0 | Dual Big3·Capacity |
| 4 | Server 0.9.0 | Micro Steps |
| 5 | Server 0.9.0 | Focus Session·Traffic |
| 6 | Server 0.9.0 | Day Close·Weekly Report |
| 7 | iOS 0.2.0 | Core models/API/cache |
| 8 | iOS 0.2.0 | Triage·Matrix·Dual Big3 |
| 9 | iOS 0.2.0 | Focus Session·Micro Steps·Day Close |
| 10 | iOS 0.2.1 | Widget·App Intents·Live Activity |
| 11 | Release | Migration·HTTP·Swift E2E·Package |

# 11. 완료 기준

1. v0.8 데이터가 손실 없이 v0.9로 이동한다.
2. AI/규칙 제안과 사용자 확정을 구분한다.
3. Q4가 외부 작업을 삭제하지 않는다.
4. Human·AI Big3가 각각 최대 3개다.
5. Capacity 초과를 표시한다.
6. Micro Steps에 실행자를 지정할 수 있다.
7. 활성 Focus가 동시에 둘 이상 생성되지 않는다.
8. Pause 시간이 실제시간에서 제외된다.
9. stale session revision이 409로 거부된다.
10. Day Close가 사유와 결과를 기록한다.
11. iOS에서 Triage부터 Focus 완료까지 실행된다.
12. Widget/App Intents가 외부 실행을 직접 수행하지 않는다.
13. Live Activity가 종료 상태에 맞춰 끝난다.
14. 기존 v0.1 Widget cache가 깨지지 않는다.
15. Python·Swift·OpenAPI·HTTP·Migration 검증을 통과한다.

# 12. 이번 릴리스에서 제외

- Apple Reminders 양방향 Sync
- Foundation Models 온디바이스 우선순위·분해
- OCR/PDF Private Capture
- AI 자동 Dispatch
- 자동 Merge/배포
- 자체 Calendar·Todo·Kanban
- 다중 Focus Session
- 복잡한 Dependency DAG

이 항목들은 실제 사용 데이터와 Apple 환경 검증 후 후속 릴리스에서 판단한다.
