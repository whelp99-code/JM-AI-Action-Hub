from __future__ import annotations

import hashlib
import re

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import ActionItem, ActionPlan, ActionType, Destination, ItemState, OutboxEvent, PlanStatus
from ..schemas import ActionItemUpdate, ExecutionErrorEntry, ExecutionSummary
from .audit import record_audit
from .outbox import enqueue_registration, process_outbox_batch
from .planner import get_plan
from .state_sync import clear_needs_review, recalculate_plan_status

TERMINAL_ITEM_STATES = {
    ItemState.COMPLETED.value,
    ItemState.REJECTED.value,
    ItemState.SKIPPED_DUPLICATE.value,
    ItemState.CANCELLED.value,
}

_ACTIVE_STATES = {ItemState.QUEUED.value, ItemState.EXECUTING.value}
_MAX_EXECUTION_ERRORS = 20

# Connector failures can echo back request context (headers, query strings) that
# carried a credential. These patterns cover the shapes actually used by the
# bundled connectors (Bearer headers, key=value pairs, provider token prefixes)
# so execution_error text is safe to return to a mobile client.
_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b(api[_-]?key|token|secret|password|access[_-]?token)\b(\s*[:=]\s*)[\"']?[A-Za-z0-9._~+/=-]{6,}[\"']?"
    ),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9-]{10,}\b"),
]


def _mask_secrets(message: str) -> str:
    masked = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)} ***", message)
    masked = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}{m.group(2)}***", masked)
    masked = _SECRET_PATTERNS[2].sub("***", masked)
    masked = _SECRET_PATTERNS[3].sub("***", masked)
    return masked


def _latest_outbox_attempts(db: Session, item_ids: list[str]) -> dict[str, int]:
    if not item_ids:
        return {}
    rows = db.execute(
        select(OutboxEvent.aggregate_id, OutboxEvent.attempts)
        .where(
            OutboxEvent.aggregate_type == "action_item",
            OutboxEvent.aggregate_id.in_(item_ids),
            OutboxEvent.event_type == "action.register",
        )
        .order_by(OutboxEvent.aggregate_id, OutboxEvent.created_at.desc())
    ).all()
    attempts: dict[str, int] = {}
    for aggregate_id, value in rows:
        # First row per aggregate_id wins because of the created_at DESC order,
        # i.e. it is the most recent outbox event for that item.
        attempts.setdefault(aggregate_id, value)
    return attempts


def build_execution_summary(db: Session, plan: ActionPlan) -> ExecutionSummary:
    """Single source of truth for the execute-plan response shape.

    Both api/mobile.py and api/routes.py called this independently before,
    which had already drifted once (mobile lacked the ``failed``/``pending``
    accounting present in the plain API). Keeping one implementation means a
    fix here reaches both callers.
    """

    action_completed = sum(item.state == ItemState.COMPLETED.value for item in plan.items)
    registered_states = {
        ItemState.REGISTERED.value,
        ItemState.WAITING.value,
        ItemState.DISPATCHED.value,
        ItemState.RUNNING.value,
        ItemState.NEEDS_INPUT.value,
        ItemState.HUMAN_REVIEW.value,
    }
    registered = sum(item.state in registered_states for item in plan.items)
    queued = sum(item.state in _ACTIVE_STATES for item in plan.items)
    failed = sum(item.state == ItemState.FAILED.value for item in plan.items)
    duplicate = sum(item.state == ItemState.SKIPPED_DUPLICATE.value for item in plan.items)
    rejected = sum(item.state == ItemState.REJECTED.value for item in plan.items)
    pending = len(plan.items) - action_completed - registered - queued - failed - duplicate - rejected

    # A retrying item is still counted in ``queued`` above (state is
    # QUEUED/EXECUTING) so existing consumers of that field keep working, but it
    # also carries an execution_error from a failed attempt -- see
    # services/outbox.py:_mark_retry. Surfacing it here is what stops a 200
    # response from reading as unconditional success.
    retrying_items = [
        item for item in plan.items if item.state in _ACTIVE_STATES and (item.execution_error or "").strip()
    ]
    errors: list[ExecutionErrorEntry] = []
    if retrying_items:
        attempts_by_item = _latest_outbox_attempts(db, [item.id for item in retrying_items])
        for item in retrying_items[:_MAX_EXECUTION_ERRORS]:
            errors.append(
                ExecutionErrorEntry(
                    item_id=item.id,
                    title=item.title,
                    error=_mask_secrets(item.execution_error or ""),
                    attempts=attempts_by_item.get(item.id, 0),
                )
            )

    return ExecutionSummary(
        plan_id=plan.id,
        plan_status=plan.status,
        completed=registered + action_completed,
        registered=registered,
        action_completed=action_completed,
        queued=queued,
        failed=failed,
        skipped_duplicate=duplicate,
        pending=max(0, pending),
        retrying=len(retrying_items),
        errors=errors,
        items=plan.items,
    )


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
        # LegacyStringEnum.__str__ returns "Type.NAME" for backward compatibility
        # with v0.1 string-enum consumers (see models.py). That form leaked into
        # this audit payload and from there into the mobile activity feed
        # subtitle (services/mobile.py:_activity_title). Use .value instead.
        payload={k: (v.value if hasattr(v, "value") else str(v)) for k, v in changes.items()},
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
        # job -- clear the flag so the item drops out of the review list. See
        # state_sync.clear_needs_review for why review_reason is left in place.
        clear_needs_review(item)
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
            clear_needs_review(item)
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
