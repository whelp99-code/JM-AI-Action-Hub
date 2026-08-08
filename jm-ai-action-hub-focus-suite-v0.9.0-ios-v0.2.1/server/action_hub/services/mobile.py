from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..models import (
    ActionItem,
    ActionPlan,
    AuditEvent,
    FollowUp,
    ItemState,
    MobileCapture,
    MobileDevice,
    WorkerExecution,
    utcnow,
)
from ..schemas import (
    InboxParseRequest,
    MobileActivityItem,
    MobileCapabilities,
    MobileCaptureBatchRequest,
    MobileCaptureBatchResponse,
    MobileCaptureReceiptRead,
    MobileChangeItem,
    MobileChangesResponse,
    MobileDashboard,
    MobileDeviceRead,
    MobileNotificationPreferencesRequest,
    MobilePushTokenRequest,
)
from .brief import build_daily_brief
from .decision import build_decision_plan
from .executor import TERMINAL_ITEM_STATES
from .focus import dashboard_focus_summary
from .mobile_auth import mobile_signing_secret
from .planner import create_plan
from .push import queue_push


def capabilities(settings: Settings) -> MobileCapabilities:
    return MobileCapabilities(
        service=settings.app_name,
        server_version=settings.version,
        mobile_enabled=settings.mobile_enabled,
        minimum_ios_app_version=settings.mobile_min_ios_app_version,
        recommended_ios_app_version=settings.mobile_recommended_ios_app_version,
        pairing_supported=settings.mobile_enabled and settings.mobile_auth_configured,
        push_supported=settings.apns_configured or settings.execution_mode == "dry_run",
        features=[
            "secure-pairing",
            "rotating-refresh-token",
            "offline-capture-batch",
            "optimistic-revision",
            "delta-audit-sync",
            "dashboard",
            "review-approval-execution",
            "apns",
            "swipe-triage",
            "eisenhower-matrix",
            "dual-big3",
            "micro-steps",
            "focus-session",
            "day-close",
            "focus-analytics",
        ],
    )


def _needs_review_item_filter():
    # Shared between list_review_plans() and the dashboard review_count so the
    # two can never drift on what counts as "still needs review". A terminal
    # item (completed/rejected/skipped_duplicate/cancelled) is excluded even if
    # some caller forgot to clear needs_review on the way there -- see
    # state_sync.clear_needs_review for the call sites that do clear it, and
    # treat this filter as the backstop for the ones that don't (yet).
    return and_(
        or_(
            ActionItem.needs_review.is_(True),
            ActionItem.state == ItemState.DRAFT.value,
        ),
        ActionItem.state.notin_(TERMINAL_ITEM_STATES),
    )


def list_review_plans(db: Session, limit: int = 50) -> list[ActionPlan]:
    # LIMIT must apply to distinct plans, not joined item rows: a single plan
    # with many needs_review items could otherwise exhaust the limit on its own
    # and silently drop every other plan from the response. Select the plan ids
    # first (DISTINCT + ORDER BY on a selected column, portable to Postgres),
    # then fetch the full plans with eager loading in a second query.
    plan_ids = list(
        db.scalars(
            select(ActionPlan.id, ActionPlan.updated_at)
            .join(ActionItem)
            .where(_needs_review_item_filter())
            .distinct()
            .order_by(desc(ActionPlan.updated_at))
            .limit(limit)
        )
    )
    if not plan_ids:
        return []
    statement = (
        select(ActionPlan)
        .where(ActionPlan.id.in_(plan_ids))
        .options(
            selectinload(ActionPlan.items).selectinload(ActionItem.external_states),
            selectinload(ActionPlan.items).selectinload(ActionItem.worker_executions),
            selectinload(ActionPlan.items).selectinload(ActionItem.followups),
            selectinload(ActionPlan.inbox),
        )
    )
    plans_by_id = {plan.id: plan for plan in db.scalars(statement).unique()}
    return [plans_by_id[plan_id] for plan_id in plan_ids if plan_id in plans_by_id]


def _activity_category(event_type: str) -> str:
    if "worker" in event_type or event_type.startswith("github.workflow"):
        return "worker"
    if "followup" in event_type:
        return "followup"
    if "failed" in event_type or "error" in event_type:
        return "failure"
    return "audit"


