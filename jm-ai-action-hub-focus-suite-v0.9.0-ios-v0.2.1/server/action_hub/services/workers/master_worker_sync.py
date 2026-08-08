"""Explicit, Owner-invoked pull of JM-AI Master Worker intake progress.

LocalWebhookWorker (see .local_webhook) creates an MW goal intake and marks the
Action Hub ``WorkerExecution`` ``dispatched``. MW has no completion callback
back to Action Hub, and there is deliberately no automatic background poller
here (Owner-explicit-execution principle) — this module only runs when the
Owner invokes ``action-hub worker-sync``.

Primary read surface (MW commit a46c988; docs/API.md "Intake progress lookup";
verified against packages/core/src/service.ts ``Service.getIntakeStatus``):
``GET /api/v1/intakes/{intakeId}`` returns
``{"intakeId","state","boundProjectId"?,"objectiveId"?,"objectiveState"?,"updatedAt"}``.
``objectiveId``/``objectiveState`` are *absent keys*, not null, until the
intake is promoted to an Objective — ``getIntakeStatus`` builds the response
by spreading ``objective?.id`` / ``objective?.state``, and JSON.stringify
drops object keys whose value is ``undefined`` — so this module tests for key
presence (``"objectiveId" in data``), never for a null/None value.

Fallback for an older MW without this route: a 404 from
``GET /intakes/{id}`` falls back to the append-only audit log this module
used exclusively before the dedicated route existed —
``GET /api/v1/audit?objectType=intake&objectId=<id>`` (packages/storage/src/
sqlite-store.ts SqliteStore.listAudit) — deriving status from the most recent
of the intake lifecycle audit actions (create/analyze/bind/discard). Every
outcome produced via that fallback records the fact in its ``reason`` so
Owner-facing summaries surface when a rolling MW upgrade is still pending.

State mapping:

- No Objective yet (``"objectiveId" not in data``): the raw MW intake
  ``state`` (packages/contracts/src/types.ts ``IntakeDraft.status``: draft |
  analyzed | bound | discarded) drives the result. See
  ``INTAKE_STATE_TO_EXECUTION_STATE`` below.
- Objective exists: ``objectiveState`` (packages/contracts/src/types.ts
  ``ObjectiveState``; transition graph verified against packages/core/src/
  state-machines.ts ``objectiveTransitions``) drives the result. See
  ``OBJECTIVE_STATE_TO_EXECUTION_STATE`` below for the full table. Any MW
  state value this module does not recognize (a future MW version may add
  states) leaves the execution untouched — fail-closed — with the raw value
  logged in the outcome reason.

Remaining limitation: the dedicated route is deliberately minimal — MW's own
docs note it exists so an external caller "does not need to see the goal body
or candidate scoring, only progress" — so Action Hub still cannot see
individual WorkItem/Run/Release detail, only the coarse Objective state
mapped above.
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
# classification without changing status. Only used by the legacy audit-trail
# fallback (see module docstring).
STATUS_RELEVANT_ACTIONS = {"create", "analyze", "bind", "discard"}

# MW Intake status (packages/contracts/src/types.ts IntakeDraft.status) once
# fetched via GET /intakes/{id} with no Objective yet promoted from it.
# None = no forward signal, leave the Action Hub execution untouched.
INTAKE_STATE_TO_EXECUTION_STATE: dict[str, str | None] = {
    "draft": None,  # awaiting Owner analyze/bind in MW
    "analyzed": None,  # awaiting Owner bind/discard in MW
    "bound": "running",  # Owner accepted; strongest forward signal before an Objective exists
    "discarded": "failed",  # Owner rejected
}

# MW Objective lifecycle (packages/contracts/src/types.ts ObjectiveState),
# mapped against the actual transition graph in packages/core/src/
# state-machines.ts objectiveTransitions (verified 2026-08-05, not guessed):
#   captured -> identified -> scoped -> compiled -> planned -> awaiting_approval
#   -> executing -> verifying -> (resolving <-> verifying/executing) -> packaging
#   -> delivered -> closed
#   Side branches: blocked (reachable from most active states), paused (Owner
#   checkpoint, resumes back to pausedFrom), cancelled (terminal, no exit).
# Target vocabulary is Action Hub's own WorkerExecution.state, as actually used
# by webhooks.py's github_pr/workflow_run/check_suite handlers:
# queued/dispatched/running/human_review/completed/failed.
# None = no forward signal (explicit design choice, not the fail-closed
# default for an unrecognized value — see "paused" below).
OBJECTIVE_STATE_TO_EXECUTION_STATE: dict[str, str | None] = {
    "captured": "running",
    "identified": "running",
    "scoped": "running",
    "compiled": "running",
    "planned": "running",
    "awaiting_approval": "running",
    "executing": "running",
    "verifying": "running",
    "resolving": "running",
    "packaging": "running",
    "delivered": "completed",  # released (objectiveTransitions.delivered -> ['closed', 'rolled_back'])
    "closed": "completed",  # archived after delivery; still a success outcome
    "blocked": "human_review",  # stuck, needs Owner/human attention to unblock or cancel
    "cancelled": "failed",  # terminal, will not complete
    # "paused" is an explicit Owner checkpoint (pauseObjective), not a forward
    # completion signal, and MW resumes it back to whatever state it was
    # paused from — so it must not overwrite the Action Hub execution state.
    "paused": None,
}

# Action Hub ActionItem.state (see action_hub.models.ItemState) mirrored per
# WorkerExecution.state, matching the pairing already used by webhooks.py.
ITEM_STATE_BY_EXECUTION_STATE = {
    "running": ItemState.RUNNING.value,
    "human_review": ItemState.HUMAN_REVIEW.value,
    "completed": ItemState.COMPLETED.value,
    "failed": ItemState.FAILED.value,
}

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


def _fetch_intake_status(
    base_url: str, token: str, intake_id: str, timeout: float
) -> tuple[dict[str, Any] | None, bool, str | None]:
    """Query MW's dedicated intake status route. Returns (data, not_found, error).

    ``not_found=True`` on a 404 signals either an intake id MW doesn't
    recognize (unlikely once dispatched) or — the case this module is built
    to absorb — an MW instance too old to have this route; the caller falls
    back to the legacy audit trail in that case. Any other error leaves the
    caller unable to distinguish and it is treated as a plain failure (no
    fallback attempted), matching fail-closed intent: a shape/auth/reachability
    problem on the new route should not fall through to a possibly-stale audit
    read.
    """
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = httpx.get(f"{base_url}/api/v1/intakes/{intake_id}", headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        return None, False, f"MW unreachable: {exc}"
    if response.status_code == 401:
        return None, False, "MW rejected the request: authentication failed (401)"
    if response.status_code == 404:
        return None, True, None
    if response.status_code >= 400:
        return None, False, f"MW intake status query failed with status {response.status_code}"
    try:
        body = response.json() if response.content else {}
    except ValueError as exc:
        return None, False, f"MW intake status response was not valid JSON: {exc}"
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None, False, "MW intake status response did not contain a data object"
    return data, False, None


def _fetch_intake_audit_trail(
    base_url: str, token: str, intake_id: str, timeout: float
) -> tuple[list[dict] | None, str | None]:
    """Query MW's audit log for one intake (legacy fallback). Returns (events, error)."""
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


