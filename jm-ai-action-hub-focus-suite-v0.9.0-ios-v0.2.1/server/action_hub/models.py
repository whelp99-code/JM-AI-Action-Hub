from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class TZDateTime(TypeDecorator):
    """Persist aware datetimes as naive UTC and restore UTC awareness."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    pass


class PlanStatus(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    QUEUED = "queued"
    ROUTED = "routed"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class ItemState(str, enum.Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    QUEUED = "queued"
    EXECUTING = "executing"
    REGISTERED = "registered"
    WAITING = "waiting"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    HUMAN_REVIEW = "human_review"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    SKIPPED_DUPLICATE = "skipped_duplicate"
    CANCELLED = "cancelled"


class ActionType(str, enum.Enum):
    EVENT = "event"
    TODO = "todo"
    PROJECT_TASK = "project_task"
    REMINDER = "reminder"
    NOTE = "note"


class Destination(str, enum.Enum):
    TODOIST = "todoist"
    GITHUB = "github"
    GOOGLE_CALENDAR = "google_calendar"
    LOCAL_ICS = "local_ics"
    NONE = "none"


class ExecutorType(str, enum.Enum):
    HUMAN = "human"
    AI = "ai"
    HYBRID = "hybrid"
    EXTERNAL = "external"


class AttentionState(str, enum.Enum):
    UNTRIAGED = "untriaged"
    CLASSIFIED = "classified"
    COMMITTED = "committed"
    FOCUSING = "focusing"
    PAUSED = "paused"
    CARRIED_OVER = "carried_over"
    SKIPPED = "skipped"
    COMPLETED = "completed"


class Quadrant(str, enum.Enum):
    Q1 = "q1"
    Q2 = "q2"
    Q3 = "q3"
    Q4 = "q4"


class FocusSessionState(str, enum.Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class TrafficState(str, enum.Enum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


class InboxEntry(Base):
    __tablename__ = "inbox_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(40), default="paste")
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Seoul")
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="parsed")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    plans: Mapped[list["ActionPlan"]] = relationship(back_populates="inbox", cascade="all, delete-orphan")


class ActionPlan(Base):
    __tablename__ = "action_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    inbox_id: Mapped[str] = mapped_column(ForeignKey("inbox_entries.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=PlanStatus.DRAFT.value, index=True)
    parser_name: Mapped[str] = mapped_column(String(80), default="rules-v2")
    summary: Mapped[str] = mapped_column(Text, default="")
    reference_time: Mapped[datetime] = mapped_column(TZDateTime(), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    inbox: Mapped[InboxEntry] = relationship(back_populates="plans")
    items: Mapped[list["ActionItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="ActionItem.created_at"
    )

    __mapper_args__ = {"version_id_col": revision}


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(ForeignKey("action_plans.id", ondelete="CASCADE"), index=True)
    item_type: Mapped[str] = mapped_column(String(32), index=True)
    destination: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    source_fragment: Mapped[str] = mapped_column(Text, default="")
    project: Mapped[str | None] = mapped_column(String(255), nullable=True)
    repository: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assignee: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    earliest_start_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    latest_finish_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=2)
    labels: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_mode: Mapped[str] = mapped_column(String(32), default="unspecified", index=True)
    executor: Mapped[str] = mapped_column(String(32), default=ExecutorType.HUMAN.value, index=True)
    preferred_worker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    energy_level: Mapped[str] = mapped_column(String(16), default="medium")
    waiting_for: Mapped[str | None] = mapped_column(String(255), nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True, index=True)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    completion_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    reschedule_count: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    attention_state: Mapped[str] = mapped_column(
        String(32), default=AttentionState.UNTRIAGED.value, index=True
    )

    state: Mapped[str] = mapped_column(String(32), default=ItemState.DRAFT.value, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    execution_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    plan: Mapped[ActionPlan] = relationship(back_populates="items")
    external_states: Mapped[list["ExternalState"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan"
    )
    worker_executions: Mapped[list["WorkerExecution"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan"
    )
    followups: Mapped[list["FollowUp"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan"
    )
    priority_assessment: Mapped["PriorityAssessment | None"] = relationship(
        back_populates="action_item", cascade="all, delete-orphan", uselist=False
    )
    commitments: Mapped[list["DailyCommitment"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan"
    )
    micro_steps: Mapped[list["MicroStep"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan", order_by="MicroStep.position"
    )
    focus_sessions: Mapped[list["FocusSession"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan"
    )
    carry_over_decisions: Mapped[list["CarryOverDecision"]] = relationship(
        back_populates="action_item", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_action_items_destination_fingerprint_state", "destination", "fingerprint", "state"),
    )
    __mapper_args__ = {"version_id_col": revision}


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(50), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    aggregate_type: Mapped[str] = mapped_column(String(50), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    destination: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    delivery_id: Mapped[str] = mapped_column(String(160))
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    headers_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("provider", "delivery_id", name="uq_webhook_provider_delivery"),)


class ExternalState(Base):
    __tablename__ = "external_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_item_id: Mapped[str] = mapped_column(ForeignKey("action_items.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(255), index=True)
    external_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(64), default="open", index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    external_updated_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(80), nullable=True)

    action_item: Mapped[ActionItem] = relationship(back_populates="external_states")
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_external_provider_id"),)


class SyncConflict(Base):
    __tablename__ = "sync_conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_item_id: Mapped[str] = mapped_column(ForeignKey("action_items.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    conflict_type: Mapped[str] = mapped_column(String(80), index=True)
    local_value: Mapped[dict] = mapped_column(JSON, default=dict)
    external_value: Mapped[dict] = mapped_column(JSON, default=dict)
    resolution: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class WorkerExecution(Base):
    __tablename__ = "worker_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_item_id: Mapped[str] = mapped_column(ForeignKey("action_items.id", ondelete="CASCADE"), index=True)
    worker: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    dispatch_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    repository: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pull_request_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    workflow_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    artifacts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    action_item: Mapped[ActionItem] = relationship(back_populates="worker_executions")


class FollowUp(Base):
    __tablename__ = "followups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_item_id: Mapped[str] = mapped_column(ForeignKey("action_items.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(32), default="waiting", index=True)
    waiting_for: Mapped[str] = mapped_column(String(255))
    channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_by: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    follow_up_at: Mapped[datetime] = mapped_column(TZDateTime(), index=True)
    template: Mapped[str | None] = mapped_column(Text, nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reminded_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    response_received_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    action_item: Mapped[ActionItem] = relationship(back_populates="followups")

    @property
    def action_title(self) -> str | None:
        return self.action_item.title if self.action_item is not None else None


class PriorityAssessment(Base):
    __tablename__ = "priority_assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_item_id: Mapped[str] = mapped_column(
        ForeignKey("action_items.id", ondelete="CASCADE"), unique=True, index=True
    )
    importance_score: Mapped[float] = mapped_column(Float, default=50)
    urgency_score: Mapped[float] = mapped_column(Float, default=50)
    quadrant: Mapped[str] = mapped_column(String(8), default=Quadrant.Q2.value, index=True)
    source: Mapped[str] = mapped_column(String(24), default="rule")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    user_overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    action_item: Mapped[ActionItem] = relationship(back_populates="priority_assessment")


class DailyFocusPlan(Base):
    __tablename__ = "daily_focus_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    plan_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    available_minutes: Mapped[int] = mapped_column(Integer, default=480)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class DailyCommitment(Base):
    __tablename__ = "daily_commitments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    commitment_date: Mapped[date] = mapped_column(Date, index=True)
    action_item_id: Mapped[str] = mapped_column(
        ForeignKey("action_items.id", ondelete="CASCADE"), index=True
    )
    owner_type: Mapped[str] = mapped_column(String(16), index=True)
    rank: Mapped[int] = mapped_column(Integer)
    committed_minutes: Mapped[int] = mapped_column(Integer, default=30)
    state: Mapped[str] = mapped_column(String(24), default="committed", index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    action_item: Mapped[ActionItem] = relationship(back_populates="commitments")
    __table_args__ = (
        UniqueConstraint("commitment_date", "owner_type", "rank", name="uq_commitment_owner_rank"),
        UniqueConstraint("commitment_date", "action_item_id", name="uq_commitment_date_item"),
        Index("ix_daily_commitments_date_owner_state", "commitment_date", "owner_type", "state"),
    )


class MicroStep(Base):
    __tablename__ = "micro_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_item_id: Mapped[str] = mapped_column(
        ForeignKey("action_items.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    executor: Mapped[str] = mapped_column(String(32), default=ExecutorType.HUMAN.value)
    preferred_worker: Mapped[str | None] = mapped_column(String(64), nullable=True)
    estimated_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    completion_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    action_item: Mapped[ActionItem] = relationship(back_populates="micro_steps")
    __table_args__ = (UniqueConstraint("action_item_id", "position", name="uq_micro_step_position"),)


class FocusSession(Base):
    __tablename__ = "focus_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_item_id: Mapped[str] = mapped_column(
        ForeignKey("action_items.id", ondelete="CASCADE"), index=True
    )
    planned_minutes: Mapped[int] = mapped_column(Integer)
    extension_minutes: Mapped[int] = mapped_column(Integer, default=0)
    active_slot: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    state: Mapped[str] = mapped_column(String(24), default=FocusSessionState.RUNNING.value, index=True)
    traffic_state: Mapped[str] = mapped_column(String(16), default=TrafficState.GREEN.value, index=True)
    started_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    paused_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
    pause_count: Mapped[int] = mapped_column(Integer, default=0)
    ended_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    actual_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[str] = mapped_column(String(100), default="user")
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    action_item: Mapped[ActionItem] = relationship(back_populates="focus_sessions")
    __mapper_args__ = {"version_id_col": revision}


class CarryOverDecision(Base):
    __tablename__ = "carry_over_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    action_item_id: Mapped[str] = mapped_column(
        ForeignKey("action_items.id", ondelete="CASCADE"), index=True
    )
    from_date: Mapped[date] = mapped_column(Date, index=True)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    reason: Mapped[str] = mapped_column(String(255), default="")
    actor: Mapped[str] = mapped_column(String(100), default="user")
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)

    action_item: Mapped[ActionItem] = relationship(back_populates="carry_over_decisions")


class PersonalRule(Base):
    __tablename__ = "personal_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    condition_json: Mapped[dict] = mapped_column(JSON, default=dict)
    action_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="proposed", index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    observations: Mapped[int] = mapped_column(Integer, default=1)
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class MetricEvent(Base):
    __tablename__ = "metric_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    metric_name: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(32), default="count")
    action_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("action_items.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)


class MeetingIntake(Base):
    __tablename__ = "meeting_intakes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(40), default="fireflies")
    external_meeting_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transcript_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    action_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("action_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    __table_args__ = (UniqueConstraint("provider", "external_meeting_id", "event_type", name="uq_meeting_event"),)


class MobileDevice(Base):
    __tablename__ = "mobile_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_name: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(32), default="ios", index=True)
    hardware_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    push_token: Mapped[str | None] = mapped_column(String(512), nullable=True, unique=True)
    push_environment: Mapped[str] = mapped_column(String(24), default="sandbox")
    notification_preferences: Mapped[dict] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    refresh_tokens: Mapped[list["MobileRefreshToken"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    captures: Mapped[list["MobileCapture"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    push_notifications: Mapped[list["PushNotification"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )


class MobilePairingSession(Base):
    __tablename__ = "mobile_pairing_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    requested_scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime(), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    claimed_device_id: Mapped[str | None] = mapped_column(
        ForeignKey("mobile_devices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(String(100), default="admin")
    claimed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class MobileRefreshToken(Base):
    __tablename__ = "mobile_refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("mobile_devices.id", ondelete="CASCADE"), index=True)
    family_id: Mapped[str] = mapped_column(String(36), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime(), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("mobile_refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    device: Mapped[MobileDevice] = relationship(back_populates="refresh_tokens")


class MobileCapture(Base):
    __tablename__ = "mobile_captures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("mobile_devices.id", ondelete="CASCADE"), index=True)
    client_capture_id: Mapped[str] = mapped_column(String(80))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("action_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    device: Mapped[MobileDevice] = relationship(back_populates="captures")
    __table_args__ = (
        UniqueConstraint("device_id", "client_capture_id", name="uq_mobile_capture_device_client"),
    )


class PushNotification(Base):
    __tablename__ = "push_notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("mobile_devices.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    state: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    device: Mapped[MobileDevice] = relationship(back_populates="push_notifications")
