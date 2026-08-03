from __future__ import annotations

import base64
import hashlib
import hmac
import json

from sqlalchemy import select

from action_hub.models import (
    ActionItem,
    AuditEvent,
    ExternalState,
    MobileDevice,
    PushNotification,
    SyncConflict,
    WebhookDelivery,
    WorkerExecution,
)
from action_hub.services.reconciliation import reconcile_external_states
from action_hub.services.webhooks import process_webhook_batch

TEST_API_KEY = "test-api-key-" + ("x" * 32)


def _create(client, text: str):
    response = client.post(
        "/api/v1/inbox/parse",
        json={
            "text": text,
            "reference_time": "2026-07-28T19:00:00+09:00",
            "timezone": "Asia/Seoul",
            "force_new": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approve_execute(client, plan):
    client.post(f"/api/v1/plans/{plan['id']}/approve", json={"actor": "test"})
    response = client.post(f"/api/v1/plans/{plan['id']}/execute", json={"actor": "test"})
    assert response.status_code == 200, response.text
    return response.json()


def _todoist_signature(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def _hex_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _github_check_suite_payload(action_item_id: str) -> dict:
    return {
        "action": "completed",
        "repository": {"full_name": "owner/repo"},
        "check_suite": {
            "id": 501,
            "status": "completed",
            "conclusion": "success",
            "head_branch": f"action-hub-{action_item_id}",
            "check_runs_url": "https://github.example/owner/repo/checks/501",
            "updated_at": "2026-07-29T08:00:00Z",
        },
    }


def _prepare_github_check_suite_target(app) -> tuple[str, str]:
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = app.state.settings.api_key
        plan = _create(client, "repo:owner/repo 로그인 오류를 codex로 수정")
    item_id = plan["items"][0]["id"]
    with app.state.database.session_factory() as db:
        execution = WorkerExecution(
            action_item_id=item_id,
            worker="codex",
            state="running",
            repository="owner/repo",
        )
        device = MobileDevice(
            device_name="queued-webhook-test-device",
            push_token=f"queued-webhook-test-token-{item_id}",
        )
        db.add(execution)
        db.add(device)
        db.commit()
        return item_id, execution.id


def _queue_github_check_suite_delivery(app, action_item_id: str, secret: str | None = None) -> str:
    from fastapi.testclient import TestClient

    body = json.dumps(_github_check_suite_payload(action_item_id), separators=(",", ":")).encode()
    headers = {
        "X-GitHub-Delivery": f"check-suite-{action_item_id}",
        "X-GitHub-Event": "check_suite",
    }
    if secret:
        headers["X-Hub-Signature-256"] = _hex_signature(secret, body)
    with TestClient(app) as client:
        response = client.post("/api/v1/webhooks/github", content=body, headers=headers)
        assert response.status_code == 202, response.text
        assert response.json()["duplicate"] is False
    with app.state.database.session_factory() as db:
        delivery = db.scalar(select(WebhookDelivery))
        assert delivery is not None
        assert delivery.status == "pending"
        assert delivery.signature_valid is bool(secret)
        return delivery.id


def _github_check_suite_domain_state(db, item_id: str, execution_id: str) -> tuple:
    item = db.get(ActionItem, item_id)
    execution = db.get(WorkerExecution, execution_id)
    assert item is not None
    assert execution is not None
    return (
        item.state,
        execution.state,
        execution.workflow_run_id,
        execution.output_summary,
        len(
            list(
                db.scalars(
                    select(ExternalState).where(
                        ExternalState.action_item_id == item_id,
                        ExternalState.provider == "github_check_suite",
                    )
                )
            )
        ),
        len(
            list(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.entity_id == execution_id,
                        AuditEvent.event_type == "worker.check_suite_updated",
                    )
                )
            )
        ),
        len(list(db.scalars(select(PushNotification)))),
    )


def test_outbox_registration_separates_routing_from_completion(client):
    plan = _create(client, "내일 오후 3시까지 제안서 작성")
    result = _approve_execute(client, plan)
    assert result["completed"] == 1  # v0.1 compatibility: successful routing
    assert result["registered"] == 1
    assert result["action_completed"] == 0
    item = result["items"][0]
    assert item["state"] == "registered"
    assert item["registered_at"] is not None
    assert item["completed_at"] is None
    assert item["external_states"][0]["state"] == "open"


def test_todoist_signed_webhook_completes_and_deduplicates(tmp_path):
    from fastapi.testclient import TestClient

    from action_hub.config import Settings
    from action_hub.main import create_app

    secret = "todoist-secret"
    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'todoist-hook.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        todoist_client_secret=secret,
    )
    with TestClient(create_app(settings)) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        plan = _create(client, "내일 오후 3시까지 제안서 작성")
        routed = _approve_execute(client, plan)
        item = routed["items"][0]
        payload = {
            "event_name": "item:completed",
            "event_data": {"id": item["external_id"], "completed_at": "2026-07-29T07:00:00Z"},
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Todoist-Hmac-SHA256": _todoist_signature(secret, body),
            "X-Todoist-Delivery-ID": "todoist-delivery-1",
        }
        first = client.post("/api/v1/webhooks/todoist", content=body, headers=headers)
        second = client.post("/api/v1/webhooks/todoist", content=body, headers=headers)
        assert first.status_code == 202
        assert first.json()["duplicate"] is False
        assert second.json()["duplicate"] is True
        refreshed = client.get(f"/api/v1/plans/{plan['id']}").json()
        assert refreshed["items"][0]["state"] == "completed"
        assert refreshed["status"] == "completed"


