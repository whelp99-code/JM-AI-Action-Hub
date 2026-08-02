from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..focus_schemas import (
    ClassifyActionRequest,
    DayCloseRequest,
    DayCloseResponse,
    DecomposeActionRequest,
    DualBig3Request,
    DualBig3Response,
    FocusActionSummary,
    FocusSessionRead,
    FocusSessionStartRequest,
    FocusSessionUpdateRequest,
    FocusWeeklyReport,
    MatrixResponse,
    MicroStepRead,
    MicroStepUpdateRequest,
    TriageResponse,
)
from ..security import require_api_key, require_mobile_scope
from ..services.focus import (
    active_focus,
    classify_action,
    close_day,
    decompose_action,
    focus_weekly_report,
    get_big3,
    list_triage,
    matrix,
    set_big3,
    start_focus,
    update_focus_session,
    update_micro_step,
)
from ..services.mobile_auth import MobilePrincipal
from .dependencies import get_db

focus_router = APIRouter(
    prefix="/api/v1/focus",
    tags=["decision-focus"],
    dependencies=[Depends(require_api_key)],
)
mobile_focus_router = APIRouter(prefix="/api/v1/mobile", tags=["mobile-focus"])


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RuntimeError) and str(exc).startswith("revision_conflict:"):
        current = int(str(exc).split(":", 1)[1])
        return HTTPException(
            status_code=409,
            detail={"code": "revision_conflict", "current_revision": current},
        )
    return HTTPException(status_code=422, detail=str(exc))


