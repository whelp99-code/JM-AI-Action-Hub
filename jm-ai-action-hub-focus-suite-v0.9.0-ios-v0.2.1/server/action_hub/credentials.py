from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass

import httpx

from .config import Settings


@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str
    expires_at_monotonic: float


class GoogleOAuthTokenBroker:
    """In-memory Google OAuth refresh broker.

    Refresh credentials remain in environment-backed Settings. Access tokens are
    cached only in process memory and are never written to the Action Hub DB.
    """

    _cache: dict[str, AccessToken] = {}
    _lock = threading.Lock()

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def refresh_configured(self) -> bool:
        return bool(
            self.settings.google_oauth_client_id
            and self.settings.google_oauth_client_secret
            and self.settings.google_oauth_refresh_token
        )

    @property
    def configured(self) -> bool:
        return bool(self.settings.google_calendar_access_token or self.refresh_configured)

    def _cache_key(self) -> str:
        raw = "|".join(
            [
                self.settings.google_oauth_token_url,
                self.settings.google_oauth_client_id or "",
                self.settings.google_oauth_refresh_token or "",
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get_token(self, *, force_refresh: bool = False) -> str | None:
        key = self._cache_key()
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached.expires_at_monotonic > now + 60:
                return cached.value

        if not force_refresh and self.settings.google_calendar_access_token:
            return self.settings.google_calendar_access_token
        if not self.refresh_configured:
            return self.settings.google_calendar_access_token

        response = httpx.post(
            self.settings.google_oauth_token_url,
            data={
                "client_id": self.settings.google_oauth_client_id,
                "client_secret": self.settings.google_oauth_client_secret,
                "refresh_token": self.settings.google_oauth_refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        token = str(body.get("access_token") or "")
        if not token:
            raise ValueError("Google OAuth refresh response did not contain access_token")
        expires_in = max(120, int(body.get("expires_in") or 3600))
        with self._lock:
            self._cache[key] = AccessToken(token, now + expires_in)
        return token

    @classmethod
    def clear_cache(cls) -> None:
        with cls._lock:
            cls._cache.clear()
