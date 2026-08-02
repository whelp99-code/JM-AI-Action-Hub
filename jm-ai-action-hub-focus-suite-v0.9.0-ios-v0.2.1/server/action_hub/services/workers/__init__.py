from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...config import Settings
from ...models import ActionItem, ItemState, OutboxEvent, WorkerExecution, utcnow
from ..audit import record_audit
from ..outbox import enqueue_event, process_outbox_batch
from ..push import queue_push_for_active_devices
from ..state_sync import recalculate_plan_status
from .github_workflow import GitHubWorkflowWorker

SUPPORTED_WORKERS = {"codex", "claude", "copilot", "orca", "hermes", "master-worker"}
ACTIVE_EXECUTION_STATES = {"queued", "dispatched", "running", "needs_input", "human_review"}


class WorkerRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get(self, name: str) -> GitHubWorkflowWorker:
        normalized = name.lower().strip()
        if normalized not in SUPPORTED_WORKERS and normalized not in self.settings.worker_routes:
            raise KeyError(f"Unsupported worker: {name}")
        return GitHubWorkflowWorker(normalized, self.settings)

    def statuses(self) -> list[dict]:
        names = sorted(SUPPORTED_WORKERS | set(self.settings.worker_routes))
        return [
            {
                "name": name,
                "configured": bool(self.settings.worker_routes.get(name)),
                "execution_mode": self.settings.execution_mode,
                "route": self.settings.worker_routes.get(name, {}),
            }
            for name in names
        ]


def queue_worker_dispatch(
    db: Session,
    *,
    item_id: str,
    worker: str,
    settings: Settings,
    actor: str = "user",
    force: bool = False,
    drain_inline: bool | None = None,
) -> WorkerExecution:
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == item_id)
        .options(selectinload(ActionItem.plan), selectinload(ActionItem.worker_executions))
    )
    if item is None:
        raise LookupError("Action item not found")
    if item.executor not in {"ai", "hybrid"} and not force:
        raise ValueError("Only AI or hybrid actions can be dispatched without force")
    if item.needs_review and not force:
        raise ValueError("Action requires review before worker dispatch")
    if item.state not in {
        ItemState.REGISTERED.value,
        ItemState.HUMAN_REVIEW.value,
        ItemState.FAILED.value,
        ItemState.APPROVED.value,
    } and not force:
        raise ValueError(f"Action state '{item.state}' is not dispatchable")
    active = next((x for x in item.worker_executions if x.state in ACTIVE_EXECUTION_STATES), None)
    if active and not force:
        return active

    adapter = WorkerRegistry(settings).get(worker)
    if not adapter.can_handle(item):
        raise ValueError(f"Worker '{worker}' cannot handle this action; repository route is missing")
    issue_number = int(item.external_id) if str(item.external_id or "").isdigit() else None
    execution = WorkerExecution(
        action_item_id=item.id,
        worker=worker.lower(),
        state="queued",
        repository=adapter.route.get("repository") or item.repository,
        issue_number=issue_number,
    )
    db.add(execution)
    db.flush()
    enqueue_event(
        db,
        aggregate_type="worker_execution",
        aggregate_id=execution.id,
        event_type="worker.dispatch",
        destination=worker.lower(),
        payload={"actor": actor, "action_item_id": item.id},
        idempotency_key=f"worker.dispatch:{execution.id}",
        max_attempts=settings.outbox_max_attempts,
    )
    item.state = ItemState.QUEUED.value
    if item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    record_audit(
        db,
        entity_type="worker_execution",
        entity_id=execution.id,
        event_type="worker.dispatch_queued",
        actor=actor,
        payload={"worker": worker, "action_item_id": item.id},
    )
    queue_push_for_active_devices(
        db,
        settings,
        event_type="ai_status",
        entity_type="worker_execution",
        entity_id=execution.id,
        idempotency_suffix=f"{execution.id}:queued",
    )
    db.commit()
    if settings.worker_inline if drain_inline is None else drain_inline:
        process_outbox_batch(db, settings)
    db.refresh(execution)
    return execution


def process_worker_dispatch(db: Session, event: OutboxEvent, settings: Settings) -> None:
    execution = db.scalar(
        select(WorkerExecution)
        .where(WorkerExecution.id == event.aggregate_id)
        .options(
            selectinload(WorkerExecution.action_item).selectinload(ActionItem.plan),
        )
    )
    if execution is None:
        raise LookupError(f"Worker execution {event.aggregate_id} not found")
    item = execution.action_item
    adapter = WorkerRegistry(settings).get(execution.worker)
    result = adapter.dispatch(item, execution)
    execution.artifacts_json = {**(execution.artifacts_json or {}), "dispatch_payload": result.payload}
    execution.error = result.error
    if not result.success:
        execution.state = "queued"
        raise RuntimeError(result.error or "Worker dispatch failed")
    execution.state = "dispatched"
    execution.dispatch_id = result.dispatch_id
    execution.started_at = execution.started_at or utcnow()
    item.state = ItemState.DISPATCHED.value
    if item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    record_audit(
        db,
        entity_type="worker_execution",
        entity_id=execution.id,
        event_type="worker.dispatched",
        actor=str(event.payload_json.get("actor") or "outbox"),
        payload={
            "worker": execution.worker,
            "dispatch_id": execution.dispatch_id,
            "simulated": result.simulated,
        },
    )
    queue_push_for_active_devices(
        db,
        settings,
        event_type="ai_status",
        entity_type="worker_execution",
        entity_id=execution.id,
        idempotency_suffix=f"{execution.id}:dispatched",
    )


__all__ = [
    "SUPPORTED_WORKERS",
    "WorkerRegistry",
    "process_worker_dispatch",
    "queue_worker_dispatch",
]
