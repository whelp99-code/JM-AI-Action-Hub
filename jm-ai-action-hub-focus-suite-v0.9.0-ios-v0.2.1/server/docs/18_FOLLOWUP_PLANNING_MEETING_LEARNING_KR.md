# Follow-up · Planning · Meeting · Personal Learning 설계

## 1. Waiting-for와 Follow-up

업무 누락의 큰 비중은 “내가 할 일”보다 “상대방의 응답을 기다리는 일”에서 발생한다.

### 필드

```text
waiting_for
channel
waiting_since
expected_by
follow_up_at
follow_up_template
reminder_count
response_received_at
resolved_at
```

### 상태

```text
waiting
follow_up_due
followed_up
response_received
resolved
cancelled
```

### 동작

- Action 생성 시 `waiting_for`와 `follow_up_at`을 추출한다.
- Worker가 만료 시각을 확인해 `follow_up_due`로 변경한다.
- Today 화면에서 응답 대기 대상과 경과 상태를 보여준다.
- `response_received`이면 더 이상 만료 목록에 나타나지 않는다.
- `followed_up`이면 기본 기간 후 다음 확인 시각을 설정한다.

메일 회신을 직접 읽는 IMAP Client는 개발하지 않는다. 실제 회신 자동 감지가 필요해질 때 Gmail/Outlook 기존 Add-on 또는 제한된 Provider Adapter를 별도 검증한다.

## 2. Action Enrichment

일정 배치와 위임을 위해 다음 정보를 추가했다.

```text
estimated_minutes
deadline_at
earliest_start_at
latest_finish_at
work_mode
executor
preferred_worker
energy_level
depends_on
actual_minutes
reschedule_count
completion_evidence
```

### 날짜 의미

- `due_at`: 실제로 수행할 예정 시각 또는 Todoist 일정
- `deadline_at`: 반드시 끝내야 하는 최종 기한
- `earliest_start_at`: 시작 가능한 가장 이른 시각
- `latest_finish_at`: 끝내야 하는 가장 늦은 시각

## 3. Daily Decision

Action Hub는 Calendar UI를 만들지 않는다. 오늘의 의사결정만 계산한다.

### 입력

```text
target_date
available_minutes
max_items
include_ai
```

### 계산

1. 종료·거부·취소된 Action 제외
2. Dependency가 완료되지 않은 항목 Block
3. Deadline·Overdue·Priority·Waiting·AI 여부 Score
4. 기본 또는 추출 예상시간 적용
5. 사용자 가용시간에서 보호 Buffer 차감
6. 순서대로 Top items 배치
7. 남는 항목 Deferred
8. AI/Hybrid 항목을 위임 후보로 분리
9. 과부하·마감·재조정·응답 대기 위험 생성

### 출력

```text
available_minutes
buffer_minutes
planned_minutes
overload_minutes
top_items
deferred_items
ai_delegation_candidates
risks
summary
```

이 기능은 자동 Calendar 쓰기를 하지 않는다. Reclaim·Akiflow 같은 기존 Planner로 해결 가능한 경우 그 제품을 그대로 사용한다.

## 4. Meeting Intake

### 흐름

```text
Fireflies meeting.summarized
→ HMAC 검증
→ MeetingIntake 저장
→ GraphQL Transcript/Summary 조회
→ action_items 추출
→ 원문이 있는 ActionPlan 생성
→ 사용자 승인
```

### 중복 방지

```text
UNIQUE(provider, external_meeting_id, event_type)
```

### 실패 복구

```text
POST /api/v1/meetings/{intake_id}/reprocess
```

Fireflies API 오류나 Action Item 부재는 Intake 상태와 error에 기록한다.

## 5. Personal Rules

### 목적

LLM 호출을 늘리는 대신 사용자가 반복해서 수정한 안정적 기본값을 학습한다.

### 제안 조건

- 같은 Project에 최소 3개 관찰
- 후보 필드 값의 80% 이상 일치
- 같은 조건의 기존 Rule이 없음

### 상태

```text
proposed → active → disabled
```

### 안전성

Rule은 Allowlist 필드만 수정한다. 다음은 금지된다.

- `state`
- `needs_review`
- `external_id`
- 토큰·Secret
- Destination 강제 실행
- 승인 우회
- 자동 Merge/배포

## 6. Weekly ROI

### 지표

- 입력 수
- 추출 Action 수
- 승인/등록/완료
- 지연
- Waiting
- AI dispatch/success
- 중복 방지
- 예상 절감시간
- 규칙 적용 횟수

### 추천 예

- 지연 Action 분할
- 예상시간 재산정
- 장기 Waiting 후속 확인
- AI Worker 성공률이 낮을 때 완료 기준 구체화
- 반복 수정 패턴을 Rule로 승인

### 한계

`estimated_minutes_saved`는 실제 Stopwatch가 아닌 이벤트 기반 추정치다. 향후 실제 업무시간 입력이 축적되면 예상시간 대비 실제시간 오차로 보정한다.
