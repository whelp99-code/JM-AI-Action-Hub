from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import ItemState, MobileDevice, PushNotification
from ..schemas import (
    ActionItemUpdate,
    ExecutionSummary,
    MobileActionItemUpdate,
    MobileActivityItem,
    MobileApprovalRequest,
    MobileCapabilities,
    MobileCaptureBatchRequest,
    MobileCaptureBatchResponse,
    MobileChangesResponse,
    MobileDashboard,
    MobileDeviceRead,
    MobileDeviceUpdateRequest,
    MobileExecuteRequest,
    MobileNotificationPreferencesRequest,
    MobilePairingClaimRequest,
    MobilePairingCreateRequest,
    MobilePairingCreateResponse,
    MobilePushTestRequest,
    MobilePushTokenRequest,
    MobileRefreshRequest,
    MobileRejectRequest,
    MobileTokenResponse,
    PlanRead,
)
from ..security import require_api_key, require_mobile_scope
from ..services.executor import approve_plan, execute_plan, reject_items, update_item
from ..services.mobile import (
    build_mobile_dashboard,
    capabilities,
    list_review_plans,
    mobile_changes,
    process_capture_batch,
    recent_activity,
    register_push_token,
    update_notification_preferences,
)
from ..services.mobile_auth import (
    MobileAuthError,
    MobilePrincipal,
    claim_pairing,
    create_pairing,
    get_device,
    revoke_device,
    rotate_refresh_token,
)
from ..services.planner import get_plan
from ..services.push import queue_push
from .dependencies import get_db

mobile_public_router = APIRouter(prefix="/api/v1/mobile", tags=["mobile"])
mobile_admin_router = APIRouter(
    prefix="/api/v1/mobile",
    tags=["mobile-admin"],
    dependencies=[Depends(require_api_key)],
)
mobile_router = APIRouter(prefix="/api/v1/mobile", tags=["mobile"])


def _auth_error(exc: MobileAuthError) -> HTTPException:
    mapping = {
        "pairing_not_found": status.HTTP_404_NOT_FOUND,
        "pairing_expired": status.HTTP_410_GONE,
        "pairing_locked": status.HTTP_423_LOCKED,
        "pairing_unavailable": status.HTTP_409_CONFLICT,
        "mobile_disabled": status.HTTP_503_SERVICE_UNAVAILABLE,
        "mobile_auth_not_configured": status.HTTP_503_SERVICE_UNAVAILABLE,
        "mobile_secret_reuses_admin_key": status.HTTP_503_SERVICE_UNAVAILABLE,
    }
    return HTTPException(status_code=mapping.get(exc.code, status.HTTP_401_UNAUTHORIZED), detail=str(exc))


def _current_device(db: Session, principal: MobilePrincipal) -> MobileDevice:
    device = db.get(MobileDevice, principal.device_id)
    if not device or device.status != "active":
        raise HTTPException(status_code=401, detail="Mobile device is unavailable")
    return device


def _check_plan_revision(plan, expected: int | None) -> None:
    if expected is not None and plan.revision != expected:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "revision_conflict",
                "entity": "plan",
                "expected_revision": expected,
                "current_revision": plan.revision,
            },
        )


def _execution_summary(plan) -> ExecutionSummary:
    action_completed = sum(item.state == ItemState.COMPLETED.value for item in plan.items)
    registered_states = {
        ItemState.REGISTERED.value,
        ItemState.WAITING.value,
        ItemState.DISPATCHED.value,
        ItemState.RUNNING.value,
        ItemState.NEEDS_INPUT.value,
        ItemState.HUMAN_REVIEW.value,
    }
    registered = sum(item.state in registered_states for item in plan.items)
    queued = sum(item.state in {ItemState.QUEUED.value, ItemState.EXECUTING.value} for item in plan.items)
    failed = sum(item.state == ItemState.FAILED.value for item in plan.items)
    duplicate = sum(item.state == ItemState.SKIPPED_DUPLICATE.value for item in plan.items)
    rejected = sum(item.state == ItemState.REJECTED.value for item in plan.items)
    pending = len(plan.items) - action_completed - registered - queued - failed - duplicate - rejected
    return ExecutionSummary(
        plan_id=plan.id,
        plan_status=plan.status,
        completed=registered + action_completed,
        registered=registered,
        action_completed=action_completed,
        queued=queued,
        failed=failed,
        skipped_duplicate=duplicate,
        pending=max(0, pending),
        items=plan.items,
    )


@mobile_public_router.get(
    "/capabilities",
    response_model=MobileCapabilities,
    operation_id="mobileCapabilities",
)
def mobile_capabilities(request: Request) -> MobileCapabilities:
    return capabilities(request.app.state.settings)


