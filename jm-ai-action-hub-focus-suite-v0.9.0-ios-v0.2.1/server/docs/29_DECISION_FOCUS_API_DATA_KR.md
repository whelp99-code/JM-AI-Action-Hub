# Decision & Focus API·데이터 명세

## 상태축

### Action 실행 상태

기존 `ActionItem.state`를 그대로 사용한다. 외부 등록·Worker·완료 상태를 나타낸다.

### Attention 상태

`ActionItem.attention_state`는 오늘의 판단과 집중 상태만 나타낸다.

| 상태 | 의미 |
|---|---|
| untriaged | 사용자 분류 전 |
| classified | Q1~Q4 확정 |
| committed | 오늘 Human/AI Big3 포함 |
| focusing | 활성 Focus 중 |
| paused | Focus 일시정지 |
| carried_over | Day Close에서 다른 날로 이동 |
| skipped | 취소·보류 결정 |
| completed | Focus에서 명시적으로 Action까지 완료 |

두 상태축은 독립적이다.

## 우선순위 평가

```json
{
  "importance_score": 86,
  "urgency_score": 72,
  "quadrant": "q1",
  "source": "rule",
  "confidence": 0.83,
  "reasons_json": ["우선순위 4/4", "고객 영향", "24시간 이내"],
  "user_overridden": false
}
```

사용자 분류 요청은 optional expected_item_revision을 받아 stale edit를 거부한다.

## Dual Big3

```json
{
  "target_date": "2026-08-01",
  "human_item_ids": ["..."],
  "ai_item_ids": ["..."],
  "available_minutes": 360,
  "actor": "user"
}
```

응답은 human/ai committed minutes, overload minutes, warnings를 포함한다.

## Focus Session 전이

```text
start → running
running → pause → paused
paused → resume → running
running/paused → extend
running/paused → complete
running/paused → abandon
```

종료된 세션의 재변경은 거부한다. `expected_revision` 불일치는 409다.

## Day Close

```json
{
  "target_date": "2026-08-01",
  "decisions": [
    {
      "action_item_id": "...",
      "decision": "reschedule",
      "to_date": "2026-08-02",
      "reason": "고객 긴급 요청 발생"
    }
  ],
  "actor": "user"
}
```

허용 결정: reschedule, split, delegate, deadline_change, cancel, waiting.

## 모바일 Dashboard Focus Summary

```json
{
  "untriaged_count": 4,
  "human_big3_count": 3,
  "ai_big3_count": 2,
  "human_committed_minutes": 210,
  "available_minutes": 360,
  "overload_minutes": 0,
  "active_focus": null
}
```

## 단일 원장 및 부작용 규칙

- Classify: 외부 시스템 변경 없음
- Big3: 외부 시스템 변경 없음
- Decompose: Action Hub 내부 Step만 생성
- Focus: 외부 원장 변경 없음
- Focus complete + mark_action_completed: Action Hub 상태와 증거 변경
- Day Close cancel: 외부 Provider 삭제 없음
- Q3: 실제 AI Dispatch 없음
