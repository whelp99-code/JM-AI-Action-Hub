from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..models import (
    ActionItem,
    ItemState,
    WebhookDelivery,
    WorkerExecution,
    utcnow,
)
from .audit import record_audit
from .push import queue_push_for_active_devices
from .state_sync import apply_external_state, find_external_state, recalculate_plan_status, upsert_external_state

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}")
_SHORT_ACTION_RE = re.compile(r"action[-_/ ]hub[-_/ ]([0-9a-fA-F-]{8,36})", re.IGNORECASE)


class WebhookSecurityError(ValueError):
    pass


class WebhookConfigurationError(RuntimeError):
    pass


def _headers_lower(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _provider_secret(settings: Settings, provider: str) -> str | None:
    return {
        "todoist": settings.todoist_client_secret,
        "github": settings.github_webhook_secret,
        "fireflies": settings.fireflies_webhook_secret,
    }.get(provider)


def _signature_header(provider: str, headers: dict[str, str]) -> str | None:
    if provider == "todoist":
        return headers.get("x-todoist-hmac-sha256")
    if provider == "github":
        return headers.get("x-hub-signature-256")
    if provider == "fireflies":
        return headers.get("x-hub-signature") or headers.get("x-hub-signature-256")
    return None


def verify_signature(provider: str, raw_body: bytes, headers: Mapping[str, str], secret: str) -> bool:
    lowered = _headers_lower(headers)
    supplied = (_signature_header(provider, lowered) or "").strip()
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    if provider == "todoist":
        expected = base64.b64encode(digest).decode("ascii")
        return hmac.compare_digest(supplied, expected)
    expected_hex = f"sha256={digest.hex()}"
    return hmac.compare_digest(supplied, expected_hex)


def _event_type(provider: str, payload: dict[str, Any], headers: dict[str, str]) -> str:
    if provider == "todoist":
        return str(payload.get("event_name") or payload.get("eventName") or "unknown")
    if provider == "github":
        base = headers.get("x-github-event", "unknown")
        action = payload.get("action")
        return f"{base}.{action}" if action else base
    if provider == "fireflies":
        return str(payload.get("event") or payload.get("eventType") or payload.get("event_type") or "unknown")
    return "unknown"


def _delivery_id(provider: str, payload: dict[str, Any], headers: dict[str, str], payload_hash: str) -> str:
    candidates = {
        "todoist": ["x-todoist-delivery-id"],
        "github": ["x-github-delivery"],
        "fireflies": ["x-fireflies-delivery-id", "x-webhook-id"],
    }.get(provider, [])
    for name in candidates:
        if headers.get(name):
            return headers[name]
    if provider == "fireflies":
        meeting_id = payload.get("meeting_id") or payload.get("meetingId") or payload.get("transcriptId")
        event = payload.get("event") or payload.get("eventType") or payload.get("event_type")
        if meeting_id and event:
            return hashlib.sha256(f"{meeting_id}|{event}|{payload_hash}".encode()).hexdigest()
    return payload_hash


def receive_webhook(
    db: Session,
    *,
    provider: str,
    raw_body: bytes,
    headers: Mapping[str, str],
    settings: Settings,
) -> tuple[WebhookDelivery, bool]:
    provider = provider.lower().strip()
    if provider not in {"todoist", "github", "fireflies"}:
        raise ValueError(f"Unsupported webhook provider: {provider}")
    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Webhook body must be valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Webhook JSON root must be an object")

    lowered = _headers_lower(headers)
    secret = _provider_secret(settings, provider)
    if not secret:
        if settings.app_env == "production":
            raise WebhookConfigurationError(f"{provider} webhook signing secret is not configured")
        signature_valid = False
    else:
        signature_valid = verify_signature(provider, raw_body, lowered, secret)
        if not signature_valid:
            raise WebhookSecurityError("Invalid webhook signature")

    payload_hash = hashlib.sha256(raw_body).hexdigest()
    delivery_id = _delivery_id(provider, payload, lowered, payload_hash)
    existing = db.scalar(
        select(WebhookDelivery).where(
            WebhookDelivery.provider == provider,
            WebhookDelivery.delivery_id == delivery_id,
        )
    )
    if existing:
        return existing, True

    safe_headers = {
        key: value
        for key, value in lowered.items()
        if key in {
            "content-type",
            "user-agent",
            "x-github-event",
            "x-github-delivery",
            "x-todoist-delivery-id",
            "x-fireflies-delivery-id",
        }
    }
    delivery = WebhookDelivery(
        provider=provider,
        delivery_id=delivery_id,
        event_type=_event_type(provider, payload, lowered),
        signature_valid=signature_valid,
        payload_hash=payload_hash,
        payload_json=payload,
        headers_json=safe_headers,
        status="pending",
    )
    db.add(delivery)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(WebhookDelivery).where(
                WebhookDelivery.provider == provider,
                WebhookDelivery.delivery_id == delivery_id,
            )
        )
        if existing is None:
            raise
        return existing, True
    db.refresh(delivery)
    return delivery, False