@mobile_admin_router.post(
    "/pairings",
    response_model=MobilePairingCreateResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createMobilePairing",
)
def create_mobile_pairing(
    payload: MobilePairingCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobilePairingCreateResponse:
    settings = request.app.state.settings
    if settings.app_env == "production":
        # Never derive a production QR target from the request Host header. A
        # reverse proxy or forwarded-host misconfiguration could otherwise put
        # an attacker-controlled server address into a legitimate pairing QR.
        base_url = payload.public_base_url or settings.mobile_public_base_url
        if not base_url:
            raise HTTPException(
                status_code=422,
                detail="Production mobile pairing requires an explicit HTTPS public base URL",
            )
    else:
        base_url = payload.public_base_url or settings.mobile_public_base_url or str(request.base_url)
    try:
        return create_pairing(
            db,
            settings,
            scopes=payload.scopes,
            created_by=payload.created_by,
            public_base_url=base_url,
        )
    except MobileAuthError as exc:
        raise _auth_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@mobile_public_router.post(
    "/pairings/claim",
    response_model=MobileTokenResponse,
    operation_id="claimMobilePairing",
)
def claim_mobile_pairing(
    payload: MobilePairingClaimRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileTokenResponse:
    try:
        return claim_pairing(db, request.app.state.settings, payload)
    except MobileAuthError as exc:
        raise _auth_error(exc) from exc


@mobile_public_router.post(
    "/token/refresh",
    response_model=MobileTokenResponse,
    operation_id="refreshMobileToken",
)
def refresh_mobile_token(
    payload: MobileRefreshRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> MobileTokenResponse:
    try:
        return rotate_refresh_token(db, request.app.state.settings, payload)
    except MobileAuthError as exc:
        raise _auth_error(exc) from exc


@mobile_admin_router.get(
    "/admin/devices",
    response_model=list[MobileDeviceRead],
    operation_id="listMobileDevices",
)
def list_mobile_devices(db: Session = Depends(get_db)) -> list[MobileDeviceRead]:
    rows = list(db.scalars(select(MobileDevice).order_by(desc(MobileDevice.created_at))))
    return [MobileDeviceRead.from_device(row) for row in rows]


@mobile_admin_router.delete(
    "/admin/devices/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revokeMobileDevice",
)
def revoke_mobile_device(device_id: str, db: Session = Depends(get_db)) -> None:
    try:
        device = get_device(db, device_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    revoke_device(db, device)


@mobile_router.get(
    "/dashboard",
    response_model=MobileDashboard,
    operation_id="getMobileDashboard",
)
def mobile_dashboard(
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("brief:read")),
    db: Session = Depends(get_db),
) -> MobileDashboard:
    return build_mobile_dashboard(
        db,
        request.app.state.settings,
        include_activity=principal.has_scope("activity:read"),
    )


@mobile_router.get(
    "/changes",
    response_model=MobileChangesResponse,
    operation_id="getMobileChanges",
)
def get_mobile_changes(
    request: Request,
    cursor: str | None = Query(default=None, max_length=2048),
    limit: int | None = Query(default=None, ge=1, le=500),
    _principal: MobilePrincipal = Depends(require_mobile_scope("activity:read")),
    db: Session = Depends(get_db),
) -> MobileChangesResponse:
    try:
        return mobile_changes(db, request.app.state.settings, cursor=cursor, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@mobile_router.get(
    "/activity",
    response_model=list[MobileActivityItem],
    operation_id="getMobileActivity",
)
def get_mobile_activity(
    limit: int = Query(default=50, ge=1, le=200),
    _principal: MobilePrincipal = Depends(require_mobile_scope("activity:read")),
    db: Session = Depends(get_db),
) -> list[MobileActivityItem]:
    return recent_activity(db, limit)


@mobile_router.post(
    "/captures/batch",
    response_model=MobileCaptureBatchResponse,
    operation_id="uploadMobileCaptures",
)
def upload_mobile_captures(
    payload: MobileCaptureBatchRequest,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("capture:write")),
    db: Session = Depends(get_db),
) -> MobileCaptureBatchResponse:
    device = _current_device(db, principal)
    try:
        return process_capture_batch(db, request.app.state.settings, device, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@mobile_router.get(
    "/review",
    response_model=list[PlanRead],
    operation_id="listMobileReviewPlans",
)
def review_queue(
    limit: int = Query(default=50, ge=1, le=100),
    _principal: MobilePrincipal = Depends(require_mobile_scope("plans:read")),
    db: Session = Depends(get_db),
):
    return list_review_plans(db, limit)


@mobile_router.get(
    "/plans/{plan_id}",
    response_model=PlanRead,
    operation_id="getMobilePlan",
)
def get_mobile_plan(
    plan_id: str,
    _principal: MobilePrincipal = Depends(require_mobile_scope("plans:read")),
    db: Session = Depends(get_db),
):
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@mobile_router.patch(
    "/plans/{plan_id}/items/{item_id}",
    response_model=PlanRead,
    operation_id="updateMobileActionItem",
)
def update_mobile_item(
    plan_id: str,
    item_id: str,
    payload: MobileActionItemUpdate,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:edit")),
    db: Session = Depends(get_db),
):
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    item = next((row for row in plan.items if row.id == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if item.revision != payload.expected_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "revision_conflict",
                "entity": "action_item",
                "expected_revision": payload.expected_revision,
                "current_revision": item.revision,
            },
        )
    patch = ActionItemUpdate.model_validate(payload.model_dump(exclude={"expected_revision"}, exclude_unset=True))
    try:
        return update_item(db, plan_id, item_id, patch, actor=f"mobile:{principal.device_id}")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@mobile_router.post(
    "/plans/{plan_id}/approve",
    response_model=PlanRead,
    operation_id="approveMobilePlan",
)
def approve_mobile_plan(
    plan_id: str,
    payload: MobileApprovalRequest,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:approve")),
    db: Session = Depends(get_db),
):
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    _check_plan_revision(plan, payload.expected_plan_revision)
    return approve_plan(
        db,
        plan_id,
        payload.item_ids,
        actor=f"mobile:{principal.device_id}",
        force_review_items=payload.force_review_items,
    )


@mobile_router.post(
    "/plans/{plan_id}/reject",
    response_model=PlanRead,
    operation_id="rejectMobilePlan",
)
def reject_mobile_plan(
    plan_id: str,
    payload: MobileRejectRequest,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:approve")),
    db: Session = Depends(get_db),
):
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    _check_plan_revision(plan, payload.expected_plan_revision)
    return reject_items(
        db,
        plan_id,
        payload.item_ids,
        actor=f"mobile:{principal.device_id}",
        reason=payload.reason,
    )


@mobile_router.post(
    "/plans/{plan_id}/execute",
    response_model=ExecutionSummary,
    operation_id="executeMobilePlan",
)
def execute_mobile_plan(
    plan_id: str,
    payload: MobileExecuteRequest,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("plans:execute")),
    db: Session = Depends(get_db),
) -> ExecutionSummary:
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    _check_plan_revision(plan, payload.expected_plan_revision)
    plan = execute_plan(
        db,
        plan_id,
        request.app.state.settings,
        payload.item_ids,
        actor=f"mobile:{principal.device_id}",
        retry_failed=payload.retry_failed,
        drain_inline=payload.drain_inline,
    )
    return _execution_summary(plan)


@mobile_router.patch(
    "/devices/me",
    response_model=MobileDeviceRead,
    operation_id="updateCurrentMobileDevice",
)
def update_current_device(
    payload: MobileDeviceUpdateRequest,
    principal: MobilePrincipal = Depends(require_mobile_scope("devices:write")),
    db: Session = Depends(get_db),
) -> MobileDeviceRead:
    device = _current_device(db, principal)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(device, key, value)
    db.commit()
    db.refresh(device)
    return MobileDeviceRead.from_device(device)


@mobile_router.post(
    "/devices/me/push-token",
    response_model=MobileDeviceRead,
    operation_id="registerMobilePushToken",
)
def set_push_token(
    payload: MobilePushTokenRequest,
    principal: MobilePrincipal = Depends(require_mobile_scope("devices:push")),
    db: Session = Depends(get_db),
) -> MobileDeviceRead:
    try:
        return register_push_token(db, _current_device(db, principal), payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@mobile_router.patch(
    "/devices/me/notification-preferences",
    response_model=MobileDeviceRead,
    operation_id="updateMobileNotificationPreferences",
)
def set_notification_preferences(
    payload: MobileNotificationPreferencesRequest,
    principal: MobilePrincipal = Depends(require_mobile_scope("devices:push")),
    db: Session = Depends(get_db),
) -> MobileDeviceRead:
    return update_notification_preferences(db, _current_device(db, principal), payload)


@mobile_router.post(
    "/devices/me/push-test",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="queueMobilePushTest",
)
def push_test(
    payload: MobilePushTestRequest,
    request: Request,
    principal: MobilePrincipal = Depends(require_mobile_scope("devices:push")),
    db: Session = Depends(get_db),
) -> dict:
    device = _current_device(db, principal)
    row, created = queue_push(
        db,
        request.app.state.settings,
        device=device,
        event_type=payload.event_type,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        idempotency_key=f"push:{device.id}:test:{payload.entity_id or 'self'}:{device.token_version}",
    )
    if row is None:
        raise HTTPException(status_code=409, detail="Push token is not registered or notifications are disabled")
    db.commit()
    return {"accepted": True, "created": created, "notification_id": row.id}


@mobile_router.get(
    "/devices/me/pushes",
    operation_id="listMobilePushes",
)
def list_pushes(
    limit: int = Query(default=50, ge=1, le=200),
    principal: MobilePrincipal = Depends(require_mobile_scope("activity:read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    rows = list(
        db.scalars(
            select(PushNotification)
            .where(PushNotification.device_id == principal.device_id)
            .order_by(desc(PushNotification.created_at))
            .limit(limit)
        )
    )
    return [
        {
            "id": row.id,
            "event_type": row.event_type,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "state": row.state,
            "attempts": row.attempts,
            "error": row.error,
            "sent_at": row.sent_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@mobile_router.delete(
    "/devices/me",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="revokeCurrentMobileDevice",
)
def revoke_current_device(
    principal: MobilePrincipal = Depends(require_mobile_scope("devices:write")),
    db: Session = Depends(get_db),
) -> None:
    revoke_device(db, _current_device(db, principal))
