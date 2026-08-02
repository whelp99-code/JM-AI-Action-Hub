from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from ..config import Settings
from ..credentials import GoogleOAuthTokenBroker
from ..models import ActionItem
from .base import ConnectorResult, ConnectorSnapshot


class GoogleCalendarConnector:
    name = "google_calendar"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.token_broker = GoogleOAuthTokenBroker(settings)

    @property
    def configured(self) -> bool:
        return self.token_broker.configured

    def build_payload(self, item: ActionItem) -> dict:
        if not item.start_at:
            raise ValueError("Calendar event requires start_at")
        end_at = item.end_at or item.start_at + timedelta(minutes=self.settings.default_event_minutes)
        if item.is_all_day:
            return {
                "id": item.fingerprint[:32],
                "summary": item.title,
                "description": item.description or "",
                "start": {"date": item.start_at.date().isoformat()},
                "end": {"date": (item.start_at.date() + timedelta(days=1)).isoformat()},
            }
        timezone_name = getattr(item.start_at.tzinfo, "key", None) or self.settings.timezone
        return {
            "id": item.fingerprint[:32],
            "summary": item.title,
            "description": item.description or "",
            "start": {"dateTime": item.start_at.isoformat(), "timeZone": timezone_name},
            "end": {"dateTime": end_at.isoformat(), "timeZone": timezone_name},
        }

    def _headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        token = self.token_broker.get_token(force_refresh=force_refresh)
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _post(self, url: str, payload: dict) -> httpx.Response:
        response = httpx.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        if response.status_code == 401 and self.token_broker.refresh_configured:
            response = httpx.post(
                url,
                headers=self._headers(force_refresh=True),
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
        return response

    def _get(self, url: str) -> httpx.Response:
        response = httpx.get(
            url,
            headers=self._headers(),
            timeout=self.settings.request_timeout_seconds,
        )
        if response.status_code == 401 and self.token_broker.refresh_configured:
            response = httpx.get(
                url,
                headers=self._headers(force_refresh=True),
                timeout=self.settings.request_timeout_seconds,
            )
        return response

    def execute(self, item: ActionItem) -> ConnectorResult:
        try:
            payload = self.build_payload(item)
        except ValueError as exc:
            return ConnectorResult(success=False, error=str(exc))
        if self.settings.execution_mode == "dry_run":
            simulated_id = f"dry-gcal-{uuid.uuid4()}"
            return ConnectorResult(
                success=True,
                external_id=simulated_id,
                external_url=f"simulated://google-calendar/{simulated_id}",
                payload=payload,
                simulated=True,
            )
        if not self.token_broker.configured:
            return ConnectorResult(success=False, payload=payload, error="Google Calendar OAuth is not configured")
        calendar_id = quote(self.settings.google_calendar_id, safe="")
        try:
            base_url = f"{self.settings.google_calendar_api_base.rstrip('/')}/calendars/{calendar_id}/events"
            response = self._post(base_url, payload)
            # A caller-supplied event ID makes a retry safe when the first insert
            # reached Google but the response was lost.
            if response.status_code == 409:
                response = self._get(f"{base_url}/{payload['id']}")
            response.raise_for_status()
            body = response.json()
            return ConnectorResult(
                success=True,
                external_id=str(body.get("id")),
                external_url=body.get("htmlLink"),
                payload=payload,
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ConnectorResult(success=False, payload=payload, error=str(exc))

    def find_existing(self, item: ActionItem) -> ConnectorResult | None:
        if not item.fingerprint:
            return None
        event_id = item.fingerprint[:32]
        snapshot = self.fetch_state(event_id, item)
        if not snapshot.success or snapshot.state == "missing":
            return None
        return ConnectorResult(
            success=True,
            external_id=event_id,
            external_url=snapshot.external_url,
            payload={"recovered": True, **snapshot.payload},
            simulated=self.settings.execution_mode == "dry_run",
        )

    def fetch_state(self, external_id: str, item: ActionItem | None = None) -> ConnectorSnapshot:
        if external_id.startswith("dry-"):
            return ConnectorSnapshot(success=True, state="scheduled", external_id=external_id, payload={"simulated": True})
        if not self.token_broker.configured:
            return ConnectorSnapshot(success=False, external_id=external_id, error="Google Calendar OAuth is not configured")
        calendar_id = quote(self.settings.google_calendar_id, safe="")
        try:
            response = self._get(
                f"{self.settings.google_calendar_api_base.rstrip('/')}/calendars/{calendar_id}/events/{external_id}"
            )
            if response.status_code == 404:
                return ConnectorSnapshot(success=True, state="missing", external_id=external_id, payload={})
            response.raise_for_status()
            body = response.json()
            state = "cancelled" if body.get("status") == "cancelled" else "scheduled"
            updated = None
            if body.get("updated"):
                try:
                    updated = datetime.fromisoformat(body["updated"].replace("Z", "+00:00"))
                except ValueError:
                    pass
            return ConnectorSnapshot(
                success=True,
                state=state,
                external_id=external_id,
                external_url=body.get("htmlLink"),
                payload=body,
                external_updated_at=updated,
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ConnectorSnapshot(success=False, external_id=external_id, error=str(exc))

    def healthcheck(self) -> tuple[bool, str]:
        if self.settings.execution_mode == "dry_run":
            return True, "dry-run payload validation"
        if not self.token_broker.configured:
            return False, "Google Calendar OAuth is not configured"
        calendar_id = quote(self.settings.google_calendar_id, safe="")
        try:
            response = self._get(
                f"{self.settings.google_calendar_api_base.rstrip('/')}/calendars/{calendar_id}"
            )
            response.raise_for_status()
            return True, "Google Calendar API reachable"
        except (httpx.HTTPError, ValueError) as exc:
            return False, str(exc)
