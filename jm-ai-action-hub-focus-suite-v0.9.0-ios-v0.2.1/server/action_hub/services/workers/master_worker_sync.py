"""Explicit, Owner-invoked pull of JM-AI Master Worker intake progress.

LocalWebhookWorker (see .local_webhook) creates an MW goal intake and marks the
Action Hub ``WorkerExecution`` ``dispatched``. MW has no completion callback
back to Action Hub, and there is deliberately no automatic background poller
here (Owner-explicit-execution principle) — this module only runs when the
Owner invokes ``action-hub worker-sync``.

Read surface actually available on MW (verified against apps/server/src/http.ts
and packages/core/src/service.ts in the MW repo, 2026-08-05): MW exposes no
``GET /api/v1/intakes/:id`` route at all — only POST/PATCH/analyze/bind/DELETE.
The only queryable, audited signal for a single intake's lifecycle is the
generic append-only audit log: ``GET /api/v1/audit?objectType=intake&objectId=<id>``
(packages/storage/src/sqlite-store.ts SqliteStore.listAudit). Each intake
lifecycle call (createIntake/analyzeIntake/bindIntake/discardIntake) records an
audit row whose ``action`` is one of ``create``/``analyze``/``bind``/``discard``
against ``objectId=<intakeId>`` (packages/core/src/service.ts ~L1090-1148).

That audit trail tells us whether an intake was bound to a project (Owner
accepted it) or discarded (Owner rejected it) — but MW records the resulting
Objective under its own id with no ``intakeId`` back-reference in the audit
``details``, and MW has no ``GET /api/v1/objectives`` list route, so Action Hub
cannot discover which Objective (if any) an intake became, nor its downstream
plan/work-item/release status. Full completion is therefore NOT observable
from Action Hub today. This module only distinguishes: still pending in MW
(no state change), bound (mapped to ``running`` — the strongest forward signal
available), or discarded (mapped to ``failed``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...config import Settings
from ...models import ActionItem, ItemState, WorkerExecution, utcnow
from ..audit import record_audit
from ..state_sync import recalculate_plan_status
from .mw_credentials import read_bearer_credential, validate_loopback_base_url

logger = logging.getLogger(__name__)

WORKER_NAME = "master-worker"
DISPATCH_ID_PREFIX = "mw-intake-"
# Audit "action" values that change an intake's lifecycle status
# (packages/core/src/service.ts createIntake/analyzeIntake/bindIntake/discardIntake).
# "autosave" (updateIntake's PATCH) is intentionally excluded: it edits text/
# classification without changing status.
STATUS_RELEVANT_ACTIONS = {"create", "analyze", "bind", "discard"}

OutcomeKind = Literal["updated", "unchanged", "skipped", "failed"]


@dataclass(slots=True)
class SyncOutcome:
    execution_id: str
    intake_id: str | None
    previous_state: str
    new_state: str | None
    outcome: OutcomeKind
    reason: str


@dataclass(slots=True)
class SyncSummary:
    checked: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    failed: int = 0
    outcomes: list[SyncOutcome] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped": self.skipped,
            "failed": self.failed,
            "outcomes": [
                {
                    "executionId": o.execution_id,
                    "intakeId": o.intake_id,
                    "previousState": o.previous_state,
                    "newState": o.new_state,
                    "outcome": o.outcome,
                    "reason": o.reason,
                }
                for o in self.outcomes
            ],
        }


def _extract_intake_id(dispatch_id: str | None) -> str | None:
    if not dispatch_id or not dispatch_id.startswith(DISPATCH_ID_PREFIX):
        return None
    intake_id = dispatch_id[len(DISPATCH_ID_PREFIX):]
    return intake_id or None


def _fetch_intake_audit_trail(
    base_url: str, token: str, intake_id: str, timeout: float
) -> tuple[list[dict] | None, str | None]:
    """Query MW's audit log for one intake. Returns (events, error)."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {"objectType": "intake", "objectId": intake_id, "result": "success", "limit": "200"}
    try:
        response = httpx.get(f"{base_url}/api/v1/audit", headers=headers, params=params, timeout=timeout)
    except httpx.HTTPError as exc:
        return None, f"MW unreachable: {exc}"
    if response.status_code == 401:
        return None, "MW rejected the request: authentication failed (401)"
    if response.status_code == 404:
        return None, "MW audit endpoint returned 404"
    if response.status_code >= 400:
        return None, f"MW audit query failed with status {response.status_code}"
    try:
        body = response.json() if response.content else {}
    except ValueError as exc:
        return None, f"MW audit response was not valid JSON: {exc}"
    events = body.get("data") if isinstance(body, dict) else None
    if not isinstance(events, list):
        return None, "MW audit response did not contain a data array"
    return events, None