def test_invalid_webhook_signature_is_rejected(tmp_path):
    from fastapi.testclient import TestClient

    from action_hub.config import Settings
    from action_hub.main import create_app

    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'invalid-hook.db'}",
        data_dir=tmp_path,
        todoist_client_secret="correct-secret",
        allow_unsigned_webhooks=True,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        response = client.post(
            "/api/v1/webhooks/todoist",
            content=b'{"event_name":"item:updated","event_data":{"id":"1"}}',
            headers={"X-Todoist-Hmac-SHA256": "bad"},
        )
        assert response.status_code == 401
    with app.state.database.session_factory() as db:
        assert db.scalar(select(WebhookDelivery)) is None


def test_missing_webhook_secret_requires_explicit_opt_in_without_delivery(tmp_path):
    from fastapi.testclient import TestClient

    from action_hub.config import Settings
    from action_hub.main import create_app

    for app_env in ("development", "test"):
        settings = Settings(
            app_env=app_env,
            api_key=TEST_API_KEY,
            database_url=f"sqlite+pysqlite:///{tmp_path / f'{app_env}-unsigned-disabled.db'}",
            data_dir=tmp_path / f"{app_env}-unsigned-disabled",
            worker_inline=False,
        )
        app = create_app(settings)
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/webhooks/todoist",
                content=b'{"event_name":"item:updated","event_data":{"id":"1"}}',
            )
            assert response.status_code == 503
        with app.state.database.session_factory() as db:
            assert db.scalar(select(WebhookDelivery)) is None


def test_unsigned_webhook_opt_in_is_non_production_only(tmp_path):
    from fastapi.testclient import TestClient

    from action_hub.config import Settings
    from action_hub.main import create_app

    body = b'{"event_name":"item:updated","event_data":{"id":"1"}}'
    for app_env in ("development", "test"):
        settings = Settings(
            app_env=app_env,
            api_key=TEST_API_KEY,
            database_url=f"sqlite+pysqlite:///{tmp_path / f'{app_env}-unsigned-enabled.db'}",
            data_dir=tmp_path / f"{app_env}-unsigned-enabled",
            allow_unsigned_webhooks=True,
            worker_inline=False,
        )
        app = create_app(settings)
        with TestClient(app) as client:
            response = client.post("/api/v1/webhooks/todoist", content=body)
            assert response.status_code == 202
        with app.state.database.session_factory() as db:
            delivery = db.scalar(select(WebhookDelivery))
            assert delivery is not None
            assert delivery.status == "pending"
            assert delivery.signature_valid is False

    settings = Settings(
        app_env="production",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'production-unsigned-enabled.db'}",
        data_dir=tmp_path / "production-unsigned-enabled",
        allow_unsigned_webhooks=True,
        worker_inline=False,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/api/v1/webhooks/todoist", content=body)
        assert response.status_code == 503
    with app.state.database.session_factory() as db:
        assert db.scalar(select(WebhookDelivery)) is None


