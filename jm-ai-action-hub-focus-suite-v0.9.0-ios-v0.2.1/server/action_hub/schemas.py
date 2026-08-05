from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import ActionType, Destination, ExecutorType, ItemState, PlanStatus


class InboxParseRequest(BaseModel):
    text: str = Field(min_length=1)
    source: str = Field(default="paste", max_length=40)
    timezone: str = "Asia/Seoul"
    reference_time: datetime | None = None
    force_new: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value


class ActionItemDraft(BaseModel):
    item_type: ActionType
    destination: Destination
    title: str
    description: str = ""
    source_fragment: str = ""
    project: str | None = None
    repository: str | None = None
    assignee: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    due_at: datetime | None = None
    deadline_at: datetime | None = None
    earliest_start_at: datetime | None = None
    latest_finish_at: datetime | None = None
    is_all_day: bool = False
    priority: int = Field(default=2, ge=1, le=4)
    labels: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0, le=1)
    needs_review: bool = False
    review_reason: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=10080)
    actual_minutes: int | None = Field(default=None, ge=0, le=10080)
    work_mode: Literal["deep", "shallow", "admin", "call", "meeting", "errand", "unspecified"] = "unspecified"
    executor: ExecutorType = ExecutorType.HUMAN
    preferred_worker: str | None = None
    energy_level: Literal["high", "medium", "low"] = "medium"
    waiting_for: str | None = None
    follow_up_at: datetime | None = None
    depends_on: list[str] = Field(default_factory=list)
    completion_evidence: str | None = None


class ActionItemUpdate(BaseModel):
    item_type: ActionType | None = None
    destination: Destination | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    source_fragment: str | None = None
    project: str | None = None
    repository: str | None = None
    assignee: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    due_at: datetime | None = None
    deadline_at: datetime | None = None
    earliest_start_at: datetime | None = None
    latest_finish_at: datetime | None = None
    is_all_day: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=4)
    labels: list[str] | None = None
    needs_review: bool | None = None
    review_reason: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=10080)
    actual_minutes: int | None = Field(default=None, ge=0, le=10080)
    work_mode: Literal["deep", "shallow", "admin", "call", "meeting", "errand", "unspecified"] | None = None
    executor: ExecutorType | None = None
    preferred_worker: str | None = None
    energy_level: Literal["high", "medium", "low"] | None = None
    waiting_for: str | None = None
    follow_up_at: datetime | None = None
    depends_on: list[str] | None = None
    completion_evidence: str | None = None


class ExternalStateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    external_id: str
    external_url: str | None
    state: str
    payload_json: dict[str, Any]
    external_updated_at: datetime | None
    last_synced_at: datetime
    sync_error: str | None


class WorkerExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_item_id: str
    worker: str
    state: str
    dispatch_id: str | None
    repository: str | None
    issue_number: int | None
    pull_request_number: int | None
    workflow_run_id: str | None
    artifacts_json: dict[str, Any]
    output_summary: str | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FollowUpRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_item_id: str
    state: str
    waiting_for: str
    channel: str | None
    expected_by: datetime | None
    follow_up_at: datetime
    template: str | None
    reminder_count: int
    last_reminded_at: datetime | None
    response_received_at: datetime | None
    created_at: datetime
    updated_at: datetime
    action_title: str | None = None


class ActionItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    plan_id: str
    item_type: ActionType
    destination: Destination
    title: str
    description: str
    source_fragment: str
    project: str | None
    repository: str | None
    assignee: str | None
    start_at: datetime | None
    end_at: datetime | None
    due_at: datetime | None
    deadline_at: datetime | None
    earliest_start_at: datetime | None
    latest_finish_at: datetime | None
    is_all_day: bool
    priority: int
    labels: list[str]
    confidence: float
    needs_review: bool
    review_reason: str | None
    estimated_minutes: int | None
    actual_minutes: int | None
    work_mode: str
    executor: ExecutorType
    preferred_worker: str | None
    energy_level: str
    waiting_for: str | None
    follow_up_at: datetime | None
    depends_on: list[str]
    completion_evidence: str | None
    reschedule_count: int
    revision: int
    attention_state: str = "untriaged"
    state: ItemState
    fingerprint: str
    external_id: str | None
    external_url: str | None
    execution_payload: dict[str, Any]
    execution_error: str | None
    registered_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    external_states: list[ExternalStateRead] = Field(default_factory=list)
    worker_executions: list[WorkerExecutionRead] = Field(default_factory=list)
    followups: list[FollowUpRead] = Field(default_factory=list)


class InboxRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source: str
    raw_text: str
    timezone: str
    fingerprint: str
    status: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    inbox_id: str
    status: PlanStatus
    parser_name: str
    summary: str
    reference_time: datetime
    revision: int
    created_at: datetime
    updated_at: datetime
    items: list[ActionItemRead]
    inbox: InboxRead | None = None
    # Populated only by approve_plan() when items were left blocked because they
    # still need review and the caller did not force an override. Empty for every
    # other endpoint that returns a PlanRead. See services/executor.py:approve_plan.
    blocked_item_ids: list[str] = Field(default_factory=list)


class ApprovalRequest(BaseModel):
    item_ids: list[str] | None = None
    actor: str = "user"
    force_review_items: bool = False


class RejectRequest(BaseModel):
    item_ids: list[str] | None = None
    actor: str = "user"
    reason: str = ""


class ExecuteRequest(BaseModel):
    item_ids: list[str] | None = None
    actor: str = "user"
    retry_failed: bool = False
    drain_inline: bool | None = None


class ConnectorStatus(BaseModel):
    name: str
    configured: bool
    execution_mode: str
    detail: str
    healthy: bool | None = None


class ExecutionSummary(BaseModel):
    plan_id: str
    plan_status: PlanStatus
    completed: int
    registered: int = 0
    action_completed: int = 0
    queued: int = 0
    failed: int
    skipped_duplicate: int
    pending: int
    items: list[ActionItemRead]


class BriefItem(BaseModel):
    id: str
    title: str
    item_type: ActionType
    destination: Destination
    when: datetime | None
    state: ItemState
    external_url: str | None = None
    estimated_minutes: int | None = None
    executor: ExecutorType = ExecutorType.HUMAN
    preferred_worker: str | None = None


class DailyBrief(BaseModel):
    generated_at: datetime
    timezone: str
    date: str
    events: list[BriefItem]
    due_tasks: list[BriefItem]
    overdue: list[BriefItem]
    needs_review: list[BriefItem]
    waiting: list[BriefItem] = Field(default_factory=list)
    ai_ready: list[BriefItem] = Field(default_factory=list)
    summary: str


class WebhookReceipt(BaseModel):
    accepted: bool
    duplicate: bool
    delivery_id: str
    provider: str
    event_type: str


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    delivery_id: str
    event_type: str
    signature_valid: bool
    payload_hash: str
    status: str
    attempts: int
    error: str | None
    received_at: datetime
    processed_at: datetime | None


class WorkerRunSummary(BaseModel):
    outbox_processed: int = 0
    webhooks_processed: int = 0
    followups_due: int = 0
    reconciled: int = 0
    push_processed: int = 0
    failed: int = 0


class ReconcileRequest(BaseModel):
    providers: list[str] | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class ReconcileSummary(BaseModel):
    checked: int
    updated: int
    unchanged: int
    failed: int
    providers: dict[str, int]


class DispatchWorkerRequest(BaseModel):
    worker: str = "codex"
    actor: str = "user"
    force: bool = False
    drain_inline: bool | None = None


class FollowUpCreateRequest(BaseModel):
    waiting_for: str = Field(min_length=1, max_length=255)
    channel: str | None = Field(default=None, max_length=40)
    expected_by: datetime | None = None
    follow_up_at: datetime
    template: str | None = None
    actor: str = "user"


