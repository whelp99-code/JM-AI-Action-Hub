from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import ActionItem, ItemState, MetricEvent, WorkerExecution, utcnow
from ..schemas import WeeklyMetric, WeeklyReport


def record_metric(
    db: Session,
    name: str,
    value: float = 1,
    unit: str = "count",
    *,
    action_item_id: str | None = None,
    payload: dict | None = None,
) -> MetricEvent:
    event = MetricEvent(
        metric_name=name,
        value=value,
        unit=unit,
        action_item_id=action_item_id,
        payload_json=payload or {},
    )
    db.add(event)
    return event


def _period_bounds(end_date: date | None = None) -> tuple[date, date, datetime, datetime]:
    end = end_date or datetime.now(UTC).date()
    start = end - timedelta(days=6)
    start_dt = datetime.combine(start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    return start, end, start_dt, end_dt


def build_weekly_report(db: Session, end_date: date | None = None) -> WeeklyReport:
    start, end, start_dt, end_dt = _period_bounds(end_date)
    metric_rows = list(
        db.execute(
            select(MetricEvent.metric_name, MetricEvent.unit, func.sum(MetricEvent.value))
            .where(MetricEvent.occurred_at >= start_dt, MetricEvent.occurred_at < end_dt)
            .group_by(MetricEvent.metric_name, MetricEvent.unit)
        )
    )
    metrics = [WeeklyMetric(name=name, unit=unit, value=float(value or 0)) for name, unit, value in metric_rows]
    completed = db.scalar(
        select(func.count(ActionItem.id)).where(
            ActionItem.completed_at >= start_dt,
            ActionItem.completed_at < end_dt,
        )
    ) or 0
    registered = db.scalar(
        select(func.count(ActionItem.id)).where(
            ActionItem.registered_at >= start_dt,
            ActionItem.registered_at < end_dt,
        )
    ) or 0
    delayed = db.scalar(
        select(func.count(ActionItem.id)).where(
            ActionItem.due_at < end_dt,
            ActionItem.state.notin_([
                ItemState.COMPLETED.value,
                ItemState.REJECTED.value,
                ItemState.SKIPPED_DUPLICATE.value,
                ItemState.CANCELLED.value,
            ]),
        )
    ) or 0
    waiting = db.scalar(
        select(func.count(ActionItem.id)).where(ActionItem.state == ItemState.WAITING.value)
    ) or 0
    ai_dispatches = db.scalar(
        select(func.count(WorkerExecution.id)).where(
            WorkerExecution.created_at >= start_dt,
            WorkerExecution.created_at < end_dt,
        )
    ) or 0
    ai_successes = db.scalar(
        select(func.count(WorkerExecution.id)).where(
            WorkerExecution.completed_at >= start_dt,
            WorkerExecution.completed_at < end_dt,
            WorkerExecution.state == "completed",
        )
    ) or 0
    minutes_saved = db.scalar(
        select(func.sum(MetricEvent.value)).where(
            MetricEvent.metric_name == "estimated_minutes_saved",
            MetricEvent.occurred_at >= start_dt,
            MetricEvent.occurred_at < end_dt,
        )
    ) or 0

    recommendations: list[str] = []
    if delayed:
        recommendations.append(f"지연 업무 {delayed}건을 분할하거나 예상시간을 다시 산정하세요.")
    if waiting:
        recommendations.append(f"응답 대기 {waiting}건의 후속 확인 시각을 점검하세요.")
    if ai_dispatches and ai_successes / ai_dispatches < 0.6:
        recommendations.append("AI Worker 성공률이 낮습니다. 작업 범위와 완료 기준을 더 구체화하세요.")
    if not recommendations:
        recommendations.append("현재 흐름을 유지하고 반복 수정 패턴을 개인 규칙으로 승인하세요.")
    summary = (
        f"{start.isoformat()}~{end.isoformat()}: 등록 {registered}건, 완료 {completed}건, "
        f"AI 위임 {ai_dispatches}건, 추정 절감 {round(float(minutes_saved))}분"
    )
    return WeeklyReport(
        period_start=start,
        period_end=end,
        generated_at=utcnow(),
        metrics=metrics,
        completed_actions=int(completed),
        registered_actions=int(registered),
        delayed_actions=int(delayed),
        waiting_actions=int(waiting),
        ai_dispatches=int(ai_dispatches),
        ai_successes=int(ai_successes),
        estimated_minutes_saved=round(float(minutes_saved)),
        recommendations=recommendations,
        summary=summary,
    )
