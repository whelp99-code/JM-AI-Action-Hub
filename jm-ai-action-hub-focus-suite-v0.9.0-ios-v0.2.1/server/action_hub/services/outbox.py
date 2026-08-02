from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..connectors import ConnectorRegistry
from ..connectors.base import ConnectorResult
from ..models import (
    ActionItem,
    ItemState,
    OutboxEvent,
    PlanStatus,
    utcnow,
)
from .audit import record_audit
from .state_sync import canonical_external_id, recalculate_plan_status, upsert_external_state

logger = logging.getLogger(__name__)

OUTBOX_PENDING = {"pending", "retry"}


def enqueue_event(
    db: Session,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    destination: str | None,
    payload: dict[str, Any] | None,
    idempotency_key: str,
    max_attempts: int,
) -> tuple[OutboxEvent, bool]:
    existing = db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))
    if existing:
        return existing, False
    event = OutboxEvent(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        destination=destination,
        payload_json=payload or {},
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        next_attempt_at=utcnow(),
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(OutboxEvent).where(OutboxEvent.idempotency_key == idempotency_key))
        if existing is None:
            raise
        return existing, False
    return event, True


def enqueue_registration(db: Session, item: ActionItem, settings: Settings, actor: str) -> tuple[OutboxEvent, bool]:
    event, created = enqueue_event(
        db,
        aggregate_type="action_item",
        aggregate_id=item.id,
        event_type="action.register",
        destination=item.destination,
        payload={"actor": actor, "fingerprint": item.fingerprint},
        idempotency_key=f"action.register:{item.id}:{item.fingerprint}",
        max_attempts=settings.outbox_max_attempts,
    )
    if created or event.state in OUTBOX_PENDING:
        item.state = ItemState.QUEUED.value
        item.execution_error = None
        if item.plan:
            item.plan.status = PlanStatus.QUEUED.value
        record_audit(
            db,
            entity_type="item",
            entity_id=item.id,
            event_type="item.registration_queued",
            actor=actor,
            payload={"outbox_event_id": event.id, "destination": item.destination},
        )
    return event, created


def _recover_existing(connector: Any, item: ActionItem) -> ConnectorResult | None:
    finder = getattr(connector, "find_existing", None)
    if not callable(finder):
        return None
    try:
        return finder(item)
    except Exception:
        logger.warning("Connector recovery lookup failed", exc_info=True)
        return None


def _initial_external_state(item: ActionItem, result: ConnectorResult) -> str:
    if item.destination == "none":
        return "completed"
    if item.destination in {"google_calendar", "local_ics"}:
        return "scheduled"
    return "open"


def _process_registration(db: Session, event: OutboxEvent, settings: Settings) -> None:
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == event.aggregate_id)
        .options(selectinload(ActionItem.plan), selectinload(ActionItem.external_states))
    )
    if item is None:
        raise LookupError(f"Action item {event.aggregate_id} not found")
    if item.state in {ItemState.COMPLETED.value, ItemState.SKIPPED_DUPLICATE.value} and item.external_id:
        return

    connector = ConnectorRegistry(settings).get(item.destination)
    item.state = ItemState.EXECUTING.value
    db.flush()

    result = _recover_existing(connector, item) if event.attempts > 1 else None
    if not result or not result.success:
        result = connector.execute(item)
    item.execution_payload = result.payload
    item.execution_error = result.error
    if not result.success:
        raise RuntimeError(result.error or f"{item.destination} registration failed")

    item.external_id = result.external_id
    item.external_url = result.external_url
    item.registered_at = utcnow()
    external_key = canonical_external_id(item.destination, result.external_id, result.payload, item)
    if external_key:
        initial_state = _initial_external_state(item, result)
        upsert_external_state(
            db,
            item=item,
            provider=item.destination,
            external_id=external_key,
            external_url=result.external_url,
            state=initial_state,
            payload=result.payload,
            source_version=settings.version,
        )
    if item.destination == "none":
        item.state = ItemState.COMPLETED.value
        item.completed_at = utcnow()
        item.completion_evidence = "local-note"
    elif item.waiting_for or item.executor == "external":
        item.state = ItemState.WAITING.value
        if item.waiting_for:
            from .followups import ensure_followup
            ensure_followup(db, item, settings, actor=str(event.payload_json.get("actor") or "outbox"))
    else:
        item.state = ItemState.REGISTERED.value
    if item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    from .metrics import record_metric
    record_metric(db, "actions_registered", 1, action_item_id=item.id)
    record_metric(db, "estimated_minutes_saved", 0.5, unit="minutes", action_item_id=item.id, payload={"reason": "automatic_routing"})
    record_audit(
        db,
        entity_type="item",
        entity_id=item.id,
        event_type="item.registered",
        actor=str(event.payload_json.get("actor") or "outbox"),
        payload={
            "destination": item.destination,
            "external_id": item.external_id,
            "external_key": external_key,
            "external_url": item.external_url,
            "simulated": result.simulated,
        },
    )