def _activity_title(event: AuditEvent, item_titles: dict[str, str]) -> str:
    if event.entity_type in {"item", "action_item"} and event.entity_id in item_titles:
        return item_titles[event.entity_id]
    if event.entity_type == "plan":
        return "Action Plan"
    if event.entity_type == "followup":
        return "응답 대기 후속 확인"
    if event.entity_type == "worker_execution":
        return "AI Worker 실행"
    return event.entity_type.replace("_", " ").title()


def recent_activity(db: Session, limit: int = 20) -> list[MobileActivityItem]:
    rows = list(db.scalars(select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(limit)))
    item_ids = [row.entity_id for row in rows if row.entity_type in {"item", "action_item"}]
    titles = {
        row.id: row.title
        for row in db.scalars(select(ActionItem).where(ActionItem.id.in_(item_ids)))
    } if item_ids else {}
    activities: list[MobileActivityItem] = []
    for row in rows:
        payload = dict(row.payload or {})
        subtitle = payload.get("error") or payload.get("reason") or payload.get("destination")
        activities.append(
            MobileActivityItem(
                id=row.id,
                category=_activity_category(row.event_type),
                title=_activity_title(row, titles),
                subtitle=str(subtitle) if subtitle else row.event_type,
                state=row.event_type,
                entity_type=row.entity_type,
                entity_id=row.entity_id,
                external_url=str(payload.get("external_url")) if payload.get("external_url") else None,
                occurred_at=row.created_at,
            )
        )
    return activities


def build_mobile_dashboard(
    db: Session,
    settings: Settings,
    *,
    include_activity: bool = True,
) -> MobileDashboard:
    brief = build_daily_brief(db, settings.timezone, None)
    decision = build_decision_plan(
        db,
        settings,
        target_date=None,
        available_minutes=None,
        max_items=12,
        include_ai=True,
    )
    # Counted in plans, matching list_review_plans() -- the review tab renders
    # one row per plan, so a badge counted in items (S7) could show a number
    # larger than the list the user taps into, which reads as a bug even though
    # each number was individually correct for its own unit.
    review_count = int(
        db.scalar(
            select(func.count(func.distinct(ActionPlan.id)))
            .select_from(ActionPlan)
            .join(ActionItem)
            .where(_needs_review_item_filter())
        )
        or 0
    )
    waiting_count = int(
        db.scalar(
            select(func.count(FollowUp.id)).where(
                FollowUp.state.in_(["waiting", "follow_up_due", "followed_up"])
            )
        )
        or 0
    )
    ai_running_count = int(
        db.scalar(
            select(func.count(WorkerExecution.id)).where(
                WorkerExecution.state.in_(["queued", "running", "needs_input", "human_review"])
            )
        )
        or 0
    )
    failed_count = int(
        db.scalar(select(func.count(ActionItem.id)).where(ActionItem.state == ItemState.FAILED.value)) or 0
    )
    return MobileDashboard(
        generated_at=utcnow(),
        server_version=settings.version,
        minimum_ios_app_version=settings.mobile_min_ios_app_version,
        review_count=review_count,
        waiting_count=waiting_count,
        ai_running_count=ai_running_count,
        failed_count=failed_count,
        brief=brief,
        decision=decision,
        recent_activity=recent_activity(db, 20) if include_activity else [],
        focus_summary=dashboard_focus_summary(db, settings).model_dump(mode="json"),
    )


