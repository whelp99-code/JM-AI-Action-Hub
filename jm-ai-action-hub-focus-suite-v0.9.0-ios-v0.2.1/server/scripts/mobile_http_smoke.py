#!/usr/bin/env python3
"""Run a destructive mobile API smoke test against a non-production Action Hub instance."""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime

import httpx


def require(response: httpx.Response, expected: int | set[int]) -> dict | list | None:
    allowed = {expected} if isinstance(expected, int) else expected
    if response.status_code not in allowed:
        raise RuntimeError(
            f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text}"
        )
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8787")
    parser.add_argument("--admin-key", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    admin = {"X-Action-Hub-Key": args.admin_key}

    with httpx.Client(timeout=20.0) as client:
        capabilities = require(client.get(f"{base}/api/v1/mobile/capabilities"), 200)
        pairing = require(
            client.post(
                f"{base}/api/v1/mobile/pairings",
                headers=admin,
                json={"created_by": "mobile-http-smoke", "public_base_url": base},
            ),
            201,
        )
        tokens = require(
            client.post(
                f"{base}/api/v1/mobile/pairings/claim",
                json={
                    "pairing_id": pairing["pairing_id"],
                    "code": pairing["code"],
                    "device_name": "HTTP Mobile Smoke",
                    "hardware_model": "smoke-runner",
                    "os_version": "integration",
                    "app_version": "0.2.1",
                    "push_environment": "sandbox",
                },
            ),
            200,
        )
        bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
        before = require(client.get(f"{base}/api/v1/mobile/dashboard", headers=bearer), 200)
        capture_id = str(uuid.uuid4())
        uploaded = require(
            client.post(
                f"{base}/api/v1/mobile/captures/batch",
                headers=bearer,
                json={
                    "captures": [
                        {
                            "client_capture_id": capture_id,
                            "text": "내일 오전 10시 모바일 E2E 미팅, 미팅 전에 API 계약 확인",
                            "source": "mobile-http-smoke",
                            "timezone": "Asia/Seoul",
                            "reference_time": datetime.now(UTC).isoformat(),
                        }
                    ]
                },
            ),
            200,
        )
        receipt = uploaded["receipts"][0]
        plan_id = receipt["plan_id"]
        plan = require(client.get(f"{base}/api/v1/mobile/plans/{plan_id}", headers=bearer), 200)
        item = plan["items"][0]
        stale = client.patch(
            f"{base}/api/v1/mobile/plans/{plan_id}/items/{item['id']}",
            headers=bearer,
            json={"expected_revision": item["revision"] + 1, "title": "stale"},
        )
        require(stale, 409)
        plan = require(
            client.patch(
                f"{base}/api/v1/mobile/plans/{plan_id}/items/{item['id']}",
                headers=bearer,
                json={
                    "expected_revision": item["revision"],
                    "title": f"모바일 E2E: {item['title']}",
                },
            ),
            200,
        )
        plan = require(
            client.post(
                f"{base}/api/v1/mobile/plans/{plan_id}/approve",
                headers=bearer,
                json={
                    "expected_plan_revision": plan["revision"],
                    "force_review_items": True,
                },
            ),
            200,
        )
        execution = require(
            client.post(
                f"{base}/api/v1/mobile/plans/{plan_id}/execute",
                headers=bearer,
                json={"expected_plan_revision": plan["revision"]},
            ),
            200,
        )
        focus_item_id = plan["items"][0]["id"]
        classified = require(
            client.post(
                f"{base}/api/v1/mobile/actions/{focus_item_id}/classify",
                headers=bearer,
                json={"quadrant": "q1", "reason": "HTTP E2E 분류", "actor": "mobile-http-smoke"},
            ),
            200,
        )
        commitments = require(
            client.post(
                f"{base}/api/v1/mobile/commitments",
                headers=bearer,
                json={
                    "human_item_ids": [focus_item_id],
                    "ai_item_ids": [],
                    "available_minutes": 240,
                    "actor": "mobile-http-smoke",
                },
            ),
            200,
        )
        microsteps = require(
            client.post(
                f"{base}/api/v1/mobile/actions/{focus_item_id}/decompose",
                headers=bearer,
                json={"max_steps": 4, "replace_existing": True, "actor": "mobile-http-smoke"},
            ),
            200,
        )
        focus = require(
            client.post(
                f"{base}/api/v1/mobile/focus-sessions",
                headers=bearer,
                json={"action_item_id": focus_item_id, "planned_minutes": 10, "actor": "mobile-http-smoke"},
            ),
            {200, 201},
        )
        for action in ("pause", "resume"):
            focus = require(
                client.patch(
                    f"{base}/api/v1/mobile/focus-sessions/{focus['id']}",
                    headers=bearer,
                    json={"action": action, "expected_revision": focus["revision"], "actor": "mobile-http-smoke"},
                ),
                200,
            )
        focus = require(
            client.patch(
                f"{base}/api/v1/mobile/focus-sessions/{focus['id']}",
                headers=bearer,
                json={
                    "action": "complete",
                    "expected_revision": focus["revision"],
                    "completion_note": "HTTP E2E 완료 증거",
                    "mark_action_completed": True,
                    "actor": "mobile-http-smoke",
                },
            ),
            200,
        )
        matrix = require(client.get(f"{base}/api/v1/mobile/matrix", headers=bearer), 200)
        focus_report = require(
            client.get(f"{base}/api/v1/mobile/reports/focus-weekly", headers=bearer), 200
        )
        changes = require(client.get(f"{base}/api/v1/mobile/changes?limit=100", headers=bearer), 200)
        activity = require(client.get(f"{base}/api/v1/mobile/activity?limit=100", headers=bearer), 200)

        push_token = "ab" * 32
        require(
            client.post(
                f"{base}/api/v1/mobile/devices/me/push-token",
                headers=bearer,
                json={"token": push_token, "environment": "sandbox"},
            ),
            200,
        )
        require(
            client.post(
                f"{base}/api/v1/mobile/devices/me/push-test",
                headers=bearer,
                json={"event_type": "test", "entity_type": "device", "entity_id": "smoke"},
            ),
            202,
        )
        push_drain = require(client.post(f"{base}/api/v1/control/push/drain", headers=admin), 200)
        pushes = require(client.get(f"{base}/api/v1/mobile/devices/me/pushes", headers=bearer), 200)
        after = require(client.get(f"{base}/api/v1/mobile/dashboard", headers=bearer), 200)

        require(client.delete(f"{base}/api/v1/mobile/devices/me", headers=bearer), 204)
        denied = client.get(f"{base}/api/v1/mobile/dashboard", headers=bearer)
        require(denied, 401)
        refresh_denied = client.post(
            f"{base}/api/v1/mobile/token/refresh",
            json={"refresh_token": tokens["refresh_token"]},
        )
        require(refresh_denied, 401)

    print(
        json.dumps(
            {
                "status": "ok",
                "server_version": capabilities["server_version"],
                "device_id": tokens["device"]["id"],
                "plan_id": plan_id,
                "capture_status": receipt["status"],
                "stale_revision_status": stale.status_code,
                "execution_completed": execution["completed"],
                "execution_failed": execution["failed"],
                "changes": len(changes["changes"]),
                "activity": len(activity),
                "push_processed": push_drain["push_processed"],
                "push_state": pushes[0]["state"],
                "review_before": before["review_count"],
                "review_after": after["review_count"],
                "classified_quadrant": classified["assessment"]["quadrant"],
                "human_big3": len(commitments["human"]),
                "microsteps": len(microsteps),
                "focus_state": focus["state"],
                "matrix_q1": len(matrix["q1"]),
                "focus_report_sessions": focus_report["total_sessions"],
                "revoked_access_status": denied.status_code,
                "revoked_refresh_status": refresh_denied.status_code,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
