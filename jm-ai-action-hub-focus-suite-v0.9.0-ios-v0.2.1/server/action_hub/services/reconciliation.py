from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..connectors import ConnectorRegistry
from ..models import ActionItem, ExternalState, SyncConflict, utcnow
from .audit import record_audit
from .state_sync import apply_external_state

logger = logging.getLogger(__name__)

RECONCILABLE_PROVIDERS = {"todoist", "github", "google_calendar", "local_ics", "none"}


def reconcile_external_states(
    db: Session,
    settings: Settings,
    providers: list[str] | None = None,
    limit: int | None = None,
) -> dict:
    selected = {x.lower() for x in providers} if providers else RECONCILABLE_PROVIDERS
    selected &= RECONCILABLE_PROVIDERS
    statement = (
        select(ExternalState)
        .where(ExternalState.provider.in_(selected))
        .options(
            selectinload(ExternalState.action_item).selectinload(ActionItem.plan),
        )
        .order_by(ExternalState.last_synced_at)
        .limit(limit or settings.reconciliation_batch_size)
    )
    mirrors = list(db.scalars(statement))
    registry = ConnectorRegistry(settings)
    summary = {"checked": 0, "updated": 0, "unchanged": 0, "failed": 0, "providers": {}}
    for mirror in mirrors:
        summary["checked"] += 1
        summary["providers"][mirror.provider] = summary["providers"].get(mirror.provider, 0) + 1
        item = mirror.action_item
        if item is None:
            mirror.sync_error = "Action item missing"
            summary["failed"] += 1
            continue
        try:
            connector = registry.get(mirror.provider)
            snapshot = connector.fetch_state(mirror.external_id, item)
        except Exception as exc:
            snapshot = None
            mirror.sync_error = str(exc)
            mirror.last_synced_at = utcnow()
            summary["failed"] += 1
            logger.warning("Reconciliation failed for %s:%s", mirror.provider, mirror.external_id, exc_info=True)
            continue
        if not snapshot.success:
            mirror.sync_error = snapshot.error or "Provider state lookup failed"
            mirror.last_synced_at = utcnow()
            summary["failed"] += 1
            continue
        if snapshot.state == "missing":
            # A 404 can be caused by retention/permissions; do not silently turn it
            # into a destructive local cancellation. Surface it as a conflict.
            mirror.state = "missing"
            mirror.sync_error = "External resource not found; manual review required"
            mirror.last_synced_at = utcnow()
            existing = db.scalar(
                select(SyncConflict).where(
                    SyncConflict.action_item_id == item.id,
                    SyncConflict.provider == mirror.provider,
                    SyncConflict.conflict_type == "external_resource_missing",
                    SyncConflict.resolved_at.is_(None),
                )
            )
            if existing is None:
                db.add(
                    SyncConflict(
                        action_item_id=item.id,
                        provider=mirror.provider,
                        conflict_type="external_resource_missing",
                        local_value={"state": item.state, "external_id": mirror.external_id},
                        external_value={"state": "missing"},
                    )
                )
            summary["updated"] += 1
            continue

        old_state = mirror.state
        apply_external_state(
            db,
            item=item,
            provider=mirror.provider,
            external_id=mirror.external_id,
            external_url=snapshot.external_url or mirror.external_url,
            state=snapshot.state or mirror.state,
            payload=snapshot.payload,
            external_updated_at=snapshot.external_updated_at,
            source_version="reconciliation",
            actor="reconciliation",
        )
        mirror.sync_error = None
        if old_state != mirror.state:
            summary["updated"] += 1
        else:
            summary["unchanged"] += 1
    record_audit(
        db,
        entity_type="system",
        entity_id="reconciliation",
        event_type="reconciliation.completed",
        payload=summary,
    )
    db.commit()
    return summary