def _parse_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _todoist_handler(db: Session, delivery: WebhookDelivery, settings: Settings) -> None:
    payload = delivery.payload_json
    data = payload.get("event_data") or payload.get("eventData") or payload.get("data") or {}
    if not isinstance(data, dict):
        data = {}
    native_id = data.get("id") or data.get("item_id") or payload.get("item_id")
    if native_id is None:
        raise ValueError("Todoist webhook does not contain an item id")
    external_id = str(native_id)
    mirror = find_external_state(db, "todoist", external_id)
    if mirror is None:
        delivery.status = "unmatched"
        delivery.error = f"No Todoist mirror for {external_id}"
        return
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == mirror.action_item_id)
        .options(selectinload(ActionItem.plan))
    )
    if item is None:
        raise LookupError("Action item for Todoist mirror not found")

    event = delivery.event_type.lower()
    if "completed" in event and "uncompleted" not in event:
        state = "completed"
    elif "uncompleted" in event:
        state = "open"
    elif "deleted" in event:
        state = "deleted"
    else:
        state = "completed" if data.get("checked") or data.get("completed_at") else "open"
    apply_external_state(
        db,
        item=item,
        provider="todoist",
        external_id=external_id,
        external_url=data.get("url") or mirror.external_url,
        state=state,
        payload=data,
        external_updated_at=_parse_datetime(data.get("updated_at") or data.get("completed_at")),
        source_version=str(payload.get("version") or "webhook"),
        actor="todoist-webhook",
    )


def _github_repository(payload: dict[str, Any]) -> str | None:
    repository = payload.get("repository") or {}
    if isinstance(repository, dict):
        return repository.get("full_name")
    return None


def _extract_action_id(*texts: Any) -> str | None:
    for raw in texts:
        text = str(raw or "")
        marker = re.search(r"Action-Hub-ID:\s*([0-9a-fA-F-]{36})", text, re.IGNORECASE)
        if marker and _UUID_RE.fullmatch(marker.group(1)):
            return marker.group(1)
        uuid_match = _UUID_RE.search(text)
        if uuid_match:
            return uuid_match.group(0)
        short = _SHORT_ACTION_RE.search(text)
        if short:
            return short.group(1)
    return None


def _find_action_for_pr(db: Session, payload: dict[str, Any], repository: str, pr: dict[str, Any]) -> ActionItem | None:
    head = pr.get("head") or {}
    action_id = _extract_action_id(pr.get("body"), pr.get("title"), head.get("ref"))
    if action_id:
        item = db.scalar(
            select(ActionItem)
            .where(ActionItem.id == action_id)
            .options(selectinload(ActionItem.plan))
        )
        if item:
            return item

    # Fall back to linked issue references in the PR body.
    body = str(pr.get("body") or "")
    for number in re.findall(r"#(\d+)", body):
        mirror = find_external_state(db, "github", f"{repository}#{number}")
        if mirror:
            return db.scalar(
                select(ActionItem)
                .where(ActionItem.id == mirror.action_item_id)
                .options(selectinload(ActionItem.plan))
            )
    return None


