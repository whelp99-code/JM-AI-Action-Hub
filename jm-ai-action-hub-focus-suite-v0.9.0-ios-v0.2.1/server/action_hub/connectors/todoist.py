from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import httpx

from ..config import Settings
from ..models import ActionItem
from .base import ConnectorResult, ConnectorSnapshot


class TodoistConnector:
    name = "todoist"

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.todoist_token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.todoist_token}",
            "Content-Type": "application/json",
        }

    def build_payload(self, item: ActionItem) -> dict:
        marker = f"Action-Hub-ID: {item.id}"
        description = (item.description or "").strip()
        if marker not in description:
            description = f"{description}\n\n---\n{marker}".strip()
        payload: dict = {
            "content": item.title,
            "description": description,
            "priority": int(item.priority),
        }
        if item.labels:
            payload["labels"] = item.labels
        if self.settings.todoist_default_project_id:
            payload["project_id"] = self.settings.todoist_default_project_id
        if item.due_at:
            if item.is_all_day:
                payload["due_date"] = item.due_at.date().isoformat()
            else:
                payload["due_datetime"] = item.due_at.isoformat()
        if item.estimated_minutes:
            payload["duration"] = int(item.estimated_minutes)
            payload["duration_unit"] = "minute"
        if item.deadline_at:
            payload["deadline_date"] = item.deadline_at.date().isoformat()
        return payload

    def execute(self, item: ActionItem) -> ConnectorResult:
        payload = self.build_payload(item)
        if self.settings.execution_mode == "dry_run":
            simulated_id = f"dry-todoist-{uuid.uuid4()}"
            return ConnectorResult(
                success=True,
                external_id=simulated_id,
                external_url=f"simulated://todoist/{simulated_id}",
                payload=payload,
                simulated=True,
            )
        if not self.settings.todoist_token:
            return ConnectorResult(success=False, payload=payload, error="TODOIST_TOKEN is not configured")
        try:
            response = httpx.post(
                f"{self.settings.todoist_api_base.rstrip('/')}/tasks",
                headers=self._headers(),
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            return ConnectorResult(
                success=True,
                external_id=str(body.get("id")),
                external_url=body.get("url"),
                payload=payload,
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ConnectorResult(success=False, payload=payload, error=str(exc))

    def find_existing(self, item: ActionItem) -> ConnectorResult | None:
        """Recover a task when a previous create reached Todoist but its response was lost."""

        if self.settings.execution_mode == "dry_run" or not self.settings.todoist_token:
            return None
        marker = f"Action-Hub-ID: {item.id}"
        try:
            response = httpx.get(
                f"{self.settings.todoist_api_base.rstrip('/')}/tasks",
                headers=self._headers(),
                params={"limit": 200},
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            candidates = body if isinstance(body, list) else body.get("results", body.get("items", []))
            for candidate in candidates:
                if marker in str(candidate.get("description") or ""):
                    return ConnectorResult(
                        success=True,
                        external_id=str(candidate.get("id")),
                        external_url=candidate.get("url"),
                        payload={"recovered": True, **candidate},
                    )
            return None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    def fetch_state(self, external_id: str, item: ActionItem | None = None) -> ConnectorSnapshot:
        if external_id.startswith("dry-"):
            return ConnectorSnapshot(success=True, state="open", external_id=external_id, payload={"simulated": True})
        if not self.settings.todoist_token:
            return ConnectorSnapshot(success=False, external_id=external_id, error="TODOIST_TOKEN is not configured")
        url = f"{self.settings.todoist_api_base.rstrip('/')}/tasks/{external_id}"
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self.settings.request_timeout_seconds)
            if response.status_code == 200:
                body = response.json()
                state = "completed" if body.get("checked") or body.get("completed_at") else "open"
                updated = _parse_datetime(body.get("updated_at") or body.get("completed_at"))
                return ConnectorSnapshot(
                    success=True,
                    state=state,
                    external_id=external_id,
                    external_url=body.get("url"),
                    payload=body,
                    external_updated_at=updated,
                )
            if response.status_code != 404:
                response.raise_for_status()

            # A completed Todoist task may no longer be returned by the active task endpoint.
            now = datetime.now(timezone.utc)
            params = {
                "since": (now - timedelta(days=89)).isoformat().replace("+00:00", "Z"),
                "until": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                "limit": 100,
            }
            completed = httpx.get(
                f"{self.settings.todoist_api_base.rstrip('/')}/tasks/completed/by_completion_date",
                headers=self._headers(),
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
            completed.raise_for_status()
            body = completed.json()
            for candidate in body.get("items", body.get("results", [])):
                if str(candidate.get("id")) == str(external_id):
                    return ConnectorSnapshot(
                        success=True,
                        state="completed",
                        external_id=external_id,
                        external_url=candidate.get("url"),
                        payload=candidate,
                        external_updated_at=_parse_datetime(candidate.get("completed_at")),
                    )
            return ConnectorSnapshot(success=True, state="missing", external_id=external_id, payload={})
        except (httpx.HTTPError, ValueError) as exc:
            return ConnectorSnapshot(success=False, external_id=external_id, error=str(exc))

    def healthcheck(self) -> tuple[bool, str]:
        if self.settings.execution_mode == "dry_run":
            return True, "dry-run payload validation"
        if not self.settings.todoist_token:
            return False, "TODOIST_TOKEN is not configured"
        try:
            response = httpx.get(
                f"{self.settings.todoist_api_base.rstrip('/')}/tasks",
                headers=self._headers(),
                params={"limit": 1},
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            return True, "Todoist API reachable"
        except httpx.HTTPError as exc:
            return False, str(exc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
