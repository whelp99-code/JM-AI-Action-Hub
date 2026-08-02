from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import AuditEvent


def record_audit(
    db: Session,
    *,
    entity_type: str,
    entity_id: str,
    event_type: str,
    actor: str = "system",
    payload: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor=actor,
        payload=payload or {},
    )
    db.add(event)
    return event
