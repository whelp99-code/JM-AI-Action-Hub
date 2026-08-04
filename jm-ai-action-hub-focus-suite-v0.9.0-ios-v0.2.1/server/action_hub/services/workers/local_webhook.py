from __future__ import annotations

import json
import stat
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ...config import Settings
from ...models import ActionItem, WorkerExecution
from .base import WorkerDispatchResult

LOOPBACK_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}
DEFAULT_INTAKE_PATH = "/api/v1/intakes"


class LocalWebhookWorker:
    """Dispatch a local ``master-worker`` route as a JM-AI Master Worker goal intake.

    This adapter deliberately performs a single live side-effect: ``POST
    {loopback baseUrl}/api/v1/intakes`` to create an MW ``IntakeDraft``
    (status ``draft``). It never calls MW's ``analyze``/``bind``/objective/
    contract/execution-approval endpoints, so the Owner approval gate on the
    Master Worker side cannot be bypassed from Action Hub.

    KNOWN LIMITATION: there is no completion callback from MW back to Action
    Hub. Once the intake draft is created, the worker execution here is
    marked ``dispatched`` and stays there until a future card adds a
    reverse-channel (webhook or poll) to reflect MW progress.
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
        valid, _ = self._validate_base_url(route.get("baseUrl"))
        return valid

    @staticmethod
    def _validate_base_url(base_url: object) -> tuple[bool, str | None]:
        if not base_url or not isinstance(base_url, str):
            return False, "worker_routes.master-worker.baseUrl is not configured"
        parts = urlsplit(base_url)
        if parts.scheme != "http":
            return False, "worker_routes.master-worker.baseUrl must use http (loopback only)"
        hostname = (parts.hostname or "").lower()
        if hostname not in LOOPBACK_HOSTNAMES:
            return False, "worker_routes.master-worker.baseUrl must resolve to a loopback host"
        return True, None

    def _read_credential(self) -> tuple[str | None, str | None]:
        credential_file = self.route.get("credentialFile")
        if not credential_file or not isinstance(credential_file, str):
            return None, "worker_routes.master-worker.credentialFile is not configured"
        path = Path(credential_file)
        try:
            file_stat = path.stat()
        except OSError as exc:
            return None, f"MW credential file is unreadable: {exc}"
        mode = stat.S_IMODE(file_stat.st_mode)
        if mode & 0o077:
            return None, "MW credential file must not be group/other accessible (chmod 0600)"
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, f"MW credential file could not be parsed: {exc}"
        token = data.get("token") if isinstance(data, dict) else None
        if not token or not isinstance(token, str):
            return None, "MW credential file is missing a string 'token' field"
        return token, None

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
        valid, error = self._validate_base_url(route.get("baseUrl"))
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
