from __future__ import annotations

import hmac
import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from ``ACTION_HUB_*`` environment variables.

    The project is single-user by default. Provider tokens and signing secrets are
    read from the environment and are never persisted to the application database.
    """

    model_config = SettingsConfigDict(
        env_prefix="ACTION_HUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "JM-AI Action Hub"
    app_env: Literal["development", "test", "production"] = "development"
    version: str = "0.9.0"
    host: str = "127.0.0.1"
    port: int = 8787
    log_level: str = "INFO"
    timezone: str = "Asia/Seoul"
    api_key: str | None = None
    allowed_origins: str = "http://localhost:8787,http://127.0.0.1:8787"

    database_url: str = "sqlite+pysqlite:///./data/action_hub.db"
    data_dir: Path = Path("./data")
    run_migrations: bool = True
    execution_mode: Literal["dry_run", "live"] = "dry_run"

    parser_mode: Literal["rules", "hybrid", "llm"] = "rules"
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = ""
    llm_timeout_seconds: float = 45.0

    todoist_api_base: str = "https://api.todoist.com/api/v1"
    todoist_token: str | None = None
    todoist_default_project_id: str | None = None
    todoist_client_secret: str | None = None

    github_api_base: str = "https://api.github.com"
    github_token: str | None = None
    github_default_repo: str | None = None
    github_api_version: str = "2026-03-10"
    github_webhook_secret: str | None = None
    allow_unsigned_webhooks: bool = False

    google_calendar_api_base: str = "https://www.googleapis.com/calendar/v3"
    google_calendar_access_token: str | None = None
    google_calendar_id: str = "primary"
    google_oauth_token_url: str = "https://oauth2.googleapis.com/token"
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
    google_oauth_refresh_token: str | None = None

    fireflies_graphql_url: str = "https://api.fireflies.ai/graphql"
    fireflies_api_key: str | None = None
    fireflies_webhook_secret: str | None = None

    project_routes_json: str = "{}"
    worker_routes_json: str = "{}"
    request_timeout_seconds: float = 20.0
    max_input_chars: int = 30_000
    max_request_body_bytes: int = 1_048_576
    default_event_minutes: int = 60

    # Durable execution and webhook processing.
    worker_inline: bool = True
    worker_poll_seconds: float = 2.0
    outbox_batch_size: int = 50
    outbox_max_attempts: int = 5
    retry_base_seconds: int = 5
    webhook_batch_size: int = 100
    reconciliation_batch_size: int = 100
    reconciliation_interval_seconds: float = 300.0
    processing_lock_timeout_seconds: int = 300

    # Planning and follow-up defaults.
    default_estimated_minutes: int = 30
    default_workday_minutes: int = 480
    planning_buffer_percent: int = 15
    followup_default_days: int = 2
    personal_rule_min_observations: int = 3

    # Decision and Focus Control defaults.
    importance_threshold: int = 60
    urgency_threshold: int = 60
    big3_limit: int = 3
    focus_default_minutes: int = 25
    focus_warning_percent: int = 80
    focus_max_minutes: int = 240
    focus_weekly_window_days: int = 7

    # Native mobile companion foundation.
    mobile_enabled: bool = True
    mobile_public_base_url: str | None = None
    mobile_access_token_secret: str | None = None
    mobile_access_token_minutes: int = 15
    mobile_refresh_token_days: int = 30
    # A refresh response can be lost after the server has already rotated the token.
    # During this bounded grace window the same predecessor deterministically returns
    # the same replacement instead of falsely revoking the device.
    mobile_refresh_reuse_grace_seconds: int = 30
    mobile_pairing_ttl_seconds: int = 300
    mobile_pairing_max_attempts: int = 5
    mobile_capture_batch_size: int = 50
    mobile_change_batch_size: int = 200
    mobile_min_ios_app_version: str = "0.1.0"
    mobile_recommended_ios_app_version: str = "0.2.1"
    mobile_default_scopes: str = (
        "capture:write,plans:read,plans:edit,plans:approve,plans:execute,"
        "brief:read,activity:read,devices:write,devices:push"
    )

    # APNs token-based provider configuration. The private key stays on the
    # server and is never returned to a mobile client.
    apns_team_id: str | None = None
    apns_key_id: str | None = None
    apns_bundle_id: str | None = None
    apns_private_key_path: Path | None = None
    apns_environment: Literal["sandbox", "production"] = "sandbox"
    apns_batch_size: int = 100
    apns_max_attempts: int = 5

    @field_validator("data_dir", mode="before")
    @classmethod
    def _data_dir(cls, value: Any) -> Path:
        return Path(value)

    @field_validator("apns_private_key_path", mode="before")
    @classmethod
    def _optional_path(cls, value: Any) -> Path | None:
        if value in (None, ""):
            return None
        return Path(value)

    @property
    def origins(self) -> list[str]:
        return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]

    @staticmethod
    def _json_mapping(value: str) -> dict[str, Any]:
        try:
            raw = json.loads(value or "{}")
            return {str(k).lower(): v for k, v in raw.items()} if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}

    @property
    def project_routes(self) -> dict[str, str]:
        return {key: str(value) for key, value in self._json_mapping(self.project_routes_json).items()}

    @property
    def worker_routes(self) -> dict[str, dict[str, Any]]:
        return {
            key: value
            for key, value in self._json_mapping(self.worker_routes_json).items()
            if isinstance(value, dict)
        }

    @property
    def api_key_is_secure(self) -> bool:
        return self._is_secure_api_key(self.api_key)

    @staticmethod
    def _is_secure_api_key(value: str | None) -> bool:
        if not value or value.strip() != value:
            return False
        if any(unicodedata.category(character) == "Cc" for character in value):
            return False
        unsafe = {
            "change-me",
            "change-me-before-exposing-to-network",
            "secret",
            "password",
        }
        return len(value) >= 32 and value.casefold() not in unsafe

    @property
    def mobile_token_secret_is_secure(self) -> bool:
        secret = self.mobile_access_token_secret
        return bool(
            self._is_secure_api_key(secret)
            and secret
            and secret.casefold() != "change-me-mobile-token-secret-before-use"
        )

    @property
    def mobile_secret_reuses_api_key(self) -> bool:
        mobile_secret = self.mobile_access_token_secret
        api_key = self.api_key
        if not mobile_secret or not api_key:
            return False
        return hmac.compare_digest(
            mobile_secret.strip().encode("utf-8"), api_key.strip().encode("utf-8")
        )

    @property
    def mobile_auth_configured(self) -> bool:
        if self.mobile_access_token_secret:
            return self.mobile_token_secret_is_secure and not self.mobile_secret_reuses_api_key
        return self.app_env == "development" and self.api_key_is_secure

    @property
    def mobile_scopes(self) -> list[str]:
        return [scope.strip() for scope in self.mobile_default_scopes.split(",") if scope.strip()]

    @property
    def apns_configured(self) -> bool:
        path = self.apns_private_key_path
        return bool(
            self.apns_team_id
            and self.apns_key_id
            and self.apns_bundle_id
            and path
            and path.is_file()
        )

    @property
    def is_production_ready(self) -> bool:
        if self.app_env != "production":
            return True
        if not self.api_key_is_secure:
            return False
        if self.mobile_enabled and (
            not self.mobile_token_secret_is_secure or self.mobile_secret_reuses_api_key
        ):
            return False
        return True

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "exports").mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