def _worker_execution_for_item(db: Session, item: ActionItem, repository: str) -> WorkerExecution:
    execution = db.scalar(
        select(WorkerExecution)
        .where(
            WorkerExecution.action_item_id == item.id,
            WorkerExecution.repository == repository,
        )
        .order_by(WorkerExecution.created_at.desc())
    )
    if execution is None:
        execution = WorkerExecution(
            action_item_id=item.id,
            worker=item.preferred_worker or "github-agent",
            state="running",
            repository=repository,
            started_at=utcnow(),
        )
        db.add(execution)
    return execution


def _github_issue_handler(db: Session, delivery: WebhookDelivery, payload: dict[str, Any], repository: str) -> None:
    issue = payload.get("issue") or {}
    number = issue.get("number")
    if number is None:
        raise ValueError("GitHub issue webhook does not contain issue.number")
    key = f"{repository}#{number}"
    mirror = find_external_state(db, "github", key)
    if mirror is None:
        delivery.status = "unmatched"
        delivery.error = f"No GitHub issue mirror for {key}"
        return
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == mirror.action_item_id)
        .options(selectinload(ActionItem.plan))
    )
    if item is None:
        raise LookupError("Action item for GitHub mirror not found")
    action = str(payload.get("action") or "")
    state = "deleted" if action == "deleted" else ("completed" if issue.get("state") == "closed" else "open")
    apply_external_state(
        db,
        item=item,
        provider="github",
        external_id=key,
        external_url=issue.get("html_url") or mirror.external_url,
        state=state,
        payload=issue,
        external_updated_at=_parse_datetime(issue.get("updated_at") or issue.get("closed_at")),
        source_version="github-webhook",
        actor="github-webhook",
    )


def _github_pr_handler(db: Session, delivery: WebhookDelivery, payload: dict[str, Any], repository: str) -> None:
    pr = payload.get("pull_request") or {}
    number = pr.get("number") or payload.get("number")
    if number is None:
        raise ValueError("GitHub pull_request webhook does not contain a number")
    item = _find_action_for_pr(db, payload, repository, pr)
    if item is None:
        delivery.status = "unmatched"
        delivery.error = f"No Action Hub item found for {repository} PR #{number}"
        return
    execution = _worker_execution_for_item(db, item, repository)
    execution.pull_request_number = int(number)
    execution.artifacts_json = {
        **(execution.artifacts_json or {}),
        "pull_request_url": pr.get("html_url"),
        "head_branch": (pr.get("head") or {}).get("ref"),
    }
    action = str(payload.get("action") or "")
    merged = bool(pr.get("merged"))
    action_is_final = item.state == ItemState.COMPLETED.value and bool(item.completion_evidence)
    if action_is_final and not merged:
        worker_state = execution.state
        item_state = item.state
        external_state = "observed_after_merge"
    elif action == "closed" and merged:
        worker_state = "completed"
        item_state = ItemState.COMPLETED.value
        external_state = "merged"
        execution.completed_at = _parse_datetime(pr.get("merged_at")) or utcnow()
        item.completed_at = execution.completed_at
        item.completion_evidence = pr.get("html_url")
    elif action == "closed":
        worker_state = "failed"
        item_state = ItemState.FAILED.value
        external_state = "closed"
        execution.completed_at = _parse_datetime(pr.get("closed_at")) or utcnow()
        execution.error = "Pull request closed without merge"
    elif action in {"ready_for_review", "review_requested"} or not pr.get("draft", False):
        worker_state = "human_review"
        item_state = ItemState.HUMAN_REVIEW.value
        external_state = "open"
    else:
        worker_state = "running"
        item_state = ItemState.RUNNING.value
        external_state = "open"
    execution.state = worker_state
    item.state = item_state
    if item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    upsert_external_state(
        db,
        item=item,
        provider="github_pr",
        external_id=f"{repository}#{number}",
        external_url=pr.get("html_url"),
        state=external_state,
        payload=pr,
        external_updated_at=_parse_datetime(pr.get("updated_at") or pr.get("merged_at")),
        source_version="github-webhook",
    )
    record_audit(
        db,
        entity_type="worker_execution",
        entity_id=execution.id,
        event_type="worker.pull_request_updated",
        actor="github-webhook",
        payload={"repository": repository, "number": number, "action": action, "state": worker_state},
    )


