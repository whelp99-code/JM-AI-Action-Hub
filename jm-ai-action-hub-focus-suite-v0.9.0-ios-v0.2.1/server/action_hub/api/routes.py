from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, selectinload

from ..connectors import ConnectorRegistry
from ..models import ActionItem, ActionPlan, AuditEvent
from ..schemas import (
    ActionItemUpdate,
    ApprovalRequest,
    ConnectorStatus,
    DailyBrief,
    ExecuteRequest,
    ExecutionSummary,
    InboxParseRequest,
    PlanRead,
    RejectRequest,
)
from ..security import require_api_key
from ..services.brief import build_daily_brief
from ..services.executor import approve_plan, build_execution_summary, execute_plan, reject_items, update_item
from ..services.planner import create_plan, get_plan
from .dependencies import get_db

health_router = APIRouter(tags=["health"])
api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
web_router = APIRouter(include_in_schema=False)


@health_router.get("/health")
def health(request: Request) -> dict:
    return {
        "status": "ok",
        "service": request.app.state.settings.app_name,
        "version": request.app.state.settings.version,
    }


@health_router.get("/readiness")
def readiness(request: Request, response: Response) -> dict:
    settings = request.app.state.settings
    database_ready = request.app.state.database.ping()
    ready = settings.is_production_ready and database_ready
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ready" if ready else "not_ready",
        "production_api_key": settings.api_key_is_secure,
        "production_ready": settings.is_production_ready,
        "mobile_enabled": settings.mobile_enabled,
        "mobile_token_secret": settings.mobile_token_secret_is_secure,
        "mobile_auth_configured": settings.mobile_auth_configured,
        "apns_configured": settings.apns_configured,
        "database": "ready" if database_ready else "unavailable",
        "execution_mode": settings.execution_mode,
        "parser_mode": settings.parser_mode,
        "worker_inline": settings.worker_inline,
    }


@api_router.post("/inbox/parse", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
def parse_inbox(
    payload: InboxParseRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> ActionPlan:
    try:
        plan, deduplicated = create_plan(db, payload, request.app.state.settings)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.headers["X-Action-Hub-Deduplicated"] = str(deduplicated).lower()
    if deduplicated:
        response.status_code = status.HTTP_200_OK
    return plan


@api_router.get("/plans", response_model=list[PlanRead])
def list_plans(
    limit: int = Query(default=20, ge=1, le=100),
    plan_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[ActionPlan]:
    statement = (
        select(ActionPlan)
        .options(
            selectinload(ActionPlan.items).selectinload(ActionItem.external_states),
            selectinload(ActionPlan.items).selectinload(ActionItem.worker_executions),
            selectinload(ActionPlan.items).selectinload(ActionItem.followups),
            selectinload(ActionPlan.inbox),
        )
        .order_by(desc(ActionPlan.created_at))
        .limit(limit)
    )
    if plan_status:
        statement = statement.where(ActionPlan.status == plan_status)
    return list(db.scalars(statement).unique())


@api_router.get("/plans/{plan_id}", response_model=PlanRead)
def read_plan(plan_id: str, db: Session = Depends(get_db)) -> ActionPlan:
    plan = get_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@api_router.patch("/plans/{plan_id}/items/{item_id}", response_model=PlanRead)
def patch_item(
    plan_id: str,
    item_id: str,
    payload: ActionItemUpdate,
    x_actor: str = Header(default="user"),
    db: Session = Depends(get_db),
) -> ActionPlan:
    try:
        return update_item(db, plan_id, item_id, payload, x_actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@api_router.post("/plans/{plan_id}/approve", response_model=PlanRead)
def approve(
    plan_id: str,
    payload: ApprovalRequest,
    db: Session = Depends(get_db),
) -> ActionPlan:
    try:
        return approve_plan(
            db,
            plan_id,
            payload.item_ids,
            payload.actor,
            payload.force_review_items,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@api_router.post("/plans/{plan_id}/reject", response_model=PlanRead)
def reject(
    plan_id: str,
    payload: RejectRequest,
    db: Session = Depends(get_db),
) -> ActionPlan:
    try:
        return reject_items(db, plan_id, payload.item_ids, payload.actor, payload.reason)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@api_router.post("/plans/{plan_id}/execute", response_model=ExecutionSummary)
def execute(
    plan_id: str,
    payload: ExecuteRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ExecutionSummary:
    try:
        plan = execute_plan(
            db,
            plan_id,
            request.app.state.settings,
            payload.item_ids,
            payload.actor,
            payload.retry_failed,
            payload.drain_inline,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_execution_summary(db, plan)


@api_router.get("/brief/today", response_model=DailyBrief)
def today_brief(
    request: Request,
    at: datetime | None = None,
    db: Session = Depends(get_db),
) -> DailyBrief:
    return build_daily_brief(db, request.app.state.settings.timezone, at)


@api_router.get("/connectors/status", response_model=list[ConnectorStatus])
def connector_status(
    request: Request,
    probe: bool = Query(default=False),
) -> list[dict]:
    return ConnectorRegistry(request.app.state.settings).statuses(probe=probe)


@api_router.get("/exports/{filename}")
def download_export(filename: str, request: Request) -> FileResponse:
    if not filename.endswith(".ics") or Path(filename).name != filename:
        raise HTTPException(status_code=400, detail="Invalid export filename")
    path = Path(request.app.state.settings.data_dir) / "exports" / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(
        path,
        media_type="text/calendar; charset=utf-8",
        filename=filename,
        headers={"Cache-Control": "private, no-store"},
    )


@api_router.get("/audit")
def audit_log(
    limit: int = Query(default=100, ge=1, le=500),
    entity_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(AuditEvent).order_by(desc(AuditEvent.created_at)).limit(limit)
    if entity_id:
        statement = statement.where(AuditEvent.entity_id == entity_id)
    rows = list(db.scalars(statement))
    return [
        {
            "id": x.id,
            "entity_type": x.entity_type,
            "entity_id": x.entity_id,
            "event_type": x.event_type,
            "actor": x.actor,
            "payload": x.payload,
            "created_at": x.created_at,
        }
        for x in rows
    ]


@web_router.get("/")
def index(request: Request) -> FileResponse:
    return FileResponse(Path(request.app.state.web_dir) / "index.html")


@web_router.get("/manifest.webmanifest")
def manifest(request: Request) -> FileResponse:
    return FileResponse(
        Path(request.app.state.web_dir) / "manifest.webmanifest",
        media_type="application/manifest+json",
    )


@web_router.get("/sw.js")
def service_worker(request: Request) -> FileResponse:
    return FileResponse(
        Path(request.app.state.web_dir) / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@web_router.post("/share-target")
async def share_target_post(request: Request) -> HTMLResponse:
    """Receive a PWA share without putting potentially sensitive text in the URL."""

    raw_body = await request.body()
    if len(raw_body) > request.app.state.settings.max_request_body_bytes:
        raise HTTPException(status_code=413, detail="Request body too large")
    raw = raw_body.decode("utf-8", errors="replace")
    form = parse_qs(raw, keep_blank_values=True)
    values = [form.get(name, [""])[0] for name in ("title", "text", "url")]
    combined = "\n".join(x for x in values if x).strip()
    shared_json = json.dumps(combined, ensure_ascii=False).replace("</", "<\\/")
    html = (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>공유 가져오기</title></head><body>"
        f"<script id='sharedPayload' type='application/json'>{shared_json}</script>"
        "<script src='/static/share-target.js' defer></script></body></html>"
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})

