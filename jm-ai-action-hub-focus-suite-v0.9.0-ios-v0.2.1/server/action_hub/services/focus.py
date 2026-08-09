from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from ..config import Settings
from ..focus_schemas import (
    Big3RecommendationRead,
    CarryOverDecisionRead,
    ClassifyActionRequest,
    DailyCommitmentRead,
    DayCloseRequest,
    DayCloseResponse,
    DecomposeActionRequest,
    DualBig3Request,
    DualBig3Response,
    FocusActionSummary,
    FocusDashboardSummary,
    FocusSessionRead,
    FocusSessionStartRequest,
    FocusSessionUpdateRequest,
    FocusWeeklyReport,
    MatrixResponse,
    MicroStepInput,
    MicroStepRead,
    MicroStepUpdateRequest,
    PriorityAssessmentRead,
    TriageResponse,
)
from ..models import (
    ActionItem,
    ActionType,
    AttentionState,
    CarryOverDecision,
    DailyCommitment,
    DailyFocusPlan,
    ExecutorType,
    FocusSession,
    FocusSessionState,
    ItemState,
    MicroStep,
    PriorityAssessment,
    Quadrant,
    TrafficState,
    utcnow,
)
from .audit import record_audit
from .followups import ensure_followup
from .metrics import record_metric
from .state_sync import clear_needs_review

TERMINAL_STATES = {
    ItemState.COMPLETED.value,
    ItemState.REJECTED.value,
    ItemState.SKIPPED_DUPLICATE.value,
    ItemState.CANCELLED.value,
}
ACTIVE_FOCUS_STATES = {FocusSessionState.RUNNING.value, FocusSessionState.PAUSED.value}
MATRIX_QUADRANTS = (Quadrant.Q1.value, Quadrant.Q2.value, Quadrant.Q3.value, Quadrant.Q4.value)


def _local(value: datetime | None, tz: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _quadrant(importance: float, urgency: float, settings: Settings) -> Quadrant:
    important = importance >= settings.importance_threshold
    urgent = urgency >= settings.urgency_threshold
    if important and urgent:
        return Quadrant.Q1
    if important:
        return Quadrant.Q2
    if urgent:
        return Quadrant.Q3
    return Quadrant.Q4


def _rule_scores(item: ActionItem, settings: Settings, now: datetime | None = None) -> tuple[float, float, list[str]]:
    tz = ZoneInfo(settings.timezone)
    now = now.astimezone(tz) if now else datetime.now(tz)
    importance = float(max(1, min(4, item.priority)) * 18)
    urgency = 12.0
    reasons: list[str] = [f"우선순위 {item.priority}/4"]

    labels = {str(label).lower() for label in (item.labels or [])}
    importance_labels = {
        "strategic": 20,
        "strategy": 20,
        "customer": 15,
        "client": 15,
        "revenue": 20,
        "security": 20,
        "production": 20,
        "critical": 20,
        "deep_work": 10,
        "deep": 10,
    }
    label_bonus = min(30, sum(value for key, value in importance_labels.items() if key in labels))
    if label_bonus:
        importance += label_bonus
        reasons.append("전략·고객·운영 영향 라벨")
    if item.project:
        importance += 8
        reasons.append("프로젝트 결과물")
    if item.repository:
        importance += 5
        reasons.append("개발 실행 원장 연결")
    if item.work_mode == "deep":
        importance += 8
        reasons.append("집중 업무")
    if item.item_type == ActionType.NOTE.value:
        importance -= 25
        reasons.append("참고 메모")

    deadline = _local(item.deadline_at, tz)
    due = _local(item.due_at, tz)
    start = _local(item.start_at, tz)
    candidate = deadline or due or start
    if candidate:
        hours = (candidate - now).total_seconds() / 3600
        if hours < 0:
            urgency += 88
            reasons.append("기한 경과")
        elif hours <= 12:
            urgency += 78
            reasons.append("12시간 이내")
        elif hours <= 24:
            urgency += 68
            reasons.append("24시간 이내")
        elif hours <= 72:
            urgency += 50
            reasons.append("3일 이내")
        elif hours <= 168:
            urgency += 28
            reasons.append("7일 이내")
        else:
            urgency += 10
    if item.follow_up_at:
        follow_up = _local(item.follow_up_at, tz)
        if follow_up and follow_up <= now:
            urgency += 60
            reasons.append("후속 확인 시각 도래")
    if item.reschedule_count:
        urgency += min(25, item.reschedule_count * 6)
        reasons.append(f"{item.reschedule_count}회 재조정")
    if item.state == ItemState.FAILED.value:
        urgency += 20
        reasons.append("실패 복구 필요")
    if item.depends_on:
        urgency -= 15
        reasons.append("선행 작업 확인 필요")
    if item.needs_review:
        importance = max(importance, 50)
        urgency = max(urgency, 45)
        reasons.append("사용자 검토 필요")
    if item.executor in {ExecutorType.AI.value, ExecutorType.HYBRID.value}:
        reasons.append("AI 위임 가능")

    return min(100.0, max(0.0, importance)), min(100.0, max(0.0, urgency)), reasons


def suggested_assessment(item: ActionItem, settings: Settings) -> PriorityAssessmentRead:
    importance, urgency, reasons = _rule_scores(item, settings)
    quadrant = _quadrant(importance, urgency, settings)
    distance = abs(importance - settings.importance_threshold) + abs(urgency - settings.urgency_threshold)
    confidence = min(0.96, max(0.55, 0.6 + distance / 300))
    return PriorityAssessmentRead(
        id=f"suggested:{item.id}",
        action_item_id=item.id,
        importance_score=round(importance, 2),
        urgency_score=round(urgency, 2),
        quadrant=quadrant,
        source="rule",
        confidence=round(confidence, 2),
        reasons_json=reasons,
        user_overridden=False,
        created_at=utcnow(),
        updated_at=utcnow(),
    )


def _assessment_read(row: PriorityAssessment | None) -> PriorityAssessmentRead | None:
    return PriorityAssessmentRead.model_validate(row) if row is not None else None


def _action_summary(item: ActionItem, settings: Settings, *, suggest_if_missing: bool = False) -> FocusActionSummary:
    assessment = _assessment_read(item.priority_assessment)
    if assessment is None and suggest_if_missing:
        assessment = suggested_assessment(item, settings)
    return FocusActionSummary(
        action_item_id=item.id,
        plan_id=item.plan_id,
        title=item.title,
        description=item.description,
        project=item.project,
        repository=item.repository,
        priority=item.priority,
        estimated_minutes=item.estimated_minutes or settings.default_estimated_minutes,
        actual_minutes=item.actual_minutes,
        executor=item.executor,
        preferred_worker=item.preferred_worker,
        state=item.state,
        attention_state=item.attention_state,
        due_at=item.due_at,
        deadline_at=item.deadline_at,
        external_url=item.external_url,
        assessment=assessment,
        energy_level=item.energy_level or "medium",
    )


def list_triage(db: Session, settings: Settings, *, limit: int = 50) -> TriageResponse:
    rows = list(
        db.scalars(
            select(ActionItem)
            .where(
                ActionItem.state.notin_(TERMINAL_STATES),
                ActionItem.state != ItemState.WAITING.value,
                ActionItem.attention_state == AttentionState.UNTRIAGED.value,
            )
            .options(selectinload(ActionItem.priority_assessment))
            .order_by(ActionItem.deadline_at.is_(None), ActionItem.deadline_at, ActionItem.created_at)
            .limit(limit)
        )
    )
    return TriageResponse(
        generated_at=utcnow(),
        total=len(rows),
        items=[_action_summary(row, settings, suggest_if_missing=True) for row in rows],
    )


def classify_action(
    db: Session,
    settings: Settings,
    item_id: str,
    request: ClassifyActionRequest,
    *,
    actor_override: str | None = None,
) -> FocusActionSummary:
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == item_id)
        .options(selectinload(ActionItem.priority_assessment))
    )
    if item is None:
        raise LookupError("Action item not found")
    if item.state in TERMINAL_STATES:
        raise ValueError("A terminal action cannot be classified")
    if request.expected_item_revision is not None and item.revision != request.expected_item_revision:
        raise RuntimeError(f"revision_conflict:{item.revision}")

    defaults = {
        Quadrant.Q1: (85.0, 85.0),
        Quadrant.Q2: (85.0, 35.0),
        Quadrant.Q3: (35.0, 85.0),
        Quadrant.Q4: (30.0, 30.0),
    }
    importance, urgency = defaults[request.quadrant]
    importance = request.importance_score if request.importance_score is not None else importance
    urgency = request.urgency_score if request.urgency_score is not None else urgency
    reasons = [request.reason] if request.reason else ["사용자 분류"]
    if item.priority_assessment is None:
        item.priority_assessment = PriorityAssessment(
            action_item_id=item.id,
            importance_score=importance,
            urgency_score=urgency,
            quadrant=request.quadrant.value,
            source="user",
            confidence=1.0,
            reasons_json=reasons,
            user_overridden=True,
        )
    else:
        row = item.priority_assessment
        row.importance_score = importance
        row.urgency_score = urgency
        row.quadrant = request.quadrant.value
        row.source = "user"
        row.confidence = 1.0
        row.reasons_json = reasons
        row.user_overridden = True
    item.attention_state = AttentionState.CLASSIFIED.value
    actor = actor_override or request.actor
    record_audit(
        db,
        entity_type="action_item",
        entity_id=item.id,
        event_type="attention.classified",
        actor=actor,
        payload={
            "quadrant": request.quadrant.value,
            "importance_score": importance,
            "urgency_score": urgency,
            "reason": request.reason,
        },
    )
    db.commit()
    db.refresh(item)
    return _action_summary(item, settings)