def _find_worker_for_workflow(db: Session, payload: dict[str, Any], repository: str) -> WorkerExecution | None:
    run = payload.get("workflow_run") or {}
    run_id = run.get("id")
    if run_id:
        existing = db.scalar(select(WorkerExecution).where(WorkerExecution.workflow_run_id == str(run_id)))
        if existing:
            return existing
    action_id = _extract_action_id(run.get("name"), run.get("display_title"), run.get("head_branch"))
    if action_id:
        return db.scalar(
            select(WorkerExecution)
            .where(WorkerExecution.action_item_id == action_id)
            .order_by(WorkerExecution.created_at.desc())
        )
    # workflow_dispatch returns no run id. A repository-only fallback is safe
    # only when exactly one execution is active; otherwise leave the delivery
    # unmatched rather than attaching a run to the wrong action.
    candidates = list(
        db.scalars(
            select(WorkerExecution)
            .where(
                WorkerExecution.repository == repository,
                WorkerExecution.state.in_(["queued", "dispatched", "running"]),
            )
            .order_by(WorkerExecution.created_at.desc())
            .limit(2)
        )
    )
    return candidates[0] if len(candidates) == 1 else None


def _github_workflow_handler(db: Session, delivery: WebhookDelivery, payload: dict[str, Any], repository: str) -> None:
    run = payload.get("workflow_run") or {}
    execution = _find_worker_for_workflow(db, payload, repository)
    if execution is None:
        delivery.status = "unmatched"
        delivery.error = f"No worker execution found for {repository} workflow run"
        return
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == execution.action_item_id)
        .options(selectinload(ActionItem.plan))
    )
    if item is None:
        raise LookupError("Worker action item not found")
    execution.workflow_run_id = str(run.get("id")) if run.get("id") is not None else execution.workflow_run_id
    status = str(run.get("status") or "")
    conclusion = str(run.get("conclusion") or "")
    action_is_final = item.state == ItemState.COMPLETED.value and bool(item.completion_evidence)
    if action_is_final:
        external_state = conclusion or status or "observed_after_completion"
    elif status == "completed" and conclusion == "success":
        execution.state = "human_review"
        item.state = ItemState.HUMAN_REVIEW.value
        external_state = "success"
        execution.output_summary = "Workflow completed successfully; human review required."
    elif status == "completed":
        execution.state = "failed"
        item.state = ItemState.FAILED.value
        external_state = conclusion or "failed"
        execution.completed_at = _parse_datetime(run.get("updated_at")) or utcnow()
        execution.error = f"Workflow conclusion: {conclusion or 'unknown'}"
    else:
        execution.state = "running"
        item.state = ItemState.RUNNING.value
        external_state = status or "in_progress"
        execution.started_at = execution.started_at or _parse_datetime(run.get("run_started_at")) or utcnow()
    if item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    run_id = str(run.get("id") or execution.id)
    upsert_external_state(
        db,
        item=item,
        provider="github_workflow",
        external_id=f"{repository}#{run_id}",
        external_url=run.get("html_url"),
        state=external_state,
        payload=run,
        external_updated_at=_parse_datetime(run.get("updated_at")),
        source_version="github-webhook",
    )