def test_queued_unsigned_github_webhook_is_rejected_after_production_switch(tmp_path):
    from action_hub.config import Settings
    from action_hub.main import create_app

    development_settings = Settings(
        app_env="development",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'queued-unsigned-production.db'}",
        data_dir=tmp_path / "queued-unsigned-production",
        allow_unsigned_webhooks=True,
        worker_inline=False,
    )
    app = create_app(development_settings)
    item_id, execution_id = _prepare_github_check_suite_target(app)
    delivery_id = _queue_github_check_suite_delivery(app, item_id)

    production_settings = development_settings.model_copy(update={"app_env": "production"})
    with app.state.database.session_factory() as db:
        before = _github_check_suite_domain_state(db, item_id, execution_id)
        result = process_webhook_batch(db, production_settings, delivery_ids=[delivery_id])
        delivery = db.get(WebhookDelivery, delivery_id)
        assert result == {"processed": 1, "completed": 0, "failed": 1, "unmatched": 0, "ignored": 0}
        assert delivery is not None
        assert delivery.status == "retry"
        assert delivery.error == "Unsigned webhook delivery is not permitted by current policy"
        assert _github_check_suite_domain_state(db, item_id, execution_id) == before


def test_queued_unsigned_github_webhook_is_rejected_when_opt_in_is_disabled(tmp_path):
    from action_hub.config import Settings
    from action_hub.main import create_app

    opted_in_settings = Settings(
        app_env="development",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'queued-unsigned-disabled.db'}",
        data_dir=tmp_path / "queued-unsigned-disabled",
        allow_unsigned_webhooks=True,
        worker_inline=False,
    )
    app = create_app(opted_in_settings)
    item_id, execution_id = _prepare_github_check_suite_target(app)
    delivery_id = _queue_github_check_suite_delivery(app, item_id)

    disabled_settings = opted_in_settings.model_copy(update={"allow_unsigned_webhooks": False})
    with app.state.database.session_factory() as db:
        before = _github_check_suite_domain_state(db, item_id, execution_id)
        result = process_webhook_batch(db, disabled_settings, delivery_ids=[delivery_id])
        delivery = db.get(WebhookDelivery, delivery_id)
        assert result == {"processed": 1, "completed": 0, "failed": 1, "unmatched": 0, "ignored": 0}
        assert delivery is not None
        assert delivery.status == "retry"
        assert _github_check_suite_domain_state(db, item_id, execution_id) == before


def test_queued_unsigned_github_webhook_processes_while_opt_in_remains_enabled(tmp_path):
    from action_hub.config import Settings
    from action_hub.main import create_app

    settings = Settings(
        app_env="development",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'queued-unsigned-enabled.db'}",
        data_dir=tmp_path / "queued-unsigned-enabled",
        allow_unsigned_webhooks=True,
        worker_inline=False,
    )
    app = create_app(settings)
    item_id, execution_id = _prepare_github_check_suite_target(app)
    delivery_id = _queue_github_check_suite_delivery(app, item_id)

    with app.state.database.session_factory() as db:
        result = process_webhook_batch(db, settings, delivery_ids=[delivery_id])
        delivery = db.get(WebhookDelivery, delivery_id)
        assert result == {"processed": 1, "completed": 1, "failed": 0, "unmatched": 0, "ignored": 0}
        assert delivery is not None
        assert delivery.status == "processed"
        assert _github_check_suite_domain_state(db, item_id, execution_id) == (
            "human_review",
            "human_review",
            None,
            "Check suite completed: success; human review required.",
            1,
            1,
            1,
        )


