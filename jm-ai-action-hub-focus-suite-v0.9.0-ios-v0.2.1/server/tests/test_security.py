from fastapi.testclient import TestClient

from action_hub.config import Settings
from action_hub.main import create_app


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
        parser_mode="llm",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'llm.db'}",
        data_dir=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
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
        assert "at least 32 characters" in response.json()["detail"]


def test_security_headers_and_api_no_store(client):
    page = client.get("/")
    assert "default-src 'self'" in page.headers["Content-Security-Policy"]
    assert page.headers["X-Frame-Options"] == "DENY"
    api_response = client.get("/api/v1/connectors/status")
    assert api_response.headers["Cache-Control"] == "no-store"


def test_request_body_limit_rejects_large_share_and_webhook_payloads(tmp_path):
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'body-limit.db'}",
        data_dir=tmp_path,
        max_request_body_bytes=32,
    )
    with TestClient(create_app(settings)) as client:
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
