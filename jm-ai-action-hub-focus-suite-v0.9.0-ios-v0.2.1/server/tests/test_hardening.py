from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import patch

import httpx
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

from action_hub.config import Settings
from action_hub.credentials import GoogleOAuthTokenBroker
from action_hub.database import Database
from action_hub.main import create_app
from action_hub.models import ActionItem, MeetingIntake, OutboxEvent, WebhookDelivery, WorkerExecution, utcnow

TEST_API_KEY = "test-api-key-" + ("x" * 32)


def _create(client: TestClient, text_value: str) -> dict:
    response = client.post(
        "/api/v1/inbox/parse",
        json={
            "text": text_value,
            "reference_time": "2026-07-28T19:00:00+09:00",
            "timezone": "Asia/Seoul",
            "force_new": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approve(client: TestClient, plan_id: str) -> None:
    response = client.post(
        f"/api/v1/plans/{plan_id}/approve",
        json={"actor": "test", "force_review_items": True},
    )
    assert response.status_code == 200, response.text


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_pre_alembic_v010_database_is_stamped_and_upgraded(tmp_path):
    database = Database(f"sqlite+pysqlite:///{tmp_path / 'upgrade.db'}")
    cfg = database._alembic_config()
    command.upgrade(cfg, "0001_initial_v010")
    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    database.migrate_schema()
    inspector = inspect(database.engine)
    assert "outbox_events" in inspector.get_table_names()
    assert "locked_at" in {column["name"] for column in inspector.get_columns("webhook_deliveries")}
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005_decision_focus_foundation"
    database.engine.dispose()


def test_stale_outbox_lock_is_recovered_by_control_loop(tmp_path):
    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'outbox.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        worker_inline=False,
        processing_lock_timeout_seconds=1,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        plan = _create(client, "내일 오후 3시까지 제안서 작성")
        _approve(client, plan["id"])
        queued = client.post(f"/api/v1/plans/{plan['id']}/execute", json={}).json()
        assert queued["queued"] == 1
        with app.state.database.session_factory() as db:
            event = db.scalar(select(OutboxEvent))
            event.state = "processing"
            event.locked_at = utcnow() - timedelta(minutes=10)
            db.commit()
        result = client.post("/api/v1/control/run-once").json()
        assert result["outbox_processed"] == 1
        refreshed = client.get(f"/api/v1/plans/{plan['id']}").json()
        assert refreshed["items"][0]["state"] == "registered"


def test_stale_webhook_lock_is_recovered_and_applied(tmp_path):
    secret = "github-hook-secret"
    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'webhook.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        worker_inline=False,
        processing_lock_timeout_seconds=1,
        github_webhook_secret=secret,
        github_default_repo="owner/repo",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        plan = _create(client, "repo:owner/repo 로그인 오류 수정")
        _approve(client, plan["id"])
        client.post(f"/api/v1/plans/{plan['id']}/execute", json={})
        client.post("/api/v1/control/run-once")
        item_id = client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]["id"]
        with app.state.database.session_factory() as db:
            item = db.get(ActionItem, item_id)
            item.external_id = "42"
            item.external_states[0].external_id = "owner/repo#42"
            db.commit()
        payload = {
            "action": "closed",
            "repository": {"full_name": "owner/repo"},
            "issue": {"number": 42, "state": "closed", "updated_at": "2026-07-29T08:00:00Z"},
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        response = client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": _signature(secret, body),
                "X-GitHub-Delivery": "stale-hook-1",
                "X-GitHub-Event": "issues",
            },
        )
        assert response.status_code == 202
        with app.state.database.session_factory() as db:
            delivery = db.scalar(select(WebhookDelivery))
            delivery.status = "processing"
            delivery.locked_at = utcnow() - timedelta(minutes=10)
            db.commit()
        result = client.post("/api/v1/control/run-once").json()
        assert result["webhooks_processed"] == 1
        assert client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]["state"] == "completed"