class FollowUpResolveRequest(BaseModel):
    state: Literal["response_received", "followed_up", "resolved", "cancelled"]
    actor: str = "user"
    note: str = ""


class PlanningRequest(BaseModel):
    target_date: date | None = None
    available_minutes: int | None = Field(default=None, ge=30, le=1440)
    max_items: int = Field(default=12, ge=1, le=50)
    include_ai: bool = True


class DecisionItem(BaseModel):
    action_item_id: str
    title: str
    score: float
    estimated_minutes: int
    executor: ExecutorType
    state: ItemState
    due_at: datetime | None
    deadline_at: datetime | None
    reasons: list[str]
    external_url: str | None = None
    preferred_worker: str | None = None


class DecisionPlan(BaseModel):
    date: str
    generated_at: datetime
    available_minutes: int
    buffer_minutes: int
    planned_minutes: int
    overload_minutes: int
    top_items: list[DecisionItem]
    deferred_items: list[DecisionItem]
    ai_delegation_candidates: list[DecisionItem]
    waiting_followups: list[FollowUpRead]
    risks: list[str]
    summary: str


class PersonalRuleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    condition: dict[str, Any]
    action: dict[str, Any]
    status: Literal["proposed", "active"] = "proposed"


class PersonalRuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    condition: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    status: Literal["proposed", "active", "rejected", "disabled"] | None = None


class PersonalRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    condition_json: dict[str, Any]
    action_json: dict[str, Any]
    status: str
    confidence: float
    observations: int
    applied_count: int
    created_at: datetime
    updated_at: datetime


class WeeklyMetric(BaseModel):
    name: str
    value: float
    unit: str


class WeeklyReport(BaseModel):
    period_start: date
    period_end: date
    generated_at: datetime
    metrics: list[WeeklyMetric]
    completed_actions: int
    registered_actions: int
    delayed_actions: int
    waiting_actions: int
    ai_dispatches: int
    ai_successes: int
    estimated_minutes_saved: int
    recommendations: list[str]
    summary: str


class MeetingIntakeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    external_meeting_id: str
    event_type: str
    status: str
    title: str | None
    transcript_url: str | None
    summary_json: dict[str, Any]
    action_plan_id: str | None
    error: str | None
    received_at: datetime
    processed_at: datetime | None


class MobileCapabilities(BaseModel):
    service: str
    server_version: str
    mobile_api_version: str = "1"
    mobile_enabled: bool
    minimum_ios_app_version: str
    recommended_ios_app_version: str | None = None
    pairing_supported: bool
    push_supported: bool
    features: list[str]


class MobilePairingCreateRequest(BaseModel):
    scopes: list[str] | None = None
    created_by: str = Field(default="admin", max_length=100)
    public_base_url: str | None = None


class MobilePairingCreateResponse(BaseModel):
    pairing_id: str
    code: str
    expires_at: datetime
    scopes: list[str]
    claim_uri: str
    qr_payload: str


class MobileDeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_name: str
    platform: str
    hardware_model: str | None
    os_version: str | None
    app_version: str | None
    status: str
    scopes: list[str]
    token_version: int
    push_environment: str
    notification_preferences: dict[str, Any]
    last_seen_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
    push_registered: bool = False

    @classmethod
    def from_device(cls, device: Any) -> MobileDeviceRead:
        return cls(
            id=device.id,
            device_name=device.device_name,
            platform=device.platform,
            hardware_model=device.hardware_model,
            os_version=device.os_version,
            app_version=device.app_version,
            status=device.status,
            scopes=list(device.scopes or []),
            token_version=device.token_version,
            push_environment=device.push_environment,
            notification_preferences=dict(device.notification_preferences or {}),
            last_seen_at=device.last_seen_at,
            revoked_at=device.revoked_at,
            created_at=device.created_at,
            updated_at=device.updated_at,
            push_registered=bool(device.push_token),
        )