def _matrix_counts(db: Session) -> tuple[dict[str, int], int]:
    counts = {quadrant: 0 for quadrant in MATRIX_QUADRANTS}
    classified_counts = db.execute(
        select(PriorityAssessment.quadrant, func.count(ActionItem.id))
        .select_from(ActionItem)
        .join(ActionItem.priority_assessment)
        .where(
            ActionItem.state.notin_(TERMINAL_STATES),
            ActionItem.attention_state != AttentionState.UNTRIAGED.value,
        )
        .group_by(PriorityAssessment.quadrant)
    )
    for quadrant, count in classified_counts:
        if quadrant in counts:
            counts[quadrant] = count

    untriaged = db.scalar(
        select(func.count(ActionItem.id))
        .select_from(ActionItem)
        .outerjoin(ActionItem.priority_assessment)
        .where(
            ActionItem.state.notin_(TERMINAL_STATES),
            or_(
                ActionItem.attention_state == AttentionState.UNTRIAGED.value,
                PriorityAssessment.id.is_(None),
            ),
        )
    )
    return counts, untriaged or 0


def _matrix_quadrant_rows(
    db: Session, quadrant: str, limit_per_quadrant: int
) -> list[ActionItem]:
    return list(
        db.scalars(
            select(ActionItem)
            .join(ActionItem.priority_assessment)
            .where(
                ActionItem.state.notin_(TERMINAL_STATES),
                ActionItem.attention_state != AttentionState.UNTRIAGED.value,
                PriorityAssessment.quadrant == quadrant,
            )
            .options(joinedload(ActionItem.priority_assessment))
            .order_by(ActionItem.deadline_at.is_(None), ActionItem.deadline_at, ActionItem.created_at)
            .limit(limit_per_quadrant)
        )
    )


