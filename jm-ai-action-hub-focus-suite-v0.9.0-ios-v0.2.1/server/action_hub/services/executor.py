from __future__ import annotations

import hashlib

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import ActionItem, ActionPlan, ActionType, Destination, ItemState, PlanStatus
from ..schemas import ActionItemUpdate
from .audit import record_audit
from .outbox import enqueue_registration, process_outbox_batch
from .planner import get_plan
from .state_sync import recalculate_plan_status

TERMINAL_ITEM_STATES = {
    ItemState.COMPLETED.value,
    ItemState.REJECTED.value,
    ItemState.SKIPPED_DUPLICATE.value,
    ItemState.CANCELLED.value,
}


def _structural_review_reasons(item: ActionItem) -> list[str]:
    reasons: list[str] = []
    calendar_destinations = {Destination.GOOGLE_CALENDAR.value, Destination.LOCAL_ICS.value}
    if item.item_type == ActionType.EVENT.value and item.destination == Destination.NONE.value:
        reasons.append("일정의 등록 대상이 없음")
    if item.destination in calendar_destinations and not item.start_at:
        reasons.append("일정 시작 시간이 없음")
    if item.start_at and item.end_at and item.end_at < item.start_at:
        reasons.append("종료 시간이 시작 시간보다 빠름")
    if item.deadline_at and item.earliest_start_at and item.deadline_at < item.earliest_start_at:
        reasons.append("마감 시간이 시작 가능 시간보다 빠름")
    if item.destination == Destination.GITHUB.value:
        repository = (item.repository or "").strip()
        if repository.count("/") != 1 or any(not part for part in repository.split("/")):
            reasons.append("GitHub 저장소는 owner/repo 형식이어야 함")
    if item.executor in {"ai", "hybrid"} and not (item.preferred_worker or item.repository):
        reasons.append("AI 실행 작업에는 Worker 또는 GitHub 저장소가 필요함")
    return list(dict.fromkeys(reasons))


def _apply_structural_review(item: ActionItem) -> list[str]:
    reasons = _structural_review_reasons(item)
    if not reasons:
        return []
    existing = [x.strip() for x in (item.review_reason or "").split(";") if x.strip()]
    item.needs_review = True
    item.review_reason = "; ".join(dict.fromkeys([*existing, *reasons]))
    return reasons


