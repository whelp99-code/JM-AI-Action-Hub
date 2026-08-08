from __future__ import annotations

import json
import stat
from pathlib import Path
from urllib.parse import urlsplit

LOOPBACK_HOSTNAMES = {"127.0.0.1", "localhost", "::1"}


def validate_loopback_base_url(base_url: object) -> tuple[bool, str | None]:
    """Validate that ``base_url`` is a plain-http, same-machine JM-AI Master Worker address.

    Shared by every code path that talks to a local MW instance: LocalWebhookWorker's
    intake dispatch (write) and the worker-sync pull path (read), so the loopback
    boundary is defined exactly once.
    """
    if not base_url or not isinstance(base_url, str):
        return False, "worker_routes.master-worker.baseUrl is not configured"
    parts = urlsplit(base_url)
    if parts.scheme != "http":
        return False, "worker_routes.master-worker.baseUrl must use http (loopback only)"
    hostname = (parts.hostname or "").lower()
    if hostname not in LOOPBACK_HOSTNAMES:
        return False, "worker_routes.master-worker.baseUrl must resolve to a loopback host"
    return True, None


def read_bearer_credential(credential_file: object) -> tuple[str | None, str | None]:
    """Read the shared MW bearer token from an owner-only (chmod 0600) credential file."""
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