def matrix(db: Session, settings: Settings, *, limit_per_quadrant: int = 100) -> MatrixResponse:
    counts, untriaged = _matrix_counts(db)
    grouped = {quadrant: [] for quadrant in MATRIX_QUADRANTS}
    if limit_per_quadrant > 0:
        for quadrant in MATRIX_QUADRANTS:
            grouped[quadrant] = [
                _action_summary(item, settings)
                for item in _matrix_quadrant_rows(db, quadrant, limit_per_quadrant)
            ]
    return MatrixResponse(
        generated_at=utcnow(),
        counts=counts,
        q1=grouped["q1"],
        q2=grouped["q2"],
        q3=grouped["q3"],
        q4=grouped["q4"],
        untriaged_count=untriaged,
    )


def _commitment_read(row: DailyCommitment, settings: Settings) -> DailyCommitmentRead:
    result = DailyCommitmentRead.model_validate(row)
    return result.model_copy(update={"action": _action_summary(row.action_item, settings)})


def _processing_intensity(item: ActionItem, settings: Settings) -> tuple[str, str]:
    estimate = item.estimated_minutes or settings.default_estimated_minutes
    energy = (item.energy_level or "medium").lower()
    if estimate >= 90 or energy == "high" or item.work_mode == "deep":
        return "heavy", "집중 처리"
    if estimate <= 20 and energy == "low" or item.work_mode in {"shallow", "admin", "errand"}:
        return "light", "가벼운 처리"
    return "medium", "보통 처리"


def _big3_recommendations(
    items: list[ActionItem],
    settings: Settings,
    *,
    owner: str,
    remaining_minutes: int,
    slots: int,
) -> list[Big3RecommendationRead]:
    if slots <= 0 or not items:
        return []

    ranked: list[tuple[float, float, float, ActionItem, PriorityAssessmentRead, str, str]] = []
    for item in items:
        if owner == "human":
            if item.executor not in {
                ExecutorType.HUMAN.value,
                ExecutorType.HYBRID.value,
                ExecutorType.EXTERNAL.value,
            }:
                continue
        elif item.executor not in {ExecutorType.AI.value, ExecutorType.HYBRID.value}:
            continue

        assessment = _assessment_read(item.priority_assessment) or suggested_assessment(item, settings)
        if assessment.quadrant == Quadrant.Q4:
            continue
        estimate = item.estimated_minutes or settings.default_estimated_minutes
        intensity, intensity_title = _processing_intensity(item, settings)
        fits = estimate <= remaining_minutes
        deficit = max(0, estimate - remaining_minutes)

        # Importance and urgency lead the decision. Schedule fit is a strong
        # tie-breaker so a recommendation does not silently consume tomorrow's
        # capacity, while intensity keeps a very deep task from crowding out
        # every smaller, finishable task.
        score = assessment.importance_score * 0.48 + assessment.urgency_score * 0.37
        score += 18 if fits else -min(30.0, deficit * 0.5)
        if intensity == "heavy" and remaining_minutes >= estimate:
            score += 5
        elif intensity == "light" and remaining_minutes <= 45:
            score += 6
        if assessment.quadrant == Quadrant.Q1:
            score += 6
        ranked.append((score, assessment.importance_score, assessment.urgency_score, item, assessment, intensity, intensity_title))

    ranked.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3].estimated_minutes or settings.default_estimated_minutes, row[3].title, row[3].id))

    selected: list[tuple[float, float, float, ActionItem, PriorityAssessmentRead, str, str, int, bool]] = []
    budget = max(0, remaining_minutes)
    for candidate in ranked:
        if len(selected) >= slots:
            break
        estimate = candidate[3].estimated_minutes or settings.default_estimated_minutes
        if estimate <= budget:
            selected.append((*candidate, budget, True))
            budget -= estimate

    # When no candidate fits, return one explicit exception rather than three
    # attractive-looking commitments that guarantee an overloaded day.
    if not selected and ranked:
        selected = [(*ranked[0], max(0, remaining_minutes), False)]

    recommendations: list[Big3RecommendationRead] = []
    for rank, candidate in enumerate(selected, 1):
        score, importance, urgency, item, assessment, intensity, intensity_title, before, fits = candidate
        estimate = item.estimated_minutes or settings.default_estimated_minutes
        after = before - estimate if fits else max(0, before)
        reasons = [f"중요도 {round(importance)} · 긴급도 {round(urgency)}"]
        if fits:
            reasons.append(f"남은 일정 {before}분에 맞고 완료 후 {after}분이 남음")
        else:
            reasons.append(f"남은 일정보다 {estimate - before}분 더 필요해 용량 초과")
        reasons.append(f"{intensity_title} · 예상 {estimate}분")
        if assessment.quadrant == Quadrant.Q1:
            reasons.append("중요하고 긴급한 Q1 업무")
        elif assessment.quadrant == Quadrant.Q2:
            reasons.append("중요도를 지켜야 하는 Q2 업무")
        elif owner == "ai":
            reasons.append("AI 실행자로 지정되어 위임하기 좋음")
        recommendations.append(
            Big3RecommendationRead(
                action=_action_summary(item, settings, suggest_if_missing=True),
                owner_type=owner,
                rank=rank,
                score=round(score, 2),
                processing_intensity=intensity,
                schedule_fit="fits" if fits else "over_capacity",
                remaining_minutes=after,
                reasons=reasons,
            )
        )
    return recommendations


def _big3_candidate_rows(db: Session, selected_ids: set[str]) -> list[ActionItem]:
    filters = [
        ActionItem.state.notin_(TERMINAL_STATES),
        ActionItem.state != ItemState.WAITING.value,
        ActionItem.attention_state != AttentionState.UNTRIAGED.value,
        or_(ActionItem.needs_review.is_(False), ActionItem.needs_review.is_(None)),
    ]
    if selected_ids:
        filters.append(ActionItem.id.notin_(selected_ids))
    return list(
        db.scalars(
            select(ActionItem)
            .where(*filters)
            .options(selectinload(ActionItem.priority_assessment))
            .order_by(ActionItem.deadline_at.is_(None), ActionItem.deadline_at, ActionItem.created_at)
        )
    )