def _find_worker_for_check_suite(
    db: Session,
    payload: dict[str, Any],
    repository: str,
) -> WorkerExecution | None:
    suite = payload.get("check_suite") or {}
    action_id = _extract_action_id(suite.get("head_branch"), suite.get("head_sha"))
    if action_id:
        return db.scalar(
            select(WorkerExecution)
            .where(WorkerExecution.action_item_id == action_id)
            .order_by(WorkerExecution.created_at.desc())
        )
    pull_requests = suite.get("pull_requests") or []
    for pull_request in pull_requests:
        number = pull_request.get("number") if isinstance(pull_request, dict) else None
        if number is not None:
            execution = db.scalar(
                select(WorkerExecution)
                .where(
                    WorkerExecution.repository == repository,
                    WorkerExecution.pull_request_number == int(number),
                )
                .order_by(WorkerExecution.created_at.desc())
            )
            if execution:
                return execution
    candidates = list(
        db.scalars(
            select(WorkerExecution)
            .where(
                WorkerExecution.repository == repository,
                WorkerExecution.state.in_(["queued", "dispatched", "running", "human_review"]),
            )
            .order_by(WorkerExecution.created_at.desc())
            .limit(2)
        )
    )
    return candidates[0] if len(candidates) == 1 else None


def _github_check_suite_handler(
    db: Session,
    delivery: WebhookDelivery,
    payload: dict[str, Any],
    repository: str,
) -> None:
    suite = payload.get("check_suite") or {}
    suite_id = suite.get("id")
    if suite_id is None:
        raise ValueError("GitHub check_suite webhook does not contain check_suite.id")
    execution = _find_worker_for_check_suite(db, payload, repository)
    if execution is None:
        delivery.status = "unmatched"
        delivery.error = f"No worker execution found for {repository} check suite #{suite_id}"
        return
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == execution.action_item_id)
        .options(selectinload(ActionItem.plan))
    )
    if item is None:
        raise LookupError("Worker action item not found")

    status = str(suite.get("status") or "")
    conclusion = str(suite.get("conclusion") or "")
    action_is_final = item.state == ItemState.COMPLETED.value and bool(item.completion_evidence)
    if action_is_final:
        external_state = conclusion or status or "observed_after_completion"
    elif status == "completed" and conclusion in {"success", "neutral", "skipped"}:
        execution.state = "human_review"
        item.state = ItemState.HUMAN_REVIEW.value
        execution.output_summary = f"Check suite completed: {conclusion}; human review required."
        external_state = conclusion
    elif status == "completed":
        execution.state = "failed"
        item.state = ItemState.FAILED.value
        execution.completed_at = _parse_datetime(suite.get("updated_at")) or utcnow()
        execution.error = f"Check suite conclusion: {conclusion or 'unknown'}"
        external_state = conclusion or "failed"
    else:
        execution.state = "running"
        item.state = ItemState.RUNNING.value
        execution.started_at = execution.started_at or utcnow()
        external_state = status or "in_progress"

    execution.artifacts_json = {
        **(execution.artifacts_json or {}),
        "check_suite_id": str(suite_id),
        "check_runs_url": suite.get("check_runs_url"),
    }
    if item.plan:
        item.plan.status = recalculate_plan_status(item.plan)
    upsert_external_state(
        db,
        item=item,
        provider="github_check_suite",
        external_id=f"{repository}#{suite_id}",
        external_url=suite.get("check_runs_url") or suite.get("url"),
        state=external_state,
        payload=suite,
        external_updated_at=_parse_datetime(suite.get("updated_at")),
        source_version="github-webhook",
    )
    record_audit(
        db,
        entity_type="worker_execution",
        entity_id=execution.id,
        event_type="worker.check_suite_updated",
        actor="github-webhook",
        payload={"repository": repository, "suite_id": suite_id, "state": external_state},
    )


def _github_handler(db: Session, delivery: WebhookDelivery, settings: Settings) -> None:
    payload = delivery.payload_json
    repository = _github_repository(payload)
    if not repository:
        raise ValueError("GitHub webhook does not contain repository.full_name")
    base_event = delivery.event_type.split(".", 1)[0]
    if base_event == "issues":
        _github_issue_handler(db, delivery, payload, repository)
    elif base_event == "pull_request":
        _github_pr_handler(db, delivery, payload, repository)
    elif base_event == "workflow_run":
        _github_workflow_handler(db, delivery, payload, repository)
    elif base_event == "check_suite":
        _github_check_suite_handler(db, delivery, payload, repository)
    elif base_event == "ping":
        delivery.status = "processed"
    else:
        delivery.status = "ignored"
        delivery.error = f"Unsupported GitHub event: {base_event}"
    if base_event in {"pull_request", "workflow_run", "check_suite"} and delivery.status != "unmatched":
        queue_push_for_active_devices(
            db,
            settings,
            event_type="ai_status",
            entity_type="webhook_delivery",
            entity_id=delivery.id,
            idempotency_suffix=delivery.id,
        )