def _current_intake_status(events: list[dict]) -> str | None:
    """Most recent status-changing action for the intake, or None if none seen.

    MW's listAudit orders rows by sequence DESC (newest first), so the first
    matching action in the list is the current status.
    """
    for event in events:
        action = event.get("action") if isinstance(event, dict) else None
        if action in STATUS_RELEVANT_ACTIONS:
            return action
    return None


def sync_execution(db: Session, execution: WorkerExecution, settings: Settings) -> SyncOutcome:
    """Pull MW's audit trail for one dispatched master-worker execution and apply it.

    Fail-closed: any MW reachability/auth/response-shape problem leaves
    ``execution.state`` untouched; only the reason is recorded on the returned
    outcome (never raised past this function for a single-execution problem).
    """
    intake_id = _extract_intake_id(execution.dispatch_id)
    if intake_id is None:
        return SyncOutcome(
            execution.id, None, execution.state, None, "skipped",
            "dispatch_id is not an MW intake reference (simulated dispatch or foreign worker)",
        )

    route = settings.worker_routes.get(WORKER_NAME, {})
    valid, base_url_error = validate_loopback_base_url(route.get("baseUrl"))
    if not valid:
        return SyncOutcome(execution.id, intake_id, execution.state, None, "failed", base_url_error or "invalid baseUrl")

    token, token_error = read_bearer_credential(route.get("credentialFile"))
    if token_error:
        return SyncOutcome(execution.id, intake_id, execution.state, None, "failed", token_error)

    base_url = str(route.get("baseUrl")).rstrip("/")
    timeout = float(route.get("timeoutSeconds") or settings.request_timeout_seconds)
    events, error = _fetch_intake_audit_trail(base_url, token, intake_id, timeout)
    if error:
        return SyncOutcome(execution.id, intake_id, execution.state, None, "failed", error)

    status_action = _current_intake_status(events or [])
    if status_action is None:
        return SyncOutcome(
            execution.id, intake_id, execution.state, None, "unchanged",
            "no MW audit history found for intake yet",
        )

    previous_state = execution.state
    if status_action == "discard":
        new_state: str | None = "failed"
    elif status_action == "bind":
        new_state = "running"
    else:
        # create/analyze: intake is still awaiting Owner action in MW; nothing to apply.
        return SyncOutcome(
            execution.id, intake_id, previous_state, None, "unchanged",
            f"MW intake status is still '{status_action}'; no change",
        )

    if new_state == previous_state:
        return SyncOutcome(
            execution.id, intake_id, previous_state, None, "unchanged",
            f"MW intake status '{status_action}' already reflected",
        )

    execution.state = new_state
    if new_state == "failed":
        execution.error = "MW intake was discarded"
        execution.completed_at = utcnow()
    item = execution.action_item
    if item is not None:
        item.state = ItemState.FAILED.value if new_state == "failed" else ItemState.RUNNING.value
        if new_state == "failed":
            item.execution_error = execution.error
        if item.plan:
            item.plan.status = recalculate_plan_status(item.plan)
    record_audit(
        db,
        entity_type="worker_execution",
        entity_id=execution.id,
        event_type="worker.master_worker_synced",
        actor="worker-sync-cli",
        payload={"intakeId": intake_id, "mwStatus": status_action, "state": new_state},
    )
    return SyncOutcome(
        execution.id, intake_id, previous_state, new_state, "updated",
        f"MW intake status '{status_action}' applied",
    )


def sync_master_worker_executions(db: Session, settings: Settings) -> SyncSummary:
    """Pull MW intake progress for every dispatched master-worker execution.

    Owner-invoked only (CLI ``action-hub worker-sync``) — never called from the
    background control loop (``action-hub-worker`` / ``worker-once --reconcile``).
    Each execution is isolated and committed independently, mirroring the
    existing outbox/reconciliation pattern, so one failure does not block others.
    """
    summary = SyncSummary()
    executions = list(
        db.scalars(
            select(WorkerExecution)
            .where(WorkerExecution.worker == WORKER_NAME, WorkerExecution.state == "dispatched")
            .options(selectinload(WorkerExecution.action_item).selectinload(ActionItem.plan))
        )
    )
    for execution in executions:
        summary.checked += 1
        try:
            outcome = sync_execution(db, execution, settings)
            db.commit()
        except Exception as exc:  # each execution is isolated; one failure must not abort the batch
            db.rollback()
            logger.warning("master-worker sync failed for execution %s: %s", execution.id, exc)
            outcome = SyncOutcome(execution.id, None, execution.state, None, "failed", f"unexpected error: {exc}")
        summary.outcomes.append(outcome)
        if outcome.outcome == "updated":
            summary.updated += 1
        elif outcome.outcome == "failed":
            summary.failed += 1
        elif outcome.outcome == "skipped":
            summary.skipped += 1
        else:
            summary.unchanged += 1
    return summary


__all__ = [
    "SyncOutcome",
    "SyncSummary",
    "sync_execution",
    "sync_master_worker_executions",
]