def get_big3(db: Session, settings: Settings, target_date: date | None = None) -> DualBig3Response:
    tz = ZoneInfo(settings.timezone)
    day = target_date or datetime.now(tz).date()
    rows = list(
        db.scalars(
            select(DailyCommitment)
            .where(DailyCommitment.commitment_date == day, DailyCommitment.state != "released")
            .options(
                selectinload(DailyCommitment.action_item).selectinload(ActionItem.priority_assessment)
            )
            .order_by(DailyCommitment.owner_type, DailyCommitment.rank)
        )
    )
    human = [_commitment_read(row, settings) for row in rows if row.owner_type == "human"]
    ai = [_commitment_read(row, settings) for row in rows if row.owner_type == "ai"]
    human_minutes = sum(row.committed_minutes for row in human)
    ai_minutes = sum(row.committed_minutes for row in ai)
    plan = db.scalar(select(DailyFocusPlan).where(DailyFocusPlan.plan_date == day))
    capacity = plan.available_minutes if plan is not None else settings.default_workday_minutes
    overload = max(0, human_minutes - capacity)
    selected_ids = {row.action_item_id for row in rows}
    candidates = _big3_candidate_rows(db, selected_ids)
    human_remaining = max(0, capacity - human_minutes)
    ai_remaining = max(0, capacity - ai_minutes)
    human_recommendations = _big3_recommendations(
        candidates,
        settings,
        owner="human",
        remaining_minutes=human_remaining,
        slots=max(0, settings.big3_limit - len(human)),
    )
    ai_recommendations = _big3_recommendations(
        candidates,
        settings,
        owner="ai",
        remaining_minutes=ai_remaining,
        slots=max(0, settings.big3_limit - len(ai)),
    )
    warnings: list[str] = []
    if overload:
        warnings.append(f"사람 Big3가 기본 가용시간보다 {overload}분 많습니다.")
    if len(human) < settings.big3_limit:
        warnings.append(f"내 Big3가 {len(human)}건입니다. 핵심 약속을 최대 {settings.big3_limit}건까지 선택할 수 있습니다.")
    if not human and human_recommendations:
        warnings.append("일정·처리 강도·중요도·긴급도를 반영한 내 Big3 제안이 있습니다.")
    if not ai and ai_recommendations:
        warnings.append("AI 실행 가능 업무를 기준으로 AI Big3 제안이 있습니다.")
    return DualBig3Response(
        date=day,
        available_minutes=capacity,
        human_committed_minutes=human_minutes,
        ai_committed_minutes=ai_minutes,
        overload_minutes=overload,
        human=human,
        ai=ai,
        warnings=warnings,
        human_remaining_minutes=human_remaining,
        ai_remaining_minutes=ai_remaining,
        human_recommendations=human_recommendations,
        ai_recommendations=ai_recommendations,
    )


def set_big3(
    db: Session,
    settings: Settings,
    request: DualBig3Request,
    *,
    actor_override: str | None = None,
) -> DualBig3Response:
    tz = ZoneInfo(settings.timezone)
    day = request.target_date or datetime.now(tz).date()
    if len(request.human_item_ids) > settings.big3_limit or len(request.ai_item_ids) > settings.big3_limit:
        raise ValueError(f"Each Big3 list may contain at most {settings.big3_limit} actions")
    ids = request.human_item_ids + request.ai_item_ids
    items = {
        row.id: row
        for row in db.scalars(
            select(ActionItem)
            .where(ActionItem.id.in_(ids) if ids else False)
            .options(selectinload(ActionItem.priority_assessment))
        )
    }
    missing = [item_id for item_id in ids if item_id not in items]
    if missing:
        raise LookupError(f"Action items not found: {', '.join(missing)}")
    terminal = [item.title for item in items.values() if item.state in TERMINAL_STATES]
    if terminal:
        raise ValueError(f"Terminal actions cannot be committed: {', '.join(terminal)}")

    previous = list(
        db.scalars(
            select(DailyCommitment)
            .where(DailyCommitment.commitment_date == day)
            .options(selectinload(DailyCommitment.action_item).selectinload(ActionItem.priority_assessment))
        )
    )
    selected_ids = set(ids)
    for commitment in previous:
        previous_item = commitment.action_item
        if previous_item is not None and previous_item.id not in selected_ids:
            previous_item.attention_state = (
                AttentionState.CLASSIFIED.value
                if previous_item.priority_assessment is not None
                else AttentionState.UNTRIAGED.value
            )
    db.execute(delete(DailyCommitment).where(DailyCommitment.commitment_date == day))
    plan = db.scalar(select(DailyFocusPlan).where(DailyFocusPlan.plan_date == day))
    capacity = request.available_minutes or settings.default_workday_minutes
    if plan is None:
        db.add(DailyFocusPlan(plan_date=day, available_minutes=capacity))
    else:
        plan.available_minutes = capacity
    db.flush()
    actor = actor_override or request.actor
    warnings: list[str] = []
    for owner, item_ids in (("human", request.human_item_ids), ("ai", request.ai_item_ids)):
        for rank, item_id in enumerate(item_ids, 1):
            item = items[item_id]
            estimate = item.estimated_minutes or settings.default_estimated_minutes
            db.add(
                DailyCommitment(
                    commitment_date=day,
                    action_item_id=item.id,
                    owner_type=owner,
                    rank=rank,
                    committed_minutes=estimate,
                    state="committed",
                )
            )
            item.attention_state = AttentionState.COMMITTED.value
            if item.priority_assessment is None:
                suggestion = suggested_assessment(item, settings)
                item.priority_assessment = PriorityAssessment(
                    action_item_id=item.id,
                    importance_score=suggestion.importance_score,
                    urgency_score=suggestion.urgency_score,
                    quadrant=suggestion.quadrant.value,
                    source="rule",
                    confidence=suggestion.confidence,
                    reasons_json=suggestion.reasons_json,
                    user_overridden=False,
                )
            if owner == "ai" and item.executor == ExecutorType.HUMAN.value:
                warnings.append(f"'{item.title}'은 현재 human 실행자로 설정되어 있습니다.")
            if owner == "human" and item.executor == ExecutorType.AI.value:
                warnings.append(f"'{item.title}'은 현재 AI 실행자로 설정되어 있습니다.")
            record_audit(
                db,
                entity_type="action_item",
                entity_id=item.id,
                event_type="attention.committed",
                actor=actor,
                payload={"date": day.isoformat(), "owner_type": owner, "rank": rank},
            )
    db.commit()
    response = get_big3(db, settings, day)
    capacity = response.available_minutes
    human_minutes = response.human_committed_minutes
    overload = max(0, human_minutes - capacity)
    merged_warnings = list(response.warnings) + warnings
    if overload:
        merged_warnings.append(f"선택한 내 Big3가 지정 가용시간보다 {overload}분 초과합니다.")
    return response.model_copy(
        update={"available_minutes": capacity, "overload_minutes": overload, "warnings": merged_warnings}
    )