def _encode_cursor(timestamp: datetime, audit_id: str, settings: Settings) -> str:
    payload = json.dumps(
        {"ts": timestamp.astimezone(UTC).isoformat(), "id": audit_id},
        separators=(",", ":"),
    ).encode("utf-8")
    segment = base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature = base64.urlsafe_b64encode(
        hmac.new(
            mobile_signing_secret(settings),
            f"mobile-changes-v1:{segment}".encode("ascii"),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode("ascii")
    return f"{segment}.{signature}"


def _decode_cursor(cursor: str, settings: Settings) -> tuple[datetime, str]:
    try:
        segment, signature = cursor.split(".", 1)
        if not segment or not signature:
            raise ValueError("missing cursor segment")
        expected = base64.urlsafe_b64encode(
            hmac.new(
                mobile_signing_secret(settings),
                f"mobile-changes-v1:{segment}".encode("ascii"),
                hashlib.sha256,
            ).digest()
        ).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(expected, signature):
            raise ValueError("cursor signature mismatch")
        padding = "=" * ((4 - len(segment) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment + padding))
        timestamp = datetime.fromisoformat(str(payload["ts"]))
        audit_id = str(payload["id"])
        if not audit_id or len(audit_id) > 128:
            raise ValueError("invalid cursor audit id")
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC), audit_id
    except Exception as exc:
        raise ValueError("Invalid mobile changes cursor") from exc


def mobile_changes(
    db: Session,
    settings: Settings,
    *,
    cursor: str | None,
    limit: int | None = None,
) -> MobileChangesResponse:
    batch_size = max(1, min(limit or settings.mobile_change_batch_size, 500))
    statement = select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id).limit(batch_size + 1)
    if cursor:
        timestamp, audit_id = _decode_cursor(cursor, settings)
        statement = statement.where(
            or_(
                AuditEvent.created_at > timestamp,
                and_(AuditEvent.created_at == timestamp, AuditEvent.id > audit_id),
            )
        )
    rows = list(db.scalars(statement))
    has_more = len(rows) > batch_size
    rows = rows[:batch_size]
    next_cursor = _encode_cursor(rows[-1].created_at, rows[-1].id, settings) if rows else cursor
    changes = [
        MobileChangeItem(
            audit_id=row.id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            event_type=row.event_type,
            actor=row.actor,
            occurred_at=row.created_at,
            payload=dict(row.payload or {}),
        )
        for row in rows
    ]
    deleted = [
        {"entity_type": row.entity_type, "entity_id": row.entity_id}
        for row in rows
        if row.event_type.endswith(".deleted")
    ]
    return MobileChangesResponse(
        next_cursor=next_cursor,
        has_more=has_more,
        changes=changes,
        deleted=deleted,
    )


