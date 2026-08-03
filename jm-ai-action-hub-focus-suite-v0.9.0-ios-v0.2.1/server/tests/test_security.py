import os
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from action_hub.config import Settings
from action_hub.main import create_app
from action_hub.models import ActionPlan

TEST_API_KEY = "test-api-key-" + ("x" * 32)


def test_production_api_key_required(tmp_path):
    settings = Settings(
        app_env="production",
        api_key="s" * 32,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'prod.db'}",
        data_dir=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/connectors/status").status_code == 401
        assert client.get(
            "/api/v1/connectors/status", headers={"X-Action-Hub-Key": "w" * 32}
        ).status_code == 401
        assert client.get(
            "/api/v1/connectors/status", headers={"X-Action-Hub-Key": "s" * 32}
        ).status_code == 200


def test_protected_export_requires_key_in_production(tmp_path):
    settings = Settings(
        app_env="production",
        api_key="s" * 32,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'prod-export.db'}",
        data_dir=tmp_path,
    )
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "event.ics").write_text("BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/exports/event.ics").status_code == 401
        response = client.get(
            "/api/v1/exports/event.ics",
            headers={"X-Action-Hub-Key": "s" * 32},
        )
        assert response.status_code == 200
        assert "BEGIN:VCALENDAR" in response.text


def test_unconfigured_llm_parser_returns_service_unavailable(tmp_path):
    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        parser_mode="llm",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'llm.db'}",
        data_dir=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        response = client.post(
            "/api/v1/inbox/parse",
            json={"text": "내일 10시 미팅", "timezone": "Asia/Seoul"},
        )
        assert response.status_code == 503
        assert "LLM parser is not configured" in response.json()["detail"]


def test_production_placeholder_api_key_is_rejected(tmp_path):
    settings = Settings(
        app_env="production",
        api_key="change-me-before-exposing-to-network",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'placeholder.db'}",
        data_dir=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        response = client.get(
            "/api/v1/connectors/status",
            headers={"X-Action-Hub-Key": "change-me-before-exposing-to-network"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "API key is not configured securely"


def test_admin_api_is_fail_closed_in_every_environment(tmp_path):
    for app_env in ("development", "test", "production"):
        for label, api_key in (("missing", None), ("placeholder", "change-me")):
            settings = Settings(
                app_env=app_env,
                api_key=api_key,
                database_url=f"sqlite+pysqlite:///{tmp_path / f'{app_env}-{label}.db'}",
                data_dir=tmp_path / f"{app_env}-{label}",
            )
            app = create_app(settings)
            with TestClient(app) as client:
                assert client.get("/health").status_code == 200
                readiness = client.get("/readiness")
                assert readiness.status_code == (503 if app_env == "production" else 200)
                assert "production_api_key" in readiness.json()
                response = client.post(
                    "/api/v1/inbox/parse",
                    json={"text": "내일 10시 미팅", "timezone": "Asia/Seoul"},
                )
                assert response.status_code == 503
                with app.state.database.session_factory() as db:
                    assert db.scalar(select(ActionPlan)) is None


def test_mobile_pairing_claim_and_refresh_are_not_admin_gated(tmp_path):
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'mobile-public.db'}",
        data_dir=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        claim = client.post(
            "/api/v1/mobile/pairings/claim",
            json={"pairing_id": "missing", "code": "ABCD-EFGH", "device_name": "Test iPhone"},
        )
        refresh = client.post(
            "/api/v1/mobile/token/refresh",
            json={"refresh_token": "x" * 40},
        )
    assert claim.status_code == 503
    assert refresh.status_code == 503
    assert claim.json()["detail"] == "Mobile access token secret is not configured"
    assert refresh.json()["detail"] == "Mobile access token secret is not configured"


def test_api_key_validation_rejects_insecure_values_and_accepts_secure_value():
    insecure_values = (
        " change-me-before-exposing-to-network",
        "change-me-before-exposing-to-network ",
        "s" * 31,
        "s" * 16 + "\n" + "s" * 16,
        "CHANGE-ME",
        "CHANGE-ME-BEFORE-EXPOSING-TO-NETWORK",
        "PASSWORD",
    )
    assert all(not Settings(api_key=value).api_key_is_secure for value in insecure_values)
    assert Settings(api_key=TEST_API_KEY).api_key_is_secure


def test_default_host_is_loopback():
    assert Settings().host == "127.0.0.1"


def test_make_dev_preserves_explicit_host_override():
    server_dir = Path(__file__).resolve().parents[1]
    default = subprocess.run(
        ["make", "-n", "dev"], cwd=server_dir, capture_output=True, check=True, text=True
    )
    override_env = {**os.environ, "ACTION_HUB_HOST": "0.0.0.0"}
    override = subprocess.run(
        ["make", "-n", "dev"], cwd=server_dir, env=override_env, capture_output=True, check=True, text=True
    )
    assert "--host 127.0.0.1" in default.stdout
    assert "--host 0.0.0.0" in override.stdout


def test_security_headers_and_api_no_store(client):
    page = client.get("/")
    assert "default-src 'self'" in page.headers["Content-Security-Policy"]
    assert page.headers["X-Frame-Options"] == "DENY"
    api_response = client.get("/api/v1/connectors/status")
    assert api_response.headers["Cache-Control"] == "no-store"


def test_request_body_limit_rejects_large_share_and_webhook_payloads(tmp_path):
    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'body-limit.db'}",
        data_dir=tmp_path,
        max_request_body_bytes=32,
    )
    with TestClient(create_app(settings)) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        share = client.post(
            "/share-target",
            content="text=" + ("가" * 40),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert share.status_code == 413

        webhook = client.post(
            "/api/v1/webhooks/github",
            content=b"{" + (b"x" * 64) + b"}",
        )
        assert webhook.status_code == 413
