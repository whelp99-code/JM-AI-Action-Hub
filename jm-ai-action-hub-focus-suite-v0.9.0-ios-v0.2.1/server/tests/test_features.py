from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone


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


def _route(client, plan):
    client.post(f"/api/v1/plans/{plan['id']}/approve", json={"force_review_items": True})
    return client.post(f"/api/v1/plans/{plan['id']}/execute", json={}).json()


def test_ai_worker_dispatch_uses_existing_github_action_layer(client):
    plan = _create(client, "repo:whelp99-code/Proof-Graph 로그인 오류를 codex로 수정")
    item = plan["items"][0]
    client.patch(
        f"/api/v1/plans/{plan['id']}/items/{item['id']}",
        json={"executor": "ai", "preferred_worker": "codex", "needs_review": False},
    )
    routed = _route(client, client.get(f"/api/v1/plans/{plan['id']}").json())
    item = routed["items"][0]
    response = client.post(
        f"/api/v1/items/{item['id']}/dispatch",
        json={"worker": "codex", "actor": "tester"},
    )
    assert response.status_code == 200, response.text
    execution = response.json()
    assert execution["state"] == "dispatched"
    assert execution["dispatch_id"].startswith("dry-codex-")
    refreshed = client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]
    assert refreshed["state"] == "dispatched"
    assert len(refreshed["worker_executions"]) == 1


def test_followup_lifecycle_and_due_processing(client):
    plan = _create(client, "협력사 회신 확인")
    item = plan["items"][0]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = client.post(
        f"/api/v1/items/{item['id']}/followups",
        json={"waiting_for": "협력사", "channel": "email", "follow_up_at": past},
    )
    assert created.status_code == 200, created.text
    followup = created.json()
    processed = client.post("/api/v1/followups/process-due")
    assert processed.json()["followups_due"] == 1
    due = client.get("/api/v1/followups/due").json()
    assert due[0]["state"] == "follow_up_due"
    resolved = client.post(
        f"/api/v1/followups/{followup['id']}/resolve",
        json={"state": "response_received", "note": "견적 회신 도착"},
    )
    assert resolved.status_code == 200
    refreshed = client.get(f"/api/v1/plans/{plan['id']}").json()["items"][0]
    assert refreshed["state"] == "human_review"


def test_decision_plan_detects_capacity_overload(client):
    for index in range(3):
        plan = _create(client, f"오늘 오후 6시까지 중요 보고서 {index + 1} 작성")
        item = plan["items"][0]
        client.patch(
            f"/api/v1/plans/{plan['id']}/items/{item['id']}",
            json={"estimated_minutes": 120, "priority": 4},
        )
    response = client.post(
        "/api/v1/planning/decision",
        json={"target_date": "2026-07-28", "available_minutes": 240, "max_items": 10},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["buffer_minutes"] > 0
    assert body["overload_minutes"] > 0
    assert len(body["top_items"]) < 3
    assert any("초과" in risk for risk in body["risks"])


def test_active_personal_rule_applies_only_safe_metadata(client):
    response = client.post(
        "/api/v1/rules",
        json={
            "name": "Proof 기본 규칙",
            "condition": {"project": "proof"},
            "action": {
                "estimated_minutes": 90,
                "work_mode": "deep",
                "executor": "ai",
                "preferred_worker": "codex",
            },
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    plan = _create(client, "#proof 로그인 흐름 개선")
    item = plan["items"][0]
    assert item["estimated_minutes"] == 90
    assert item["work_mode"] == "deep"
    assert item["executor"] == "ai"
    unsafe = client.post(
        "/api/v1/rules",
        json={"name": "위험", "condition": {"project": "proof"}, "action": {"state": "completed"}},
    )
    assert unsafe.status_code == 422


def test_fireflies_v2_webhook_creates_review_plan(tmp_path):
    from fastapi.testclient import TestClient
    from action_hub.config import Settings
    from action_hub.main import create_app

    secret = "fireflies-secret"
    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'fireflies.db'}",
        data_dir=tmp_path,
        fireflies_webhook_secret=secret,
    )
    payload = {
        "event": "meeting.summarized",
        "timestamp": 1785300000000,
        "meeting_id": "meeting-123",
        "transcript": {
            "title": "HCI 고객 회의",
            "transcript_url": "https://fireflies.example/meeting-123",
            "summary": {
                "overview": "고객 요구사항 검토",
                "action_items": "- 내일 오전 10시 고객에게 견적서 발송\n- repo:owner/repo GPU 오류 수정",
            },
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/webhooks/fireflies",
            content=body,
            headers={"X-Hub-Signature": signature, "Content-Type": "application/json"},
        )
        assert response.status_code == 202, response.text
        meetings = client.get("/api/v1/meetings").json()
        assert meetings[0]["status"] == "plan_created"
        assert meetings[0]["action_plan_id"] is not None
        plan = client.get(f"/api/v1/plans/{meetings[0]['action_plan_id']}").json()
        assert len(plan["items"]) == 2
        assert all(item["state"] == "draft" for item in plan["items"])


def test_weekly_report_exposes_measured_estimates(client):
    plan = _create(client, "내일 오후 3시까지 제안서 작성")
    _route(client, plan)
    report = client.get("/api/v1/reports/weekly").json()
    assert report["registered_actions"] >= 1
    assert report["estimated_minutes_saved"] >= 1
    assert report["summary"]
