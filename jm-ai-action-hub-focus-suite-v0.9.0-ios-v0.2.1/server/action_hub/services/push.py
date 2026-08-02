from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..models import MobileDevice, PushNotification, utcnow

logger = logging.getLogger(__name__)

PENDING_STATES = {"pending", "retry"}
EVENT_PREFERENCE = {
    "review_required": "review_required",
    "ai_status": "ai_status",
    "follow_up_due": "follow_up_due",
    "deadline_risk": "deadline_risk",
    "connector_failure": "connector_failure",
    "test": "review_required",
}
GENERIC_ALERTS = {
    "review_required": ("검토할 작업이 있습니다", "Action Hub에서 분석 결과를 확인하세요."),
    "ai_status": ("AI 작업 상태가 변경되었습니다", "Action Hub 활동 화면에서 결과를 확인하세요."),
    "follow_up_due": ("후속 확인 시간이 되었습니다", "Action Hub의 응답 대기 항목을 확인하세요."),
    "deadline_risk": ("마감 위험이 감지되었습니다", "오늘 화면에서 우선순위를 확인하세요."),
    "connector_failure": ("연결 작업에 문제가 발생했습니다", "Action Hub 활동 화면에서 재시도 상태를 확인하세요."),
    "test": ("Action Hub 알림 테스트", "이 기기의 푸시 알림 연결이 정상입니다."),
}


def _notification_allowed(device: MobileDevice, event_type: str) -> bool:
    preference = EVENT_PREFERENCE.get(event_type)
    if not preference:
        return True
    preferences = device.notification_preferences or {}
    return bool(preferences.get(preference, True))


