from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import WebhookDelivery
from ..schemas import ReconcileRequest, ReconcileSummary, WebhookDeliveryRead, WorkerRunSummary
from ..security import require_api_key
from ..services.outbox import process_outbox_batch
from ..services.push import process_push_batch
from ..services.reconciliation import reconcile_external_states
from ..services.webhooks import process_webhook_batch
from ..worker import run_once
from .dependencies import get_db


control_router = APIRouter(
    prefix="/api/v1/control",
    tags=["control-loop"],
    dependencies=[Depends(require_api_key)],
)


@control_router.post("/run-once", response_model=WorkerRunSummary)
def control_run_once(
    request: Request,
    reconcile: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> WorkerRunSummary:
    result = run_once(db, request.app.state.settings, reconcile=reconcile)
    return WorkerRunSummary(**result.as_dict())


@control_router.post("/outbox/drain", response_model=WorkerRunSummary)
def drain_outbox(request: Request, db: Session = Depends(get_db)) -> WorkerRunSummary:
    result = process_outbox_batch(db, request.app.state.settings)
    return WorkerRunSummary(outbox_processed=result["processed"], failed=result["failed"])


@control_router.post("/webhooks/drain", response_model=WorkerRunSummary)
def drain_webhooks(request: Request, db: Session = Depends(get_db)) -> WorkerRunSummary:
    result = process_webhook_batch(db, request.app.state.settings)
    return WorkerRunSummary(webhooks_processed=result["processed"], failed=result["failed"])


@control_router.post("/push/drain", response_model=WorkerRunSummary)
def drain_pushes(request: Request, db: Session = Depends(get_db)) -> WorkerRunSummary:
    result = process_push_batch(db, request.app.state.settings)
    return WorkerRunSummary(push_processed=result["processed"], failed=result["failed"])


@control_router.get("/webhooks", response_model=list[WebhookDeliveryRead])
def list_webhooks(
    limit: int = Query(default=100, ge=1, le=500),
    provider: str | None = None,
    db: Session = Depends(get_db),
) -> list[WebhookDelivery]:
    statement = select(WebhookDelivery).order_by(desc(WebhookDelivery.received_at)).limit(limit)
    if provider:
        statement = statement.where(WebhookDelivery.provider == provider)
    return list(db.scalars(statement))


@control_router.post("/reconcile", response_model=ReconcileSummary)
def reconcile(
    payload: ReconcileRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ReconcileSummary:
    return ReconcileSummary(**reconcile_external_states(
        db,
        request.app.state.settings,
        providers=payload.providers,
        limit=payload.limit,
    ))
