from __future__ import annotations

import uuid

import httpx

from ...config import Settings
from ...models import ActionItem, WorkerExecution
from .base import WorkerDispatchResult
from .mw_credentials import read_bearer_credential, validate_loopback_base_url

DEFAULT_INTAKE_PATH = "/api/v1/intakes"


class LocalWebhookWorker:
    """Dispatch a local ``master-worker`` route as a JM-AI Master Worker goal intake.

    This adapter deliberately performs a single live side-effect: ``POST
    {loopback baseUrl}/api/v1/intakes`` to create an MW ``IntakeDraft``
    (status ``draft``). It never calls MW's ``analyze``/``bind``/objective/
    contract/execution-approval endpoints, so the Owner approval gate on the
    Master Worker side cannot be bypassed from Action Hub.

    There is no completion callback (webhook/push) from MW back to Action Hub.
    Once the intake draft is created, the worker execution here is marked
    ``dispatched`` and stays there until the Owner explicitly runs
    ``action-hub worker-sync`` (see .master_worker_sync), which pulls the
    intake's MW audit trail and advances the execution accordingly. There is
    no automatic background poller for this reverse channel by design.
    """

    def __init__(self, name: str, settings: Settings):
        self.name = name
        self.settings = settings

    @property
    def route(self) -> dict:
        return self.settings.worker_routes.get(self.name.lower(), {})

    def can_handle(self, item: ActionItem) -> bool:  # noqa: ARG002 - protocol parity
        route = self.route
        if route.get("kind") != "local_webhook":
            return False
        valid, _ = validate_loopback_base_url(route.get("baseUrl"))
        return valid

    def _read_credential(self) -> tuple[str | None, str | None]:
        return read_bearer_credential(self.route.get("credentialFile"))

    def build_request(self, item: ActionItem, execution: WorkerExecution) -> dict:  # noqa: ARG002
        text_parts = [item.title.strip()] if item.title else []
        if item.description and item.description.strip():
            text_parts.append(item.description.strip())
        return {
            "text": "\n\n".join(text_parts),
            "sources": [{"type": "text", "value": item.id, "trust": "external_untrusted"}],
        }

    def dispatch(self, item: ActionItem, execution: WorkerExecution) -> WorkerDispatchResult:
        route = self.route
        payload = self.build_request(item, execution)
        valid, error = validate_loopback_base_url(route.get("baseUrl"))
        if not valid:
            return WorkerDispatchResult(success=False, payload=payload, error=error)

        if self.settings.execution_mode == "dry_run":
            dispatch_id = f"dry-{self.name}-{uuid.uuid4()}"
            return WorkerDispatchResult(success=True, dispatch_id=dispatch_id, payload=payload, simulated=True)

        token, token_error = self._read_credential()
        if token_error:
            return WorkerDispatchResult(success=False, payload=payload, error=token_error)

        base_url = str(route.get("baseUrl")).rstrip("/")
        # The intake path is pinned: this adapter's only permitted side effect is MW goal
        # intake creation, so a route-supplied path override is refused outright.
        if route.get("path") not in (None, DEFAULT_INTAKE_PATH):
            return WorkerDispatchResult(success=False, payload=payload, error="local_webhook route path override is not allowed")
        path = DEFAULT_INTAKE_PATH
        timeout = float(route.get("timeoutSeconds") or self.settings.request_timeout_seconds)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": f"ah-worker-exec-{execution.id}",
        }
        try:
            response = httpx.post(f"{base_url}{path}", headers=headers, json=payload, timeout=timeout)
            if response.status_code == 401:
                return WorkerDispatchResult(
                    success=False,
                    payload=payload,
                    error="MW rejected the request: authentication failed (401)",
                )
            response.raise_for_status()
            body = response.json() if response.content else {}
            intake_id = str((body.get("data") or {}).get("id") or "") if isinstance(body, dict) else ""
            dispatch_id = f"mw-intake-{intake_id}" if intake_id else f"mw-intake-{uuid.uuid4()}"
            return WorkerDispatchResult(success=True, dispatch_id=dispatch_id, payload=payload)
        except (httpx.HTTPError, ValueError) as exc:
            return WorkerDispatchResult(success=False, payload=payload, error=str(exc))