def _item_fingerprint(item: ActionItem) -> str:
    canonical = "|".join(
        [
            item.item_type,
            item.destination,
            " ".join(item.title.lower().split()),
            item.repository or "",
            item.start_at.isoformat() if item.start_at else "",
            item.due_at.isoformat() if item.due_at else "",
            item.deadline_at.isoformat() if item.deadline_at else "",
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def update_item(db: Session, plan_id: str, item_id: str, patch: ActionItemUpdate, actor: str = "user") -> ActionPlan:
    plan = get_plan(db, plan_id)
    if not plan:
        raise LookupError("Plan not found")
    item = next((x for x in plan.items if x.id == item_id), None)
    if not item:
        raise LookupError("Item not found")
    if item.state in TERMINAL_ITEM_STATES:
        raise ValueError("Completed or rejected items cannot be edited")
    changes = patch.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if hasattr(value, "value"):
            value = value.value
        setattr(item, field, value)
    _apply_structural_review(item)
    item.fingerprint = _item_fingerprint(item)
    item.state = ItemState.DRAFT.value
    plan.status = PlanStatus.DRAFT.value
    record_audit(
        db,
        entity_type="item",
        entity_id=item.id,
        event_type="item.updated",
        actor=actor,
        payload={k: str(v) for k, v in changes.items()},
    )
    db.commit()
    refreshed = get_plan(db, plan_id)
    if not refreshed:
        raise RuntimeError("Plan missing after update")
    return refreshed


def approve_plan(
    db: Session,
    plan_id: str,
    item_ids: list[str] | None,
    actor: str,
    force_review_items: bool = False,
) -> ActionPlan:
    plan = get_plan(db, plan_id)
    if not plan:
        raise LookupError("Plan not found")
    selected = set(item_ids or [x.id for x in plan.items])
    blocked: list[str] = []
    approved = 0
    for item in plan.items:
        if item.id not in selected or item.state in TERMINAL_ITEM_STATES:
            continue
        structural_reasons = _apply_structural_review(item)
        if item.needs_review and not force_review_items:
            blocked.append(item.id)
            if structural_reasons:
                record_audit(
                    db,
                    entity_type="item",
                    entity_id=item.id,
                    event_type="item.approval_blocked",
                    actor=actor,
                    payload={"reasons": structural_reasons},
                )
            continue
        record_audit(
            db,
            entity_type="item",
            entity_id=item.id,
            event_type="item.approved",
            actor=actor,
            payload={"forced_review": force_review_items and item.needs_review},
        )
        # A human explicitly approved this item, so the safety gate has done its
        # job -- clear the flag so the item drops out of the review list. The
        # structural/manual `review_reason` text is intentionally left in place
        # as an audit trail of why it needed review in the first place.
        item.needs_review = False
        item.state = ItemState.APPROVED.value
        item.execution_error = None
        approved += 1
    if approved:
        plan.status = PlanStatus.APPROVED.value
    record_audit(
        db,
        entity_type="plan",
        entity_id=plan.id,
        event_type="plan.approval_requested",
        actor=actor,
        payload={"approved": approved, "blocked_review_items": blocked},
    )
    db.commit()
    refreshed = get_plan(db, plan_id)
    if not refreshed:
        raise RuntimeError("Plan missing after approval")
    # Transient, non-persisted attribute: lets the API layer surface which items
    # were silently blocked (needs_review + no force override) so a 200 response
    # never looks like unconditional success. See schemas.PlanRead.blocked_item_ids.
    refreshed.blocked_item_ids = blocked
    return refreshed


def reject_items(
    db: Session,
    plan_id: str,
    item_ids: list[str] | None,
    actor: str,
    reason: str,
) -> ActionPlan:
    plan = get_plan(db, plan_id)
    if not plan:
        raise LookupError("Plan not found")
    selected = set(item_ids or [x.id for x in plan.items])
    for item in plan.items:
        if item.id in selected and item.state not in TERMINAL_ITEM_STATES:
            item.state = ItemState.REJECTED.value
            # Same reasoning as approve_plan(): an explicit human decision (here,
            # exclusion) closes out the review, so the item must stop matching the
            # needs_review OR draft review-list filter. review_reason is kept.
            item.needs_review = False
            record_audit(
                db,
                entity_type="item",
                entity_id=item.id,
                event_type="item.rejected",
                actor=actor,
                payload={"reason": reason},
            )
    plan.status = recalculate_plan_status(plan)
    db.commit()
    refreshed = get_plan(db, plan_id)
    if not refreshed:
        raise RuntimeError("Plan missing after rejection")
    return refreshed


def _find_duplicate(db: Session, item: ActionItem) -> ActionItem | None:
    return db.scalar(
        select(ActionItem).where(
            and_(
                ActionItem.id != item.id,
                ActionItem.destination == item.destination,
                ActionItem.fingerprint == item.fingerprint,
                ActionItem.state.in_(
                    [
                        ItemState.REGISTERED.value,
                        ItemState.WAITING.value,
                        ItemState.DISPATCHED.value,
                        ItemState.RUNNING.value,
                        ItemState.HUMAN_REVIEW.value,
                        ItemState.COMPLETED.value,
                        ItemState.SKIPPED_DUPLICATE.value,
                    ]
                ),
            )
        )
    )


def execute_plan(
    db: Session,
    plan_id: str,
    settings: Settings,
    item_ids: list[str] | None,
    actor: str,
    retry_failed: bool = False,
    drain_inline: bool | None = None,
) -> ActionPlan:
    plan = get_plan(db, plan_id)
    if not plan:
        raise LookupError("Plan not found")
    selected = set(item_ids or [x.id for x in plan.items])

    for item in plan.items:
        if item.id not in selected:
            continue
        allowed = item.state == ItemState.APPROVED.value or (
            retry_failed and item.state == ItemState.FAILED.value
        )
        if not allowed:
            continue
        duplicate = _find_duplicate(db, item)
        if duplicate:
            item.state = ItemState.SKIPPED_DUPLICATE.value
            item.external_id = duplicate.external_id
            item.external_url = duplicate.external_url
            item.execution_payload = {"duplicate_of": duplicate.id}
            item.execution_error = None
            record_audit(
                db,
                entity_type="item",
                entity_id=item.id,
                event_type="item.duplicate_skipped",
                actor=actor,
                payload={"duplicate_of": duplicate.id},
            )
            continue
        enqueue_registration(db, item, settings, actor)

    plan.status = recalculate_plan_status(plan)
    record_audit(
        db,
        entity_type="plan",
        entity_id=plan.id,
        event_type="plan.execution_queued",
        actor=actor,
        payload={"status": plan.status},
    )
    db.commit()

    should_drain = settings.worker_inline if drain_inline is None else drain_inline
    if should_drain:
        # Drain enough events to include all selected items while still respecting
        # the configured batch size for unrelated work.
        process_outbox_batch(db, settings, max(settings.outbox_batch_size, len(selected)))

    refreshed = get_plan(db, plan_id)
    if not refreshed:
        raise RuntimeError("Plan missing after execution")
    return refreshed
