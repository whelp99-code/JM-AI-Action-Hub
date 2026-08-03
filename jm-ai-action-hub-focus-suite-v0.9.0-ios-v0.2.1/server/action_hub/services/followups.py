from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..models import ActionItem, FollowUp, ItemState, utcnow
from .audit import record_audit
from .push import queue_push_for_active_devices
from .state_sync import recalculate_plan_status

ACTIVE_FOLLOWUP_STATES = {"waiting", "follow_up_due", "followed_up"}


def ensure_followup(
    db: Session,
    item: ActionItem,
    settings: Settings,
    *,
    actor: str = "system",
    channel: str | None = None,
    expected_by=None,
    template: str | None = None,
) -> FollowUp | None:
    if not item.waiting_for:
        return None
    existing = db.scalar(
        select(FollowUp).where(
            FollowUp.action_item_id == item.id,
            FollowUp.state.in_(ACTIVE_FOLLOWUP_STATES),
        )
    )
    if existing:
        return existing
    follow_at = item.follow_up_at or (utcnow() + timedelta(days=settings.followup_default_days))
    followup = FollowUp(
        action_item_id=item.id,
        state="waiting",
        waiting_for=item.waiting_for,
        channel=channel,
        expected_by=expected_by,
        follow_up_at=follow_at,
        template=template,
    )
    db.add(followup)
    db.flush()
    item.follow_up_at = follow_at
    if item.state not in {ItemState.COMPLETED.value, ItemState.CANCELLED.value}:
        item.state = ItemState.WAITING.value
    record_audit(
        db,
        entity_type="followup",
        entity_id=followup.id,
        event_type="followup.created",
        actor=actor,
        payload={"action_item_id": item.id, "waiting_for": item.waiting_for, "follow_up_at": follow_at.isoformat()},
    )
    return followup


def create_followup(
    db: Session,
    *,
    item_id: str,
    waiting_for: str,
    follow_up_at,
    settings: Settings,
    channel: str | None = None,
    expected_by=None,
    template: str | None = None,
    actor: str = "user",
) -> FollowUp:
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == item_id)
        .options(selectinload(ActionItem.plan))
    )
    if item is None:
        raise LookupError("Action item not found")
    item.waiting_for = waiting_for
    item.follow_up_at = follow_up_at
    followup = FollowUp(
        action_item_id=item.id,
        state="waiting",
        waiting_for=waiting_for,
        channel=channel,
        expected_by=expected_by,
        follow_up_at=follow_up_at,
        template=template,
    )
    db.add(followup)
    item.state = ItemState.WAITING.value
    if item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    db.flush()
    record_audit(
        db,
        entity_type="followup",
        entity_id=followup.id,
        event_type="followup.created",
        actor=actor,
        payload={"action_item_id": item.id, "waiting_for": waiting_for, "follow_up_at": follow_up_at.isoformat()},
    )
    db.commit()
    db.refresh(followup)
    return followup


def process_due_followups(db: Session, settings: Settings, limit: int = 100) -> list[FollowUp]:
    now = utcnow()
    followups = list(
        db.scalars(
            select(FollowUp)
            .where(
                FollowUp.state.in_(["waiting", "followed_up"]),
                FollowUp.follow_up_at <= now,
            )
            .options(selectinload(FollowUp.action_item).selectinload(ActionItem.plan))
            .order_by(FollowUp.follow_up_at)
            .limit(limit)
        )
    )
    for followup in followups:
        followup.state = "follow_up_due"
        followup.reminder_count += 1
        followup.last_reminded_at = now
        item = followup.action_item
        if item and item.state not in {ItemState.COMPLETED.value, ItemState.CANCELLED.value}:
            item.state = ItemState.WAITING.value
            if item.plan:
                item.plan.status = recalculate_plan_status(item.plan)
        record_audit(
            db,
            entity_type="followup",
            entity_id=followup.id,
            event_type="followup.due",
            payload={"reminder_count": followup.reminder_count, "waiting_for": followup.waiting_for},
        )
        queue_push_for_active_devices(
            db,
            settings,
            event_type="follow_up_due",
            entity_type="followup",
            entity_id=followup.id,
            idempotency_suffix=f"{followup.id}:{followup.reminder_count}",
        )
    db.commit()
    return followups


def resolve_followup(
    db: Session,
    *,
    followup_id: str,
    state: str,
    settings: Settings,
    actor: str = "user",
    note: str = "",
) -> FollowUp:
    followup = db.scalar(
        select(FollowUp)
        .where(FollowUp.id == followup_id)
        .options(selectinload(FollowUp.action_item).selectinload(ActionItem.plan))
    )
    if followup is None:
        raise LookupError("Follow-up not found")
    if state not in {"response_received", "followed_up", "resolved", "cancelled"}:
        raise ValueError("Unsupported follow-up state")
    now = utcnow()
    followup.state = state
    item = followup.action_item
    if state == "response_received":
        followup.response_received_at = now
        if item and item.state not in {ItemState.COMPLETED.value, ItemState.CANCELLED.value}:
            item.state = ItemState.HUMAN_REVIEW.value
            item.completion_evidence = note or "External response received"
    elif state == "followed_up":
        followup.reminder_count += 1
        followup.last_reminded_at = now
        followup.follow_up_at = now + timedelta(days=settings.followup_default_days)
        if item:
            item.follow_up_at = followup.follow_up_at
            item.state = ItemState.WAITING.value
    elif state == "resolved":
        if item:
            item.state = ItemState.COMPLETED.value
            item.completed_at = now
            item.completion_evidence = note or "Follow-up resolved"
    elif state == "cancelled":
        if item and item.state == ItemState.WAITING.value:
            item.state = ItemState.REGISTERED.value
    if item and item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    record_audit(
        db,
        entity_type="followup",
        entity_id=followup.id,
        event_type=f"followup.{state}",
        actor=actor,
        payload={"note": note},
    )
    db.commit()
    db.refresh(followup)
    return followup
