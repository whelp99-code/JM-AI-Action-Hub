from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from ..schemas import WebhookReceipt
from ..services.webhooks import (
    WebhookConfigurationError,
    WebhookSecurityError,
    process_webhook_batch,
    receive_webhook,
)

webhook_router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@webhook_router.post("/{provider}", response_model=WebhookReceipt, status_code=status.HTTP_202_ACCEPTED)
async def provider_webhook(provider: str, request: Request) -> WebhookReceipt:
    raw_body = await request.body()
    settings = request.app.state.settings
    if len(raw_body) > settings.max_request_body_bytes:
        raise HTTPException(status_code=413, detail="Request body too large")
    with request.app.state.database.session_factory() as db:
        try:
            delivery, duplicate = receive_webhook(
                db,
                provider=provider,
                raw_body=raw_body,
                headers=request.headers,
                settings=settings,
            )
        except WebhookSecurityError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except WebhookConfigurationError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if settings.worker_inline and not duplicate:
            process_webhook_batch(db, settings, delivery_ids=[delivery.id])
        return WebhookReceipt(
            accepted=True,
            duplicate=duplicate,
            delivery_id=delivery.delivery_id,
            provider=delivery.provider,
            event_type=delivery.event_type,
        )