class MobilePairingClaimRequest(BaseModel):
    pairing_id: str
    code: str = Field(min_length=8, max_length=200)
    device_name: str = Field(min_length=1, max_length=255)
    platform: Literal["ios", "ipados"] = "ios"
    hardware_model: str | None = Field(default=None, max_length=128)
    os_version: str | None = Field(default=None, max_length=64)
    app_version: str | None = Field(default=None, max_length=64)
    push_environment: Literal["sandbox", "production"] = "sandbox"


class MobileTokenResponse(BaseModel):
    token_type: Literal["Bearer"] = "Bearer"
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_at: datetime
    device: MobileDeviceRead


class MobileRefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=40, max_length=500)
    app_version: str | None = Field(default=None, max_length=64)
    os_version: str | None = Field(default=None, max_length=64)


class MobilePushTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    environment: Literal["sandbox", "production"] = "sandbox"


class MobileNotificationPreferencesRequest(BaseModel):
    review_required: bool = True
    ai_status: bool = True
    follow_up_due: bool = True
    deadline_risk: bool = True
    connector_failure: bool = True
    focus_ready: bool = True
    focus_overrun: bool = True


class MobileCaptureInput(BaseModel):
    client_capture_id: str = Field(min_length=8, max_length=80)
    text: str = Field(min_length=1, max_length=30_000)
    source: str = Field(default="ios", max_length=40)
    timezone: str = "Asia/Seoul"
    reference_time: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def normalize_capture_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be empty")
        return value


class MobileCaptureBatchRequest(BaseModel):
    captures: list[MobileCaptureInput] = Field(min_length=1, max_length=100)


class MobileCaptureReceiptRead(BaseModel):
    client_capture_id: str
    status: Literal["processed", "duplicate", "failed"]
    plan_id: str | None = None
    error: str | None = None
    deduplicated: bool = False


class MobileCaptureBatchResponse(BaseModel):
    accepted: int
    processed: int
    duplicate: int
    failed: int
    receipts: list[MobileCaptureReceiptRead]


class MobileActivityItem(BaseModel):
    id: str
    category: Literal["audit", "worker", "followup", "failure"]
    title: str
    subtitle: str | None = None
    state: str
    entity_type: str | None = None
    entity_id: str | None = None
    external_url: str | None = None
    occurred_at: datetime


class MobileDashboard(BaseModel):
    generated_at: datetime
    server_version: str
    minimum_ios_app_version: str
    review_count: int
    waiting_count: int
    ai_running_count: int
    failed_count: int
    brief: DailyBrief
    decision: DecisionPlan
    recent_activity: list[MobileActivityItem]
    focus_summary: dict[str, Any] = Field(default_factory=dict)


class MobileChangeItem(BaseModel):
    audit_id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor: str
    occurred_at: datetime
    payload: dict[str, Any]


class MobileChangesResponse(BaseModel):
    next_cursor: str | None
    has_more: bool
    changes: list[MobileChangeItem]
    deleted: list[dict[str, str]] = Field(default_factory=list)


class MobileActionItemUpdate(ActionItemUpdate):
    expected_revision: int = Field(ge=1)


class MobileApprovalRequest(ApprovalRequest):
    expected_plan_revision: int | None = Field(default=None, ge=1)


class MobileRejectRequest(RejectRequest):
    expected_plan_revision: int | None = Field(default=None, ge=1)


class MobileExecuteRequest(ExecuteRequest):
    expected_plan_revision: int | None = Field(default=None, ge=1)


class MobileDeviceUpdateRequest(BaseModel):
    device_name: str | None = Field(default=None, min_length=1, max_length=255)
    app_version: str | None = Field(default=None, max_length=64)
    os_version: str | None = Field(default=None, max_length=64)


class MobilePushTestRequest(BaseModel):
    event_type: str = Field(default="test", min_length=1, max_length=80)
    entity_type: str | None = Field(default=None, max_length=50)
    entity_id: str | None = Field(default=None, max_length=64)
