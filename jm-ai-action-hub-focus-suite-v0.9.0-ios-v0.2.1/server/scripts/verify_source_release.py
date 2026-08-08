#!/usr/bin/env python3
"""Verify source-release layout, forbidden paths, and safe environment template."""
from __future__ import annotations

import json
import os
import posixpath
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from build_source_release import (
    ALLOWED_DIRECTORIES,
    ALLOWED_ROOT_FILES,
    ARCHIVE_ROOT,
    FORBIDDEN_PATH_PATTERN,
    OPTIONAL_LEGAL_FILES,
    REPOSITORY_ROOT,
    archive_output_path,
    is_allowed_env_path,
)

EXPECTED_ENV_KEYS = {
    "ACTION_HUB_APP_ENV",
    "ACTION_HUB_HOST",
    "ACTION_HUB_PORT",
    "ACTION_HUB_LOG_LEVEL",
    "ACTION_HUB_TIMEZONE",
    "ACTION_HUB_API_KEY",
    "ACTION_HUB_ALLOWED_ORIGINS",
    "ACTION_HUB_DATABASE_URL",
    "ACTION_HUB_DATA_DIR",
    "ACTION_HUB_RUN_MIGRATIONS",
    "ACTION_HUB_EXECUTION_MODE",
    "ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS",
    "ACTION_HUB_WORKER_INLINE",
    "ACTION_HUB_WORKER_POLL_SECONDS",
    "ACTION_HUB_OUTBOX_BATCH_SIZE",
    "ACTION_HUB_OUTBOX_MAX_ATTEMPTS",
    "ACTION_HUB_RETRY_BASE_SECONDS",
    "ACTION_HUB_WEBHOOK_BATCH_SIZE",
    "ACTION_HUB_RECONCILIATION_BATCH_SIZE",
    "ACTION_HUB_RECONCILIATION_INTERVAL_SECONDS",
    "ACTION_HUB_PROCESSING_LOCK_TIMEOUT_SECONDS",
    "ACTION_HUB_DEFAULT_ESTIMATED_MINUTES",
    "ACTION_HUB_DEFAULT_WORKDAY_MINUTES",
    "ACTION_HUB_PLANNING_BUFFER_PERCENT",
    "ACTION_HUB_FOLLOWUP_DEFAULT_DAYS",
    "ACTION_HUB_PERSONAL_RULE_MIN_OBSERVATIONS",
    "ACTION_HUB_IMPORTANCE_THRESHOLD",
    "ACTION_HUB_URGENCY_THRESHOLD",
    "ACTION_HUB_BIG3_LIMIT",
    "ACTION_HUB_FOCUS_DEFAULT_MINUTES",
    "ACTION_HUB_FOCUS_WARNING_PERCENT",
    "ACTION_HUB_FOCUS_MAX_MINUTES",
    "ACTION_HUB_FOCUS_WEEKLY_WINDOW_DAYS",
    "ACTION_HUB_MOBILE_ENABLED",
    "ACTION_HUB_MOBILE_PUBLIC_BASE_URL",
    "ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET",
    "ACTION_HUB_MOBILE_ACCESS_TOKEN_MINUTES",
    "ACTION_HUB_MOBILE_REFRESH_TOKEN_DAYS",
    "ACTION_HUB_MOBILE_REFRESH_REUSE_GRACE_SECONDS",
    "ACTION_HUB_MOBILE_PAIRING_TTL_SECONDS",
    "ACTION_HUB_MOBILE_PAIRING_MAX_ATTEMPTS",
    "ACTION_HUB_MOBILE_CAPTURE_BATCH_SIZE",
    "ACTION_HUB_MOBILE_CHANGE_BATCH_SIZE",
    "ACTION_HUB_MOBILE_MIN_IOS_APP_VERSION",
    "ACTION_HUB_MOBILE_RECOMMENDED_IOS_APP_VERSION",
    "ACTION_HUB_APNS_TEAM_ID",
    "ACTION_HUB_APNS_KEY_ID",
    "ACTION_HUB_APNS_BUNDLE_ID",
    "ACTION_HUB_APNS_PRIVATE_KEY_PATH",
    "ACTION_HUB_APNS_ENVIRONMENT",
    "ACTION_HUB_APNS_BATCH_SIZE",
    "ACTION_HUB_APNS_MAX_ATTEMPTS",
    "ACTION_HUB_PARSER_MODE",
    "ACTION_HUB_LLM_BASE_URL",
    "ACTION_HUB_LLM_API_KEY",
    "ACTION_HUB_LLM_MODEL",
    "ACTION_HUB_LLM_TIMEOUT_SECONDS",
    "ACTION_HUB_REQUEST_TIMEOUT_SECONDS",
    "ACTION_HUB_MAX_INPUT_CHARS",
    "ACTION_HUB_MAX_REQUEST_BODY_BYTES",
    "ACTION_HUB_DEFAULT_EVENT_MINUTES",
    "ACTION_HUB_TODOIST_TOKEN",
    "ACTION_HUB_TODOIST_DEFAULT_PROJECT_ID",
    "ACTION_HUB_TODOIST_CLIENT_SECRET",
    "ACTION_HUB_GITHUB_TOKEN",
    "ACTION_HUB_GITHUB_DEFAULT_REPO",
    "ACTION_HUB_GITHUB_WEBHOOK_SECRET",
    "ACTION_HUB_PROJECT_ROUTES_JSON",
    "ACTION_HUB_WORKER_ROUTES_JSON",
    "ACTION_HUB_GOOGLE_CALENDAR_ACCESS_TOKEN",
    "ACTION_HUB_GOOGLE_CALENDAR_ID",
    "ACTION_HUB_GOOGLE_OAUTH_CLIENT_ID",
    "ACTION_HUB_GOOGLE_OAUTH_CLIENT_SECRET",
    "ACTION_HUB_GOOGLE_OAUTH_REFRESH_TOKEN",
    "ACTION_HUB_GOOGLE_OAUTH_TOKEN_URL",
    "ACTION_HUB_FIREFLIES_API_KEY",
    "ACTION_HUB_FIREFLIES_WEBHOOK_SECRET",
    "ACTION_HUB_FIREFLIES_GRAPHQL_URL",
    "POSTGRES_PASSWORD",
}
NONEMPTY_CREDENTIAL_VALUES = {
    "ACTION_HUB_API_KEY": "change-me-before-exposing-to-network",
    "ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET": "change-me-mobile-token-secret-before-use",
    "POSTGRES_PASSWORD": "change-this-postgres-password",
}
CREDENTIAL_KEY_PATTERN = re.compile(r"(API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY)")
NON_CREDENTIAL_TOKEN_CONFIGURATION_KEYS = frozenset(
    {
        "ACTION_HUB_MOBILE_ACCESS_TOKEN_MINUTES",
        "ACTION_HUB_MOBILE_REFRESH_TOKEN_DAYS",
        "ACTION_HUB_GOOGLE_OAUTH_TOKEN_URL",
    }
)


