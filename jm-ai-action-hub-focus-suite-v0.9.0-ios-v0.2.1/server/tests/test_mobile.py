from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from action_hub.config import Settings
from action_hub.main import create_app
from action_hub.models import (
    ActionItem,
    ItemState,
    MobileCapture,
    MobileDevice,
    MobilePairingSession,
    MobileRefreshToken,
    PushNotification,
    utcnow,
)
from action_hub.services import mobile as mobile_service
from action_hub.services.mobile_auth import MobileAuthError, decode_access_token, mobile_signing_secret
from action_hub.services.push import queue_push


def _pair(
    client: TestClient,
    *,
    device_name: str = "Jae Min iPhone",
    scopes: list[str] | None = None,
) -> dict:
    created = client.post(
        "/api/v1/mobile/pairings",
        json={
            "created_by": "test",
            "public_base_url": "https://hub.example.test",
            "scopes": scopes,
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    claimed = client.post(
        "/api/v1/mobile/pairings/claim",
        json={
            "pairing_id": payload["pairing_id"],
            "code": payload["code"],
            "device_name": device_name,
            "hardware_model": "iPhone17,1",
            "os_version": "26.5.2",
            "app_version": "0.1.0",
        },
    )
    assert claimed.status_code == 200, claimed.text
    return claimed.json()


def _auth(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _signed_token(payload: dict, settings: Settings) -> str:
    def segment(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = segment({"alg": "HS256", "typ": "JWT"})
    body = segment(payload)
    signature = base64.urlsafe_b64encode(
        hmac.new(
            settings.mobile_access_token_secret.encode("utf-8"),
            f"{header}.{body}".encode("ascii"),
            hashlib.sha256,
        ).digest()
    ).rstrip(b"=").decode("ascii")
    return f"{header}.{body}.{signature}"


def _mobile_state_counts(app) -> tuple[int, int, int]:
    with app.state.database.session_factory() as db:
        return (
            len(list(db.scalars(select(MobilePairingSession)))),
            len(list(db.scalars(select(MobileDevice)))),
            len(list(db.scalars(select(MobileRefreshToken)))),
        )


def test_explicit_mobile_secret_is_preferred_for_signing():
    settings = Settings(
        app_env="development",
        api_key="a" * 32,
        mobile_access_token_secret="m" * 48,
    )
    assert mobile_signing_secret(settings) == ("m" * 48).encode("utf-8")


def test_development_api_key_fallback_uses_domain_separated_hkdf_vector():
    settings = Settings(app_env="development", api_key="a" * 32)
    derived = mobile_signing_secret(settings)
    assert len(derived) == 32
    assert derived != settings.api_key.encode("utf-8")
    assert derived.hex() == "bf1d6bcac5a2cc5e9780c35384e7f5115c28342167c111dee1e7c42f69896e18"
    assert mobile_signing_secret(settings) == derived


@pytest.mark.parametrize(
    ("mobile_secret", "expected_code", "expected_detail"),
    [
        (
            "s" * 40,
            "mobile_secret_reuses_admin_key",
            "Mobile access token secret must differ from the administrative API key",
        ),
        (
            "change-me-mobile-token-secret-before-use",
            "mobile_auth_not_configured",
            "Mobile access token secret is not configured",
        ),
    ],
)
def test_mobile_secret_misconfiguration_rejects_pairing_without_state_change(
    tmp_path, mobile_secret, expected_code, expected_detail
):
    api_key = "s" * 40
    settings = Settings(
        app_env="test",
        api_key=api_key,
        mobile_access_token_secret=mobile_secret,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'invalid-mobile-secret.db'}",
        data_dir=tmp_path,
    )
    with pytest.raises(MobileAuthError) as error:
        mobile_signing_secret(settings)
    assert error.value.code == expected_code
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/mobile/pairings",
            headers={"X-Action-Hub-Key": api_key},
            json={"public_base_url": "https://hub.example.test"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == expected_detail
    assert _mobile_state_counts(app) == (0, 0, 0)


def test_production_missing_mobile_secret_rejects_pairing_without_state_change(tmp_path):
    settings = Settings(
        app_env="production",
        api_key="a" * 40,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'production-mobile-secret.db'}",
        data_dir=tmp_path,
    )
    with pytest.raises(MobileAuthError) as error:
        mobile_signing_secret(settings)
    assert error.value.code == "mobile_auth_not_configured"
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/mobile/pairings",
            headers={"X-Action-Hub-Key": settings.api_key},
            json={"public_base_url": "https://hub.example.test"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "Mobile access token secret is not configured"
    assert _mobile_state_counts(app) == (0, 0, 0)


@pytest.mark.parametrize(
    ("configured_secret", "expected_detail"),
    [
        (None, "Mobile access token secret is not configured"),
        (
            "change-me-mobile-token-secret-before-use",
            "Mobile access token secret is not configured",
        ),
        ("__ADMIN_API_KEY__", "Mobile access token secret must differ from the administrative API key"),
    ],
)
def test_mobile_configuration_failure_precedes_claim_refresh_and_bearer_processing(
    tmp_path, configured_secret, expected_detail
):
    api_key = "a" * 40
    settings = Settings(
        app_env="test",
        api_key=api_key,
        mobile_access_token_secret="m" * 48,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'mobile-config-order.db'}",
        data_dir=tmp_path,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = api_key
        pending = client.post(
            "/api/v1/mobile/pairings",
            json={"public_base_url": "https://hub.example.test"},
        ).json()
        tokens = _pair(client)
        before_counts = _mobile_state_counts(app)
        refresh_id = tokens["refresh_token"].removeprefix("ahmr_").split(".", 1)[0]

        settings.mobile_access_token_secret = (
            api_key if configured_secret == "__ADMIN_API_KEY__" else configured_secret
        )
        claim_payload = {
            "code": pending["code"],
            "device_name": "Blocked iPhone",
        }
        missing_claim = client.post(
            "/api/v1/mobile/pairings/claim",
            json={**claim_payload, "pairing_id": "missing"},
        )
        existing_claim = client.post(
            "/api/v1/mobile/pairings/claim",
            json={**claim_payload, "pairing_id": pending["pairing_id"]},
        )
        malformed_refresh = client.post(
            "/api/v1/mobile/token/refresh",
            json={"refresh_token": "x" * 40},
        )
        existing_refresh = client.post(
            "/api/v1/mobile/token/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        missing_bearer = client.get("/api/v1/mobile/dashboard")
        wrong_bearer = client.get(
            "/api/v1/mobile/dashboard", headers={"Authorization": "Bearer wrong"}
        )
        valid_bearer = client.get("/api/v1/mobile/dashboard", headers=_auth(tokens))

    for response in (
        missing_claim,
        existing_claim,
        malformed_refresh,
        existing_refresh,
        missing_bearer,
        wrong_bearer,
        valid_bearer,
    ):
        assert response.status_code == 503
        assert response.json()["detail"] == expected_detail
    assert _mobile_state_counts(app) == before_counts
    with app.state.database.session_factory() as db:
        pairing = db.get(MobilePairingSession, pending["pairing_id"])
        refresh = db.get(MobileRefreshToken, refresh_id)
        device = db.get(MobileDevice, tokens["device"]["id"])
        assert pairing is not None and pairing.status == "pending" and pairing.attempts == 0
        assert refresh is not None and refresh.consumed_at is None and refresh.revoked_at is None
        assert device is not None and device.status == "active"


def test_mobile_migration_and_capabilities(client, settings):
    response = client.get("/api/v1/mobile/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["server_version"] == "0.9.0"
    assert "secure-pairing" in body["features"]
    inspector = inspect(client.app.state.database.engine)
    tables = set(inspector.get_table_names())
    assert {"mobile_devices", "mobile_pairing_sessions", "mobile_refresh_tokens", "mobile_captures", "push_notifications"}.issubset(tables)
    assert "revision" in {column["name"] for column in inspector.get_columns("action_items")}


def test_pairing_claim_and_device_admin(client):
    tokens = _pair(client)
    assert tokens["device"]["device_name"] == "Jae Min iPhone"
    assert tokens["device"]["push_registered"] is False
    assert "capture:write" in tokens["device"]["scopes"]

    dashboard = client.get("/api/v1/mobile/dashboard", headers=_auth(tokens))
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["minimum_ios_app_version"] == "0.1.0"
    assert dashboard.json()["focus_summary"]["untriaged_count"] == 0

    devices = client.get("/api/v1/mobile/admin/devices")
    assert devices.status_code == 200
    assert len(devices.json()) == 1
    assert devices.json()[0]["id"] == tokens["device"]["id"]


def test_pairing_code_is_only_persisted_as_a_hash(client):
    created = client.post(
        "/api/v1/mobile/pairings",
        json={"created_by": "test", "public_base_url": "https://hub.example.test"},
    )
    assert created.status_code == 201
    body = created.json()
    claim_uri = urlparse(body["claim_uri"])
    assert claim_uri.scheme == "jmactionhub"
    assert claim_uri.hostname == "pair"
    qr_payload = json.loads(body["qr_payload"])
    assert qr_payload["type"] == "jm-ai-action-hub-pairing"
    assert qr_payload["version"] == 1
    assert qr_payload["server"] == "https://hub.example.test"
    canonical_code = body["code"].replace("-", "")
    with client.app.state.database.session_factory() as db:
        row = db.get(MobilePairingSession, body["pairing_id"])
        assert row is not None
        assert row.code_hash != canonical_code
        assert len(row.code_hash) == 64
        assert body["code"] not in row.code_hash


def test_pairing_rejects_bad_code_and_expires_after_attempt_limit(client):
    created = client.post(
        "/api/v1/mobile/pairings",
        json={"public_base_url": "https://hub.example.test"},
    ).json()
    for _attempt in range(5):
        response = client.post(
            "/api/v1/mobile/pairings/claim",
            json={
                "pairing_id": created["pairing_id"],
                "code": "WRONG-WRONG-WRONG-WRONG",
                "device_name": "Attacker",
            },
        )
        assert response.status_code in {401, 423}
    locked = client.post(
        "/api/v1/mobile/pairings/claim",
        json={
            "pairing_id": created["pairing_id"],
            "code": created["code"],
            "device_name": "Late Device",
        },
    )
    assert locked.status_code == 409 or locked.status_code == 423


def test_refresh_rotation_lost_response_retry_returns_same_replacement(client):
    tokens = _pair(client)
    first_refresh = tokens["refresh_token"]
    rotated = client.post(
        "/api/v1/mobile/token/refresh",
        json={"refresh_token": first_refresh, "app_version": "0.1.1"},
    )
    assert rotated.status_code == 200, rotated.text
    second = rotated.json()
    assert second["refresh_token"] != first_refresh
    assert second["device"]["app_version"] == "0.1.1"

    # Simulate a client that never received the first response and repeats the
    # predecessor token inside the bounded grace period. It must receive the
    # exact same replacement rather than losing the whole device session.
    retry = client.post(
        "/api/v1/mobile/token/refresh",
        json={"refresh_token": first_refresh},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["refresh_token"] == second["refresh_token"]

    allowed = client.get("/api/v1/mobile/dashboard", headers=_auth(retry.json()))
    assert allowed.status_code == 200
    with client.app.state.database.session_factory() as db:
        device = db.get(MobileDevice, tokens["device"]["id"])
        assert device.status == "active"


def test_refresh_reuse_after_grace_revokes_device(client, settings):
    tokens = _pair(client)
    first_refresh = tokens["refresh_token"]
    rotated = client.post(
        "/api/v1/mobile/token/refresh",
        json={"refresh_token": first_refresh},
    )
    assert rotated.status_code == 200
    second = rotated.json()

    token_id = first_refresh.removeprefix("ahmr_").split(".", 1)[0]
    with client.app.state.database.session_factory() as db:
        row = db.get(MobileRefreshToken, token_id)
        row.consumed_at = row.consumed_at - timedelta(
            seconds=settings.mobile_refresh_reuse_grace_seconds + 1
        )
        db.commit()

    reuse = client.post(
        "/api/v1/mobile/token/refresh",
        json={"refresh_token": first_refresh},
    )
    assert reuse.status_code == 401
    assert "reuse" in reuse.json()["detail"].lower()

    denied = client.get("/api/v1/mobile/dashboard", headers=_auth(second))
    assert denied.status_code == 401
    with client.app.state.database.session_factory() as db:
        device = db.get(MobileDevice, tokens["device"]["id"])
        assert device.status == "revoked"
        rows = list(
            db.scalars(
                select(MobileRefreshToken).where(MobileRefreshToken.device_id == device.id)
            )
        )
        assert rows and all(row.revoked_at is not None for row in rows)



def test_pairing_claim_is_single_use_under_concurrency(client):
    created = client.post(
        "/api/v1/mobile/pairings",
        json={"public_base_url": "https://hub.example.test"},
    ).json()
    payload = {
        "pairing_id": created["pairing_id"],
        "code": created["code"],
        "device_name": "Concurrent iPhone",
    }

    def claim() -> int:
        return client.post("/api/v1/mobile/pairings/claim", json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _: claim(), range(2)))

    assert statuses[0] == 200
    assert statuses[1] in {409, 423}
    with client.app.state.database.session_factory() as db:
        devices = list(db.scalars(select(MobileDevice)))
        assert len(devices) == 1


def test_parallel_refresh_retries_converge_on_one_replacement(client):
    tokens = _pair(client)
    refresh_token = tokens["refresh_token"]

    def refresh() -> tuple[int, str | None]:
        response = client.post(
            "/api/v1/mobile/token/refresh",
            json={"refresh_token": refresh_token},
        )
        body = response.json()
        return response.status_code, body.get("refresh_token")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: refresh(), range(2)))

    assert [status for status, _ in results] == [200, 200]
    replacements = {token for _, token in results}
    assert len(replacements) == 1
    with client.app.state.database.session_factory() as db:
        device = db.get(MobileDevice, tokens["device"]["id"])
        assert device is not None
        assert device.status == "active"
        family = list(
            db.scalars(
                select(MobileRefreshToken).where(
                    MobileRefreshToken.device_id == device.id
                )
            )
        )
        assert len(family) == 2
        assert all(row.revoked_at is None for row in family)

def test_mobile_scopes_are_enforced(client):
    tokens = _pair(client, scopes=["brief:read"])
    dashboard = client.get("/api/v1/mobile/dashboard", headers=_auth(tokens))
    assert dashboard.status_code == 200
    # A brief-only token must not receive the activity feed embedded in the
    # full dashboard response.
    assert dashboard.json()["recent_activity"] == []
    device_update = client.patch(
        "/api/v1/mobile/devices/me",
        headers=_auth(tokens),
        json={"device_name": "Scope escalation attempt"},
    )
    assert device_update.status_code == 403
    self_revoke = client.delete("/api/v1/mobile/devices/me", headers=_auth(tokens))
    assert self_revoke.status_code == 403
    denied = client.post(
        "/api/v1/mobile/captures/batch",
        headers=_auth(tokens),
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "내일 고객에게 전화",
                }
            ]
        },
    )
    assert denied.status_code == 403
    assert "capture:write" in denied.json()["detail"]


def test_access_tokens_reject_tampering_oversize_and_malformed_claims(client, settings):
    tokens = _pair(client)
    token = tokens["access_token"]
    tampered = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"
    response = client.get(
        "/api/v1/mobile/dashboard",
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert response.status_code == 401

    oversized = client.get(
        "/api/v1/mobile/dashboard",
        headers={"Authorization": f"Bearer {'x' * 4097}"},
    )
    assert oversized.status_code == 401

    malformed_claims = {
        "iss": "jm-ai-action-hub",
        "aud": "jm-ai-action-hub-ios",
        "sub": tokens["device"]["id"],
        "scp": "brief:read",
        "ver": "not-an-integer",
        "iat": "invalid",
        "exp": "invalid",
    }
    with pytest.raises(MobileAuthError):
        decode_access_token(_signed_token(malformed_claims, settings), settings)


def test_mobile_capture_batch_is_idempotent_and_exposes_review(client):
    tokens = _pair(client)
    headers = _auth(tokens)
    capture_id = str(uuid.uuid4())
    payload = {
        "captures": [
            {
                "client_capture_id": capture_id,
                "text": "내일 오전 10시 선진 HCI 미팅, 회의 전에 GPU 라이선스 확인",
                "source": "ios-share-extension",
                "timezone": "Asia/Seoul",
                "reference_time": "2026-07-30T21:00:00+09:00",
            }
        ]
    }
    first = client.post("/api/v1/mobile/captures/batch", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    receipt = first.json()["receipts"][0]
    assert receipt["status"] == "processed"
    assert receipt["plan_id"]

    duplicate = client.post("/api/v1/mobile/captures/batch", json=payload, headers=headers)
    assert duplicate.status_code == 200
    assert duplicate.json()["receipts"][0]["status"] == "duplicate"

    conflicting = payload.copy()
    conflicting["captures"] = [dict(payload["captures"][0], text="다른 내용")]
    conflict = client.post("/api/v1/mobile/captures/batch", json=conflicting, headers=headers)
    assert conflict.status_code == 200
    failed_receipt = conflict.json()["receipts"][0]
    assert failed_receipt["client_capture_id"] == capture_id
    assert failed_receipt["status"] == "failed"
    assert failed_receipt["plan_id"] == receipt["plan_id"]
    assert isinstance(failed_receipt["error"], str) and failed_receipt["error"]

    review = client.get("/api/v1/mobile/review", headers=headers)
    assert review.status_code == 200
    assert any(plan["id"] == receipt["plan_id"] for plan in review.json())



def test_mobile_capture_same_id_concurrent_retry_is_not_an_http_500(client):
    tokens = _pair(client)
    headers = _auth(tokens)
    capture_id = str(uuid.uuid4())
    payload = {
        "captures": [
            {
                "client_capture_id": capture_id,
                "text": "내일 오전 10시 동시 수집 검증 미팅",
                "reference_time": "2026-07-30T09:00:00+09:00",
            }
        ]
    }

    def upload():
        return client.post(
            "/api/v1/mobile/captures/batch", json=payload, headers=headers
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: upload(), range(2)))

    assert all(response.status_code == 200 for response in responses)
    statuses = {response.json()["receipts"][0]["status"] for response in responses}
    assert "processed" in statuses
    assert statuses <= {"processed", "duplicate", "failed"}
    retry = client.post("/api/v1/mobile/captures/batch", json=payload, headers=headers)
    assert retry.status_code == 200
    assert retry.json()["receipts"][0]["status"] == "duplicate"
    with client.app.state.database.session_factory() as db:
        rows = list(
            db.scalars(
                select(MobileCapture).where(
                    MobileCapture.device_id == tokens["device"]["id"],
                    MobileCapture.client_capture_id == capture_id,
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].status == "processed"
        assert rows[0].plan_id

def test_failed_mobile_capture_can_be_retried_with_the_same_id(client, monkeypatch):
    tokens = _pair(client)
    headers = _auth(tokens)
    capture_id = str(uuid.uuid4())
    payload = {
        "captures": [
            {
                "client_capture_id": capture_id,
                "text": "내일 오전 10시 재시도 검증 미팅",
                "reference_time": "2026-07-30T09:00:00+09:00",
            }
        ]
    }
    real_create_plan = mobile_service.create_plan
    attempts = 0

    def flaky_create_plan(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient parser failure")
        return real_create_plan(*args, **kwargs)

    monkeypatch.setattr(mobile_service, "create_plan", flaky_create_plan)
    first = client.post("/api/v1/mobile/captures/batch", json=payload, headers=headers)
    assert first.status_code == 200
    assert first.json()["receipts"][0]["status"] == "failed"

    second = client.post("/api/v1/mobile/captures/batch", json=payload, headers=headers)
    assert second.status_code == 200, second.text
    receipt = second.json()["receipts"][0]
    assert receipt["status"] == "processed"
    assert receipt["plan_id"]
    with client.app.state.database.session_factory() as db:
        row = db.scalar(
            select(MobileCapture).where(
                MobileCapture.device_id == tokens["device"]["id"],
                MobileCapture.client_capture_id == capture_id,
            )
        )
        assert row is not None
        assert row.status == "processed"
        assert row.error is None


def test_stale_mobile_capture_processing_lock_is_recovered(client):
    tokens = _pair(client)
    headers = _auth(tokens)
    capture_id = str(uuid.uuid4())
    text = "내일 오전 11시 중단 복구 검증 미팅"
    with client.app.state.database.session_factory() as db:
        db.add(
            MobileCapture(
                device_id=tokens["device"]["id"],
                client_capture_id=capture_id,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                status="processing",
                locked_at=utcnow()
                - timedelta(seconds=client.app.state.settings.processing_lock_timeout_seconds + 1),
            )
        )
        db.commit()

    response = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": capture_id,
                    "text": text,
                    "reference_time": "2026-07-30T09:00:00+09:00",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    receipt = response.json()["receipts"][0]
    assert receipt["status"] == "processed"
    assert receipt["plan_id"]
    with client.app.state.database.session_factory() as db:
        row = db.scalar(
            select(MobileCapture).where(
                MobileCapture.device_id == tokens["device"]["id"],
                MobileCapture.client_capture_id == capture_id,
            )
        )
        assert row is not None
        assert row.status == "processed"
        assert row.locked_at is None


def test_fresh_mobile_capture_processing_lock_is_not_stolen(client):
    tokens = _pair(client)
    headers = _auth(tokens)
    capture_id = str(uuid.uuid4())
    text = "내일 오후 1시 동시 처리 잠금 검증"
    with client.app.state.database.session_factory() as db:
        db.add(
            MobileCapture(
                device_id=tokens["device"]["id"],
                client_capture_id=capture_id,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                status="processing",
                locked_at=utcnow(),
            )
        )
        db.commit()

    response = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={"captures": [{"client_capture_id": capture_id, "text": text}]},
    )
    assert response.status_code == 200
    receipt = response.json()["receipts"][0]
    assert receipt["status"] == "failed"
    assert "already being processed" in receipt["error"]


def test_mobile_revision_conflict_and_approval_execution(client):
    tokens = _pair(client)
    headers = _auth(tokens)
    response = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "내일 오후 2시 고객 미팅",
                    "reference_time": "2026-07-30T09:00:00+09:00",
                }
            ]
        },
    ).json()
    plan_id = response["receipts"][0]["plan_id"]
    plan = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
    item = plan["items"][0]

    stale = client.patch(
        f"/api/v1/mobile/plans/{plan_id}/items/{item['id']}",
        headers=headers,
        json={"expected_revision": item["revision"] + 1, "title": "수정 제목"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"

    updated = client.patch(
        f"/api/v1/mobile/plans/{plan_id}/items/{item['id']}",
        headers=headers,
        json={"expected_revision": item["revision"], "title": "고객 미팅 준비"},
    )
    assert updated.status_code == 200, updated.text
    updated_plan = updated.json()
    assert updated_plan["items"][0]["revision"] > item["revision"]

    approve = client.post(
        f"/api/v1/mobile/plans/{plan_id}/approve",
        headers=headers,
        json={
            "expected_plan_revision": updated_plan["revision"],
            "force_review_items": True,
        },
    )
    assert approve.status_code == 200, approve.text
    approved = approve.json()
    execute = client.post(
        f"/api/v1/mobile/plans/{plan_id}/execute",
        headers=headers,
        json={"expected_plan_revision": approved["revision"]},
    )
    assert execute.status_code == 200, execute.text
    assert execute.json()["completed"] == 1


def test_mobile_approve_clears_review_flag_and_drops_from_review_list(client):
    # Regression for RV-01: the review tab showed no visible change after tapping
    # 승인 because approve_plan() left needs_review=True on approved items, so the
    # item stayed matched by the "needs_review OR draft" review-list filter.
    tokens = _pair(client)
    headers = _auth(tokens)
    response = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "내일 고객 미팅",
                    "reference_time": "2026-07-30T09:00:00+09:00",
                }
            ]
        },
    ).json()
    plan_id = response["receipts"][0]["plan_id"]
    plan = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
    item = plan["items"][0]
    assert item["needs_review"] is True
    review_reason = item["review_reason"]
    assert review_reason

    review_before = client.get("/api/v1/mobile/review", headers=headers)
    assert any(p["id"] == plan_id for p in review_before.json())

    approve = client.post(
        f"/api/v1/mobile/plans/{plan_id}/approve",
        headers=headers,
        json={
            "item_ids": [item["id"]],
            "expected_plan_revision": plan["revision"],
            "force_review_items": True,
        },
    )
    assert approve.status_code == 200, approve.text
    approved_item = approve.json()["items"][0]
    assert approved_item["state"] == "approved"
    assert approved_item["needs_review"] is False
    # The reason history must survive the flag being cleared.
    assert approved_item["review_reason"] == review_reason
    assert approve.json()["blocked_item_ids"] == []

    review_after = client.get("/api/v1/mobile/review", headers=headers)
    assert all(p["id"] != plan_id for p in review_after.json())