def _apply_state_transition(
    db: Session,
    execution: WorkerExecution,
    intake_id: str,
    new_state: str | None,
    outcome_reason: str,
    *,
    mw_status_label: str,
    error_message: str | None = None,
) -> SyncOutcome:
    """Apply (or no-op) a resolved target state to ``execution``.

    Fail-closed / idempotent: ``new_state is None`` or already matching the
    current state produces an "unchanged" outcome and mutates nothing.
    """
    previous_state = execution.state
    if new_state is None:
        return SyncOutcome(execution.id, intake_id, previous_state, None, "unchanged", outcome_reason)
    if new_state == previous_state:
        return SyncOutcome(
            execution.id, intake_id, previous_state, None, "unchanged",
            f"{outcome_reason} (already reflected)",
        )

    execution.state = new_state
    if new_state in ("failed", "completed"):
        execution.completed_at = utcnow()
    if new_state == "failed":
        execution.error = error_message or outcome_reason

    item = execution.action_item
    if item is not None:
        item.state = ITEM_STATE_BY_EXECUTION_STATE.get(new_state, item.state)
        if new_state == "failed":
            item.execution_error = execution.error
        elif new_state == "completed" and not item.completion_evidence:
            item.completion_evidence = f"mw-intake:{intake_id}"
        if item.plan:
            item.plan.status = recalculate_plan_status(item.plan)

    record_audit(
        db,
        entity_type="worker_execution",
        entity_id=execution.id,
        event_type="worker.master_worker_synced",
        actor="worker-sync-cli",
        payload={"intakeId": intake_id, "mwStatus": mw_status_label, "state": new_state},
    )
    return SyncOutcome(execution.id, intake_id, previous_state, new_state, "updated", outcome_reason)