def test_queued_signed_github_webhook_processes_in_production(tmp_path):
    from action_hub.config import Settings
    from action_hub.main import create_app

    secret = "github-webhook-secret"
    settings = Settings(
        app_env="production",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'queued-signed-production.db'}",
        data_dir=tmp_path / "queued-signed-production",
        github_webhook_secret=secret,
        worker_inline=False,
    )
    app = create_app(settings)
    item_id, execution_id = _prepare_github_check_suite_target(app)
    delivery_id = _queue_github_check_suite_delivery(app, item_id, secret)

    with app.state.database.session_factory() as db:
        result = process_webhook_batch(db, settings, delivery_ids=[delivery_id])
        delivery = db.get(WebhookDelivery, delivery_id)
        assert result == {"processed": 1, "completed": 1, "failed": 0, "unmatched": 0, "ignored": 0}
        assert delivery is not None
        assert delivery.signature_valid is True
        assert delivery.status == "processed"
        assert _github_check_suite_domain_state(db, item_id, execution_id) == (
            "human_review",
            "human_review",
            None,
            "Check suite completed: success; human review required.",
            1,
            1,
            1,
        )


def test_github_close_and_reopen_records_resolved_conflict(tmp_path):
    from fastapi.testclient import TestClient

    from action_hub.config import Settings
    from action_hub.main import create_app

    secret = "github-secret"
    settings = Settings(
        app_env="test",
        api_key=TEST_API_KEY,
        database_url=f"sqlite+pysqlite:///{tmp_path / 'github-hook.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        github_webhook_secret=secret,
        github_default_repo="owner/repo",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["X-Action-Hub-Key"] = settings.api_key
        plan = _create(client, "repo:owner/repo 로그인 오류 수정")
        routed = _approve_execute(client, plan)
        item_id = routed["items"][0]["id"]
        with app.state.database.session_factory() as db:
            item = db.get(ActionItem, item_id)
            mirror = db.scalar(select(ExternalState).where(ExternalState.action_item_id == item_id))
            item.external_id = "42"
            mirror.external_id = "owner/repo#42"
            db.commit()

        def send(action: str, state: str, delivery: str):
            payload = {
                "action": action,
                "repository": {"full_name": "owner/repo"},
                "issue": {
                    "number": 42,
                    "state": state,
                    "html_url": "https://github.example/owner/repo/issues/42",
                    "updated_at": "2026-07-29T08:00:00Z" if action == "closed" else "2026-07-29T09:00:00Z",
                },
            }
            body = json.dumps(payload, separators=(",", ":")).encode()
            return client.post(
                "/api/v1/webhooks/github",
                content=body,
                headers={
                    "X-Hub-Signature-256": _hex_signature(secret, body),
                    "X-GitHub-Delivery": delivery,
                    "X-GitHub-Event": "issues",
                },
            )

        assert send("closed", "closed", "g1").status_code == 202
        assert client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]["state"] == "completed"
        assert send("reopened", "open", "g2").status_code == 202
        refreshed = client.get(f"/api/v1/plans/{plan['id']}").json()
        assert refreshed["items"][0]["state"] == "registered"
        with app.state.database.session_factory() as db:
            conflict = db.scalar(select(SyncConflict).where(SyncConflict.action_item_id == item_id))
            assert conflict is not None
            assert conflict.resolution == "external_source_wins"


def test_reconciliation_updates_state_and_is_non_destructive_on_missing(client, settings, monkeypatch):
    from action_hub.connectors.base import ConnectorSnapshot
    from action_hub.connectors.registry import ConnectorRegistry

    plan = _create(client, "내일 오후 3시까지 제안서 작성")
    _approve_execute(client, plan)

    class FakeConnector:
        def fetch_state(self, external_id, item=None):
            return ConnectorSnapshot(success=True, state="completed", external_id=external_id)

    monkeypatch.setattr(ConnectorRegistry, "get", lambda self, name: FakeConnector())
    with client.app.state.database.session_factory() as db:
        result = reconcile_external_states(db, settings, providers=["todoist"])
        assert result["updated"] == 1
    assert client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]["state"] == "completed"