def _generated_steps(item: ActionItem, settings: Settings, max_steps: int) -> list[MicroStepInput]:
    estimate = item.estimated_minutes or settings.default_estimated_minutes
    if item.item_type == ActionType.EVENT.value or item.work_mode == "meeting":
        titles = [
            "회의 목적과 완료 기준 확인",
            "필요 자료와 질문 준비",
            "회의 진행 및 핵심 결정 기록",
            "후속 Action과 담당자 정리",
            "결과 공유 및 일정 반영",
        ]
    elif item.repository or item.destination == "github":
        titles = [
            "현상과 완료 기준 재현",
            "변경 범위와 위험 분석",
            "핵심 구현",
            "테스트와 회귀 검증",
            "PR 설명과 후속 작업 정리",
        ]
    elif item.work_mode == "call":
        titles = [
            "통화 목적과 질문 정리",
            "필요한 연락 정보 확인",
            "통화 실행 및 메모",
            "합의사항과 후속 일정 등록",
        ]
    else:
        titles = [
            "완료 기준과 산출물 확인",
            "필요 자료·제약 수집",
            "핵심 작업 수행",
            "결과 검증",
            "공유·후속 처리",
        ]
    titles = titles[:max_steps]
    each = max(5, math.ceil(estimate / max(1, len(titles))))
    rows: list[MicroStepInput] = []
    for index, title in enumerate(titles):
        middle = 1 <= index < len(titles) - 1
        executor = ExecutorType.HUMAN
        worker = None
        if middle and item.executor in {ExecutorType.AI.value, ExecutorType.HYBRID.value}:
            executor = ExecutorType.AI
            worker = item.preferred_worker
        rows.append(
            MicroStepInput(
                title=title,
                executor=executor,
                preferred_worker=worker,
                estimated_minutes=each,
            )
        )
    return rows


def decompose_action(
    db: Session,
    settings: Settings,
    item_id: str,
    request: DecomposeActionRequest,
    *,
    actor_override: str | None = None,
) -> list[MicroStepRead]:
    item = db.scalar(
        select(ActionItem).where(ActionItem.id == item_id).options(selectinload(ActionItem.micro_steps))
    )
    if item is None:
        raise LookupError("Action item not found")
    if item.state in TERMINAL_STATES:
        raise ValueError("A terminal action cannot be decomposed")
    if item.micro_steps and not request.replace_existing:
        return [MicroStepRead.model_validate(row) for row in item.micro_steps]
    if request.replace_existing:
        db.execute(delete(MicroStep).where(MicroStep.action_item_id == item.id))
        db.flush()
    steps = request.steps or _generated_steps(item, settings, request.max_steps)
    rows = []
    for position, step in enumerate(steps, 1):
        row = MicroStep(
            action_item_id=item.id,
            position=position,
            title=step.title,
            executor=step.executor.value,
            preferred_worker=step.preferred_worker,
            estimated_minutes=step.estimated_minutes,
            state="pending",
        )
        db.add(row)
        rows.append(row)
    actor = actor_override or request.actor
    record_audit(
        db,
        entity_type="action_item",
        entity_id=item.id,
        event_type="focus.decomposed",
        actor=actor,
        payload={"steps": len(rows), "source": "provided" if request.steps else "rules"},
    )
    db.commit()
    return [MicroStepRead.model_validate(row) for row in rows]


def update_micro_step(
    db: Session,
    step_id: str,
    request: MicroStepUpdateRequest,
    *,
    actor_override: str | None = None,
) -> MicroStepRead:
    row = db.get(MicroStep, step_id)
    if row is None:
        raise LookupError("Micro step not found")
    patch = request.model_dump(exclude_unset=True, exclude={"actor"})
    if "executor" in patch and patch["executor"] is not None:
        patch["executor"] = patch["executor"].value
    for key, value in patch.items():
        setattr(row, key, value)
    record_audit(
        db,
        entity_type="micro_step",
        entity_id=row.id,
        event_type="focus.micro_step_updated",
        actor=actor_override or request.actor,
        payload=patch,
    )
    db.commit()
    db.refresh(row)
    return MicroStepRead.model_validate(row)


def _session_elapsed_seconds(row: FocusSession, now: datetime | None = None) -> int:
    now = now or utcnow()
    endpoint = row.ended_at or now
    elapsed = max(0, int((endpoint - row.started_at).total_seconds()))
    paused = row.paused_seconds
    if row.state == FocusSessionState.PAUSED.value and row.paused_at is not None and row.ended_at is None:
        paused += max(0, int((now - row.paused_at).total_seconds()))
    return max(0, elapsed - paused)


def _traffic(row: FocusSession, settings: Settings, elapsed_seconds: int | None = None) -> TrafficState:
    elapsed = elapsed_seconds if elapsed_seconds is not None else _session_elapsed_seconds(row)
    total = max(60, (row.planned_minutes + row.extension_minutes) * 60)
    if elapsed > total:
        return TrafficState.RED
    if elapsed >= total * settings.focus_warning_percent / 100:
        return TrafficState.YELLOW
    return TrafficState.GREEN


