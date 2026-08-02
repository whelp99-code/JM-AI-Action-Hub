from __future__ import annotations

import base64
import hashlib
import hmac
import json
from sqlalchemy import select

from action_hub.models import ActionItem, ExternalState, SyncConflict
from action_hub.services.reconciliation import reconcile_external_states


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
        database_url=f"sqlite+pysqlite:///{tmp_path / 'todoist-hook.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        todoist_client_secret=secret,
    )
    with TestClient(create_app(settings)) as client:
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
        database_url=f"sqlite+pysqlite:///{tmp_path / 'invalid-hook.db'}",
        data_dir=tmp_path,
        todoist_client_secret="correct-secret",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/webhooks/todoist",
            content=b'{"event_name":"item:updated","event_data":{"id":"1"}}',
            headers={"X-Todoist-Hmac-SHA256": "bad"},
        )
        assert response.status_code == 401


def test_github_close_and_reopen_records_resolved_conflict(tmp_path):
    from fastapi.testclient import TestClient
    from action_hub.config import Settings
    from action_hub.main import create_app

    secret = "github-secret"
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'github-hook.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
        github_webhook_secret=secret,
        github_default_repo="owner/repo",
    )
    app = create_app(settings)
    with TestClient(app) as client:
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
    routed = _approve_execute(client, plan)
    item_id = routed["items"][0]["id"]

    class FakeConnector:
        def fetch_state(self, external_id, item=None):
            return ConnectorSnapshot(success=True, state="completed", external_id=external_id)

    monkeypatch.setattr(ConnectorRegistry, "get", lambda self, name: FakeConnector())
    with client.app.state.database.session_factory() as db:
        result = reconcile_external_states(db, settings, providers=["todoist"])
        assert result["updated"] == 1
    assert client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]["state"] == "completed"
