from __future__ import annotations

import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import MeetingIntake, utcnow
from ..schemas import InboxParseRequest
from .audit import record_audit
from .planner import create_plan

FIREFLIES_TRANSCRIPT_QUERY = """
query Transcript($transcriptId: String!) {
  transcript(id: $transcriptId) {
    id
    title
    transcript_url
    participants
    summary {
      action_items
      keywords
      overview
      short_summary
      gist
      topics_discussed
    }
  }
}
""".strip()


def _meeting_id(payload: dict[str, Any]) -> str | None:
    return str(
        payload.get("meeting_id")
        or payload.get("meetingId")
        or payload.get("transcript_id")
        or payload.get("transcriptId")
        or ""
    ) or None


def fetch_fireflies_transcript(meeting_id: str, settings: Settings) -> dict[str, Any]:
    if not settings.fireflies_api_key:
        raise RuntimeError("FIREFLIES_API_KEY is not configured")
    response = httpx.post(
        settings.fireflies_graphql_url,
        headers={
            "Authorization": f"Bearer {settings.fireflies_api_key}",
            "Content-Type": "application/json",
        },
        json={"query": FIREFLIES_TRANSCRIPT_QUERY, "variables": {"transcriptId": meeting_id}},
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("errors"):
        raise RuntimeError(f"Fireflies GraphQL error: {body['errors']}")
    transcript = (body.get("data") or {}).get("transcript")
    if not isinstance(transcript, dict):
        raise RuntimeError("Fireflies transcript was not returned")
    return transcript


def _embedded_transcript(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("transcript", "data", "meeting"):
        value = payload.get(key)
        if isinstance(value, dict) and (value.get("summary") or value.get("action_items")):
            return value
    if payload.get("summary") or payload.get("action_items"):
        return payload
    return None


def _split_action_items(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(x) for x in value]
    elif isinstance(value, str):
        # Fireflies summary.action_items is a string and commonly contains
        # newline bullets. Semicolon splitting handles compact custom summaries.
        raw_items = re.split(r"\n+|\s*;\s*", value)
    else:
        return []
    result: list[str] = []
    for raw in raw_items:
        item = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
        if item and item.lower() not in {"none", "n/a", "no action items"}:
            result.append(item)
    return list(dict.fromkeys(result))


def process_meeting_intake(db: Session, intake: MeetingIntake, settings: Settings, payload: dict[str, Any] | None = None) -> MeetingIntake:
    source_payload = payload or {}
    transcript = _embedded_transcript(source_payload)
    if transcript is None:
        transcript = fetch_fireflies_transcript(intake.external_meeting_id, settings)

    summary = transcript.get("summary") if isinstance(transcript.get("summary"), dict) else {}
    action_value = summary.get("action_items") or transcript.get("action_items")
    actions = _split_action_items(action_value)
    intake.title = transcript.get("title") or intake.title
    intake.transcript_url = transcript.get("transcript_url") or transcript.get("transcriptUrl")
    intake.summary_json = {
        "summary": summary,
        "participants": transcript.get("participants") or [],
        "action_items": actions,
    }
    if not actions:
        intake.status = "processed_no_actions" if "summarized" in intake.event_type else "awaiting_summary"
        intake.processed_at = utcnow()
        db.commit()
        return intake

    text = "\n".join(actions)
    plan, _ = create_plan(
        db,
        InboxParseRequest(
            text=text,
            source="fireflies",
            timezone=settings.timezone,
            force_new=False,
            metadata={
                "provider": "fireflies",
                "meeting_id": intake.external_meeting_id,
                "meeting_title": intake.title,
                "transcript_url": intake.transcript_url,
            },
        ),
        settings,
    )
    intake.action_plan_id = plan.id
    intake.status = "plan_created"
    intake.processed_at = utcnow()
    intake.error = None
    record_audit(
        db,
        entity_type="meeting_intake",
        entity_id=intake.id,
        event_type="meeting.plan_created",
        payload={"meeting_id": intake.external_meeting_id, "plan_id": plan.id, "actions": len(actions)},
    )
    db.commit()
    db.refresh(intake)
    return intake


def ingest_fireflies_event(
    db: Session,
    payload: dict[str, Any],
    event_type: str,
    settings: Settings,
) -> MeetingIntake:
    meeting_id = _meeting_id(payload)
    if not meeting_id:
        raise ValueError("Fireflies webhook does not contain meeting_id")
    normalized_event = str(event_type or payload.get("event") or payload.get("eventType") or "unknown")
    intake = db.scalar(
        select(MeetingIntake).where(
            MeetingIntake.provider == "fireflies",
            MeetingIntake.external_meeting_id == meeting_id,
            MeetingIntake.event_type == normalized_event,
        )
    )
    if intake is None:
        intake = MeetingIntake(
            provider="fireflies",
            external_meeting_id=meeting_id,
            event_type=normalized_event,
            status="received",
        )
        db.add(intake)
        db.flush()
    record_audit(
        db,
        entity_type="meeting_intake",
        entity_id=intake.id,
        event_type="meeting.webhook_received",
        payload={"meeting_id": meeting_id, "event_type": normalized_event},
    )
    if normalized_event in {"meeting.summarized", "meeting.transcribed", "Transcription completed"}:
        try:
            return process_meeting_intake(db, intake, settings, payload)
        except Exception as exc:
            intake.status = "failed"
            intake.error = str(exc)
            intake.processed_at = utcnow()
            db.commit()
            # Missing API credentials after a transcribed event is recoverable via
            # the manual reprocess endpoint, so retain the intake instead of
            # failing webhook delivery retries indefinitely.
            return intake
    intake.status = "received"
    db.commit()
    db.refresh(intake)
    return intake


def reprocess_meeting(db: Session, intake_id: str, settings: Settings) -> MeetingIntake:
    intake = db.get(MeetingIntake, intake_id)
    if intake is None:
        raise LookupError("Meeting intake not found")
    return process_meeting_intake(db, intake, settings)