def test_google_oauth_refresh_token_is_cached_in_memory(tmp_path):
    GoogleOAuthTokenBroker.clear_cache()
    settings = Settings(
        app_env="test",
        data_dir=tmp_path,
        google_oauth_client_id="client",
        google_oauth_client_secret="secret",
        google_oauth_refresh_token="refresh",
    )
    response = httpx.Response(
        200,
        json={"access_token": "fresh-token", "expires_in": 3600},
        request=httpx.Request("POST", settings.google_oauth_token_url),
    )
    with patch("action_hub.credentials.httpx.post", return_value=response) as refresh:
        broker = GoogleOAuthTokenBroker(settings)
        assert broker.get_token() == "fresh-token"
        assert broker.get_token() == "fresh-token"
        assert refresh.call_count == 1


def test_google_calendar_retries_unauthorized_with_refreshed_token(settings):
    from action_hub.connectors.google_calendar import GoogleCalendarConnector

    live = settings.model_copy(update={
        "execution_mode": "live",
        "google_calendar_access_token": "expired",
        "google_oauth_client_id": "client",
        "google_oauth_client_secret": "secret",
        "google_oauth_refresh_token": "refresh",
    })
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        plan = _create(client, "내일 오전 10시 고객 미팅")
        with app.state.database.session_factory() as db:
            item = db.get(ActionItem, plan["items"][0]["id"])
            unauthorized = httpx.Response(401, request=httpx.Request("POST", "https://calendar.example"))
            created = httpx.Response(
                200,
                json={"id": "event-1", "htmlLink": "https://calendar.example/event-1"},
                request=httpx.Request("POST", "https://calendar.example"),
            )
            connector = GoogleCalendarConnector(live)
            with patch.object(connector.token_broker, "get_token", side_effect=["expired", "fresh"]), patch(
                "action_hub.connectors.google_calendar.httpx.post", side_effect=[unauthorized, created]
            ) as post:
                result = connector.execute(item)
            assert result.success is True
            assert post.call_count == 2
            assert post.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer fresh"


def test_github_workflow_and_pull_request_close_the_ai_loop(tmp_path):
    secret = "github-secret"
    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'worker-hooks.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        github_default_repo="owner/repo",
        github_webhook_secret=secret,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        plan = _create(client, "repo:owner/repo 로그인 오류를 codex로 수정")
        item = plan["items"][0]
        client.patch(
            f"/api/v1/plans/{plan['id']}/items/{item['id']}",
            json={"executor": "ai", "preferred_worker": "codex", "needs_review": False},
        )
        _approve(client, plan["id"])
        client.post(f"/api/v1/plans/{plan['id']}/execute", json={})
        dispatched = client.post(
            f"/api/v1/items/{item['id']}/dispatch",
            json={"worker": "codex"},
        )
        assert dispatched.status_code == 200

        def webhook(event: str, action: str, payload: dict, delivery: str):
            body_payload = {"action": action, "repository": {"full_name": "owner/repo"}, **payload}
            body = json.dumps(body_payload, separators=(",", ":")).encode()
            return client.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": _signature(secret, body),
                    "X-GitHub-Delivery": delivery,
                    "X-GitHub-Event": event,
                },
            )

        running = webhook(
            "workflow_run",
            "requested",
            {"workflow_run": {"id": 501, "status": "in_progress", "head_branch": f"action-hub-{item['id']}"}},
            "workflow-1",
        )
        assert running.status_code == 202
        with app.state.database.session_factory() as db:
            execution = db.scalar(select(WorkerExecution))
            assert execution.state == "running"
            assert execution.workflow_run_id == "501"

        success = webhook(
            "workflow_run",
            "completed",
            {"workflow_run": {"id": 501, "status": "completed", "conclusion": "success"}},
            "workflow-2",
        )
        assert success.status_code == 202
        assert client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]["state"] == "human_review"

        opened = webhook(
            "pull_request",
            "opened",
            {
                "number": 12,
                "pull_request": {
                    "number": 12,
                    "title": "Fix login",
                    "body": f"Action-Hub-ID: {item['id']}",
                    "draft": False,
                    "html_url": "https://github.example/owner/repo/pull/12",
                    "head": {"ref": f"action-hub-{item['id']}"},
                },
            },
            "pr-1",
        )
        assert opened.status_code == 202
        merged = webhook(
            "pull_request",
            "closed",
            {
                "number": 12,
                "pull_request": {
                    "number": 12,
                    "title": "Fix login",
                    "body": f"Action-Hub-ID: {item['id']}",
                    "merged": True,
                    "merged_at": "2026-07-29T10:00:00Z",
                    "html_url": "https://github.example/owner/repo/pull/12",
                    "head": {"ref": f"action-hub-{item['id']}"},
                },
            },
            "pr-2",
        )
        assert merged.status_code == 202
        refreshed = client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]
        assert refreshed["state"] == "completed"
        assert refreshed["completion_evidence"].endswith("/pull/12")