def queue_push(
    db: Session,
    settings: Settings,
    *,
    device: MobileDevice,
    event_type: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> tuple[PushNotification | None, bool]:
    if device.status != "active" or not device.push_token or not _notification_allowed(device, event_type):
        return None, False
    key = idempotency_key or f"push:{device.id}:{event_type}:{entity_type or '-'}:{entity_id or uuid.uuid4()}"
    existing = db.scalar(select(PushNotification).where(PushNotification.idempotency_key == key))
    if existing:
        return existing, False
    notification = PushNotification(
        device_id=device.id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_json=payload or {},
        idempotency_key=key,
        max_attempts=settings.apns_max_attempts,
        next_attempt_at=utcnow(),
    )
    try:
        # A SAVEPOINT prevents a duplicate notification race from rolling
        # back unrelated state changes made by the caller's transaction.
        with db.begin_nested():
            db.add(notification)
            db.flush()
    except IntegrityError:
        existing = db.scalar(select(PushNotification).where(PushNotification.idempotency_key == key))
        return existing, False
    return notification, True


def queue_push_for_active_devices(
    db: Session,
    settings: Settings,
    *,
    event_type: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
    idempotency_suffix: str | None = None,
) -> int:
    devices = list(
        db.scalars(
            select(MobileDevice).where(
                MobileDevice.status == "active",
                MobileDevice.push_token.is_not(None),
            )
        )
    )
    created = 0
    for device in devices:
        suffix = idempotency_suffix or entity_id or str(uuid.uuid4())
        _, was_created = queue_push(
            db,
            settings,
            device=device,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            idempotency_key=f"push:{device.id}:{event_type}:{suffix}",
        )
        created += int(was_created)
    return created


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class APNsProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._provider_token: str | None = None
        self._provider_token_created_at = 0

    def _token(self) -> str:
        now = int(utcnow().timestamp())
        if self._provider_token and now - self._provider_token_created_at < 3000:
            return self._provider_token
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
        except ImportError as exc:  # pragma: no cover - optional dependency boundary
            raise RuntimeError("APNs live delivery requires the 'push' optional dependencies") from exc
        path = self.settings.apns_private_key_path
        if not path:
            raise RuntimeError("APNs private key path is not configured")
        private_key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(private_key, ec.EllipticCurvePrivateKey):
            raise RuntimeError("APNs private key is not an EC private key")
        header = _b64url(
            json.dumps(
                {"alg": "ES256", "kid": self.settings.apns_key_id},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        claims = _b64url(
            json.dumps(
                {"iss": self.settings.apns_team_id, "iat": now},
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signing_input = f"{header}.{claims}".encode("ascii")
        der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r_value, s_value = decode_dss_signature(der_signature)
        raw_signature = r_value.to_bytes(32, "big") + s_value.to_bytes(32, "big")
        self._provider_token = f"{header}.{claims}.{_b64url(raw_signature)}"
        self._provider_token_created_at = now
        return self._provider_token

    def send(self, notification: PushNotification, device: MobileDevice) -> tuple[bool, bool, str | None]:
        if self.settings.execution_mode == "dry_run":
            return True, False, None
        if not self.settings.apns_configured:
            return False, True, "APNs is not configured"
        if not device.push_token:
            return False, False, "Device has no APNs token"
        host = (
            "https://api.push.apple.com"
            if device.push_environment == "production"
            else "https://api.sandbox.push.apple.com"
        )
        title, body = GENERIC_ALERTS.get(
            notification.event_type,
            ("Action Hub 업데이트", "Action Hub에서 변경 내용을 확인하세요."),
        )
        payload = {
            "aps": {
                "alert": {"title": title, "body": body},
                "sound": "default",
                "mutable-content": 0,
            },
            "event": notification.event_type,
            "entity_type": notification.entity_type,
            "entity_id": notification.entity_id,
        }
        headers = {
            "authorization": f"bearer {self._token()}",
            "apns-topic": str(self.settings.apns_bundle_id),
            "apns-push-type": "alert",
            "apns-priority": "10",
            "apns-id": notification.id,
        }
        with httpx.Client(http2=True, timeout=self.settings.request_timeout_seconds) as client:
            response = client.post(f"{host}/3/device/{device.push_token}", headers=headers, json=payload)
        if response.status_code == 200:
            return True, False, None
        reason = ""
        try:
            reason = str(response.json().get("reason") or "")
        except Exception:
            reason = response.text[:200]
        permanent = response.status_code in {400, 403, 404, 405, 410} and reason not in {
            "TooManyProviderTokenUpdates",
        }
        return False, not permanent, f"APNs {response.status_code}: {reason or 'unknown error'}"


def recover_stale_pushes(db: Session, settings: Settings) -> int:
    cutoff = utcnow() - timedelta(seconds=settings.processing_lock_timeout_seconds)
    rows = list(
        db.scalars(
            select(PushNotification).where(
                PushNotification.state == "processing",
                PushNotification.locked_at.is_not(None),
                PushNotification.locked_at < cutoff,
            )
        )
    )
    for row in rows:
        row.state = "retry"
        row.locked_at = None
        row.next_attempt_at = utcnow()
        row.error = "Recovered stale APNs processing lock"
    if rows:
        db.commit()
    return len(rows)


def process_push_batch(
    db: Session,
    settings: Settings,
    limit: int | None = None,
    *,
    provider: APNsProvider | None = None,
) -> dict[str, int]:
    recover_stale_pushes(db, settings)
    batch_size = max(1, min(limit or settings.apns_batch_size, 500))
    now = utcnow()
    rows = list(
        db.scalars(
            select(PushNotification)
            .where(
                PushNotification.state.in_(PENDING_STATES),
                PushNotification.next_attempt_at <= now,
            )
            .options(selectinload(PushNotification.device))
            .order_by(PushNotification.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    )
    for row in rows:
        row.state = "processing"
        row.locked_at = utcnow()
        row.attempts += 1
    if rows:
        # Commit the claim before network I/O so another worker cannot select
        # the same rows. Stale claims are recovered by recover_stale_pushes().
        db.commit()

    sender = provider or APNsProvider(settings)
    result = {"processed": 0, "sent": 0, "failed": 0, "retry": 0}
    for row in rows:
        # Reattach relationships after the claim transaction if the session
        # expires objects on commit.
        row = db.get(PushNotification, row.id)
        if row is None:  # pragma: no cover - defensive persistence boundary
            continue
        try:
            success, retryable, error = sender.send(row, row.device)
            result["processed"] += 1
            if success:
                row.state = "simulated" if settings.execution_mode == "dry_run" else "sent"
                row.sent_at = utcnow()
                row.error = None
                result["sent"] += 1
            elif retryable and row.attempts < row.max_attempts:
                row.state = "retry"
                delay = min(settings.retry_base_seconds * (2 ** max(0, row.attempts - 1)), 3600)
                row.next_attempt_at = utcnow() + timedelta(seconds=delay)
                row.error = error
                result["retry"] += 1
            else:
                row.state = "failed"
                row.error = error
                if error and ("BadDeviceToken" in error or "Unregistered" in error):
                    row.device.push_token = None
                result["failed"] += 1
        except Exception as exc:  # pragma: no cover - network/crypto boundary
            logger.warning("APNs delivery failed", exc_info=True)
            result["processed"] += 1
            row.error = str(exc)
            if row.attempts < row.max_attempts:
                row.state = "retry"
                row.next_attempt_at = utcnow() + timedelta(seconds=settings.retry_base_seconds)
                result["retry"] += 1
            else:
                row.state = "failed"
                result["failed"] += 1
        finally:
            row.locked_at = None
            db.commit()
    return result
