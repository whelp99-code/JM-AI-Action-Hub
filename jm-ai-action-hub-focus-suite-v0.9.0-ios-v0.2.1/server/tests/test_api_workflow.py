import json
from pathlib import Path

from fastapi.testclient import TestClient

from action_hub.main import create_app


def create_plan(client, text, force_new=False):
    response = client.post(
        "/api/v1/inbox/parse",
        json={
            "text": text,
            "source": "test",
            "timezone": "Asia/Seoul",
            "reference_time": "2026-07-28T19:00:00+09:00",
            "force_new": force_new,
        },
    )
    assert response.status_code in (200, 201), response.text
    return response.json(), response


def test_health_and_pwa(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/").status_code == 200
    assert "Action Hub" in client.get("/").text
    assert client.get("/manifest.webmanifest").status_code == 200


def test_parse_approve_execute_dry_run(client, settings):
    plan, _ = create_plan(client, "내일 오전 10시 고객 미팅\n내일 오후 3시까지 제안서 작성")
    assert len(plan["items"]) == 2
    assert all(not item["needs_review"] for item in plan["items"])

    approved = client.post(
        f"/api/v1/plans/{plan['id']}/approve",
        json={"item_ids": [x["id"] for x in plan["items"]], "actor": "tester"},
    )
    assert approved.status_code == 200
    assert all(x["state"] == "approved" for x in approved.json()["items"])

    executed = client.post(
        f"/api/v1/plans/{plan['id']}/execute",
        json={"actor": "tester"},
    )
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["completed"] == 2
    event = next(x for x in body["items"] if x["item_type"] == "event")
    assert event["external_url"].startswith("/api/v1/exports/")
    assert (Path(settings.data_dir) / "exports" / f"{event['id']}.ics").exists()
    downloaded = client.get(event["external_url"])
    assert downloaded.status_code == 200
    assert "BEGIN:VCALENDAR" in downloaded.text
    assert downloaded.headers["Cache-Control"] == "private, no-store"


def test_review_gate(client):
    plan, _ = create_plan(client, "내일 고객 미팅")
    item = plan["items"][0]
    assert item["needs_review"] is True
    blocked = client.post(
        f"/api/v1/plans/{plan['id']}/approve",
        json={"item_ids": [item["id"]], "actor": "tester", "force_review_items": False},
    ).json()
    assert blocked["items"][0]["state"] == "draft"
    forced = client.post(
        f"/api/v1/plans/{plan['id']}/approve",
        json={"item_ids": [item["id"]], "actor": "tester", "force_review_items": True},
    ).json()
    assert forced["items"][0]["state"] == "approved"


def test_inbox_and_action_idempotency(client):
    text = "내일 오후 2시까지 API 문서 검토"
    first, first_response = create_plan(client, text)
    second, second_response = create_plan(client, text)
    assert first["id"] == second["id"]
    assert second_response.headers["X-Action-Hub-Deduplicated"] == "true"

    client.post(f"/api/v1/plans/{first['id']}/approve", json={"actor": "tester"})
    client.post(f"/api/v1/plans/{first['id']}/execute", json={"actor": "tester"})

    duplicate_plan, _ = create_plan(client, text, force_new=True)
    client.post(f"/api/v1/plans/{duplicate_plan['id']}/approve", json={"actor": "tester"})
    executed = client.post(f"/api/v1/plans/{duplicate_plan['id']}/execute", json={"actor": "tester"}).json()
    assert executed["skipped_duplicate"] == 1


def test_update_item_clears_review(client):
    plan, _ = create_plan(client, "내일 고객 미팅")
    item = plan["items"][0]
    updated = client.patch(
        f"/api/v1/plans/{plan['id']}/items/{item['id']}",
        json={"start_at": "2026-07-29T10:00:00+09:00", "needs_review": False, "review_reason": None},
    )
    assert updated.status_code == 200
    assert updated.json()["items"][0]["needs_review"] is False


def test_daily_brief(client):
    plan, _ = create_plan(client, "오늘 오후 8시까지 보고서 작성")
    brief = client.get("/api/v1/brief/today?at=2026-07-28T19:00:00%2B09:00")
    assert brief.status_code == 200
    assert len(brief.json()["due_tasks"]) == 1


def test_force_new_always_creates_unique_inbox(client):
    first, _ = create_plan(client, "내일 오후 2시까지 검토", force_new=True)
    second, _ = create_plan(client, "내일 오후 2시까지 검토", force_new=True)
    assert first["id"] != second["id"]
    assert first["inbox_id"] != second["inbox_id"]


def test_client_cannot_clear_structural_calendar_review(client):
    plan, _ = create_plan(client, "고객 미팅")
    item = plan["items"][0]
    assert item["start_at"] is None
    updated = client.patch(
        f"/api/v1/plans/{plan['id']}/items/{item['id']}",
        json={"needs_review": False, "review_reason": None},
    )
    assert updated.status_code == 200
    body = updated.json()["items"][0]
    assert body["needs_review"] is True
    assert "시작 시간이 없음" in body["review_reason"]


def test_invalid_github_repository_is_blocked(client):
    plan, _ = create_plan(client, "repo:whelp99-code/Proof-Graph 로그인 버그 수정")
    item = plan["items"][0]
    updated = client.patch(
        f"/api/v1/plans/{plan['id']}/items/{item['id']}",
        json={"repository": "invalid", "needs_review": False, "review_reason": None},
    ).json()
    changed = updated["items"][0]
    assert changed["needs_review"] is True
    blocked = client.post(
        f"/api/v1/plans/{plan['id']}/approve",
        json={"item_ids": [item["id"]], "force_review_items": False},
    ).json()
    assert blocked["items"][0]["state"] == "draft"


def test_pwa_post_share_target_keeps_text_out_of_url(client):
    response = client.post(
        "/share-target",
        content="title=%EA%B3%A0%EA%B0%9D+%EC%9A%94%EC%B2%AD&text=%EB%82%B4%EC%9D%BC+10%EC%8B%9C+%EB%AF%B8%ED%8C%85",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200
    assert "id='sharedPayload'" in response.text
    assert "src='/static/share-target.js'" in response.text
    assert "sessionStorage.setItem" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]


def test_share_target_rejects_get_query_payload(client):
    response = client.get('/share-target?text=sensitive-source-text', follow_redirects=False)
    assert response.status_code == 405
    assert 'location' not in {key.lower() for key in response.headers}


def test_execute_reports_retrying_items_and_errors_instead_of_hiding_failure(settings):
    # Regression for P0-2: services/outbox.py:_mark_retry keeps the item state
    # QUEUED (not FAILED) while a retry is pending, so the old summary counted
    # it as an ordinary in-flight item and reported {"failed": 0}, which read as
    # unconditional success even though the connector never ran. execution_mode
    # "live" with no GITHUB_TOKEN configured makes the connector fail
    # deterministically without any network mocking.
    live_settings = settings.model_copy(update={"execution_mode": "live"})
    with TestClient(create_app(live_settings)) as live_client:
        live_client.headers["X-Action-Hub-Key"] = live_settings.api_key
        plan, _ = create_plan(live_client, "repo:owner/repo 로그인 오류를 codex로 수정")
        item = plan["items"][0]
        assert item["destination"] == "github"
        approved = live_client.post(f"/api/v1/plans/{plan['id']}/approve", json={"actor": "tester"})
        assert approved.status_code == 200, approved.text
        executed = live_client.post(f"/api/v1/plans/{plan['id']}/execute", json={"actor": "tester"})

    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["failed"] == 0
    assert body["queued"] == 1
    assert body["retrying"] == 1
    assert len(body["errors"]) == 1
    error = body["errors"][0]
    assert error["item_id"] == item["id"]
    assert error["title"] == item["title"]
    assert "GITHUB_TOKEN" in error["error"]
    assert error["attempts"] >= 1
    stuck_item = next(x for x in body["items"] if x["id"] == item["id"])
    assert stuck_item["state"] == "queued"
    assert stuck_item["execution_error"]


def test_execution_error_masks_bearer_and_key_value_secrets():
    # P0-2's brief requires that execution_error text reaching the client never
    # carries a credential. Connectors generally don't echo secrets today, but
    # the masking must hold if one ever does (e.g. a future connector or a
    # provider that reflects the request back in an error body).
    from action_hub.services.executor import _mask_secrets

    assert _mask_secrets("401 Unauthorized: Bearer ghp_ABCDEFGHIJKLMNOPQRSTUVWX") == "401 Unauthorized: Bearer ***"
    assert _mask_secrets("token=sk-abcdefghijklmnop rejected") == "token=*** rejected"
    assert _mask_secrets("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345 is invalid") == "*** is invalid"
    assert _mask_secrets("resource not found") == "resource not found"


def test_updated_destination_does_not_leak_enum_repr_into_audit_or_activity(client):
    # Regression for S17: update_item()'s audit payload used str(v) on the raw
    # patch values, and LegacyStringEnum.__str__ deliberately returns
    # "Destination.GITHUB" for v0.1 string-enum compatibility (see
    # test_features.py:test_string_enums_preserve_legacy_string_and_value_contracts).
    # That repr then leaked verbatim into the mobile activity feed subtitle via
    # services/mobile.py:_activity_title -> payload.get("destination").
    plan, _ = create_plan(client, "제안서 정리")
    item = plan["items"][0]
    assert item["destination"] != "github"
    updated = client.patch(
        f"/api/v1/plans/{plan['id']}/items/{item['id']}",
        json={"destination": "github", "repository": "owner/repo"},
    )
    assert updated.status_code == 200, updated.text

    audit = client.get("/api/v1/audit", params={"entity_id": item["id"]}).json()
    changed_event = next(row for row in audit if row["event_type"] == "item.updated")
    assert changed_event["payload"]["destination"] == "github"
    assert "Destination." not in json.dumps(changed_event["payload"])