def test_rule_suggestion_update_and_meeting_reprocess(client, settings):
    for index in range(3):
        plan = _create(client, f"#proof 반복 업무 {index}")
        item = plan["items"][0]
        response = client.patch(
            f"/api/v1/plans/{plan['id']}/items/{item['id']}",
            json={
                "project": "proof",
                "repository": "owner/proof",
                "estimated_minutes": 90,
                "work_mode": "deep",
                "executor": "ai",
                "preferred_worker": "codex",
            },
        )
        assert response.status_code == 200
    suggested = client.post("/api/v1/rules/suggest")
    assert suggested.status_code == 200
    rule = suggested.json()[0]
    assert rule["status"] == "proposed"
    activated = client.patch(f"/api/v1/rules/{rule['id']}", json={"status": "active", "name": "Proof 자동 기본값"})
    assert activated.status_code == 200
    assert client.get("/api/v1/rules").json()[0]["status"] == "active"

    with client.app.state.database.session_factory() as db:
        intake = MeetingIntake(
            provider="fireflies",
            external_meeting_id="meeting-retry",
            event_type="meeting.summarized",
            status="failed",
        )
        db.add(intake)
        db.commit()
        intake_id = intake.id
    transcript = {
        "data": {
            "transcript": {
                "id": "meeting-retry",
                "title": "재처리 회의",
                "summary": {"action_items": "- 내일 오전 10시 보고서 발송"},
            }
        }
    }
    response = httpx.Response(
        200,
        json=transcript,
        request=httpx.Request("POST", settings.fireflies_graphql_url),
    )
    client.app.state.settings.fireflies_api_key = "test-key"
    with patch("action_hub.services.meetings.httpx.post", return_value=response):
        retried = client.post(f"/api/v1/meetings/{intake_id}/reprocess")
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "plan_created"


def test_control_and_error_endpoints_are_safe(client):
    assert client.get("/readiness").json()["database"] == "ready"
    assert client.post("/api/v1/control/outbox/drain").status_code == 200
    assert client.post("/api/v1/control/webhooks/drain").status_code == 200
    assert client.get("/api/v1/control/webhooks").status_code == 200
    assert client.post("/api/v1/control/reconcile", json={"providers": ["todoist"], "limit": 5}).status_code == 200
    assert client.post("/api/v1/meetings/missing/reprocess").status_code == 404
    assert client.patch("/api/v1/rules/missing", json={"status": "active"}).status_code == 404
    assert client.post("/api/v1/followups/missing/resolve", json={"state": "resolved"}).status_code == 404
    assert client.post("/api/v1/webhooks/unknown", content=b"{}").status_code == 422


