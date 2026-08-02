from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..models import ActionItem, ActionPlan, InboxEntry
from ..schemas import InboxParseRequest
from .audit import record_audit
from .parser import action_fingerprint, build_parser, normalize_text


def inbox_fingerprint(text: str, timezone_name: str) -> str:
    canonical = f"{timezone_name}|{normalize_text(text)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_plan(db: Session, plan_id: str) -> ActionPlan | None:
    statement = (
        select(ActionPlan)
        .where(ActionPlan.id == plan_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(ActionPlan.items).selectinload(ActionItem.external_states),
            selectinload(ActionPlan.items).selectinload(ActionItem.worker_executions),
            selectinload(ActionPlan.items).selectinload(ActionItem.followups),
            selectinload(ActionPlan.inbox),
        )
    )
    return db.scalar(statement)


def create_plan(db: Session, request: InboxParseRequest, settings: Settings) -> tuple[ActionPlan, bool]:
    if len(request.text) > settings.max_input_chars:
        raise ValueError(f"Input exceeds {settings.max_input_chars} characters")

    timezone_name = request.timezone or settings.timezone
    tz = ZoneInfo(timezone_name)
    reference = request.reference_time or datetime.now(tz)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=tz)
    else:
        reference = reference.astimezone(tz)

    fingerprint = inbox_fingerprint(request.text, timezone_name)
    if not request.force_new:
        existing = db.scalar(
            select(InboxEntry)
            .where(InboxEntry.fingerprint == fingerprint)
            .options(selectinload(InboxEntry.plans).selectinload(ActionPlan.items))
        )
        if existing and existing.plans:
            return existing.plans[-1], True

    inbox = InboxEntry(
        source=request.source,
        raw_text=normalize_text(request.text),
        timezone=timezone_name,
        fingerprint=fingerprint if not request.force_new else hashlib.sha256(f"{fingerprint}|{reference.isoformat()}|{uuid.uuid4()}".encode()).hexdigest(),
        metadata_json=request.metadata,
    )
    db.add(inbox)
    db.flush()

    parser = build_parser(settings)
    drafts = parser.parse(inbox.raw_text, reference, timezone_name)
    from .rules import apply_active_rules
    applied_rule_count = apply_active_rules(db, drafts)
    actionable = sum(1 for x in drafts if x.destination.value != "none")
    review_count = sum(1 for x in drafts if x.needs_review)
    plan = ActionPlan(
        inbox_id=inbox.id,
        parser_name=parser.name,
        summary=f"{len(drafts)}개 항목 · 실행 가능 {actionable}개 · 검토 필요 {review_count}개",
        reference_time=reference,
    )
    db.add(plan)
    db.flush()

    for draft in drafts:
        item = ActionItem(
            plan_id=plan.id,
            item_type=draft.item_type.value,
            destination=draft.destination.value,
            title=draft.title,
            description=draft.description,
            source_fragment=draft.source_fragment,
            project=draft.project,
            repository=draft.repository,
            assignee=draft.assignee,
            start_at=draft.start_at,
            end_at=draft.end_at,
            due_at=draft.due_at,
            deadline_at=draft.deadline_at,
            earliest_start_at=draft.earliest_start_at,
            latest_finish_at=draft.latest_finish_at,
            is_all_day=draft.is_all_day,
            priority=draft.priority,
            labels=draft.labels,
            confidence=draft.confidence,
            needs_review=draft.needs_review,
            review_reason=draft.review_reason,
            estimated_minutes=draft.estimated_minutes,
            actual_minutes=draft.actual_minutes,
            work_mode=draft.work_mode,
            executor=draft.executor.value,
            preferred_worker=draft.preferred_worker,
            energy_level=draft.energy_level,
            waiting_for=draft.waiting_for,
            follow_up_at=draft.follow_up_at,
            depends_on=draft.depends_on,
            completion_evidence=draft.completion_evidence,
            fingerprint=action_fingerprint(draft),
        )
        db.add(item)

    record_audit(
        db,
        entity_type="plan",
        entity_id=plan.id,
        event_type="plan.created",
        payload={"source": request.source, "items": len(drafts), "deduplicated": False, "rule_matches": applied_rule_count},
    )
    from .metrics import record_metric
    record_metric(db, "actions_parsed", len(drafts), action_item_id=None, payload={"plan_id": plan.id})
    record_metric(db, "estimated_minutes_saved", len(drafts), unit="minutes", payload={"reason": "structured_capture", "plan_id": plan.id})
    db.commit()
    refreshed = get_plan(db, plan.id)
    if refreshed is None:
        raise RuntimeError("Plan disappeared after commit")
    return refreshed, False