def _outcome_from_audit_action(
    db: Session, execution: WorkerExecution, intake_id: str, status_action: str | None
) -> SyncOutcome:
    """Legacy fallback: derive an outcome from the most recent status-relevant audit action."""
    if status_action is None:
        return SyncOutcome(
            execution.id, intake_id, execution.state, None, "unchanged",
            "no MW audit history found for intake yet",
        )
    if status_action == "discard":
        return _apply_state_transition(
            db, execution, intake_id, "failed", f"MW intake status '{status_action}' applied",
            mw_status_label=status_action, error_message="MW intake was discarded",
        )
    if status_action == "bind":
        return _apply_state_transition(
            db, execution, intake_id, "running", f"MW intake status '{status_action}' applied",
            mw_status_label=status_action,
        )
    # create/analyze: intake is still awaiting Owner action in MW; nothing to apply.
    return SyncOutcome(
        execution.id, intake_id, execution.state, None, "unchanged",
        f"MW intake status is still '{status_action}'; no change",
    )


def _outcome_from_intake_state(
    db: Session, execution: WorkerExecution, intake_id: str, intake_state: Any
) -> SyncOutcome:
    """New route, no Objective promoted yet: derive an outcome from the raw intake state."""
    if not isinstance(intake_state, str) or intake_state not in INTAKE_STATE_TO_EXECUTION_STATE:
        return SyncOutcome(
            execution.id, intake_id, execution.state, None, "unchanged",
            f"unrecognized MW intake state {intake_state!r}; no mapping, fail-closed",
        )
    mapped = INTAKE_STATE_TO_EXECUTION_STATE[intake_state]
    if mapped is None:
        return SyncOutcome(
            execution.id, intake_id, execution.state, None, "unchanged",
            f"MW intake status is still '{intake_state}'; no change",
        )
    error_message = "MW intake was discarded" if intake_state == "discarded" else None
    return _apply_state_transition(
        db, execution, intake_id, mapped, f"MW intake status '{intake_state}' applied",
        mw_status_label=intake_state, error_message=error_message,
    )


def _outcome_from_objective_state(
    db: Session, execution: WorkerExecution, intake_id: str, objective_state: Any
) -> SyncOutcome:
    """New route, Objective promoted: derive an outcome from the Objective's lifecycle state."""
    if not isinstance(objective_state, str) or objective_state not in OBJECTIVE_STATE_TO_EXECUTION_STATE:
        return SyncOutcome(
            execution.id, intake_id, execution.state, None, "unchanged",
            f"unrecognized MW objective state {objective_state!r}; no mapping, fail-closed",
        )
    mapped = OBJECTIVE_STATE_TO_EXECUTION_STATE[objective_state]
    if mapped is None:
        return SyncOutcome(
            execution.id, intake_id, execution.state, None, "unchanged",
            f"MW objective status is '{objective_state}'; no forward completion signal, left unchanged",
        )
    error_message = "MW objective was cancelled" if objective_state == "cancelled" else None
    return _apply_state_transition(
        db, execution, intake_id, mapped, f"MW objective status '{objective_state}' applied",
        mw_status_label=objective_state, error_message=error_message,
    )


def _outcome_from_intake_status_data(
    db: Session, execution: WorkerExecution, intake_id: str, data: dict[str, Any]
) -> SyncOutcome:
    """Route the new endpoint's response body to the intake- or Objective-state mapping.

    ``"objectiveId" in data`` is the presence check, not a null/None check:
    MW's getIntakeStatus spreads ``objective?.id``/``objective?.state`` and
    JSON.stringify drops undefined-valued keys entirely when no Objective has
    been created from this intake yet.
    """
    if "objectiveId" in data:
        return _outcome_from_objective_state(db, execution, intake_id, data.get("objectiveState"))
    return _outcome_from_intake_state(db, execution, intake_id, data.get("state"))


def sync_execution(db: Session, execution: WorkerExecution, settings: Settings) -> SyncOutcome:
    """Pull MW's intake progress for one dispatched master-worker execution and apply it.

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

    data, not_found, error = _fetch_intake_status(base_url, token, intake_id, timeout)
    if not_found:
        # Older MW without GET /intakes/{id} (or, less likely, an id it genuinely
        # doesn't know) — fall back to the audit trail this module used exclusively
        # before the dedicated route existed. The fallback is always noted in the
        # returned reason so an Owner-facing summary surfaces a pending MW upgrade.
        events, audit_error = _fetch_intake_audit_trail(base_url, token, intake_id, timeout)
        if audit_error:
            return SyncOutcome(
                execution.id, intake_id, execution.state, None, "failed",
                f"fell back to legacy audit route (MW intake status route returned 404): {audit_error}",
            )
        status_action = _current_intake_status(events or [])
        outcome = _outcome_from_audit_action(db, execution, intake_id, status_action)
        outcome.reason = f"fell back to legacy audit route (MW intake status route returned 404): {outcome.reason}"
        return outcome
    if error:
        return SyncOutcome(execution.id, intake_id, execution.state, None, "failed", error)

    return _outcome_from_intake_status_data(db, execution, intake_id, data or {})


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