def test_mobile_approve_without_force_surfaces_blocked_items(client):
    # Regression for RV-01 candidate (b): approving without force_review_items on
    # an item that still needs review must not look like unconditional success.
    # The item stays blocked and the response must say so via blocked_item_ids.
    tokens = _pair(client)
    headers = _auth(tokens)
    response = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "내일 고객 미팅",
                    "reference_time": "2026-07-30T09:00:00+09:00",
                }
            ]
        },
    ).json()
    plan_id = response["receipts"][0]["plan_id"]
    plan = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
    item = plan["items"][0]
    assert item["needs_review"] is True

    approve = client.post(
        f"/api/v1/mobile/plans/{plan_id}/approve",
        headers=headers,
        json={
            "item_ids": [item["id"]],
            "expected_plan_revision": plan["revision"],
        },
    )
    assert approve.status_code == 200, approve.text
    body = approve.json()
    assert body["items"][0]["state"] == "draft"
    assert body["items"][0]["needs_review"] is True
    assert body["blocked_item_ids"] == [item["id"]]


def test_mobile_reject_clears_review_flag_and_drops_from_review_list(client):
    # Regression for RV-01: 전체 제외 (reject) suffered the identical bug as
    # approve -- reject_items() never cleared needs_review, so a rejected item
    # stayed matched by the review-list filter forever, looking untouched.
    tokens = _pair(client)
    headers = _auth(tokens)
    response = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "내일 고객 미팅",
                    "reference_time": "2026-07-30T09:00:00+09:00",
                }
            ]
        },
    ).json()
    plan_id = response["receipts"][0]["plan_id"]
    plan = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
    item = plan["items"][0]
    assert item["needs_review"] is True
    review_reason = item["review_reason"]

    reject = client.post(
        f"/api/v1/mobile/plans/{plan_id}/reject",
        headers=headers,
        json={
            "item_ids": [item["id"]],
            "reason": "iOS에서 제외",
            "expected_plan_revision": plan["revision"],
        },
    )
    assert reject.status_code == 200, reject.text
    rejected_item = reject.json()["items"][0]
    assert rejected_item["state"] == "rejected"
    assert rejected_item["needs_review"] is False
    assert rejected_item["review_reason"] == review_reason

    review_after = client.get("/api/v1/mobile/review", headers=headers)
    assert all(p["id"] != plan_id for p in review_after.json())


