from __future__ import annotations

import uuid
from datetime import datetime

import httpx

from ..config import Settings
from ..models import ActionItem
from .base import ConnectorResult, ConnectorSnapshot


class GitHubConnector:
    name = "github"

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.github_token)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.settings.github_token}",
            "X-GitHub-Api-Version": self.settings.github_api_version,
        }

    def resolve_repository(self, item: ActionItem) -> str | None:
        if item.repository:
            return item.repository
        if item.project:
            route = self.settings.project_routes.get(item.project.lower())
            if route:
                return route
        return self.settings.github_default_repo

    def build_payload(self, item: ActionItem) -> tuple[str | None, dict]:
        repository = self.resolve_repository(item)
        body_lines = [item.description or "", "", "---", f"Action-Hub-ID: {item.id}"]
        if item.due_at:
            body_lines.insert(1, f"Scheduled: {item.due_at.isoformat()}")
        if item.deadline_at:
            body_lines.insert(1, f"Deadline: {item.deadline_at.isoformat()}")
        if item.estimated_minutes:
            body_lines.insert(1, f"Estimate: {item.estimated_minutes} minutes")
        if item.executor:
            body_lines.insert(1, f"Executor: {item.executor}")
        payload: dict = {"title": item.title, "body": "\n".join(body_lines).strip()}
        if item.labels:
            payload["labels"] = item.labels
        if item.assignee:
            payload["assignees"] = [item.assignee]
        return repository, payload

    @staticmethod
    def canonical_external_id(repository: str, number: int | str) -> str:
        return f"{repository}#{number}"

    def execute(self, item: ActionItem) -> ConnectorResult:
        repository, payload = self.build_payload(item)
        if not repository or repository.count("/") != 1:
            return ConnectorResult(success=False, payload=payload, error="GitHub repository must be owner/repo")
        if self.settings.execution_mode == "dry_run":
            simulated_number = uuid.uuid4().int % 100000
            simulated_id = f"dry-github-{uuid.uuid4()}"
            return ConnectorResult(
                success=True,
                external_id=simulated_id,
                external_url=f"simulated://github/{repository}/issues/{simulated_id}",
                payload={"repository": repository, "native_id": simulated_id, **payload},
                simulated=True,
            )
        if not self.settings.github_token:
            return ConnectorResult(success=False, payload=payload, error="GITHUB_TOKEN is not configured")
        try:
            response = httpx.post(
                f"{self.settings.github_api_base.rstrip('/')}/repos/{repository}/issues",
                headers=self._headers(),
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            number = body.get("number") or body.get("id")
            return ConnectorResult(
                success=True,
                external_id=str(number),
                external_url=body.get("html_url"),
                payload={"repository": repository, "native_id": number, **payload},
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ConnectorResult(success=False, payload={"repository": repository, **payload}, error=str(exc))

    def find_existing(self, item: ActionItem) -> ConnectorResult | None:
        repository = self.resolve_repository(item)
        if self.settings.execution_mode == "dry_run" or not self.settings.github_token or not repository:
            return None
        marker = f"Action-Hub-ID: {item.id}"
        try:
            response = httpx.get(
                f"{self.settings.github_api_base.rstrip('/')}/repos/{repository}/issues",
                headers=self._headers(),
                params={"state": "all", "per_page": 100},
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            for candidate in response.json():
                if marker in str(candidate.get("body") or ""):
                    number = candidate.get("number") or candidate.get("id")
                    return ConnectorResult(
                        success=True,
                        external_id=str(number),
                        external_url=candidate.get("html_url"),
                        payload={"repository": repository, "native_id": number, "recovered": True},
                    )
            return None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    def fetch_state(self, external_id: str, item: ActionItem | None = None) -> ConnectorSnapshot:
        if external_id.startswith("dry-") or "#dry-" in external_id:
            return ConnectorSnapshot(success=True, state="open", external_id=external_id, payload={"simulated": True})
        repository, number = _parse_external_id(external_id, item)
        if not repository or not number:
            return ConnectorSnapshot(success=False, external_id=external_id, error="Invalid GitHub external id")
        if not self.settings.github_token:
            return ConnectorSnapshot(success=False, external_id=external_id, error="GITHUB_TOKEN is not configured")
        try:
            response = httpx.get(
                f"{self.settings.github_api_base.rstrip('/')}/repos/{repository}/issues/{number}",
                headers=self._headers(),
                timeout=self.settings.request_timeout_seconds,
            )
            if response.status_code == 404:
                return ConnectorSnapshot(success=True, state="missing", external_id=external_id, payload={})
            response.raise_for_status()
            body = response.json()
            state = "completed" if body.get("state") == "closed" else "open"
            return ConnectorSnapshot(
                success=True,
                state=state,
                external_id=str(number),
                external_url=body.get("html_url"),
                payload=body,
                external_updated_at=_parse_datetime(body.get("updated_at") or body.get("closed_at")),
            )
        except (httpx.HTTPError, ValueError) as exc:
            return ConnectorSnapshot(success=False, external_id=external_id, error=str(exc))

    def healthcheck(self) -> tuple[bool, str]:
        if self.settings.execution_mode == "dry_run":
            return True, "dry-run payload validation"
        if not self.settings.github_token:
            return False, "GITHUB_TOKEN is not configured"
        repository = self.settings.github_default_repo
        url = (
            f"{self.settings.github_api_base.rstrip('/')}/repos/{repository}"
            if repository
            else f"{self.settings.github_api_base.rstrip('/')}/user"
        )
        try:
            response = httpx.get(url, headers=self._headers(), timeout=self.settings.request_timeout_seconds)
            response.raise_for_status()
            return True, "GitHub API reachable"
        except httpx.HTTPError as exc:
            return False, str(exc)


def _parse_external_id(external_id: str, item: ActionItem | None) -> tuple[str | None, str | None]:
    if "#" in external_id:
        repository, number = external_id.rsplit("#", 1)
        return repository, number
    if item and item.repository:
        return item.repository, external_id
    return None, None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