def process_capture_batch(
    db: Session,
    settings: Settings,
    device: MobileDevice,
    request: MobileCaptureBatchRequest,
) -> MobileCaptureBatchResponse:
    if len(request.captures) > settings.mobile_capture_batch_size:
        raise ValueError(f"A batch may contain at most {settings.mobile_capture_batch_size} captures")
    receipts: list[MobileCaptureReceiptRead] = []
    for capture in request.captures:
        content_hash = hashlib.sha256(capture.text.strip().encode("utf-8")).hexdigest()
        existing = db.scalar(
            select(MobileCapture).where(
                MobileCapture.device_id == device.id,
                MobileCapture.client_capture_id == capture.client_capture_id,
            )
        )
        if existing is None:
            candidate = MobileCapture(
                device_id=device.id,
                client_capture_id=capture.client_capture_id,
                content_hash=content_hash,
                status="received",
            )
            try:
                # SAVEPOINT handles app/extension retries arriving at the same
                # time without turning a uniqueness race into an HTTP 500.
                with db.begin_nested():
                    db.add(candidate)
                    db.flush()
                existing = candidate
            except IntegrityError:
                existing = db.scalar(
                    select(MobileCapture).where(
                        MobileCapture.device_id == device.id,
                        MobileCapture.client_capture_id == capture.client_capture_id,
                    )
                )
                if existing is None:  # pragma: no cover - defensive race boundary
                    raise

        if not hmac_compare(existing.content_hash, content_hash):
            receipts.append(
                MobileCaptureReceiptRead(
                    client_capture_id=capture.client_capture_id,
                    status="failed",
                    plan_id=existing.plan_id,
                    error="client_capture_id was already used with different content",
                )
            )
            continue
        if existing.status == "processed":
            receipts.append(
                MobileCaptureReceiptRead(
                    client_capture_id=capture.client_capture_id,
                    status="duplicate",
                    plan_id=existing.plan_id,
                    deduplicated=True,
                )
            )
            continue

        # Atomically claim parsing. The app and Share Extension may upload the
        # same queued file at once; only one request may run create_plan(). A
        # process can die after claiming, so stale processing locks are eligible
        # for recovery instead of leaving an offline capture stuck forever.
        claimed_at = utcnow()
        stale_before = claimed_at - timedelta(seconds=settings.processing_lock_timeout_seconds)
        claimed = db.execute(
            update(MobileCapture)
            .where(
                MobileCapture.id == existing.id,
                or_(
                    MobileCapture.status.in_(["received", "failed"]),
                    and_(
                        MobileCapture.status == "processing",
                        or_(
                            MobileCapture.locked_at.is_(None),
                            MobileCapture.locked_at < stale_before,
                        ),
                    ),
                ),
            )
            .values(status="processing", locked_at=claimed_at, error=None, processed_at=None)
        )
        db.commit()
        if claimed.rowcount != 1:
            current = db.get(MobileCapture, existing.id)
            if current and current.status == "processed":
                receipts.append(
                    MobileCaptureReceiptRead(
                        client_capture_id=capture.client_capture_id,
                        status="duplicate",
                        plan_id=current.plan_id,
                        deduplicated=True,
                    )
                )
            else:
                receipts.append(
                    MobileCaptureReceiptRead(
                        client_capture_id=capture.client_capture_id,
                        status="failed",
                        plan_id=current.plan_id if current else None,
                        error="capture is already being processed; retry",
                    )
                )
            continue
        row = db.get(MobileCapture, existing.id)
        if row is None:  # pragma: no cover - defensive persistence boundary
            raise RuntimeError("Mobile capture receipt disappeared before processing")
        try:
            metadata = dict(capture.metadata)
            metadata.update(
                {
                    "mobile_device_id": device.id,
                    "client_capture_id": capture.client_capture_id,
                }
            )
            plan, deduplicated = create_plan(
                db,
                InboxParseRequest(
                    text=capture.text,
                    source=capture.source,
                    timezone=capture.timezone,
                    reference_time=capture.reference_time,
                    metadata=metadata,
                ),
                settings,
            )
            row = db.get(MobileCapture, row.id)
            if row is None:  # pragma: no cover - defensive persistence boundary
                raise RuntimeError("Mobile capture receipt disappeared")
            row.plan_id = plan.id
            row.status = "processed"
            row.locked_at = None
            row.processed_at = utcnow()
            queue_push(
                db,
                settings,
                device=device,
                event_type="review_required",
                entity_type="plan",
                entity_id=plan.id,
                idempotency_key=f"push:{device.id}:review_required:{plan.id}",
            )
            db.commit()
            receipts.append(
                MobileCaptureReceiptRead(
                    client_capture_id=capture.client_capture_id,
                    status="duplicate" if deduplicated else "processed",
                    plan_id=plan.id,
                    deduplicated=deduplicated,
                )
            )
        except Exception as exc:
            db.rollback()
            persisted = db.scalar(
                select(MobileCapture).where(
                    MobileCapture.device_id == device.id,
                    MobileCapture.client_capture_id == capture.client_capture_id,
                )
            )
            if persisted:
                persisted.status = "failed"
                persisted.locked_at = None
                persisted.error = str(exc)
                persisted.processed_at = utcnow()
                db.commit()
            receipts.append(
                MobileCaptureReceiptRead(
                    client_capture_id=capture.client_capture_id,
                    status="failed",
                    error=str(exc),
                )
            )

    return MobileCaptureBatchResponse(
        accepted=len(request.captures),
        processed=sum(row.status == "processed" for row in receipts),
        duplicate=sum(row.status == "duplicate" for row in receipts),
        failed=sum(row.status == "failed" for row in receipts),
        receipts=receipts,
    )


def hmac_compare(left: str, right: str) -> bool:
    # Kept local to avoid exposing content hashes through timing differences.
    import hmac

    return hmac.compare_digest(left, right)


def register_push_token(
    db: Session,
    device: MobileDevice,
    request: MobilePushTokenRequest,
) -> MobileDeviceRead:
    raw = request.token.strip().lower()
    if not re.fullmatch(r"[0-9a-f]+", raw) or len(raw) < 64 or len(raw) % 2:
        raise ValueError("APNs token must be an even-length hexadecimal string of at least 64 characters")
    normalized = raw
    other = db.scalar(
        select(MobileDevice).where(MobileDevice.push_token == normalized, MobileDevice.id != device.id)
    )
    if other:
        other.push_token = None
    device.push_token = normalized
    device.push_environment = request.environment
    device.last_seen_at = utcnow()
    db.commit()
    db.refresh(device)
    return MobileDeviceRead.from_device(device)


def update_notification_preferences(
    db: Session,
    device: MobileDevice,
    request: MobileNotificationPreferencesRequest,
) -> MobileDeviceRead:
    device.notification_preferences = request.model_dump()
    db.commit()
    db.refresh(device)
    return MobileDeviceRead.from_device(device)