def test_mobile_changes_cursor_and_activity(client):
    tokens = _pair(client)
    headers = _auth(tokens)
    capture = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "금요일까지 제안서 보내기",
                    "reference_time": "2026-07-30T09:00:00+09:00",
                }
            ]
        },
    ).json()
    plan_id = capture["receipts"][0]["plan_id"]
    plan = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
    client.post(
        f"/api/v1/mobile/plans/{plan_id}/approve",
        headers=headers,
        json={"expected_plan_revision": plan["revision"], "force_review_items": True},
    )
    first = client.get("/api/v1/mobile/changes?limit=1", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["changes"]) == 1
    assert body["next_cursor"]
    assert "." in body["next_cursor"]
    tampered = body["next_cursor"][:-1] + ("A" if body["next_cursor"][-1] != "A" else "B")
    rejected = client.get(
        "/api/v1/mobile/changes",
        params={"cursor": tampered, "limit": 100},
        headers=headers,
    )
    assert rejected.status_code == 400
    second = client.get(
        "/api/v1/mobile/changes",
        params={"cursor": body["next_cursor"], "limit": 100},
        headers=headers,
    )
    assert second.status_code == 200
    audit_ids = {row["audit_id"] for row in body["changes"] + second.json()["changes"]}
    assert len(audit_ids) >= 2
    activity = client.get("/api/v1/mobile/activity", headers=headers)
    assert activity.status_code == 200
    assert activity.json()