class SourceReleaseVerificationError(RuntimeError):
    """The archive does not meet the source-release boundary."""


@dataclass(frozen=True)
class ReleaseArchiveSummary:
    path: Path
    forbidden_count: int
    version: str


def parse_env_template(template: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(template.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SourceReleaseVerificationError(f"Invalid .env.example line {line_number}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise SourceReleaseVerificationError(f"Invalid .env.example key {key!r}")
        if key in values:
            raise SourceReleaseVerificationError(f"Duplicate .env.example key {key}")
        values[key] = value
    if set(values) != EXPECTED_ENV_KEYS:
        missing = sorted(EXPECTED_ENV_KEYS - set(values))
        unknown = sorted(set(values) - EXPECTED_ENV_KEYS)
        raise SourceReleaseVerificationError(
            f".env.example key mismatch missing={missing} unknown={unknown}"
        )
    return values


def validate_env_template(template: str) -> None:
    values = parse_env_template(template)
    for key, value in values.items():
        if not value or not key.endswith(("_URL", "_BASE", "_DATABASE_URL")):
            continue
        parsed = urlsplit(value)
        if parsed.username is not None or parsed.password is not None:
            raise SourceReleaseVerificationError(f".env.example URL userinfo is forbidden for {key}")
    nonempty_credentials = {
        key: value
        for key, value in values.items()
        if CREDENTIAL_KEY_PATTERN.search(key)
        and key not in NON_CREDENTIAL_TOKEN_CONFIGURATION_KEYS
        and value
    }
    if nonempty_credentials != NONEMPTY_CREDENTIAL_VALUES:
        raise SourceReleaseVerificationError(
            f".env.example credential values must equal the approved map: {sorted(nonempty_credentials)}"
        )


def is_allowed_archive_path(relative_path: str) -> bool:
    parts = Path(relative_path).parts
    if not parts:
        return False
    if len(parts) == 1:
        return parts[0] in ALLOWED_ROOT_FILES or parts[0] in OPTIONAL_LEGAL_FILES
    return parts[0] in ALLOWED_DIRECTORIES and is_allowed_env_path(relative_path)


def archive_input_path() -> Path:
    configured = os.environ.get("SOURCE_RELEASE_INPUT")
    if configured:
        return Path(configured).expanduser().resolve()
    return archive_output_path(REPOSITORY_ROOT)


def normalized_archive_member_path(member_name: str) -> str:
    """Return a canonical member path or reject a path unsafe to extract."""
    if not member_name:
        raise SourceReleaseVerificationError("Archive member path is empty")
    if member_name.startswith("/"):
        raise SourceReleaseVerificationError(f"Absolute archive member path: {member_name}")
    if "\\" in member_name:
        raise SourceReleaseVerificationError(f"Non-normal archive member path: {member_name}")

    raw_path = member_name.rstrip("/")
    if not raw_path:
        raise SourceReleaseVerificationError("Archive member path is empty")
    raw_parts = raw_path.split("/")
    if ".." in raw_parts:
        raise SourceReleaseVerificationError(f"Path traversal archive member: {member_name}")
    if any(part in {"", "."} for part in raw_parts):
        normalized = posixpath.normpath(raw_path)
    else:
        normalized = "/".join(raw_parts)

    if normalized.startswith("../") or normalized == "..":
        raise SourceReleaseVerificationError(f"Path traversal archive member: {member_name}")
    return normalized


def verify_archive(archive_path: Path) -> ReleaseArchiveSummary:
    env_templates: list[tarfile.TarInfo] = []
    forbidden_count = 0
    seen_paths: set[str] = set()
    root_seen = False
    release_info: dict[str, object] | None = None

    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            name = normalized_archive_member_path(member.name)
            if name == ARCHIVE_ROOT:
                # tarfile normalizes the builder's trailing slash away when it
                # reads a directory member, so this is the canonical in-memory
                # representation of the required archive root.
                if member.name != ARCHIVE_ROOT:
                    raise SourceReleaseVerificationError(f"Non-normal archive root: {member.name}")
                if root_seen:
                    raise SourceReleaseVerificationError("Duplicate archive root member")
                if not member.isdir():
                    raise SourceReleaseVerificationError("Archive root must be a directory")
                root_seen = True
                continue
            if member.name.endswith("/"):
                raise SourceReleaseVerificationError(f"Non-normal archive member path: {member.name}")
            if not name.startswith(f"{ARCHIVE_ROOT}/"):
                raise SourceReleaseVerificationError(f"Unexpected archive root: {member.name}")
            relative = name.removeprefix(f"{ARCHIVE_ROOT}/")
            if not relative or relative in seen_paths:
                raise SourceReleaseVerificationError(f"Duplicate or empty archive path: {member.name}")
            seen_paths.add(relative)
            if member.name != name:
                raise SourceReleaseVerificationError(f"Non-normal archive member path: {member.name}")
            if member.issym() or member.islnk() or not member.isfile():
                raise SourceReleaseVerificationError(f"Non-regular archive member: {member.name}")
            if FORBIDDEN_PATH_PATTERN.search(relative) or not is_allowed_archive_path(relative):
                forbidden_count += 1
            basename = Path(relative).name
            if basename.startswith(".env"):
                if relative == "server/.env.example":
                    env_templates.append(member)
                else:
                    forbidden_count += 1
            if relative == "RELEASE_INFO.json":
                stream = archive.extractfile(member)
                if stream is None:
                    raise SourceReleaseVerificationError("Cannot read RELEASE_INFO.json")
                release_info = json.loads(stream.read().decode("utf-8"))

        if forbidden_count:
            raise SourceReleaseVerificationError(f"Forbidden archive entries: {forbidden_count}")
        if not root_seen:
            raise SourceReleaseVerificationError("Expected exactly one archive root member")
        if len(env_templates) != 1:
            raise SourceReleaseVerificationError(
                f"Expected exactly one server/.env.example, found {len(env_templates)}"
            )
        env_stream = archive.extractfile(env_templates[0])
        if env_stream is None:
            raise SourceReleaseVerificationError("Cannot read server/.env.example")
        validate_env_template(env_stream.read().decode("utf-8"))

    if not release_info or release_info.get("server_version") != "0.9.0":
        raise SourceReleaseVerificationError("RELEASE_INFO.json server_version must equal 0.9.0")
    return ReleaseArchiveSummary(path=archive_path, forbidden_count=forbidden_count, version="0.9.0")


def main() -> int:
    summary = verify_archive(archive_input_path())
    print(
        f"SOURCE_RELEASE_OK forbidden_count={summary.forbidden_count} "
        f"version={summary.version} path={summary.path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