def _focus_read(row: FocusSession, settings: Settings) -> FocusSessionRead:
    elapsed = _session_elapsed_seconds(row)
    total_minutes = row.planned_minutes + row.extension_minutes
    total_seconds = total_minutes * 60
    traffic = _traffic(row, settings, elapsed)
    action = row.action_item
    return FocusSessionRead(
        id=row.id,
        action_item_id=row.action_item_id,
        planned_minutes=row.planned_minutes,
        extension_minutes=row.extension_minutes,
        total_planned_minutes=total_minutes,
        elapsed_seconds=elapsed,
        remaining_seconds=max(0, total_seconds - elapsed),
        progress=round(elapsed / max(1, total_seconds), 4),
        state=row.state,
        traffic_state=traffic.value,
        started_at=row.started_at,
        paused_at=row.paused_at,
        paused_seconds=row.paused_seconds,
        pause_count=row.pause_count,
        ended_at=row.ended_at,
        actual_minutes=row.actual_minutes,
        completion_note=row.completion_note,
        started_by=row.started_by,
        revision=row.revision,
        created_at=row.created_at,
        updated_at=row.updated_at,
        action=_action_summary(action, settings) if action else None,
        micro_steps=[MicroStepRead.model_validate(step) for step in (action.micro_steps if action else [])],
    )


def active_focus(db: Session, settings: Settings) -> FocusSessionRead | None:
    row = db.scalar(
        select(FocusSession)
        .where(FocusSession.state.in_(ACTIVE_FOCUS_STATES))
        .options(
            selectinload(FocusSession.action_item).selectinload(ActionItem.priority_assessment),
            selectinload(FocusSession.action_item).selectinload(ActionItem.micro_steps),
        )
        .order_by(FocusSession.started_at.desc())
    )
    return _focus_read(row, settings) if row else None


