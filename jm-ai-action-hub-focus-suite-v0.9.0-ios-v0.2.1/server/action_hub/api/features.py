from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from ..models import FollowUp, MeetingIntake, PersonalRule
from ..schemas import (
    DecisionPlan,
    DispatchWorkerRequest,
    FollowUpCreateRequest,
    FollowUpRead,
    FollowUpResolveRequest,
    MeetingIntakeRead,
    PersonalRuleCreateRequest,
    PersonalRuleRead,
    PersonalRuleUpdateRequest,
    PlanningRequest,
    WeeklyReport,
    WorkerExecutionRead,
    WorkerRunSummary,
)
from ..security import require_api_key
from ..services.decision import build_decision_plan
from ..services.followups import create_followup, process_due_followups, resolve_followup
from ..services.meetings import reprocess_meeting
from ..services.metrics import build_weekly_report
from ..services.rules import create_rule, suggest_rules, update_rule
from ..services.workers import WorkerRegistry, queue_worker_dispatch
from .dependencies import get_db

feature_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@feature_router.post("/items/{item_id}/dispatch", response_model=WorkerExecutionRead, tags=["workers"])
def dispatch_item(
    item_id: str,
    payload: DispatchWorkerRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        return queue_worker_dispatch(
            db,
            item_id=item_id,
            worker=payload.worker,
            settings=request.app.state.settings,
            actor=payload.actor,
            force=payload.force,
            drain_inline=payload.drain_inline,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@feature_router.get("/workers/status", tags=["workers"])
def worker_status(request: Request) -> list[dict]:
    return WorkerRegistry(request.app.state.settings).statuses()


@feature_router.post("/items/{item_id}/followups", response_model=FollowUpRead, tags=["follow-up"])
def add_followup(
    item_id: str,
    payload: FollowUpCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> FollowUp:
    try:
        return create_followup(
            db,
            item_id=item_id,
            waiting_for=payload.waiting_for,
            follow_up_at=payload.follow_up_at,
            settings=request.app.state.settings,
            channel=payload.channel,
            expected_by=payload.expected_by,
            template=payload.template,
            actor=payload.actor,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@feature_router.get("/followups/due", response_model=list[FollowUpRead], tags=["follow-up"])
def due_followups(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[FollowUp]:
    from ..models import utcnow

    return list(
        db.scalars(
            select(FollowUp)
            .where(
                FollowUp.state.in_(["waiting", "follow_up_due", "followed_up"]),
                FollowUp.follow_up_at <= utcnow(),
            )
            .options(selectinload(FollowUp.action_item))
            .order_by(FollowUp.follow_up_at)
            .limit(limit)
        )
    )


@feature_router.post("/followups/process-due", response_model=WorkerRunSummary, tags=["follow-up"])
def mark_due_followups(request: Request, db: Session = Depends(get_db)) -> WorkerRunSummary:
    rows = process_due_followups(db, request.app.state.settings)
    return WorkerRunSummary(followups_due=len(rows))


@feature_router.post("/followups/{followup_id}/resolve", response_model=FollowUpRead, tags=["follow-up"])
def update_followup_state(
    followup_id: str,
    payload: FollowUpResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> FollowUp:
    try:
        return resolve_followup(
            db,
            followup_id=followup_id,
            state=payload.state,
            settings=request.app.state.settings,
            actor=payload.actor,
            note=payload.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@feature_router.post("/planning/decision", response_model=DecisionPlan, tags=["planning"])
def decision_plan(
    payload: PlanningRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DecisionPlan:
    return build_decision_plan(
        db,
        request.app.state.settings,
        target_date=payload.target_date,
        available_minutes=payload.available_minutes,
        max_items=payload.max_items,
        include_ai=payload.include_ai,
    )


@feature_router.get("/meetings", response_model=list[MeetingIntakeRead], tags=["meetings"])
def list_meetings(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[MeetingIntake]:
    return list(db.scalars(select(MeetingIntake).order_by(desc(MeetingIntake.received_at)).limit(limit)))


@feature_router.post("/meetings/{intake_id}/reprocess", response_model=MeetingIntakeRead, tags=["meetings"])
def retry_meeting(
    intake_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> MeetingIntake:
    try:
        return reprocess_meeting(db, intake_id, request.app.state.settings)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@feature_router.get("/rules", response_model=list[PersonalRuleRead], tags=["personal-rules"])
def list_rules(db: Session = Depends(get_db)) -> list[PersonalRule]:
    return list(db.scalars(select(PersonalRule).order_by(desc(PersonalRule.created_at))))


@feature_router.post("/rules", response_model=PersonalRuleRead, tags=["personal-rules"])
def add_rule(payload: PersonalRuleCreateRequest, db: Session = Depends(get_db)) -> PersonalRule:
    try:
        return create_rule(
            db,
            name=payload.name,
            condition=payload.condition,
            action=payload.action,
            status=payload.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@feature_router.patch("/rules/{rule_id}", response_model=PersonalRuleRead, tags=["personal-rules"])
def patch_rule(
    rule_id: str,
    payload: PersonalRuleUpdateRequest,
    db: Session = Depends(get_db),
) -> PersonalRule:
    try:
        return update_rule(db, rule_id, payload.model_dump(exclude_unset=True))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@feature_router.post("/rules/suggest", response_model=list[PersonalRuleRead], tags=["personal-rules"])
def propose_rules(request: Request, db: Session = Depends(get_db)) -> list[PersonalRule]:
    return suggest_rules(db, request.app.state.settings.personal_rule_min_observations)


@feature_router.get("/reports/weekly", response_model=WeeklyReport, tags=["reports"])
def weekly_report(
    end_date: date | None = None,
    db: Session = Depends(get_db),
) -> WeeklyReport:
    return build_weekly_report(db, end_date)
