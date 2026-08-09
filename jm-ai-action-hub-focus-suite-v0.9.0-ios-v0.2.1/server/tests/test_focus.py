from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, insert, inspect, select

from action_hub.models import (
    ActionItem,
    AttentionState,
    AuditEvent,
    CarryOverDecision,
    DailyFocusPlan,
    FocusSession,
    FollowUp,
    ItemState,
    MicroStep,
    PriorityAssessment,
    utcnow,
)
from action_hub.services.focus import matrix


def _plan(client: TestClient, text: str | None = None) -> dict:
    response = client.post(
        "/api/v1/inbox/parse",
        json={
            "text": text
            or "내일 오전 10시 고객 미팅\n금요일까지 제안서 작성 2시간\nAPI 테스트 보강 repo:owner/repo"
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _pair(client: TestClient, scopes: list[str] | None = None) -> dict:
    created = client.post(
        "/api/v1/mobile/pairings",
        json={"public_base_url": "https://hub.example.test", "scopes": scopes},
    )
    assert created.status_code == 201, created.text
    pairing = created.json()
    claimed = client.post(
        "/api/v1/mobile/pairings/claim",
        json={
            "pairing_id": pairing["pairing_id"],
            "code": pairing["code"],
            "device_name": "Focus Test iPhone",
            "app_version": "0.2.1",
        },
    )
    assert claimed.status_code == 200, claimed.text
    return claimed.json()


def _auth(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_focus_migration_and_capabilities(client: TestClient) -> None:
    inspector = inspect(client.app.state.database.engine)
    tables = set(inspector.get_table_names())
    assert {
        "priority_assessments",
        "daily_focus_plans",
        "daily_commitments",
        "micro_steps",
        "focus_sessions",
        "carry_over_decisions",
    }.issubset(tables)
    assert "attention_state" in {column["name"] for column in inspector.get_columns("action_items")}
    assert "active_slot" in {column["name"] for column in inspector.get_columns("focus_sessions")}

    capabilities = client.get("/api/v1/mobile/capabilities")
    assert capabilities.status_code == 200
    body = capabilities.json()
    assert body["server_version"] == "0.9.0"
    assert body["recommended_ios_app_version"] == "0.2.1"
    assert {
        "swipe-triage",
        "eisenhower-matrix",
        "dual-big3",
        "micro-steps",
        "focus-session",
        "day-close",
        "focus-analytics",
    }.issubset(body["features"])


def test_triage_suggestion_classification_revision_and_q4_safety(client: TestClient) -> None:
    plan = _plan(client, "언젠가 참고 자료 정리")
    item = plan["items"][0]

    triage = client.get("/api/v1/focus/triage")
    assert triage.status_code == 200
    suggestion = triage.json()["items"][0]["assessment"]
    assert suggestion["id"].startswith("suggested:")
    assert suggestion["source"] == "rule"
    assert 0 <= suggestion["importance_score"] <= 100
    assert 0 <= suggestion["urgency_score"] <= 100

    classified = client.post(
        f"/api/v1/focus/actions/{item['id']}/classify",
        json={
            "quadrant": "q4",
            "reason": "보류하되 삭제하지 않음",
            "expected_item_revision": item["revision"],
        },
    )
    assert classified.status_code == 200, classified.text
    assert classified.json()["assessment"]["quadrant"] == "q4"
    assert classified.json()["attention_state"] == "classified"

    stale = client.post(
        f"/api/v1/focus/actions/{item['id']}/classify",
        json={"quadrant": "q1", "expected_item_revision": item["revision"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"

    matrix = client.get("/api/v1/focus/matrix").json()
    assert matrix["counts"]["q4"] == 1
    with client.app.state.database.session_factory() as db:
        stored = db.get(ActionItem, item["id"])
        assert stored is not None
        assert stored.state == ItemState.DRAFT.value
        assert stored.attention_state == AttentionState.CLASSIFIED.value
        assert db.scalar(select(PriorityAssessment).where(PriorityAssessment.action_item_id == stored.id)) is not None


def test_matrix_uses_bounded_quadrant_queries_with_exact_aggregate_counts(
    client: TestClient, settings
) -> None:
    plan_id = _plan(client, "Matrix stress fixture")["id"]
    quadrants = ("q1", "q2", "q3", "q4")
    classified_per_quadrant = 2_400
    untriaged_without_assessment = 200
    untriaged_with_assessment = 200

    with client.app.state.database.session_factory() as db:
        db.execute(delete(ActionItem).where(ActionItem.plan_id == plan_id))
        action_rows = []
        assessment_rows = []
        for index in range(classified_per_quadrant * len(quadrants) + untriaged_without_assessment + untriaged_with_assessment):
            item_id = f"matrix-{index:05d}"
            is_classified = index < classified_per_quadrant * len(quadrants)
            has_assessment = is_classified or index >= classified_per_quadrant * len(quadrants) + untriaged_without_assessment
            attention_state = AttentionState.CLASSIFIED.value if is_classified else AttentionState.UNTRIAGED.value
            action_rows.append(
                {
                    "id": item_id,
                    "plan_id": plan_id,
                    "item_type": "todo",
                    "destination": "none",
                    "title": f"Matrix item {index}",
                    "fingerprint": f"matrix-fingerprint-{index}",
                    "attention_state": attention_state,
                }
            )
            if has_assessment:
                quadrant = quadrants[index // classified_per_quadrant] if is_classified else "q1"
                assessment_rows.append(
                    {
                        "id": f"assessment-{index:05d}",
                        "action_item_id": item_id,
                        "quadrant": quadrant,
                    }
                )
        db.execute(insert(ActionItem), action_rows)
        db.execute(insert(PriorityAssessment), assessment_rows)
        db.commit()

    select_count = 0
    action_item_load_count = 0
    statements: list[str] = []

    def count_select(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1
            statements.append(statement)

    def count_action_item_load(_target, _context) -> None:
        nonlocal action_item_load_count
        action_item_load_count += 1

    engine = client.app.state.database.engine
    event.listen(engine, "before_cursor_execute", count_select)
    event.listen(ActionItem, "load", count_action_item_load)
    try:
        with client.app.state.database.session_factory() as db:
            response = matrix(db, settings, limit_per_quadrant=3)
    finally:
        event.remove(engine, "before_cursor_execute", count_select)
        event.remove(ActionItem, "load", count_action_item_load)

    assert response.counts == {quadrant: classified_per_quadrant for quadrant in quadrants}
    assert response.untriaged_count == untriaged_without_assessment + untriaged_with_assessment
    assert all(len(getattr(response, quadrant)) == 3 for quadrant in quadrants)
    assert select_count <= 6
    assert action_item_load_count <= 4 * 3
    assert sum("LIMIT" in statement.upper() for statement in statements) == 4


def test_dual_big3_capacity_persists_and_releases_previous_attention(client: TestClient) -> None:
    plan = _plan(client)
    ids = [item["id"] for item in plan["items"]]
    configured = client.post(
        "/api/v1/focus/commitments",
        json={
            "human_item_ids": ids[:2],
            "ai_item_ids": ids[2:],
            "available_minutes": 60,
        },
    )
    assert configured.status_code == 200, configured.text
    body = configured.json()
    assert body["available_minutes"] == 60
    assert body["human_committed_minutes"] > 60
    assert body["overload_minutes"] == body["human_committed_minutes"] - 60
    assert len(body["human"]) == 2
    assert len(body["ai"]) == 1

    persisted = client.get("/api/v1/focus/commitments").json()
    assert persisted["available_minutes"] == 60

    replaced = client.post(
        "/api/v1/focus/commitments",
        json={"human_item_ids": [ids[1]], "ai_item_ids": [], "available_minutes": 90},
    )
    assert replaced.status_code == 200
    assert replaced.json()["available_minutes"] == 90
    with client.app.state.database.session_factory() as db:
        removed = db.get(ActionItem, ids[0])
        retained = db.get(ActionItem, ids[1])
        plan_row = db.scalar(select(DailyFocusPlan))
        assert removed.attention_state in {AttentionState.CLASSIFIED.value, AttentionState.UNTRIAGED.value}
        assert retained.attention_state == AttentionState.COMMITTED.value
        assert plan_row.available_minutes == 90


def test_dual_big3_recommends_by_capacity_intensity_and_priority(client: TestClient) -> None:
    plan = _plan(client, "전략 설계 90분\n긴급 회신 20분\nAI 자동화 30분\n보류 자료 읽기")
    strategy, reply, ai_task, deferred = [item["id"] for item in plan["items"]]
    with client.app.state.database.session_factory() as db:
        rows = {row.id: row for row in db.scalars(select(ActionItem).where(ActionItem.id.in_(plan["items"][i]["id"] for i in range(4))))}
        rows[strategy].estimated_minutes = 90
        rows[strategy].energy_level = "high"
        rows[strategy].executor = "human"
        rows[reply].estimated_minutes = 20
        rows[reply].energy_level = "low"
        rows[reply].executor = "human"
        rows[ai_task].estimated_minutes = 30
        rows[ai_task].executor = "ai"
        rows[deferred].estimated_minutes = 15
        for item_id, importance, urgency, quadrant in (
            (strategy, 95, 70, "q1"),
            (reply, 75, 95, "q1"),
            (ai_task, 80, 80, "q2"),
            (deferred, 90, 10, "q4"),
        ):
            rows[item_id].attention_state = AttentionState.CLASSIFIED.value
            rows[item_id].priority_assessment = PriorityAssessment(
                action_item_id=item_id,
                importance_score=importance,
                urgency_score=urgency,
                quadrant=quadrant,
                source="user",
                confidence=1.0,
                reasons_json=["테스트 평가"],
                user_overridden=True,
            )
        db.commit()

    response = client.post(
        "/api/v1/focus/commitments",
        json={"human_item_ids": [], "ai_item_ids": [], "available_minutes": 45},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["human_remaining_minutes"] == 45
    assert body["ai_remaining_minutes"] == 45
    assert body["human_recommendations"][0]["action"]["action_item_id"] == reply
    assert body["human_recommendations"][0]["processing_intensity"] == "light"
    assert body["human_recommendations"][0]["schedule_fit"] == "fits"
    assert body["human_recommendations"][0]["action"]["assessment"]["importance_score"] == 75
    assert any("남은 일정 45분" in reason for reason in body["human_recommendations"][0]["reasons"])
    assert body["ai_recommendations"][0]["action"]["action_item_id"] == ai_task

    accepted = client.post(
        "/api/v1/focus/commitments",
        json={"human_item_ids": [reply], "ai_item_ids": [], "available_minutes": 45},
    )
    assert accepted.status_code == 200, accepted.text
    assert all(item["action"]["action_item_id"] != reply for item in accepted.json()["human_recommendations"])


def test_microstep_generation_update_and_replace_policy(client: TestClient) -> None:
    plan = _plan(client, "API 인증 오류 수정 repo:owner/repo")
    item_id = plan["items"][0]["id"]
    generated = client.post(
        f"/api/v1/focus/actions/{item_id}/decompose",
        json={"max_steps": 5},
    )
    assert generated.status_code == 200, generated.text
    steps = generated.json()
    assert len(steps) == 5
    assert "테스트" in steps[-2]["title"]

    updated = client.patch(
        f"/api/v1/focus/microsteps/{steps[0]['id']}",
        json={"state": "completed", "completion_note": "재현 완료"},
    )
    assert updated.status_code == 200
    assert updated.json()["state"] == "completed"

    kept = client.post(
        f"/api/v1/focus/actions/{item_id}/decompose",
        json={"replace_existing": False},
    )
    assert kept.status_code == 200
    assert len(kept.json()) == 5
    assert kept.json()[0]["state"] == "completed"


def test_focus_lifecycle_traffic_single_active_and_completion(client: TestClient) -> None:
    plan = _plan(client, "고객 제안서 작성 2시간\n검토 결과 보고 30분")
    first, second = [item["id"] for item in plan["items"]]
    client.post("/api/v1/focus/commitments", json={"human_item_ids": [first, second]})
    client.post(f"/api/v1/focus/actions/{first}/decompose", json={"max_steps": 3})

    started = client.post(
        "/api/v1/focus/sessions",
        json={"action_item_id": first, "planned_minutes": 25},
    )
    assert started.status_code == 201, started.text
    session = started.json()
    assert session["state"] == "running"
    assert session["traffic_state"] == "green"
    assert len(session["micro_steps"]) == 3

    concurrent = client.post(
        "/api/v1/focus/sessions",
        json={"action_item_id": second, "planned_minutes": 10},
    )
    assert concurrent.status_code == 422

    paused = client.patch(
        f"/api/v1/focus/sessions/{session['id']}",
        json={"action": "pause", "expected_revision": session["revision"]},
    )
    assert paused.status_code == 200
    assert paused.json()["state"] == "paused"

    stale = client.patch(
        f"/api/v1/focus/sessions/{session['id']}",
        json={"action": "resume", "expected_revision": session["revision"]},
    )
    assert stale.status_code == 409

    resumed = client.patch(
        f"/api/v1/focus/sessions/{session['id']}",
        json={"action": "resume", "expected_revision": paused.json()["revision"]},
    )
    extended = client.patch(
        f"/api/v1/focus/sessions/{session['id']}",
        json={"action": "extend", "extension_minutes": 10, "expected_revision": resumed.json()["revision"]},
    )
    assert extended.status_code == 200
    assert extended.json()["total_planned_minutes"] == 35

    with client.app.state.database.session_factory() as db:
        row = db.get(FocusSession, session["id"])
        row.started_at = utcnow() - timedelta(minutes=40)
        db.commit()
    active = client.get("/api/v1/focus/sessions/active")
    assert active.status_code == 200
    assert active.json()["traffic_state"] == "red"

    completed = client.patch(
        f"/api/v1/focus/sessions/{session['id']}",
        json={
            "action": "complete",
            "completion_note": "초안 완료",
            "expected_revision": active.json()["revision"],
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["state"] == "completed"
    assert completed.json()["actual_minutes"] >= 40

    second_session = client.post(
        "/api/v1/focus/sessions",
        json={"action_item_id": second, "planned_minutes": 10},
    )
    assert second_session.status_code == 201
    closed = client.patch(
        f"/api/v1/focus/sessions/{second_session.json()['id']}",
        json={
            "action": "complete",
            "mark_action_completed": True,
            "completion_note": "보고 완료",
            "expected_revision": second_session.json()["revision"],
        },
    )
    assert closed.status_code == 200
    with client.app.state.database.session_factory() as db:
        item = db.get(ActionItem, second)
        assert item.state == ItemState.COMPLETED.value
        assert item.attention_state == AttentionState.COMPLETED.value
        assert item.completion_evidence == "보고 완료"


def test_close_day_decisions_are_explicit_and_followup_is_idempotent(client: TestClient) -> None:
    plan = _plan(
        client,
        "A 자료 정리\nB 구현 분할 repo:owner/repo\nC 조사 위임\nD 계약 검토\nE 회신 확인\nF 불필요 업무",
    )
    ids = [item["id"] for item in plan["items"]]
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    follow_at = (utcnow() + timedelta(days=2)).isoformat()
    payload = {
        "decisions": [
            {"action_item_id": ids[0], "decision": "reschedule", "reason": "시간 부족", "to_date": tomorrow},
            {"action_item_id": ids[1], "decision": "split", "reason": "범위 큼"},
            {"action_item_id": ids[2], "decision": "delegate", "reason": "AI 적합", "executor": "ai"},
            {"action_item_id": ids[3], "decision": "deadline_change", "reason": "합의", "to_date": tomorrow},
            {
                "action_item_id": ids[4],
                "decision": "waiting",
                "reason": "외부 회신",
                "waiting_for": "김 과장",
                "follow_up_at": follow_at,
            },
            {"action_item_id": ids[5], "decision": "cancel", "reason": "가치 없음"},
        ]
    }
    result = client.post("/api/v1/focus/day-close", json=payload)
    assert result.status_code == 200, result.text
    assert result.json()["processed"] == 6
    with client.app.state.database.session_factory() as db:
        assert db.get(ActionItem, ids[0]).attention_state == AttentionState.CARRIED_OVER.value
        assert len(list(db.scalars(select(MicroStep).where(MicroStep.action_item_id == ids[1])))) >= 3
        assert db.get(ActionItem, ids[2]).executor == "ai"
        assert db.get(ActionItem, ids[3]).deadline_at is not None
        assert db.get(ActionItem, ids[4]).state == ItemState.WAITING.value
        assert db.get(ActionItem, ids[5]).state == ItemState.CANCELLED.value
        assert len(list(db.scalars(select(FollowUp).where(FollowUp.action_item_id == ids[4])))) == 1

    repeated_wait = client.post(
        "/api/v1/focus/day-close",
        json={
            "decisions": [
                {
                    "action_item_id": ids[4],
                    "decision": "waiting",
                    "reason": "다시 확인",
                    "waiting_for": "김 과장",
                    "follow_up_at": follow_at,
                }
            ]
        },
    )
    assert repeated_wait.status_code == 200
    with client.app.state.database.session_factory() as db:
        assert len(list(db.scalars(select(FollowUp).where(FollowUp.action_item_id == ids[4])))) == 1


def test_close_day_preflight_missing_item_leaves_all_domain_and_audit_rows_unchanged(client: TestClient) -> None:
    plan = _plan(client, "Atomic first\nAtomic missing")
    first_id = plan["items"][0]["id"]
    with client.app.state.database.session_factory() as db:
        original = db.get(ActionItem, first_id)
        original_due_at = original.due_at
        initial_reschedule_count = original.reschedule_count
        initial_micro_steps = db.scalar(select(func.count()).select_from(MicroStep))
        initial_followups = db.scalar(select(func.count()).select_from(FollowUp))
        initial_decisions = db.scalar(select(func.count()).select_from(CarryOverDecision))
        initial_audits = db.scalar(select(func.count()).select_from(AuditEvent))

    response = client.post(
        "/api/v1/focus/day-close",
        json={
            "decisions": [
                {"action_item_id": first_id, "decision": "reschedule"},
                {"action_item_id": "missing-action-item", "decision": "cancel"},
            ]
        },
    )

    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": {"code": "action_item_not_found", "action_item_id": "missing-action-item"}
    }
    with client.app.state.database.session_factory() as db:
        assert db.get(ActionItem, first_id).due_at == original_due_at
        assert db.get(ActionItem, first_id).reschedule_count == initial_reschedule_count
        assert db.scalar(select(func.count()).select_from(MicroStep)) == initial_micro_steps
        assert db.scalar(select(func.count()).select_from(FollowUp)) == initial_followups
        assert db.scalar(select(func.count()).select_from(CarryOverDecision)) == initial_decisions
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == initial_audits


def test_close_day_rejects_duplicate_ids_and_invalid_decision_fields_before_service(client: TestClient) -> None:
    item_id = _plan(client, "Schema target")["items"][0]["id"]
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    invalid_payloads = [
        {
            "decisions": [
                {"action_item_id": item_id, "decision": "cancel"},
                {"action_item_id": item_id, "decision": "cancel"},
            ]
        },
        {"decisions": [{"action_item_id": item_id, "decision": "deadline_change"}]},
        {
            "decisions": [
                {
                    "action_item_id": item_id,
                    "decision": "waiting",
                    "waiting_for": "   ",
                    "follow_up_at": "2030-01-02T10:00:00",
                }
            ]
        },
        {
            "decisions": [
                {
                    "action_item_id": item_id,
                    "decision": "waiting",
                    "waiting_for": "External owner",
                    "follow_up_at": "2030-01-02T10:00:00",
                }
            ]
        },
        {"decisions": [{"action_item_id": item_id, "decision": "reschedule", "executor": "ai"}]},
        {"decisions": [{"action_item_id": item_id, "decision": "split", "to_date": tomorrow}]},
        {"decisions": [{"action_item_id": item_id, "decision": "delegate", "to_date": tomorrow}]},
        {
            "decisions": [
                {"action_item_id": item_id, "decision": "deadline_change", "to_date": tomorrow, "waiting_for": "x"}
            ]
        },
        {"decisions": [{"action_item_id": item_id, "decision": "cancel", "executor": "ai"}]},
        {"decisions": [{"action_item_id": item_id, "decision": "waiting", "executor": "ai"}]},
    ]
    with client.app.state.database.session_factory() as db:
        initial_decisions = db.scalar(select(func.count()).select_from(CarryOverDecision))
        initial_audits = db.scalar(select(func.count()).select_from(AuditEvent))
    for payload in invalid_payloads:
        response = client.post("/api/v1/focus/day-close", json=payload)
        assert response.status_code == 422, response.text
    duplicate_response = client.post("/api/v1/focus/day-close", json=invalid_payloads[0])
    assert "duplicate action_item_id" in duplicate_response.text
    with client.app.state.database.session_factory() as db:
        assert db.get(ActionItem, item_id).state != ItemState.CANCELLED.value
        assert db.scalar(select(func.count()).select_from(CarryOverDecision)) == initial_decisions
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == initial_audits

def test_weekly_focus_report_and_dashboard_summary(client: TestClient) -> None:
    plan = _plan(client, "전략 문서 작성 60분 #strategy\n자동화 테스트 30분 repo:owner/repo")
    first, second = [item["id"] for item in plan["items"]]
    client.post(f"/api/v1/focus/actions/{first}/classify", json={"quadrant": "q2"})
    client.post(f"/api/v1/focus/actions/{second}/classify", json={"quadrant": "q3"})
    client.post(
        "/api/v1/focus/commitments",
        json={"human_item_ids": [first], "ai_item_ids": [second], "available_minutes": 120},
    )
    session = client.post(
        "/api/v1/focus/sessions", json={"action_item_id": first, "planned_minutes": 10}
    ).json()
    completed = client.patch(
        f"/api/v1/focus/sessions/{session['id']}",
        json={
            "action": "complete",
            "mark_action_completed": True,
            "completion_note": "전략 문서 완료",
            "expected_revision": session["revision"],
        },
    )
    assert completed.status_code == 200

    report = client.get("/api/v1/focus/reports/weekly")
    assert report.status_code == 200
    body = report.json()
    assert body["total_sessions"] == 1
    assert body["completed_sessions"] == 1
    assert body["focus_minutes"] >= 1
    assert body["q2_investment_minutes"] >= 1
    assert body["human_big3_total"] == 1
    assert body["human_big3_completed"] == 1
    assert body["recommendations"]

    tokens = _pair(client)
    dashboard = client.get("/api/v1/mobile/dashboard", headers=_auth(tokens))
    assert dashboard.status_code == 200
    focus = dashboard.json()["focus_summary"]
    assert focus["matrix_counts"]["q2"] == 0
    assert focus["matrix_counts"]["q3"] == 1
    assert len(focus["human_big3"]) == 1
    assert focus["active_focus"] is None


def test_mobile_focus_api_scope_and_change_stream(client: TestClient) -> None:
    plan = _plan(client, "모바일 분류 테스트")
    item_id = plan["items"][0]["id"]
    read_only = _pair(client, scopes=["plans:read", "activity:read"])
    forbidden = client.post(
        f"/api/v1/mobile/actions/{item_id}/classify",
        headers=_auth(read_only),
        json={"quadrant": "q1"},
    )
    assert forbidden.status_code == 403

    tokens = _pair(client)
    triage = client.get("/api/v1/mobile/triage", headers=_auth(tokens))
    assert triage.status_code == 200
    classified = client.post(
        f"/api/v1/mobile/actions/{item_id}/classify",
        headers=_auth(tokens),
        json={"quadrant": "q1", "reason": "모바일 확인"},
    )
    assert classified.status_code == 200
    big3 = client.post(
        "/api/v1/mobile/commitments",
        headers=_auth(tokens),
        json={"human_item_ids": [item_id], "available_minutes": 45},
    )
    assert big3.status_code == 200
    session = client.post(
        "/api/v1/mobile/focus-sessions",
        headers=_auth(tokens),
        json={"action_item_id": item_id, "planned_minutes": 10},
    )
    assert session.status_code == 201
    finished = client.patch(
        f"/api/v1/mobile/focus-sessions/{session.json()['id']}",
        headers=_auth(tokens),
        json={"action": "abandon", "expected_revision": session.json()["revision"]},
    )
    assert finished.status_code == 200

    changes = client.get("/api/v1/mobile/changes", headers=_auth(tokens))
    assert changes.status_code == 200
    event_types = {change["event_type"] for change in changes.json()["changes"]}
    assert "attention.classified" in event_types
    assert "attention.committed" in event_types
    assert "focus.started" in event_types
    assert "focus.abandon" in event_types


def test_focus_session_complete_clears_needs_review_and_drops_from_review_list(client: TestClient) -> None:
    # Regression for P1-4: act_on_focus_session()'s "complete" branch with
    # mark_action_completed moved the item to COMPLETED but never cleared
    # needs_review -- the same bug pattern fixed today for approve/reject
    # (RV-01), at a different call site (focus.py, not executor.py).
    from action_hub.services.mobile import list_review_plans

    plan = _plan(client, "제안서 검토 30분")
    item_id = plan["items"][0]["id"]
    with client.app.state.database.session_factory() as db:
        row = db.get(ActionItem, item_id)
        row.needs_review = True
        row.review_reason = "테스트: 검토 필요"
        db.commit()
        assert any(p.id == plan["id"] for p in list_review_plans(db, 50))

    started = client.post(
        "/api/v1/focus/sessions",
        json={"action_item_id": item_id, "planned_minutes": 25},
    )
    assert started.status_code == 201, started.text
    session = started.json()

    completed = client.patch(
        f"/api/v1/focus/sessions/{session['id']}",
        json={
            "action": "complete",
            "mark_action_completed": True,
            "completion_note": "완료",
            "expected_revision": session["revision"],
        },
    )
    assert completed.status_code == 200, completed.text

    with client.app.state.database.session_factory() as db:
        row = db.get(ActionItem, item_id)
        assert row.state == ItemState.COMPLETED.value
        assert row.needs_review is False
        assert row.review_reason == "테스트: 검토 필요"
        assert all(p.id != plan["id"] for p in list_review_plans(db, 50))


def test_close_day_cancel_clears_needs_review_and_drops_from_review_list(client: TestClient) -> None:
    # Regression for P1-4: close_day()'s "cancel" decision moved the item to
    # CANCELLED but never cleared needs_review, the same bug pattern at a third
    # call site.
    from action_hub.services.mobile import list_review_plans

    plan = _plan(client, "가치 없는 업무")
    item_id = plan["items"][0]["id"]
    with client.app.state.database.session_factory() as db:
        row = db.get(ActionItem, item_id)
        row.needs_review = True
        row.review_reason = "테스트: 검토 필요"
        db.commit()
        assert any(p.id == plan["id"] for p in list_review_plans(db, 50))

    result = client.post(
        "/api/v1/focus/day-close",
        json={"decisions": [{"action_item_id": item_id, "decision": "cancel", "reason": "가치 없음"}]},
    )
    assert result.status_code == 200, result.text

    with client.app.state.database.session_factory() as db:
        row = db.get(ActionItem, item_id)
        assert row.state == ItemState.CANCELLED.value
        assert row.needs_review is False
        assert row.review_reason == "테스트: 검토 필요"
        assert all(p.id != plan["id"] for p in list_review_plans(db, 50))