def test_push_registration_queue_and_dry_run_delivery(client):
    tokens = _pair(client)
    headers = _auth(tokens)
    token = "ab" * 32
    registered = client.post(
        "/api/v1/mobile/devices/me/push-token",
        headers=headers,
        json={"token": token, "environment": "sandbox"},
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["push_registered"] is True

    queued = client.post(
        "/api/v1/mobile/devices/me/push-test",
        headers=headers,
        json={"event_type": "test", "entity_id": "self"},
    )
    assert queued.status_code == 202, queued.text
    drained = client.post("/api/v1/control/push/drain")
    assert drained.status_code == 200
    assert drained.json()["push_processed"] == 1

    pushes = client.get("/api/v1/mobile/devices/me/pushes", headers=headers)
    assert pushes.status_code == 200
    assert pushes.json()[0]["state"] == "simulated"
    with client.app.state.database.session_factory() as db:
        row = db.scalar(select(PushNotification))
        assert row.sent_at is not None


def test_push_token_rejects_non_hex_wrappers(client):
    tokens = _pair(client)
    response = client.post(
        "/api/v1/mobile/devices/me/push-token",
        headers=_auth(tokens),
        json={"token": f"<{('ab' * 32)}>", "environment": "sandbox"},
    )
    assert response.status_code == 422


def test_push_idempotency_conflict_does_not_rollback_caller_state(client, monkeypatch):
    tokens = _pair(client)
    device_id = tokens["device"]["id"]
    key = f"push:{device_id}:test:savepoint"
    with client.app.state.database.session_factory() as db:
        device = db.get(MobileDevice, device_id)
        assert device is not None
        device.push_token = "ab" * 32
        existing = PushNotification(
            device_id=device.id,
            event_type="test",
            entity_type="device",
            entity_id=device.id,
            idempotency_key=key,
            next_attempt_at=device.created_at,
        )
        db.add(existing)
        db.commit()

        device = db.get(MobileDevice, device_id)
        device.device_name = "Renamed before duplicate push"
        original_scalar = db.scalar
        calls = 0

        def hide_first_lookup(statement, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return original_scalar(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", hide_first_lookup)
        returned, created = queue_push(
            db,
            client.app.state.settings,
            device=device,
            event_type="test",
            entity_type="device",
            entity_id=device.id,
            idempotency_key=key,
        )
        assert created is False
        assert returned is not None
        db.commit()

    with client.app.state.database.session_factory() as db:
        assert db.get(MobileDevice, device_id).device_name == "Renamed before duplicate push"


def test_remote_device_revoke_invalidates_access(client):
    tokens = _pair(client)
    device_id = tokens["device"]["id"]
    revoked = client.delete(f"/api/v1/mobile/admin/devices/{device_id}")
    assert revoked.status_code == 204
    denied = client.get("/api/v1/mobile/dashboard", headers=_auth(tokens))
    assert denied.status_code == 401


def test_production_pairing_rejects_plain_http(tmp_path):
    settings = Settings(
        app_env="production",
        api_key="a" * 40,
        mobile_access_token_secret="m" * 48,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'production.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/mobile/pairings",
            headers={"X-Action-Hub-Key": settings.api_key},
            json={"public_base_url": "http://hub.example.test"},
        )
    assert response.status_code == 422
    assert "HTTPS" in response.json()["detail"]


def test_production_pairing_requires_explicit_or_configured_public_url(tmp_path):
    settings = Settings(
        app_env="production",
        api_key="a" * 40,
        mobile_access_token_secret="m" * 48,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'production-missing-url.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
    )
    with TestClient(create_app(settings)) as client:
        missing = client.post(
            "/api/v1/mobile/pairings",
            headers={"X-Action-Hub-Key": settings.api_key},
            json={},
        )
    assert missing.status_code == 422
    assert "explicit HTTPS public base URL" in missing.json()["detail"]

    configured = settings.model_copy(
        update={
            "mobile_public_base_url": "https://hub.example.test",
            "database_url": f"sqlite+pysqlite:///{tmp_path / 'production-configured-url.db'}",
        }
    )
    with TestClient(create_app(configured)) as client:
        created = client.post(
            "/api/v1/mobile/pairings",
            headers={"X-Action-Hub-Key": configured.api_key},
            json={},
        )
    assert created.status_code == 201, created.text
    assert '"server":"https://hub.example.test"' in created.json()["qr_payload"]


def test_pairing_qr_svg_and_ascii(tmp_path):
    import io

    from action_hub.services.qr import print_qr_ascii, write_qr_svg

    payload = '{"type":"jm-ai-action-hub-pairing","code":"ABCD-EFGH"}'
    target = write_qr_svg(payload, tmp_path / "pairing.svg")
    text = target.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "path" in text

    output = io.StringIO()
    print_qr_ascii(payload, output)
    rendered = output.getvalue()
    assert len(rendered.splitlines()) > 10
    assert "█" in rendered


def test_mobile_execute_reports_retrying_items_and_errors_instead_of_hiding_failure(settings):
    # Same regression as test_api_workflow.py's plain /api/v1 coverage, but
    # through the mobile router. P0-2 requires api/mobile.py and api/routes.py
    # to share one execution-summary implementation (build_execution_summary)
    # so a fix to one cannot silently drift from the other, as they already had
    # (mobile lacked the failed/pending accounting the plain API had).
    live_settings = settings.model_copy(update={"execution_mode": "live"})
    with TestClient(create_app(live_settings)) as live_client:
        live_client.headers["X-Action-Hub-Key"] = live_settings.api_key
        tokens = _pair(live_client)
        headers = _auth(tokens)
        capture = live_client.post(
            "/api/v1/mobile/captures/batch",
            headers=headers,
            json={
                "captures": [
                    {
                        "client_capture_id": str(uuid.uuid4()),
                        "text": "repo:owner/repo 로그인 오류를 codex로 수정",
                        "reference_time": "2026-07-30T09:00:00+09:00",
                    }
                ]
            },
        ).json()
        plan_id = capture["receipts"][0]["plan_id"]
        plan = live_client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
        item = plan["items"][0]
        assert item["destination"] == "github"
        approve = live_client.post(
            f"/api/v1/mobile/plans/{plan_id}/approve",
            headers=headers,
            json={"expected_plan_revision": plan["revision"]},
        )
        assert approve.status_code == 200, approve.text
        execute = live_client.post(
            f"/api/v1/mobile/plans/{plan_id}/execute",
            headers=headers,
            json={"expected_plan_revision": approve.json()["revision"]},
        )

    assert execute.status_code == 200, execute.text
    body = execute.json()
    assert body["failed"] == 0
    assert body["retrying"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["item_id"] == item["id"]
    assert "GITHUB_TOKEN" in body["errors"][0]["error"]


def test_dashboard_review_count_matches_plan_unit_not_item_unit(client):
    # Regression for S7: the badge (review_count) counted ActionItem rows while
    # the list it links to (list_review_plans) returns one row per ActionPlan.
    # A plan with 2 needs_review items made the badge read 2 while the list the
    # user taps into showed 1 plan -- individually correct per unit, but reads
    # as a bug side by side. Badge is aligned to the list's plan unit.
    tokens = _pair(client)
    headers = _auth(tokens)
    capture = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "내일 고객 미팅\n모레 협력사 미팅",
                    "reference_time": "2026-07-30T09:00:00+09:00",
                }
            ]
        },
    ).json()
    plan_id = capture["receipts"][0]["plan_id"]
    plan = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
    assert len(plan["items"]) == 2
    assert all(item["needs_review"] for item in plan["items"])

    review = client.get("/api/v1/mobile/review", headers=headers)
    assert review.status_code == 200
    assert len(review.json()) == 1

    dashboard = client.get("/api/v1/mobile/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["review_count"] == 1


def test_review_list_and_badge_exclude_terminal_states_even_if_needs_review_lingers(client):
    # Regression for P1-4's root cause: the review-list filter and the
    # dashboard badge only checked needs_review/DRAFT and never excluded
    # terminal states. Approve/reject were fixed today to clear needs_review
    # explicitly, but that leaves every future caller one missed line away
    # from the same bug. The filter itself must exclude terminal states
    # regardless of whether the flag was cleared.
    tokens = _pair(client)
    headers = _auth(tokens)
    capture = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "내일 고객 미팅",
                    "reference_time": "2026-07-30T09:00:00+09:00",
                }
            ]
        },
    ).json()
    plan_id = capture["receipts"][0]["plan_id"]
    plan = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
    item = plan["items"][0]
    assert item["needs_review"] is True

    with client.app.state.database.session_factory() as db:
        row = db.get(ActionItem, item["id"])
        row.state = ItemState.CANCELLED.value
        db.commit()

    review_after = client.get("/api/v1/mobile/review", headers=headers)
    assert all(p["id"] != plan_id for p in review_after.json())

    dashboard = client.get("/api/v1/mobile/dashboard", headers=headers)
    assert dashboard.json()["review_count"] == 0