def _process_worker_dispatch(db: Session, event: OutboxEvent, settings: Settings) -> None:
    # Imported lazily to keep worker adapters independent from the core outbox.
    from .workers import process_worker_dispatch

    process_worker_dispatch(db, event, settings)


def _dispatch_event(db: Session, event: OutboxEvent, settings: Settings) -> None:
    if event.event_type == "action.register":
        _process_registration(db, event, settings)
    elif event.event_type == "worker.dispatch":
        _process_worker_dispatch(db, event, settings)
    else:
        raise ValueError(f"Unsupported outbox event type: {event.event_type}")


def _mark_retry(db: Session, event: OutboxEvent, settings: Settings, exc: Exception) -> None:
    event.last_error = str(exc)
    event.locked_at = None
    if event.attempts >= event.max_attempts:
        event.state = "failed"
        item = db.get(ActionItem, event.aggregate_id) if event.aggregate_type == "action_item" else None
        if item:
            item.state = ItemState.FAILED.value
            item.execution_error = str(exc)
            if item.plan:
                item.plan.status = recalculate_plan_status(item.plan)
        if event.aggregate_type == "worker_execution":
            from ..models import WorkerExecution
            execution = db.get(WorkerExecution, event.aggregate_id)
            if execution:
                execution.state = "failed"
                execution.error = str(exc)
                execution.completed_at = utcnow()
                worker_item = db.get(ActionItem, execution.action_item_id)
                if worker_item:
                    worker_item.state = ItemState.FAILED.value
                    worker_item.execution_error = str(exc)
        record_audit(
            db,
            entity_type=event.aggregate_type,
            entity_id=event.aggregate_id,
            event_type="outbox.permanently_failed",
            payload={"event_type": event.event_type, "attempts": event.attempts, "error": str(exc)},
        )
    else:
        event.state = "retry"
        delay = min(settings.retry_base_seconds * (2 ** max(0, event.attempts - 1)), 3600)
        event.next_attempt_at = utcnow() + timedelta(seconds=delay)
        item = db.get(ActionItem, event.aggregate_id) if event.aggregate_type == "action_item" else None
        if item and item.state == ItemState.EXECUTING.value:
            item.state = ItemState.QUEUED.value
            item.execution_error = str(exc)
        if event.aggregate_type == "worker_execution":
            from ..models import WorkerExecution
            execution = db.get(WorkerExecution, event.aggregate_id)
            if execution:
                execution.state = "queued"
                execution.error = str(exc)


def recover_stale_outbox_events(db: Session, settings: Settings) -> int:
    cutoff = utcnow() - timedelta(seconds=settings.processing_lock_timeout_seconds)
    rows = list(
        db.scalars(
            select(OutboxEvent).where(
                OutboxEvent.state == "processing",
                OutboxEvent.locked_at.is_not(None),
                OutboxEvent.locked_at < cutoff,
            )
        )
    )
    for event in rows:
        event.state = "retry"
        event.locked_at = None
        event.next_attempt_at = utcnow()
        event.last_error = "Recovered stale processing lock"
    if rows:
        db.commit()
    return len(rows)


def _claim_outbox_events(db: Session, settings: Settings, limit: int) -> list[str]:
    recover_stale_outbox_events(db, settings)
    now = utcnow()
    statement = (
        select(OutboxEvent)
        .where(
            OutboxEvent.state.in_(OUTBOX_PENDING),
            or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
        )
        .order_by(OutboxEvent.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    events = list(db.scalars(statement))
    claimed_at = utcnow()
    for event in events:
        event.state = "processing"
        event.attempts += 1
        event.locked_at = claimed_at
    db.commit()
    return [event.id for event in events]


def process_outbox_batch(db: Session, settings: Settings, limit: int | None = None) -> dict[str, int]:
    event_ids = _claim_outbox_events(db, settings, limit or settings.outbox_batch_size)
    summary = {"processed": 0, "completed": 0, "failed": 0, "retry": 0}
    for event_id in event_ids:
        event = db.get(OutboxEvent, event_id)
        if event is None or event.state != "processing":
            continue
        try:
            _dispatch_event(db, event, settings)
            event.state = "completed"
            event.completed_at = utcnow()
            event.locked_at = None
            event.last_error = None
            summary["completed"] += 1
        except Exception as exc:  # each event is isolated and retried durably
            logger.warning("Outbox event %s failed: %s", event.id, exc)
            _mark_retry(db, event, settings, exc)
            summary["failed"] += 1
            if event.state == "retry":
                summary["retry"] += 1
        db.commit()
        summary["processed"] += 1
    return summary

