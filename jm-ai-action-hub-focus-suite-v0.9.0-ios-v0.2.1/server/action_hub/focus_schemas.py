from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import ExecutorType, ItemState, Quadrant


class PriorityAssessmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_item_id: str
    importance_score: float
    urgency_score: float
    quadrant: Quadrant
    source: str
    confidence: float
    reasons_json: list[str]
    user_overridden: bool
    created_at: datetime
    updated_at: datetime


class FocusActionSummary(BaseModel):
    action_item_id: str
    plan_id: str
    title: str
    description: str = ""
    project: str | None = None
    repository: str | None = None
    priority: int
    estimated_minutes: int
    actual_minutes: int | None = None
    executor: ExecutorType
    preferred_worker: str | None = None
    state: ItemState
    attention_state: str
    due_at: datetime | None = None
    deadline_at: datetime | None = None
    external_url: str | None = None
    assessment: PriorityAssessmentRead | None = None


class TriageResponse(BaseModel):
    generated_at: datetime
    total: int
    items: list[FocusActionSummary]


class ClassifyActionRequest(BaseModel):
    quadrant: Quadrant
    importance_score: float | None = Field(default=None, ge=0, le=100)
    urgency_score: float | None = Field(default=None, ge=0, le=100)
    reason: str | None = Field(default=None, max_length=500)
    expected_item_revision: int | None = Field(default=None, ge=1)
    actor: str = Field(default="user", max_length=100)


class MatrixResponse(BaseModel):
    generated_at: datetime
    counts: dict[str, int]
    q1: list[FocusActionSummary]
    q2: list[FocusActionSummary]
    q3: list[FocusActionSummary]
    q4: list[FocusActionSummary]
    untriaged_count: int


class DailyCommitmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    commitment_date: date
    action_item_id: str
    owner_type: Literal["human", "ai"]
    rank: int
    committed_minutes: int
    state: str
    created_at: datetime
    updated_at: datetime
    action: FocusActionSummary | None = None


class DualBig3Request(BaseModel):
    target_date: date | None = None
    human_item_ids: list[str] = Field(default_factory=list, max_length=3)
    ai_item_ids: list[str] = Field(default_factory=list, max_length=3)
    available_minutes: int | None = Field(default=None, ge=30, le=1440)
    actor: str = Field(default="user", max_length=100)

    @model_validator(mode="after")
    def unique_items(self) -> "DualBig3Request":
        combined = self.human_item_ids + self.ai_item_ids
        if len(combined) != len(set(combined)):
            raise ValueError("The same action cannot be committed to both Human and AI Big3")
        return self


class DualBig3Response(BaseModel):
    date: date
    available_minutes: int
    human_committed_minutes: int
    ai_committed_minutes: int
    overload_minutes: int
    human: list[DailyCommitmentRead]
    ai: list[DailyCommitmentRead]
    warnings: list[str]


class MicroStepInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    executor: ExecutorType = ExecutorType.HUMAN
    preferred_worker: str | None = Field(default=None, max_length=64)
    estimated_minutes: int | None = Field(default=None, ge=1, le=480)


class DecomposeActionRequest(BaseModel):
    max_steps: int = Field(default=5, ge=3, le=5)
    replace_existing: bool = True
    steps: list[MicroStepInput] | None = Field(default=None, min_length=1, max_length=8)
    actor: str = Field(default="user", max_length=100)


class MicroStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_item_id: str
    position: int
    title: str
    executor: ExecutorType
    preferred_worker: str | None
    estimated_minutes: int | None
    state: str
    completion_note: str | None
    created_at: datetime
    updated_at: datetime


class MicroStepUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    executor: ExecutorType | None = None
    preferred_worker: str | None = Field(default=None, max_length=64)
    estimated_minutes: int | None = Field(default=None, ge=1, le=480)
    state: Literal["pending", "running", "completed", "skipped"] | None = None
    completion_note: str | None = Field(default=None, max_length=2000)
    actor: str = Field(default="user", max_length=100)


class FocusSessionStartRequest(BaseModel):
    action_item_id: str
    planned_minutes: int = Field(default=25, ge=5, le=240)
    actor: str = Field(default="user", max_length=100)


class FocusSessionUpdateRequest(BaseModel):
    action: Literal["pause", "resume", "extend", "complete", "abandon"]
    expected_revision: int | None = Field(default=None, ge=1)
    extension_minutes: int | None = Field(default=None, ge=1, le=90)
    completion_note: str | None = Field(default=None, max_length=2000)
    mark_action_completed: bool = False
    actor: str = Field(default="user", max_length=100)


class FocusSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_item_id: str
    planned_minutes: int
    extension_minutes: int
    total_planned_minutes: int
    elapsed_seconds: int
    remaining_seconds: int
    progress: float
    state: str
    traffic_state: str
    started_at: datetime
    paused_at: datetime | None
    paused_seconds: int
    pause_count: int
    ended_at: datetime | None
    actual_minutes: int | None
    completion_note: str | None
    started_by: str
    revision: int
    created_at: datetime
    updated_at: datetime
    action: FocusActionSummary | None = None
    micro_steps: list[MicroStepRead] = Field(default_factory=list)


class DayCloseDecisionInput(BaseModel):
    action_item_id: str
    decision: Literal["reschedule", "split", "delegate", "deadline_change", "cancel", "waiting"]
    reason: str = Field(default="", max_length=255)
    to_date: date | None = None
    waiting_for: str | None = Field(default=None, max_length=255)
    follow_up_at: datetime | None = None
    executor: ExecutorType | None = None


class DayCloseRequest(BaseModel):
    target_date: date | None = None
    decisions: list[DayCloseDecisionInput] = Field(min_length=1, max_length=100)
    actor: str = Field(default="user", max_length=100)


class CarryOverDecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_item_id: str
    from_date: date
    to_date: date | None
    decision: str
    reason: str
    actor: str
    result_json: dict
    created_at: datetime


class DayCloseResponse(BaseModel):
    date: date
    processed: int
    decisions: list[CarryOverDecisionRead]
    warnings: list[str]


class FocusWeeklyReport(BaseModel):
    period_start: date
    period_end: date
    generated_at: datetime
    total_sessions: int
    completed_sessions: int
    focus_minutes: int
    human_big3_total: int
    human_big3_completed: int
    ai_big3_total: int
    ai_big3_completed: int
    big3_completion_rate: float
    quadrant_focus_minutes: dict[str, int]
    traffic_distribution: dict[str, int]
    carry_over_count: int
    average_estimate_accuracy: float | None
    q2_investment_minutes: int
    q3_delegated_count: int
    recommendations: list[str]
    summary: str


class FocusDashboardSummary(BaseModel):
    matrix_counts: dict[str, int]
    human_big3: list[DailyCommitmentRead]
    ai_big3: list[DailyCommitmentRead]
    active_focus: FocusSessionRead | None = None
    untriaged_count: int = 0