def test_review_list_limit_is_plan_scoped_not_join_row_scoped(client):
    # Regression for S8: list_review_plans() joined ActionPlan to ActionItem
    # and applied LIMIT to that joined query, so LIMIT bounded item rows, not
    # distinct plans. A single busy plan with >= limit needs_review items could
    # exhaust the limit by itself and silently drop every other plan from the
    # response.
    from action_hub.models import ActionPlan, InboxEntry
    from action_hub.services import mobile as mobile_service

    with client.app.state.database.session_factory() as db:
        busy_inbox = InboxEntry(raw_text="busy", timezone="Asia/Seoul", fingerprint="busy-inbox".ljust(64, "0"))
        db.add(busy_inbox)
        db.flush()
        busy_plan = ActionPlan(inbox_id=busy_inbox.id, reference_time=utcnow())
        db.add(busy_plan)
        db.flush()
        busy_plan_id = busy_plan.id
        for i in range(5):
            db.add(
                ActionItem(
                    plan_id=busy_plan_id,
                    item_type="todo",
                    destination="none",
                    title=f"busy {i}",
                    fingerprint=f"busy-item-{i}".ljust(64, "0"),
                    needs_review=True,
                    review_reason="test",
                )
            )

        other_plan_ids = []
        for j in range(2):
            inbox = InboxEntry(
                raw_text=f"other{j}", timezone="Asia/Seoul", fingerprint=f"other-inbox-{j}".ljust(64, "0")
            )
            db.add(inbox)
            db.flush()
            plan = ActionPlan(inbox_id=inbox.id, reference_time=utcnow())
            db.add(plan)
            db.flush()
            other_plan_ids.append(plan.id)
            db.add(
                ActionItem(
                    plan_id=plan.id,
                    item_type="todo",
                    destination="none",
                    title=f"other {j}",
                    fingerprint=f"other-item-{j}".ljust(64, "0"),
                    needs_review=True,
                    review_reason="test",
                )
            )
        db.commit()

        plans = mobile_service.list_review_plans(db, limit=3)
        returned_ids = {plan.id for plan in plans}

    assert len(plans) == 3
    assert busy_plan_id in returned_ids
    assert other_plan_ids[0] in returned_ids
    assert other_plan_ids[1] in returned_ids