def test_concurrent_update_conflict_is_reported_as_409_not_500(client, monkeypatch):
    # Regression for S9: ActionPlan/ActionItem/FocusSession all use
    # version_id_col=revision for optimistic locking (models.py), but there was
    # no StaleDataError handling anywhere in the codebase, so a genuine write
    # race between two overlapping requests fell through to the catch-all
    # Exception handler and came back as an unhelpful 500. Forcing the service
    # call to raise StaleDataError isolates the exception-mapping behavior
    # (main.py's dedicated handler) from the harder problem of deterministically
    # reproducing a real concurrent write race in a single-threaded test.
    from sqlalchemy.orm.exc import StaleDataError

    import action_hub.api.routes as routes_module

    def _raise_stale(*args, **kwargs):
        raise StaleDataError("UPDATE statement matched 0 rows")

    monkeypatch.setattr(routes_module, "update_item", _raise_stale)

    response = client.patch(
        "/api/v1/plans/plan-does-not-matter/items/item-does-not-matter",
        json={"title": "x"},
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "concurrent_update"
    assert detail["message"]


def test_connector_health_probe_in_dry_run(client):
    response = client.get("/api/v1/connectors/status?probe=true")
    assert response.status_code == 200
    statuses = response.json()
    assert {status["name"] for status in statuses} == {
        "todoist",
        "github",
        "google_calendar",
        "local_ics",
        "none",
    }
    assert all(status["healthy"] is True for status in statuses)
    assert all("·" in status["detail"] for status in statuses)


def test_check_suite_updates_worker_without_downgrading_merged_action(tmp_path):
    secret = "github-check-secret"
    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'checks.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        github_default_repo="owner/repo",
        github_webhook_secret=secret,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        plan = _create(client, "repo:owner/repo 로그인 오류를 codex로 수정")
        item = plan["items"][0]
        client.patch(
            f"/api/v1/plans/{plan['id']}/items/{item['id']}",
            json={"executor": "ai", "preferred_worker": "codex", "needs_review": False},
        )
        _approve(client, plan["id"])
        client.post(f"/api/v1/plans/{plan['id']}/execute", json={})
        assert client.post(
            f"/api/v1/items/{item['id']}/dispatch", json={"worker": "codex"}
        ).status_code == 200

        def send(event: str, action: str, payload: dict, delivery: str):
            body = json.dumps(
                {"action": action, "repository": {"full_name": "owner/repo"}, **payload},
                separators=(",", ":"),
            ).encode()
            return client.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": _signature(secret, body),
                    "X-GitHub-Delivery": delivery,
                    "X-GitHub-Event": event,
                },
            )

        check = send(
            "check_suite",
            "completed",
            {
                "check_suite": {
                    "id": 777,
                    "status": "completed",
                    "conclusion": "success",
                    "head_branch": f"action-hub-{item['id']}",
                    "check_runs_url": "https://api.github.example/check-suites/777/runs",
                    "updated_at": "2026-07-29T09:00:00Z",
                    "pull_requests": [],
                }
            },
            "check-1",
        )
        assert check.status_code == 202
        assert client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]["state"] == "human_review"

        merged = send(
            "pull_request",
            "closed",
            {
                "number": 14,
                "pull_request": {
                    "number": 14,
                    "body": f"Action-Hub-ID: {item['id']}",
                    "merged": True,
                    "merged_at": "2026-07-29T10:00:00Z",
                    "html_url": "https://github.example/owner/repo/pull/14",
                    "head": {"ref": f"action-hub-{item['id']}"},
                },
            },
            "pr-check-1",
        )
        assert merged.status_code == 202
        assert client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]["state"] == "completed"

        late = send(
            "check_suite",
            "rerequested",
            {
                "check_suite": {
                    "id": 778,
                    "status": "queued",
                    "conclusion": None,
                    "head_branch": f"action-hub-{item['id']}",
                    "check_runs_url": "https://api.github.example/check-suites/778/runs",
                    "updated_at": "2026-07-29T09:30:00Z",
                    "pull_requests": [{"number": 14}],
                }
            },
            "check-2",
        )
        assert late.status_code == 202
        refreshed = client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]
        assert refreshed["state"] == "completed"
        assert refreshed["completion_evidence"].endswith("/pull/14")