def start_focus(
    db: Session,
    settings: Settings,
    request: FocusSessionStartRequest,
    *,
    actor_override: str | None = None,
) -> FocusSessionRead:
    if request.planned_minutes > settings.focus_max_minutes:
        raise ValueError(f"Focus session may not exceed {settings.focus_max_minutes} minutes")
    existing = db.scalar(select(FocusSession).where(FocusSession.state.in_(ACTIVE_FOCUS_STATES)))
    if existing:
        raise ValueError(f"Another focus session is already active: {existing.id}")
    item = db.scalar(
        select(ActionItem)
        .where(ActionItem.id == request.action_item_id)
        .options(selectinload(ActionItem.priority_assessment), selectinload(ActionItem.micro_steps))
    )
    if item is None:
        raise LookupError("Action item not found")
    if item.state in TERMINAL_STATES:
        raise ValueError("A terminal action cannot start a focus session")
    row = FocusSession(
        action_item_id=item.id,
        planned_minutes=request.planned_minutes,
        active_slot="global",
        state=FocusSessionState.RUNNING.value,
        traffic_state=TrafficState.GREEN.value,
        started_by=actor_override or request.actor,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Another focus session is already active") from exc
    item.attention_state = AttentionState.FOCUSING.value
    record_audit(
        db,
        entity_type="focus_session",
        entity_id=row.id,
        event_type="focus.started",
        actor=actor_override or request.actor,
        payload={"action_item_id": item.id, "planned_minutes": request.planned_minutes},
    )
    db.commit()
    db.refresh(row)
    return _focus_read(row, settings)


def update_focus_session(
    db: Session,
    settings: Settings,
    session_id: str,
    request: FocusSessionUpdateRequest,
    *,
    actor_override: str | None = None,
) -> FocusSessionRead:
    row = db.scalar(
        select(FocusSession)
        .where(FocusSession.id == session_id)
        .options(
            selectinload(FocusSession.action_item).selectinload(ActionItem.priority_assessment),
            selectinload(FocusSession.action_item).selectinload(ActionItem.micro_steps),
            selectinload(FocusSession.action_item).selectinload(ActionItem.commitments),
        )
    )
    if row is None:
        raise LookupError("Focus session not found")
    if request.expected_revision is not None and row.revision != request.expected_revision:
        raise RuntimeError(f"revision_conflict:{row.revision}")
    now = utcnow()
    actor = actor_override or request.actor
    action = request.action
    item = row.action_item

    if action == "pause":
        if row.state != FocusSessionState.RUNNING.value:
            raise ValueError("Only a running focus session can be paused")
        row.state = FocusSessionState.PAUSED.value
        row.paused_at = now
        row.pause_count += 1
        item.attention_state = AttentionState.PAUSED.value
    elif action == "resume":
        if row.state != FocusSessionState.PAUSED.value or row.paused_at is None:
            raise ValueError("Only a paused focus session can be resumed")
        row.paused_seconds += max(0, int((now - row.paused_at).total_seconds()))
        row.paused_at = None
        row.state = FocusSessionState.RUNNING.value
        item.attention_state = AttentionState.FOCUSING.value
    elif action == "extend":
        if row.state not in ACTIVE_FOCUS_STATES:
            raise ValueError("Only an active focus session can be extended")
        row.extension_minutes += request.extension_minutes or 10
        if row.planned_minutes + row.extension_minutes > settings.focus_max_minutes:
            raise ValueError(f"Extended focus session may not exceed {settings.focus_max_minutes} minutes")
    elif action in {"complete", "abandon"}:
        if row.state not in ACTIVE_FOCUS_STATES:
            raise ValueError("The focus session has already ended")
        if row.state == FocusSessionState.PAUSED.value and row.paused_at is not None:
            row.paused_seconds += max(0, int((now - row.paused_at).total_seconds()))
            row.paused_at = None
        row.ended_at = now
        row.active_slot = None
        elapsed_seconds = _session_elapsed_seconds(row, now)
        row.actual_minutes = max(1, math.ceil(elapsed_seconds / 60))
        row.traffic_state = _traffic(row, settings, elapsed_seconds).value
        row.completion_note = request.completion_note
        row.state = (
            FocusSessionState.COMPLETED.value if action == "complete" else FocusSessionState.ABANDONED.value
        )
        if action == "complete" and request.mark_action_completed:
            item.state = ItemState.COMPLETED.value
            item.completed_at = now
            item.completion_evidence = request.completion_note or "Focus session completed"
            item.attention_state = AttentionState.COMPLETED.value
            clear_needs_review(item)
        else:
            today = datetime.now(ZoneInfo(settings.timezone)).date()
            committed_today = any(
                commitment.commitment_date == today and commitment.state != "released"
                for commitment in item.commitments
            )
            item.attention_state = (
                AttentionState.COMMITTED.value if committed_today else AttentionState.CLASSIFIED.value
            )
        previous_actual = item.actual_minutes or 0
        item.actual_minutes = previous_actual + row.actual_minutes
        record_metric(
            db,
            "focus_minutes",
            row.actual_minutes,
            "minutes",
            action_item_id=item.id,
            payload={"session_id": row.id, "traffic_state": row.traffic_state},
        )
    else:  # pragma: no cover - Pydantic constrains this
        raise ValueError("Unsupported focus action")

    row.traffic_state = _traffic(row, settings).value
    record_audit(
        db,
        entity_type="focus_session",
        entity_id=row.id,
        event_type=f"focus.{action}",
        actor=actor,
        payload={
            "action_item_id": item.id,
            "extension_minutes": request.extension_minutes,
            "mark_action_completed": request.mark_action_completed,
        },
    )
    db.commit()
    db.refresh(row)
    return _focus_read(row, settings)


def close_day(
    db: Session,
    settings: Settings,
    request: DayCloseRequest,
    *,
    actor_override: str | None = None,
) -> DayCloseResponse:
    tz = ZoneInfo(settings.timezone)
    day = request.target_date or datetime.now(tz).date()
    actor = actor_override or request.actor

    # Preflight every target before changing an item, creating a decision row,
    # or recording an audit event.  The following writes then share this
    # session's one commit, including any flush performed by ensure_followup.
    requested_ids = [decision.action_item_id for decision in request.decisions]
    items_by_id = {
        item.id: item
        for item in db.scalars(select(ActionItem).where(ActionItem.id.in_(requested_ids)))
    }
    for action_item_id in requested_ids:
        if action_item_id not in items_by_id:
            raise LookupError(f"action_item_not_found:{action_item_id}")

    rows: list[CarryOverDecision] = []
    for decision in request.decisions:
        item = items_by_id[decision.action_item_id]
        result: dict = {}
        to_date = decision.to_date
        if decision.decision == "reschedule":
            to_date = to_date or (day + timedelta(days=1))
            item.reschedule_count += 1
            item.attention_state = AttentionState.CARRIED_OVER.value
            if item.due_at is None or _local(item.due_at, tz).date() <= day:
                item.due_at = datetime.combine(to_date, time(hour=9), tzinfo=tz)
            result = {"due_at": item.due_at.isoformat(), "reschedule_count": item.reschedule_count}
        elif decision.decision == "split":
            if not item.micro_steps:
                generated = _generated_steps(item, settings, 5)
                for position, step in enumerate(generated, 1):
                    db.add(
                        MicroStep(
                            action_item_id=item.id,
                            position=position,
                            title=step.title,
                            executor=step.executor.value,
                            preferred_worker=step.preferred_worker,
                            estimated_minutes=step.estimated_minutes,
                        )
                    )
                result = {"micro_steps_created": len(generated)}
            item.attention_state = AttentionState.CLASSIFIED.value
        elif decision.decision == "delegate":
            item.executor = (decision.executor or ExecutorType.AI).value
            item.attention_state = AttentionState.CLASSIFIED.value
            result = {"executor": item.executor}
        elif decision.decision == "deadline_change":
            if to_date is None:
                raise ValueError("deadline_change requires to_date")
            item.deadline_at = datetime.combine(to_date, time(hour=23, minute=59), tzinfo=tz)
            item.attention_state = AttentionState.CLASSIFIED.value
            result = {"deadline_at": item.deadline_at.isoformat()}
        elif decision.decision == "cancel":
            item.state = ItemState.CANCELLED.value
            item.attention_state = AttentionState.SKIPPED.value
            clear_needs_review(item)
            result = {"state": item.state}
        elif decision.decision == "waiting":
            if not decision.waiting_for or not decision.follow_up_at:
                raise ValueError("waiting requires waiting_for and follow_up_at")
            item.state = ItemState.WAITING.value
            item.waiting_for = decision.waiting_for
            item.follow_up_at = decision.follow_up_at
            item.attention_state = AttentionState.CLASSIFIED.value
            ensure_followup(db, item, settings, actor=actor)
            result = {"waiting_for": decision.waiting_for, "follow_up_at": decision.follow_up_at.isoformat()}

        commitment = db.scalar(
            select(DailyCommitment).where(
                DailyCommitment.commitment_date == day,
                DailyCommitment.action_item_id == item.id,
            )
        )
        if commitment:
            commitment.state = "released"
        row = CarryOverDecision(
            action_item_id=item.id,
            from_date=day,
            to_date=to_date,
            decision=decision.decision,
            reason=decision.reason,
            actor=actor,
            result_json=result,
        )
        db.add(row)
        rows.append(row)
        record_audit(
            db,
            entity_type="action_item",
            entity_id=item.id,
            event_type=f"day_close.{decision.decision}",
            actor=actor,
            payload={"from_date": day.isoformat(), "to_date": to_date.isoformat() if to_date else None, **result},
        )
    db.commit()
    return DayCloseResponse(
        date=day,
        processed=len(rows),
        decisions=[CarryOverDecisionRead.model_validate(row) for row in rows],
        warnings=[],
    )


def focus_weekly_report(
    db: Session,
    settings: Settings,
    *,
    end_date: date | None = None,
) -> FocusWeeklyReport:
    tz = ZoneInfo(settings.timezone)
    end = end_date or datetime.now(tz).date()
    start = end - timedelta(days=settings.focus_weekly_window_days - 1)
    start_dt = datetime.combine(start, time.min, tzinfo=tz)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    sessions = list(
        db.scalars(
            select(FocusSession)
            .where(FocusSession.started_at >= start_dt, FocusSession.started_at < end_dt)
            .options(
                selectinload(FocusSession.action_item).selectinload(ActionItem.priority_assessment)
            )
        )
    )
    commitments = list(
        db.scalars(
            select(DailyCommitment)
            .where(DailyCommitment.commitment_date >= start, DailyCommitment.commitment_date <= end)
            .options(selectinload(DailyCommitment.action_item))
        )
    )
    focus_minutes = sum(row.actual_minutes or math.ceil(_session_elapsed_seconds(row) / 60) for row in sessions)
    completed_sessions = sum(row.state == FocusSessionState.COMPLETED.value for row in sessions)
    traffic = {key: 0 for key in ("green", "yellow", "red")}
    quadrant_minutes = {key: 0 for key in ("q1", "q2", "q3", "q4")}
    accuracy_values: list[float] = []
    for session in sessions:
        state = session.traffic_state or _traffic(session, settings).value
        traffic[state] = traffic.get(state, 0) + 1
        minutes = session.actual_minutes or math.ceil(_session_elapsed_seconds(session) / 60)
        assessment = session.action_item.priority_assessment if session.action_item else None
        if assessment:
            quadrant_minutes[assessment.quadrant] = quadrant_minutes.get(assessment.quadrant, 0) + minutes
        item = session.action_item
        if item and item.estimated_minutes and session.actual_minutes:
            denominator = max(item.estimated_minutes, session.actual_minutes)
            accuracy_values.append(max(0.0, 1 - abs(item.estimated_minutes - session.actual_minutes) / denominator))
    human = [row for row in commitments if row.owner_type == "human"]
    ai = [row for row in commitments if row.owner_type == "ai"]
    complete_states = {ItemState.COMPLETED.value}
    human_completed = sum(row.action_item and row.action_item.state in complete_states for row in human)
    ai_completed = sum(row.action_item and row.action_item.state in complete_states for row in ai)
    total_commitments = len(human) + len(ai)
    total_completed = human_completed + ai_completed
    carryover_count = db.scalar(
        select(func.count(CarryOverDecision.id)).where(
            CarryOverDecision.created_at >= start_dt,
            CarryOverDecision.created_at < end_dt,
        )
    ) or 0
    q3_delegated = db.scalar(
        select(func.count(ActionItem.id))
        .join(PriorityAssessment, PriorityAssessment.action_item_id == ActionItem.id)
        .where(
            PriorityAssessment.quadrant == Quadrant.Q3.value,
            PriorityAssessment.updated_at >= start_dt,
            PriorityAssessment.updated_at < end_dt,
            ActionItem.executor.in_([ExecutorType.AI.value, ExecutorType.HYBRID.value, ExecutorType.EXTERNAL.value]),
        )
    ) or 0
    recommendations: list[str] = []
    if quadrant_minutes["q2"] < focus_minutes * 0.25 and focus_minutes:
        recommendations.append("Q2 전략 업무 집중시간이 25% 미만입니다. 다음 주 Big3에 Q2를 최소 1건 포함하세요.")
    if carryover_count >= 3:
        recommendations.append("반복 이월이 많습니다. 작업 분할 또는 AI 위임을 우선 검토하세요.")
    if traffic["red"] > traffic["green"] and sessions:
        recommendations.append("예정시간을 초과한 세션이 많습니다. 예상시간을 재학습하거나 세션을 더 작게 나누세요.")
    if total_commitments and total_completed / total_commitments < 0.6:
        recommendations.append("Big3 완료율이 60% 미만입니다. 하루 약속 수와 가용시간을 다시 맞추세요.")
    if not recommendations:
        recommendations.append("현재 Focus Loop를 유지하고 실제시간 데이터를 다음 계획에 반영하세요.")
    rate = round(total_completed / total_commitments * 100, 1) if total_commitments else 0.0
    accuracy = round(sum(accuracy_values) / len(accuracy_values) * 100, 1) if accuracy_values else None
    summary = (
        f"{start.isoformat()}~{end.isoformat()}: 집중 {focus_minutes}분, "
        f"Big3 완료율 {rate}%, 이월 {carryover_count}건"
    )
    return FocusWeeklyReport(
        period_start=start,
        period_end=end,
        generated_at=utcnow(),
        total_sessions=len(sessions),
        completed_sessions=completed_sessions,
        focus_minutes=focus_minutes,
        human_big3_total=len(human),
        human_big3_completed=human_completed,
        ai_big3_total=len(ai),
        ai_big3_completed=ai_completed,
        big3_completion_rate=rate,
        quadrant_focus_minutes=quadrant_minutes,
        traffic_distribution=traffic,
        carry_over_count=int(carryover_count),
        average_estimate_accuracy=accuracy,
        q2_investment_minutes=quadrant_minutes["q2"],
        q3_delegated_count=int(q3_delegated),
        recommendations=recommendations,
        summary=summary,
    )


def dashboard_focus_summary(db: Session, settings: Settings) -> FocusDashboardSummary:
    matrix_response = matrix(db, settings, limit_per_quadrant=0)
    big3 = get_big3(db, settings)
    return FocusDashboardSummary(
        matrix_counts=matrix_response.counts,
        human_big3=big3.human,
        ai_big3=big3.ai,
        active_focus=active_focus(db, settings),
        untriaged_count=matrix_response.untriaged_count,
        human_big3_recommendations=big3.human_recommendations,
        ai_big3_recommendations=big3.ai_recommendations,
    )
