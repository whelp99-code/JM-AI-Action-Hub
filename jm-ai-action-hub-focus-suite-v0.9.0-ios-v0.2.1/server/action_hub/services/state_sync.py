from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ActionItem,
    ActionPlan,
    ExternalState,
    ItemState,
    PlanStatus,
    SyncConflict,
    utcnow,
)
from .audit import record_audit

ROUTED_STATES = {
    ItemState.REGISTERED.value,
    ItemState.WAITING.value,
    ItemState.DISPATCHED.value,
    ItemState.RUNNING.value,
    ItemState.NEEDS_INPUT.value,
    ItemState.HUMAN_REVIEW.value,
    ItemState.COMPLETED.value,
    ItemState.SKIPPED_DUPLICATE.value,
}
TERMINAL_STATES = {
    ItemState.COMPLETED.value,
    ItemState.REJECTED.value,
    ItemState.SKIPPED_DUPLICATE.value,
    ItemState.CANCELLED.value,
}


def clear_needs_review(item: ActionItem) -> None:
    """Close out the review gate on an explicit state transition.

    Single place for the fix applied across approve/reject/focus-complete/
    day-close-cancel/followup-resolve/external-sync -- every caller that moves
    an item into a state a human (or an authoritative external system) has
    settled must stop matching the needs_review-based review list and badge
    count. ``review_reason`` is intentionally preserved as an audit trail of
    why the item needed review in the first place.
    """

    item.needs_review = False


def canonical_external_id(
    provider: str,
    native_external_id: str | None,
    payload: dict[str, Any] | None = None,
    item: ActionItem | None = None,
) -> str | None:
    """Build a globally unique provider resource key without changing the v0.1 API field.

    GitHub issue numbers are only unique inside a repository, so the mirror stores
    ``owner/repo#number`` while ``ActionItem.external_id`` keeps the legacy number.
    """

    if native_external_id is None:
        return None
    native = str(native_external_id)
    data = payload or {}
    if provider == "github":
        repository = data.get("repository") or (item.repository if item else None)
        native_id = data.get("native_id") or native
        if repository:
            return f"{repository}#{native_id}"
    return native


def find_external_state(db: Session, provider: str, external_id: str) -> ExternalState | None:
    return db.scalar(
        select(ExternalState).where(
            ExternalState.provider == provider,
            ExternalState.external_id == external_id,
        )
    )


def upsert_external_state(
    db: Session,
    *,
    item: ActionItem,
    provider: str,
    external_id: str,
    external_url: str | None,
    state: str,
    payload: dict[str, Any] | None = None,
    external_updated_at: datetime | None = None,
    source_version: str | None = None,
    sync_error: str | None = None,
) -> ExternalState:
    mirror = find_external_state(db, provider, external_id)
    if mirror is None:
        mirror = ExternalState(
            action_item_id=item.id,
            provider=provider,
            external_id=external_id,
            external_url=external_url,
            state=state,
            payload_json=payload or {},
            external_updated_at=external_updated_at,
            last_synced_at=utcnow(),
            source_version=source_version,
            sync_error=sync_error,
        )
        db.add(mirror)
    else:
        # Ignore a delayed webhook/poll response that is older than the state we
        # have already accepted. Providers are allowed to deliver out of order.
        if (
            external_updated_at
            and mirror.external_updated_at
            and external_updated_at < mirror.external_updated_at
        ):
            return mirror
        mirror.action_item_id = item.id
        mirror.external_url = external_url or mirror.external_url
        mirror.state = state
        mirror.payload_json = payload or mirror.payload_json
        mirror.external_updated_at = external_updated_at or mirror.external_updated_at
        mirror.last_synced_at = utcnow()
        mirror.source_version = source_version or mirror.source_version
        mirror.sync_error = sync_error
    return mirror


