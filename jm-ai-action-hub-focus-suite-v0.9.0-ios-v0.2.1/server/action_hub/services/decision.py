from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import ActionItem, FollowUp, ItemState, utcnow
from ..schemas import DecisionItem, DecisionPlan

EXCLUDED_STATES = {
    ItemState.COMPLETED.value,
    ItemState.REJECTED.value,
    ItemState.SKIPPED_DUPLICATE.value,
    ItemState.CANCELLED.value,
}


def _local(value: datetime | None, tz: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _score_item(item: ActionItem, day_start: datetime, day_end: datetime, tz: ZoneInfo) -> tuple[float, list[str]]:
    score = float(item.priority * 20)
    reasons = [f"우선순위 P{5 - item.priority if item.priority in range(1, 5) else item.priority}"]
    deadline = _local(item.deadline_at, tz)
    due = _local(item.due_at, tz)
    if deadline:
        delta_days = (deadline.date() - day_start.date()).days
        if deadline < day_start:
            score += 120
            reasons.append("마감 경과")
        elif delta_days == 0:
            score += 80
            reasons.append("오늘 최종 마감")
        elif delta_days == 1:
            score += 45
            reasons.append("내일 최종 마감")
        elif delta_days <= 3:
            score += 25
            reasons.append("3일 이내 마감")
    if due:
        if due < day_start:
            score += 90
            reasons.append("예정일 경과")
        elif day_start <= due < day_end:
            score += 55
            reasons.append("오늘 예정")
    if item.work_mode == "deep":
        score += 8
        reasons.append("집중 업무")
    if item.executor in {"ai", "hybrid"}:
        score += 5
        reasons.append("AI 위임 가능")
    if item.reschedule_count:
        score += min(item.reschedule_count * 7, 35)
        reasons.append(f"{item.reschedule_count}회 재조정")
    if item.needs_review:
        score -= 100
        reasons.append("검토 필요")
    if item.state == ItemState.FAILED.value:
        score += 15
        reasons.append("실패 복구 필요")
    if item.depends_on:
        score -= 20
        reasons.append("선행 작업 확인 필요")
    return score, reasons


def build_decision_plan(
    db: Session,
    settings: Settings,
    *,
    target_date: date | None = None,
    available_minutes: int | None = None,
    max_items: int = 12,
    include_ai: bool = True,
) -> DecisionPlan:
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    day = target_date or now.date()
    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    capacity = available_minutes or settings.default_workday_minutes
    buffer_minutes = round(capacity * settings.planning_buffer_percent / 100)
    usable = max(0, capacity - buffer_minutes)

    candidates = list(
        db.scalars(
            select(ActionItem).where(
                ActionItem.state.notin_(EXCLUDED_STATES),
                ActionItem.state != ItemState.WAITING.value,
            )
        )
    )
    scored: list[DecisionItem] = []
    for item in candidates:
        earliest = _local(item.earliest_start_at, tz)
        if earliest and earliest >= day_end:
            continue
        score, reasons = _score_item(item, day_start, day_end, tz)
        estimate = item.estimated_minutes or settings.default_estimated_minutes
        scored.append(
            DecisionItem(
                action_item_id=item.id,
                title=item.title,
                score=round(score, 2),
                estimated_minutes=estimate,
                executor=item.executor,
                state=item.state,
                due_at=item.due_at,
                deadline_at=item.deadline_at,
                reasons=reasons,
                external_url=item.external_url,
                preferred_worker=item.preferred_worker,
            )
        )
    scored.sort(key=lambda x: (-x.score, x.deadline_at or x.due_at or day_end))

    selected: list[DecisionItem] = []
    deferred: list[DecisionItem] = []
    planned = 0
    for candidate in scored:
        if len(selected) < max_items and planned + candidate.estimated_minutes <= usable:
            selected.append(candidate)
            planned += candidate.estimated_minutes
        else:
            deferred.append(candidate)

    ai_candidates = [x for x in scored if x.executor.value in {"ai", "hybrid"}]
    if not include_ai:
        ai_candidates = []
    waiting = list(
        db.scalars(
            select(FollowUp)
            .where(FollowUp.state.in_(["waiting", "follow_up_due", "followed_up"]))
            .order_by(FollowUp.follow_up_at)
        )
    )
    overload = max(0, sum(x.estimated_minutes for x in scored) - usable)
    risks: list[str] = []
    overdue = sum(any("경과" in reason for reason in x.reasons) for x in scored)
    if overload:
        risks.append(f"가용시간 대비 {overload}분 초과")
    if overdue:
        risks.append(f"기한이 지난 업무 {overdue}건")
    due_followups = sum(x.follow_up_at <= utcnow() for x in waiting)
    if due_followups:
        risks.append(f"후속 확인 필요 {due_followups}건")
    review_count = sum(item.needs_review for item in candidates)
    if review_count:
        risks.append(f"등록 전 검토가 필요한 업무 {review_count}건")
    summary = (
        f"가용 {capacity}분 중 버퍼 {buffer_minutes}분을 제외하고 "
        f"{len(selected)}건·{planned}분을 우선 계획했습니다."
    )
    return DecisionPlan(
        date=day.isoformat(),
        generated_at=now,
        available_minutes=capacity,
        buffer_minutes=buffer_minutes,
        planned_minutes=planned,
        overload_minutes=overload,
        top_items=selected,
        deferred_items=deferred,
        ai_delegation_candidates=ai_candidates,
        waiting_followups=waiting,
        risks=risks,
        summary=summary,
    )
