from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import ActionItem, ActionType, ItemState
from ..schemas import BriefItem, DailyBrief


def _brief_item(item: ActionItem, when: datetime | None) -> BriefItem:
    return BriefItem(
        id=item.id,
        title=item.title,
        item_type=item.item_type,
        destination=item.destination,
        when=when,
        state=item.state,
        external_url=item.external_url,
        estimated_minutes=item.estimated_minutes,
        executor=item.executor,
        preferred_worker=item.preferred_worker,
    )


def build_daily_brief(db: Session, timezone_name: str, target: datetime | None = None) -> DailyBrief:
    tz = ZoneInfo(timezone_name)
    now = target.astimezone(tz) if target and target.tzinfo else (target.replace(tzinfo=tz) if target else datetime.now(tz))
    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    end = start + timedelta(days=1)

    items = list(
        db.scalars(
            select(ActionItem).where(
                ActionItem.state.notin_([ItemState.REJECTED.value]),
                or_(
                    ActionItem.start_at.is_not(None),
                    ActionItem.due_at.is_not(None),
                    ActionItem.deadline_at.is_not(None),
                    ActionItem.follow_up_at.is_not(None),
                    ActionItem.executor.in_(["ai", "hybrid"]),
                    ActionItem.needs_review.is_(True),
                ),
            )
        )
    )
    events: list[BriefItem] = []
    due_tasks: list[BriefItem] = []
    overdue: list[BriefItem] = []
    review: list[BriefItem] = []
    waiting: list[BriefItem] = []
    ai_ready: list[BriefItem] = []

    for item in items:
        if item.needs_review and item.state in {ItemState.DRAFT.value, ItemState.APPROVED.value}:
            review.append(_brief_item(item, item.start_at or item.due_at))
        if item.state == ItemState.WAITING.value:
            waiting.append(_brief_item(item, item.follow_up_at or item.due_at))
        if item.executor in {"ai", "hybrid"} and item.state in {
            ItemState.APPROVED.value, ItemState.REGISTERED.value, ItemState.FAILED.value
        } and not item.needs_review:
            ai_ready.append(_brief_item(item, item.due_at or item.deadline_at))
        if item.item_type == ActionType.EVENT.value and item.start_at and start <= item.start_at.astimezone(tz) < end:
            events.append(_brief_item(item, item.start_at))
        elif item.due_at:
            local_due = item.due_at.astimezone(tz)
            if start <= local_due < end and item.state not in {ItemState.COMPLETED.value, ItemState.SKIPPED_DUPLICATE.value}:
                due_tasks.append(_brief_item(item, item.due_at))
            elif local_due < start and item.state not in {ItemState.COMPLETED.value, ItemState.SKIPPED_DUPLICATE.value}:
                overdue.append(_brief_item(item, item.due_at))

    events.sort(key=lambda x: x.when or start)
    due_tasks.sort(key=lambda x: x.when or end)
    overdue.sort(key=lambda x: x.when or start)
    waiting.sort(key=lambda x: x.when or end)
    ai_ready.sort(key=lambda x: x.when or end)
    summary = (
        f"일정 {len(events)}개 · 오늘 마감 {len(due_tasks)}개 · 지연 {len(overdue)}개 · "
        f"검토 {len(review)}개 · 응답 대기 {len(waiting)}개 · AI 위임 후보 {len(ai_ready)}개"
    )
    return DailyBrief(
        generated_at=now,
        timezone=timezone_name,
        date=now.date().isoformat(),
        events=events,
        due_tasks=due_tasks,
        overdue=overdue,
        needs_review=review,
        waiting=waiting,
        ai_ready=ai_ready,
        summary=summary,
    )