@focus_router.get("/triage", response_model=TriageResponse, operation_id="listFocusTriage")
def admin_triage(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> TriageResponse:
    return list_triage(db, request.app.state.settings, limit=limit)


@focus_router.post(
    "/actions/{item_id}/classify",
    response_model=FocusActionSummary,
    operation_id="classifyFocusAction",
)
def admin_classify(
    item_id: str,
    payload: ClassifyActionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> FocusActionSummary:
    try:
        return classify_action(db, request.app.state.settings, item_id, payload)
    except (LookupError, ValueError, RuntimeError) as exc:
        raise _translate_error(exc) from exc


@focus_router.get("/matrix", response_model=MatrixResponse, operation_id="getFocusMatrix")
def admin_matrix(
    request: Request,
    limit_per_quadrant: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> MatrixResponse:
    return matrix(db, request.app.state.settings, limit_per_quadrant=limit_per_quadrant)


@focus_router.get("/commitments", response_model=DualBig3Response, operation_id="getFocusCommitments")
def admin_commitments(
    request: Request,
    target_date: date | None = None,
    db: Session = Depends(get_db),
) -> DualBig3Response:
    return get_big3(db, request.app.state.settings, target_date)


@focus_router.post("/commitments", response_model=DualBig3Response, operation_id="setFocusCommitments")
def admin_set_commitments(
    payload: DualBig3Request,
    request: Request,
    db: Session = Depends(get_db),
) -> DualBig3Response:
    try:
        return set_big3(db, request.app.state.settings, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@focus_router.post(
    "/actions/{item_id}/decompose",
    response_model=list[MicroStepRead],
    operation_id="decomposeFocusAction",
)
def admin_decompose(
    item_id: str,
    payload: DecomposeActionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> list[MicroStepRead]:
    try:
        return decompose_action(db, request.app.state.settings, item_id, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@focus_router.patch(
    "/microsteps/{step_id}",
    response_model=MicroStepRead,
    operation_id="updateFocusMicroStep",
)
def admin_update_microstep(
    step_id: str,
    payload: MicroStepUpdateRequest,
    db: Session = Depends(get_db),
) -> MicroStepRead:
    try:
        return update_micro_step(db, step_id, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@focus_router.get("/sessions/active", response_model=FocusSessionRead | None, operation_id="getActiveFocusSession")
def admin_active_focus(request: Request, db: Session = Depends(get_db)) -> FocusSessionRead | None:
    return active_focus(db, request.app.state.settings)


@focus_router.post("/sessions", response_model=FocusSessionRead, status_code=201, operation_id="startFocusSession")
def admin_start_focus(
    payload: FocusSessionStartRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> FocusSessionRead:
    try:
        return start_focus(db, request.app.state.settings, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@focus_router.patch(
    "/sessions/{session_id}",
    response_model=FocusSessionRead,
    operation_id="updateFocusSession",
)
def admin_update_focus(
    session_id: str,
    payload: FocusSessionUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> FocusSessionRead:
    try:
        return update_focus_session(db, request.app.state.settings, session_id, payload)
    except (LookupError, ValueError, RuntimeError) as exc:
        raise _translate_error(exc) from exc


@focus_router.post("/day-close", response_model=DayCloseResponse, operation_id="closeFocusDay")
def admin_close_day(
    payload: DayCloseRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> DayCloseResponse:
    try:
        return close_day(db, request.app.state.settings, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@focus_router.get(
    "/reports/weekly",
    response_model=FocusWeeklyReport,
    operation_id="getFocusWeeklyReport",
)
def admin_focus_weekly(
    request: Request,
    end_date: date | None = None,
    db: Session = Depends(get_db),
) -> FocusWeeklyReport:
    return focus_weekly_report(db, request.app.state.settings, end_date=end_date)


@mobile_focus_router.get(
    "/triage",
    response_model=TriageResponse,
    operation_id="listMobileFocusTriage",
)
def mobile_triage(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    _principal: MobilePrincipal = Depends(require_mobile_scope("plans:read")),
    db: Session = Depends(get_db),
) -> TriageResponse:
    return list_triage(db, request.app.state.settings, limit=limit)


@mobile_focus_router.post(
    "/actions/{item_id}/classify",
    response_model=FocusActionSummary,
    operation_id="classifyMobileFocusAction",
)
def mobile_classify(
    item_id: str,
    payload: ClassifyActionRequest,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:edit")),
    db: Session = Depends(get_db),
) -> FocusActionSummary:
    try:
        return classify_action(
            db,
            request.app.state.settings,
            item_id,
            payload,
            actor_override=f"mobile:{principal.device_id}",
        )
    except (LookupError, ValueError, RuntimeError) as exc:
        raise _translate_error(exc) from exc


@mobile_focus_router.get(
    "/matrix",
    response_model=MatrixResponse,
    operation_id="getMobileFocusMatrix",
)
def mobile_matrix(
    request: Request,
    limit_per_quadrant: int = Query(default=100, ge=1, le=500),
    _principal: MobilePrincipal = Depends(require_mobile_scope("plans:read")),
    db: Session = Depends(get_db),
) -> MatrixResponse:
    return matrix(db, request.app.state.settings, limit_per_quadrant=limit_per_quadrant)


@mobile_focus_router.get(
    "/commitments/today",
    response_model=DualBig3Response,
    operation_id="getMobileBig3",
)
def mobile_big3(
    request: Request,
    target_date: date | None = None,
    _principal: MobilePrincipal = Depends(require_mobile_scope("plans:read")),
    db: Session = Depends(get_db),
) -> DualBig3Response:
    return get_big3(db, request.app.state.settings, target_date)


@mobile_focus_router.post(
    "/commitments",
    response_model=DualBig3Response,
    operation_id="setMobileBig3",
)
def mobile_set_big3(
    payload: DualBig3Request,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:edit")),
    db: Session = Depends(get_db),
) -> DualBig3Response:
    try:
        return set_big3(
            db,
            request.app.state.settings,
            payload,
            actor_override=f"mobile:{principal.device_id}",
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@mobile_focus_router.post(
    "/actions/{item_id}/decompose",
    response_model=list[MicroStepRead],
    operation_id="decomposeMobileFocusAction",
)
def mobile_decompose(
    item_id: str,
    payload: DecomposeActionRequest,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:edit")),
    db: Session = Depends(get_db),
) -> list[MicroStepRead]:
    try:
        return decompose_action(
            db,
            request.app.state.settings,
            item_id,
            payload,
            actor_override=f"mobile:{principal.device_id}",
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@mobile_focus_router.patch(
    "/microsteps/{step_id}",
    response_model=MicroStepRead,
    operation_id="updateMobileMicroStep",
)
def mobile_update_microstep(
    step_id: str,
    payload: MicroStepUpdateRequest,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:edit")),
    db: Session = Depends(get_db),
) -> MicroStepRead:
    try:
        return update_micro_step(
            db, step_id, payload, actor_override=f"mobile:{principal.device_id}"
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@mobile_focus_router.get(
    "/focus-sessions/active",
    response_model=FocusSessionRead | None,
    operation_id="getMobileActiveFocusSession",
)
def mobile_active_focus(
    request: Request,
    _principal: MobilePrincipal = Depends(require_mobile_scope("plans:read")),
    db: Session = Depends(get_db),
) -> FocusSessionRead | None:
    return active_focus(db, request.app.state.settings)


@mobile_focus_router.post(
    "/focus-sessions",
    response_model=FocusSessionRead,
    status_code=201,
    operation_id="startMobileFocusSession",
)
def mobile_start_focus(
    payload: FocusSessionStartRequest,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:edit")),
    db: Session = Depends(get_db),
) -> FocusSessionRead:
    try:
        return start_focus(
            db,
            request.app.state.settings,
            payload,
            actor_override=f"mobile:{principal.device_id}",
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@mobile_focus_router.patch(
    "/focus-sessions/{session_id}",
    response_model=FocusSessionRead,
    operation_id="updateMobileFocusSession",
)
def mobile_update_focus(
    session_id: str,
    payload: FocusSessionUpdateRequest,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:edit")),
    db: Session = Depends(get_db),
) -> FocusSessionRead:
    try:
        return update_focus_session(
            db,
            request.app.state.settings,
            session_id,
            payload,
            actor_override=f"mobile:{principal.device_id}",
        )
    except (LookupError, ValueError, RuntimeError) as exc:
        raise _translate_error(exc) from exc


@mobile_focus_router.post(
    "/day-close",
    response_model=DayCloseResponse,
    operation_id="closeMobileFocusDay",
)
def mobile_close_day(
    payload: DayCloseRequest,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:edit")),
    db: Session = Depends(get_db),
) -> DayCloseResponse:
    try:
        return close_day(
            db,
            request.app.state.settings,
            payload,
            actor_override=f"mobile:{principal.device_id}",
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@mobile_focus_router.get(
    "/reports/focus-weekly",
    response_model=FocusWeeklyReport,
    operation_id="getMobileFocusWeeklyReport",
)
def mobile_focus_weekly(
    request: Request,
    end_date: date | None = None,
    _principal: MobilePrincipal = Depends(require_mobile_scope("activity:read")),
    db: Session = Depends(get_db),
) -> FocusWeeklyReport:
    return focus_weekly_report(db, request.app.state.settings, end_date=end_date)
