from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import MobileDevice, MobilePairingSession, MobileRefreshToken, utcnow
from ..schemas import (
    MobileDeviceRead,
    MobilePairingClaimRequest,
    MobilePairingCreateResponse,
    MobileRefreshRequest,
    MobileTokenResponse,
)

TOKEN_ISSUER = "jm-ai-action-hub"
TOKEN_AUDIENCE = "jm-ai-action-hub-ios"
REFRESH_PREFIX = "ahmr_"
PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
MOBILE_AUTH_HKDF_SALT = b"jm-ai-action-hub/mobile-auth/salt/v1"
MOBILE_AUTH_HKDF_INFO = b"jm-ai-action-hub/mobile-auth/v1"


class MobileAuthError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid_mobile_credentials") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class MobilePrincipal:
    device_id: str
    device_name: str
    scopes: frozenset[str]
    token_version: int

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise MobileAuthError("Malformed access token") from exc


def _secret(settings: Settings) -> bytes:
    secret = settings.mobile_access_token_secret
    if secret:
        if settings.mobile_secret_reuses_api_key:
            raise MobileAuthError(
                "Mobile access token secret must differ from the administrative API key",
                code="mobile_secret_reuses_admin_key",
            )
        if not settings.mobile_token_secret_is_secure:
            raise MobileAuthError(
                "Mobile access token secret is not configured",
                code="mobile_auth_not_configured",
            )
        return secret.encode("utf-8")
    if settings.app_env == "development" and settings.api_key_is_secure:
        return _hkdf_sha256(settings.api_key.encode("utf-8"))
    raise MobileAuthError(
        "Mobile access token secret is not configured",
        code="mobile_auth_not_configured",
    )


def _hkdf_sha256(ikm: bytes) -> bytes:
    prk = hmac.new(MOBILE_AUTH_HKDF_SALT, ikm, hashlib.sha256).digest()
    return hmac.new(prk, MOBILE_AUTH_HKDF_INFO + b"\x01", hashlib.sha256).digest()


def mobile_signing_secret(settings: Settings) -> bytes:
    """Return the configured mobile signing key for internal authenticated tokens.

    The key is never exposed through an API. Cursor signing reuses the mobile
    authentication trust boundary while adding a separate HMAC context label.
    """

    return _secret(settings)


def _json_segment(payload: dict[str, Any]) -> str:
    return _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))