def test_capture_with_no_actions_stays_visible_until_dismissed(client, monkeypatch):
    # The LLM parsers are allowed to return nothing when a shared message holds no
    # commitment -- forwarded chatter, a bare link -- and that is the right answer.
    # The review list joined items with an INNER JOIN, so those plans vanished and
    # the share looked lost with no trace anywhere in the app. Measured on a real
    # KakaoTalk forward: two shares arrived, both parsed to zero items, neither was
    # visible. The rules parser always emits at least one item, so only the llm and
    # hybrid modes can reach this state.
    from action_hub.services import planner

    class _NothingParser:
        name = "nothing-v1"

        def parse(self, text, reference, timezone_name):
            return []

    monkeypatch.setattr(planner, "build_parser", lambda settings: _NothingParser())

    tokens = _pair(client)
    headers = _auth(tokens)
    receipt = client.post(
        "/api/v1/mobile/captures/batch",
        headers=headers,
        json={
            "captures": [
                {
                    "client_capture_id": str(uuid.uuid4()),
                    "text": "미세팁인데 요새 비행기 와이파이 참고하세요",
                    "reference_time": "2026-08-08T23:17:00+09:00",
                }
            ]
        },
    ).json()["receipts"][0]
    assert receipt["status"] == "processed"
    plan_id = receipt["plan_id"]

    plan = client.get(f"/api/v1/mobile/plans/{plan_id}", headers=headers).json()
    assert plan["items"] == []

    review = client.get("/api/v1/mobile/review", headers=headers)
    assert review.status_code == 200
    assert any(entry["id"] == plan_id for entry in review.json())

    dashboard = client.get("/api/v1/mobile/dashboard", headers=headers).json()
    assert dashboard["review_count"] >= 1

    dismissed = client.post(
        f"/api/v1/mobile/plans/{plan_id}/reject",
        headers=headers,
        json={"reason": "실행할 일이 없음"},
    )
    assert dismissed.status_code == 200, dismissed.text

    after = client.get("/api/v1/mobile/review", headers=headers).json()
    assert all(entry["id"] != plan_id for entry in after)
    assert client.get("/api/v1/mobile/dashboard", headers=headers).json()["review_count"] == 0