def _fireflies_handler(db: Session, delivery: WebhookDelivery, settings: Settings) -> None:
    from .meetings import ingest_fireflies_event

    ingest_fireflies_event(db, delivery.payload_json, delivery.event_type, settings)


def process_webhook_delivery(db: Session, delivery: WebhookDelivery, settings: Settings) -> None:
    if delivery.provider == "todoist":
        _todoist_handler(db, delivery, settings)
    elif delivery.provider == "github":
        _github_handler(db, delivery, settings)
    elif delivery.provider == "fireflies":
        _fireflies_handler(db, delivery, settings)
    else:
        raise ValueError(f"Unsupported webhook provider: {delivery.provider}")


def recover_stale_webhook_deliveries(db: Session, settings: Settings) -> int:
    from datetime import timedelta

    cutoff = utcnow() - timedelta(seconds=settings.processing_lock_timeout_seconds)
    rows = list(
        db.scalars(
            select(WebhookDelivery).where(
                WebhookDelivery.status == "processing",
                WebhookDelivery.locked_at.is_not(None),
                WebhookDelivery.locked_at < cutoff,
            )
        )
    )
    for delivery in rows:
        delivery.status = "retry"
        delivery.locked_at = None
        delivery.error = "Recovered stale processing lock"
    if rows:
        db.commit()
    return len(rows)


def _claim_webhook_deliveries(
    db: Session,
    settings: Settings,
    limit: int,
    delivery_ids: list[str] | None,
) -> list[str]:
    recover_stale_webhook_deliveries(db, settings)
    statement = select(WebhookDelivery).where(WebhookDelivery.status.in_(["pending", "retry"]))
    if delivery_ids:
        statement = statement.where(WebhookDelivery.id.in_(delivery_ids))
    statement = (
        statement.order_by(WebhookDelivery.received_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    deliveries = list(db.scalars(statement))
    claimed_at = utcnow()
    for delivery in deliveries:
        delivery.status = "processing"
        delivery.attempts += 1
        delivery.locked_at = claimed_at
    db.commit()
    return [delivery.id for delivery in deliveries]


def process_webhook_batch(
    db: Session,
    settings: Settings,
    limit: int | None = None,
    delivery_ids: list[str] | None = None,
) -> dict[str, int]:
    claimed_ids = _claim_webhook_deliveries(
        db,
        settings,
        limit or settings.webhook_batch_size,
        delivery_ids,
    )
    summary = {"processed": 0, "completed": 0, "failed": 0, "unmatched": 0, "ignored": 0}
    for delivery_id in claimed_ids:
        delivery = db.get(WebhookDelivery, delivery_id)
        if delivery is None or delivery.status != "processing":
            continue
        try:
            process_webhook_delivery(db, delivery, settings)
            if delivery.status == "processing":
                delivery.status = "processed"
            delivery.processed_at = utcnow()
            delivery.locked_at = None
            delivery.error = delivery.error if delivery.status in {"unmatched", "ignored"} else None
            if delivery.status in {"processed", "unmatched", "ignored"}:
                summary[delivery.status if delivery.status != "processed" else "completed"] += 1
        except Exception as exc:
            logger.warning("Webhook delivery %s failed: %s", delivery.id, exc)
            delivery.error = str(exc)
            delivery.locked_at = None
            delivery.status = "failed" if delivery.attempts >= settings.outbox_max_attempts else "retry"
            summary["failed"] += 1
        db.commit()
        summary["processed"] += 1
    return summary