def encode_access_token(device: MobileDevice, settings: Settings) -> tuple[str, int]:
    now = utcnow()
    lifetime = max(1, settings.mobile_access_token_minutes) * 60
    header = _json_segment({"alg": "HS256", "typ": "JWT"})
    payload = _json_segment(
        {
            "iss": TOKEN_ISSUER,
            "aud": TOKEN_AUDIENCE,
            "sub": device.id,
            "scp": list(device.scopes or []),
            "ver": int(device.token_version),
            "iat": int(now.timestamp()),
            "exp": int(now.timestamp()) + lifetime,
            "jti": str(uuid.uuid4()),
        }
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = _b64url_encode(hmac.new(_secret(settings), signing_input, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}", lifetime


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    if not token or len(token) > 4096:
        raise MobileAuthError("Malformed access token")
    parts = token.split(".")
    if len(parts) != 3:
        raise MobileAuthError("Malformed access token")
    header_segment, payload_segment, signature_segment = parts
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    expected = _b64url_encode(hmac.new(_secret(settings), signing_input, hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature_segment):
        raise MobileAuthError("Invalid access token signature")
    try:
        header = json.loads(_b64url_decode(header_segment))
        payload = json.loads(_b64url_decode(payload_segment))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise MobileAuthError("Malformed access token") from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise MobileAuthError("Malformed access token")
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise MobileAuthError("Unsupported access token")
    now = int(utcnow().timestamp())
    if payload.get("iss") != TOKEN_ISSUER or payload.get("aud") != TOKEN_AUDIENCE:
        raise MobileAuthError("Access token issuer or audience mismatch")
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 128:
        raise MobileAuthError("Access token subject missing")
    try:
        expires_at = int(payload["exp"])
        issued_at = int(payload["iat"])
        token_version = int(payload["ver"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise MobileAuthError("Malformed access token claims") from exc
    scopes = payload.get("scp")
    if not isinstance(scopes, list) or any(
        not isinstance(scope, str) or not scope or len(scope) > 100 for scope in scopes
    ):
        raise MobileAuthError("Malformed access token scopes")
    if token_version < 0:
        raise MobileAuthError("Malformed access token version")
    if expires_at <= now:
        raise MobileAuthError("Access token expired", code="access_token_expired")
    if issued_at > now + 60:
        raise MobileAuthError("Access token issued in the future")
    if issued_at < now - (settings.mobile_access_token_minutes * 60 + 300):
        raise MobileAuthError("Access token issued outside the accepted lifetime")
    payload["exp"] = expires_at
    payload["iat"] = issued_at
    payload["ver"] = token_version
    return payload


def authenticate_mobile(db: Session, token: str, settings: Settings) -> MobilePrincipal:
    payload = decode_access_token(token, settings)
    device = db.get(MobileDevice, str(payload["sub"]))
    if not device or device.status != "active" or device.revoked_at is not None:
        raise MobileAuthError("Mobile device is revoked")
    if int(payload.get("ver") or 0) != device.token_version:
        raise MobileAuthError("Access token has been revoked")
    token_scopes = frozenset(str(scope) for scope in payload.get("scp") or [])
    device_scopes = frozenset(str(scope) for scope in device.scopes or [])
    scopes = token_scopes.intersection(device_scopes)
    device.last_seen_at = utcnow()
    db.commit()
    return MobilePrincipal(
        device_id=device.id,
        device_name=device.device_name,
        scopes=scopes,
        token_version=device.token_version,
    )


def _canonical_pairing_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch in string.ascii_uppercase + string.digits)


def _pairing_hash(pairing_id: str, code: str, settings: Settings) -> str:
    canonical = _canonical_pairing_code(code)
    return hmac.new(_secret(settings), f"{pairing_id}:{canonical}".encode(), hashlib.sha256).hexdigest()


def _new_pairing_code() -> str:
    raw = "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(16))
    return "-".join(raw[index : index + 4] for index in range(0, len(raw), 4))


def _validate_scopes(requested: list[str] | None, settings: Settings) -> list[str]:
    allowed = set(settings.mobile_scopes)
    scopes = requested or settings.mobile_scopes
    normalized = list(dict.fromkeys(str(scope).strip() for scope in scopes if str(scope).strip()))
    invalid = sorted(set(normalized) - allowed)
    if invalid:
        raise ValueError(f"Unsupported mobile scopes: {', '.join(invalid)}")
    if not normalized:
        raise ValueError("At least one mobile scope is required")
    return normalized


def create_pairing(
    db: Session,
    settings: Settings,
    *,
    scopes: list[str] | None,
    created_by: str,
    public_base_url: str,
) -> MobilePairingCreateResponse:
    if not settings.mobile_enabled:
        raise MobileAuthError("Mobile companion is disabled", code="mobile_disabled")
    _secret(settings)
    base_url = public_base_url.rstrip("/")
    if settings.app_env == "production" and not base_url.lower().startswith("https://"):
        raise ValueError("Production mobile pairing requires an HTTPS public base URL")
    normalized_scopes = _validate_scopes(scopes, settings)
    code = _new_pairing_code()
    pairing_id = str(uuid.uuid4())
    pairing = MobilePairingSession(
        id=pairing_id,
        code_hash=_pairing_hash(pairing_id, code, settings),
        requested_scopes=normalized_scopes,
        expires_at=utcnow() + timedelta(seconds=max(60, settings.mobile_pairing_ttl_seconds)),
        max_attempts=max(1, settings.mobile_pairing_max_attempts),
        created_by=created_by,
    )
    db.add(pairing)
    db.flush()
    db.commit()
    claim_query = urlencode({"server": base_url, "pairing_id": pairing.id, "code": code})
    claim_uri = f"jmactionhub://pair?{claim_query}"
    qr_payload = json.dumps(
        {
            "type": "jm-ai-action-hub-pairing",
            "version": 1,
            "server": base_url,
            "pairing_id": pairing.id,
            "code": code,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return MobilePairingCreateResponse(
        pairing_id=pairing.id,
        code=code,
        expires_at=pairing.expires_at,
        scopes=normalized_scopes,
        claim_uri=claim_uri,
        qr_payload=qr_payload,
    )


def _refresh_token_raw(
    token_id: str,
    device_id: str,
    family_id: str,
    settings: Settings,
) -> str:
    """Reconstruct a high-entropy refresh token without storing its plaintext.

    A deterministic HMAC secret lets the server return the exact same replacement
    when a client retries immediately after a lost rotation response. The database
    still stores only a SHA-256 verifier.
    """

    material = f"refresh:{token_id}:{device_id}:{family_id}".encode()
    secret = _b64url_encode(hmac.new(_secret(settings), material, hashlib.sha256).digest())
    return f"{REFRESH_PREFIX}{token_id}.{secret}"


def _new_refresh_token(
    db: Session,
    device: MobileDevice,
    settings: Settings,
    *,
    family_id: str | None = None,
) -> tuple[MobileRefreshToken, str]:
    token_id = str(uuid.uuid4())
    resolved_family_id = family_id or str(uuid.uuid4())
    raw = _refresh_token_raw(token_id, device.id, resolved_family_id, settings)
    row = MobileRefreshToken(
        id=token_id,
        device_id=device.id,
        family_id=resolved_family_id,
        token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        expires_at=utcnow() + timedelta(days=max(1, settings.mobile_refresh_token_days)),
    )
    db.add(row)
    db.flush()
    return row, raw


def _token_response(
    db: Session,
    device: MobileDevice,
    refresh: MobileRefreshToken,
    raw_refresh_token: str,
    settings: Settings,
) -> MobileTokenResponse:
    access_token, expires_in = encode_access_token(device, settings)
    db.commit()
    db.refresh(device)
    return MobileTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=raw_refresh_token,
        refresh_expires_at=refresh.expires_at,
        device=MobileDeviceRead.from_device(device),
    )


def claim_pairing(
    db: Session,
    settings: Settings,
    request: MobilePairingClaimRequest,
) -> MobileTokenResponse:
    _secret(settings)
    pairing = db.scalar(
        select(MobilePairingSession)
        .where(MobilePairingSession.id == request.pairing_id)
        .with_for_update()
    )
    if not pairing:
        raise MobileAuthError("Pairing session not found", code="pairing_not_found")
    now = utcnow()
    if pairing.status != "pending":
        raise MobileAuthError("Pairing session is no longer available", code="pairing_unavailable")
    if pairing.expires_at <= now:
        pairing.status = "expired"
        db.commit()
        raise MobileAuthError("Pairing session expired", code="pairing_expired")
    if pairing.attempts >= pairing.max_attempts:
        pairing.status = "locked"
        db.commit()
        raise MobileAuthError("Pairing session is locked", code="pairing_locked")
    supplied_hash = _pairing_hash(pairing.id, request.code, settings)
    if not hmac.compare_digest(pairing.code_hash, supplied_hash):
        # Increment attempts atomically. SQLite ignores SELECT FOR UPDATE, so a
        # read/modify/write counter can otherwise lose concurrent bad attempts.
        db.execute(
            update(MobilePairingSession)
            .where(
                MobilePairingSession.id == pairing.id,
                MobilePairingSession.status == "pending",
                MobilePairingSession.expires_at > now,
                MobilePairingSession.attempts < MobilePairingSession.max_attempts,
            )
            .values(
                attempts=MobilePairingSession.attempts + 1,
                status=case(
                    (
                        MobilePairingSession.attempts + 1
                        >= MobilePairingSession.max_attempts,
                        "locked",
                    ),
                    else_="pending",
                ),
                updated_at=now,
            )
        )
        db.commit()
        latest = db.get(MobilePairingSession, pairing.id)
        if latest and latest.status == "locked":
            raise MobileAuthError("Pairing session is locked", code="pairing_locked")
        raise MobileAuthError("Pairing code is invalid", code="pairing_code_invalid")

    # Compare-and-set the one-time pairing state before creating credentials.
    # This keeps the single-use guarantee even on SQLite where row locks are
    # not implemented. The transaction is committed only with the device and
    # refresh token, so any downstream failure returns the session to pending.
    claimed = db.execute(
        update(MobilePairingSession)
        .where(
            MobilePairingSession.id == pairing.id,
            MobilePairingSession.status == "pending",
            MobilePairingSession.code_hash == supplied_hash,
            MobilePairingSession.expires_at > now,
            MobilePairingSession.attempts < MobilePairingSession.max_attempts,
        )
        .values(status="claiming", updated_at=now)
    )
    if claimed.rowcount != 1:
        db.rollback()
        latest = db.get(MobilePairingSession, pairing.id)
        if latest is None:
            raise MobileAuthError("Pairing session not found", code="pairing_not_found")
        if latest.expires_at <= now or latest.status == "expired":
            raise MobileAuthError("Pairing session expired", code="pairing_expired")
        if latest.status == "locked" or latest.attempts >= latest.max_attempts:
            raise MobileAuthError("Pairing session is locked", code="pairing_locked")
        raise MobileAuthError("Pairing session is no longer available", code="pairing_unavailable")
    db.refresh(pairing)

    device = MobileDevice(
        device_name=request.device_name,
        platform=request.platform,
        hardware_model=request.hardware_model,
        os_version=request.os_version,
        app_version=request.app_version,
        scopes=list(pairing.requested_scopes or settings.mobile_scopes),
        push_environment=request.push_environment,
        notification_preferences={
            "review_required": True,
            "ai_status": True,
            "follow_up_due": True,
            "deadline_risk": True,
            "connector_failure": True,
        },
        last_seen_at=now,
    )
    db.add(device)
    db.flush()
    refresh, raw_refresh = _new_refresh_token(db, device, settings)
    pairing.status = "claimed"
    pairing.claimed_device_id = device.id
    pairing.claimed_at = now
    return _token_response(db, device, refresh, raw_refresh, settings)


def _parse_refresh_token(raw_token: str) -> str:
    if not raw_token.startswith(REFRESH_PREFIX) or "." not in raw_token:
        raise MobileAuthError("Malformed refresh token")
    token_id = raw_token[len(REFRESH_PREFIX) :].split(".", 1)[0]
    try:
        uuid.UUID(token_id)
    except ValueError as exc:
        raise MobileAuthError("Malformed refresh token") from exc
    return token_id


def _revoke_family(db: Session, family_id: str) -> None:
    db.execute(
        update(MobileRefreshToken)
        .where(MobileRefreshToken.family_id == family_id, MobileRefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def _retry_rotated_refresh(
    db: Session,
    token: MobileRefreshToken,
    device: MobileDevice,
    settings: Settings,
    now: datetime,
) -> MobileTokenResponse | None:
    """Return the already-issued replacement during the lost-response grace window."""

    if token.consumed_at is None or not token.replaced_by_id:
        return None
    grace = max(0, settings.mobile_refresh_reuse_grace_seconds)
    if grace == 0 or (now - token.consumed_at).total_seconds() > grace:
        return None
    replacement = db.get(MobileRefreshToken, token.replaced_by_id)
    if (
        replacement is None
        or replacement.device_id != device.id
        or replacement.family_id != token.family_id
        or replacement.revoked_at is not None
        or replacement.consumed_at is not None
        or replacement.expires_at <= now
    ):
        return None
    raw_replacement = _refresh_token_raw(
        replacement.id, replacement.device_id, replacement.family_id, settings
    )
    expected_hash = hashlib.sha256(raw_replacement.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(replacement.token_hash, expected_hash):
        # Legacy/random tokens cannot be reconstructed. Fall through to the
        # conservative theft response instead of disclosing a wrong credential.
        return None
    token.last_used_at = now
    device.last_seen_at = now
    return _token_response(db, device, replacement, raw_replacement, settings)


def _revoke_reused_refresh(
    db: Session, token: MobileRefreshToken, device: MobileDevice, now: datetime
) -> None:
    _revoke_family(db, token.family_id)
    device.status = "revoked"
    device.revoked_at = now
    device.token_version += 1
    device.push_token = None
    db.commit()


def rotate_refresh_token(
    db: Session,
    settings: Settings,
    request: MobileRefreshRequest,
) -> MobileTokenResponse:
    _secret(settings)
    token_id = _parse_refresh_token(request.refresh_token)
    token = db.scalar(
        select(MobileRefreshToken)
        .where(MobileRefreshToken.id == token_id)
        .with_for_update()
    )
    if not token:
        raise MobileAuthError("Refresh token is invalid")
    supplied_hash = hashlib.sha256(request.refresh_token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(token.token_hash, supplied_hash):
        raise MobileAuthError("Refresh token is invalid")
    device = db.get(MobileDevice, token.device_id)
    if not device or device.status != "active" or device.revoked_at is not None:
        raise MobileAuthError("Mobile device is revoked")
    now = utcnow()
    if token.consumed_at is not None:
        retry = _retry_rotated_refresh(db, token, device, settings, now)
        if retry is not None:
            return retry
        _revoke_reused_refresh(db, token, device, now)
        raise MobileAuthError(
            "Refresh token reuse detected; device access revoked",
            code="refresh_token_reuse",
        )
    if token.revoked_at is not None or token.expires_at <= now:
        raise MobileAuthError("Refresh token expired or revoked", code="refresh_token_expired")

    consumed = db.execute(
        update(MobileRefreshToken)
        .where(
            MobileRefreshToken.id == token.id,
            MobileRefreshToken.consumed_at.is_(None),
            MobileRefreshToken.revoked_at.is_(None),
            MobileRefreshToken.expires_at > now,
        )
        .values(consumed_at=now, last_used_at=now)
    )
    if consumed.rowcount != 1:
        # A concurrent refresh already consumed this token. Treat that as token
        # reuse and revoke the entire family rather than issuing parallel chains.
        db.rollback()
        token = db.get(MobileRefreshToken, token_id)
        device = db.get(MobileDevice, token.device_id) if token else None
        if token and token.consumed_at is not None and device:
            retry = _retry_rotated_refresh(db, token, device, settings, now)
            if retry is not None:
                return retry
            _revoke_reused_refresh(db, token, device, now)
            raise MobileAuthError(
                "Refresh token reuse detected; device access revoked",
                code="refresh_token_reuse",
            )
        raise MobileAuthError("Refresh token expired or revoked", code="refresh_token_expired")

    db.refresh(token)
    replacement, raw_replacement = _new_refresh_token(
        db,
        device,
        settings,
        family_id=token.family_id,
    )
    token.replaced_by_id = replacement.id
    device.app_version = request.app_version or device.app_version
    device.os_version = request.os_version or device.os_version
    device.last_seen_at = now
    return _token_response(db, device, replacement, raw_replacement, settings)


def revoke_device(db: Session, device: MobileDevice) -> None:
    now = utcnow()
    device.status = "revoked"
    device.revoked_at = now
    device.token_version += 1
    device.push_token = None
    db.execute(
        update(MobileRefreshToken)
        .where(MobileRefreshToken.device_id == device.id, MobileRefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.commit()


def get_device(db: Session, device_id: str) -> MobileDevice:
    device = db.scalar(select(MobileDevice).where(MobileDevice.id == device_id))
    if not device:
        raise LookupError("Mobile device not found")
    return device