def recalculate_plan_status(plan: ActionPlan) -> str:
    active = [item for item in plan.items if item.state != ItemState.REJECTED.value]
    if not active:
        return PlanStatus.REJECTED.value

    states = {item.state for item in active}
    completed_count = sum(
        item.state in {ItemState.COMPLETED.value, ItemState.SKIPPED_DUPLICATE.value}
        for item in active
    )
    failed_count = sum(item.state == ItemState.FAILED.value for item in active)

    if completed_count == len(active):
        return PlanStatus.COMPLETED.value
    if states & {ItemState.QUEUED.value, ItemState.EXECUTING.value}:
        return PlanStatus.QUEUED.value
    if failed_count:
        if failed_count == len(active):
            return PlanStatus.FAILED.value
        return PlanStatus.PARTIAL.value
    if all(item.state in ROUTED_STATES for item in active):
        return PlanStatus.ROUTED.value
    if ItemState.APPROVED.value in states:
        return PlanStatus.APPROVED.value
    return PlanStatus.DRAFT.value


def _create_reopen_conflict(
    db: Session,
    item: ActionItem,
    provider: str,
    external_state: str,
) -> None:
    db.add(
        SyncConflict(
            action_item_id=item.id,
            provider=provider,
            conflict_type="external_reopened_after_local_completion",
            local_value={"state": item.state, "completed_at": item.completed_at.isoformat() if item.completed_at else None},
            external_value={"state": external_state},
            resolution="external_source_wins",
            resolved_at=utcnow(),
        )
    )


def apply_external_state(
    db: Session,
    *,
    item: ActionItem,
    provider: str,
    external_id: str,
    state: str,
    external_url: str | None = None,
    payload: dict[str, Any] | None = None,
    external_updated_at: datetime | None = None,
    source_version: str | None = None,
    actor: str = "sync",
) -> ExternalState:
    """Mirror a provider state and update the local action lifecycle.

    Provider resources are authoritative for completion/open/cancelled state. A
    reopened external task therefore reopens the local action and records the
    resolved conflict instead of silently keeping stale local completion.
    """

    normalized = (state or "unknown").lower()
    mirror = upsert_external_state(
        db,
        item=item,
        provider=provider,
        external_id=external_id,
        external_url=external_url,
        state=normalized,
        payload=payload,
        external_updated_at=external_updated_at,
        source_version=source_version,
    )
    previous = item.state

    completed_states = {"completed", "closed", "merged", "resolved", "succeeded", "success"}
    open_states = {"open", "active", "scheduled", "reopened", "in_progress", "queued"}
    cancelled_states = {"cancelled", "canceled", "deleted"}
    failed_states = {"failed", "failure", "timed_out", "action_required"}

    if normalized in completed_states:
        item.state = ItemState.COMPLETED.value
        item.completed_at = external_updated_at or utcnow()
        item.completion_evidence = external_url or f"{provider}:{external_id}"
        clear_needs_review(item)
    elif normalized in open_states:
        if item.state == ItemState.COMPLETED.value:
            _create_reopen_conflict(db, item, provider, normalized)
        # Keep active worker/follow-up substates, otherwise return to registered.
        if item.state not in {
            ItemState.WAITING.value,
            ItemState.DISPATCHED.value,
            ItemState.RUNNING.value,
            ItemState.NEEDS_INPUT.value,
            ItemState.HUMAN_REVIEW.value,
        }:
            item.state = ItemState.REGISTERED.value
        item.completed_at = None
    elif normalized in cancelled_states:
        item.state = ItemState.CANCELLED.value
        item.completed_at = external_updated_at or utcnow()
        clear_needs_review(item)
    elif normalized in failed_states:
        item.state = ItemState.FAILED.value
        item.execution_error = f"External provider reported {normalized}"

    if external_url:
        item.external_url = external_url
    if previous != item.state:
        record_audit(
            db,
            entity_type="item",
            entity_id=item.id,
            event_type="item.external_state_changed",
            actor=actor,
            payload={
                "provider": provider,
                "external_id": external_id,
                "from": previous,
                "to": item.state,
                "external_state": normalized,
            },
        )
    if item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    return mirror
