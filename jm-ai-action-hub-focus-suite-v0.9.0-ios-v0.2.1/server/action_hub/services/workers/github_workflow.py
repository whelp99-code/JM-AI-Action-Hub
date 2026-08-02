from __future__ import annotations

import uuid
from urllib.parse import quote

import httpx

from ...config import Settings
from ...models import ActionItem, WorkerExecution
from .base import WorkerDispatchResult


class GitHubWorkflowWorker:
    """Dispatch an existing GitHub Actions workflow for a configured AI worker.

    Action Hub deliberately does not reimplement Codex, Claude Code, Copilot,
    Orca, or Hermes. Each route points to a repository workflow that owns the
    provider-specific setup and permissions.
    """

    def __init__(self, name: str, settings: Settings):
        self.name = name
        self.settings = settings

    @property
    def route(self) -> dict:
        return self.settings.worker_routes.get(self.name.lower(), {})

    def can_handle(self, item: ActionItem) -> bool:
        repository = self.route.get("repository") or item.repository
        return bool(repository and str(repository).count("/") == 1)

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.settings.github_token}",
            "X-GitHub-Api-Version": self.settings.github_api_version,
        }

    def build_request(self, item: ActionItem, execution: WorkerExecution) -> tuple[str | None, str | None, dict]:
        route = self.route
        repository = str(route.get("repository") or item.repository or "") or None
        workflow = str(route.get("workflow") or "") or None
        ref = str(route.get("ref") or "main")
        issue_number = execution.issue_number or (int(item.external_id) if str(item.external_id or "").isdigit() else None)
        default_inputs = {
            "action_id": item.id,
            "title": item.title,
            "description": item.description or "",
            "source_fragment": item.source_fragment or "",
            "issue_number": str(issue_number or ""),
            "issue_url": item.external_url or "",
            "repository": item.repository or repository or "",
            "worker": self.name,
            "completion_evidence_required": "true",
        }
        configured_inputs = route.get("inputs") if isinstance(route.get("inputs"), dict) else {}
        inputs = {**default_inputs, **{str(k): str(v) for k, v in configured_inputs.items()}}
        return repository, workflow, {"ref": ref, "inputs": inputs}

    def dispatch(self, item: ActionItem, execution: WorkerExecution) -> WorkerDispatchResult:
        repository, workflow, payload = self.build_request(item, execution)
        if not repository or repository.count("/") != 1:
            return WorkerDispatchResult(success=False, payload=payload, error="Worker repository must be owner/repo")
        if self.settings.execution_mode == "dry_run":
            dispatch_id = f"dry-{self.name}-{uuid.uuid4()}"
            return WorkerDispatchResult(
                success=True,
                dispatch_id=dispatch_id,
                payload={"repository": repository, "workflow": workflow or f"{self.name}.yml", **payload},
                simulated=True,
            )
        if not workflow:
            return WorkerDispatchResult(
                success=False,
                payload=payload,
                error=f"No workflow configured for worker '{self.name}'",
            )
        if not self.settings.github_token:
            return WorkerDispatchResult(success=False, payload=payload, error="GITHUB_TOKEN is not configured")
        try:
            response = httpx.post(
                f"{self.settings.github_api_base.rstrip('/')}/repos/{repository}/actions/workflows/{quote(workflow, safe='')}/dispatches",
                headers=self._headers(),
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            # workflow_dispatch returns 204 and no run id; a local correlation id
            # is linked to the later workflow_run webhook.
            dispatch_id = f"dispatch-{uuid.uuid4()}"
            return WorkerDispatchResult(
                success=True,
                dispatch_id=dispatch_id,
                payload={"repository": repository, "workflow": workflow, **payload},
            )
        except (httpx.HTTPError, ValueError) as exc:
            return WorkerDispatchResult(success=False, payload=payload, error=str(exc))
