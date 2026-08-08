from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from action_hub.models import ActionItem, ItemState, WorkerExecution
from action_hub.services.workers.master_worker_sync import (
    sync_execution,
    sync_master_worker_executions,
)

LOCAL_ROUTE = {
    "master-worker": {
        "kind": "local_webhook",
        "baseUrl": "http://127.0.0.1:4310",
        "credentialFile": "/tmp/does-not-matter.json",
    }
}


def _write_credential(path, token="mw-owner-token", mode=0o600):
    path.write_text(json.dumps({"token": token}), encoding="utf-8")
    os.chmod(path, mode)


def _live_settings(settings, tmp_path, token="mw-owner-token"):
    credential_path = tmp_path / "owner-credential.json"
    _write_credential(credential_path, token=token)
    route = {
        "master-worker": {
            "kind": "local_webhook",
            "baseUrl": "http://127.0.0.1:4310",
            "credentialFile": str(credential_path),
        }
    }
    return settings.model_copy(update={"worker_routes_json": json.dumps(route), "execution_mode": "live"})


def _create_dispatched_execution(client, *, intake_id: str = "int_abc123", state: str = "dispatched"):
    response = client.post(
        "/api/v1/inbox/parse",
        json={
            "text": "레거시 로그인 버그 조사",
            "reference_time": "2026-08-01T09:00:00+09:00",
            "timezone": "Asia/Seoul",
            "force_new": True,
        },
    )
    assert response.status_code == 201, response.text
    item_id = response.json()["items"][0]["id"]
    app = client.app
    with app.state.database.session_factory() as db:
        execution = WorkerExecution(
            action_item_id=item_id,
            worker="master-worker",
            state=state,
            dispatch_id=f"mw-intake-{intake_id}" if intake_id else None,
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)
        execution_id = execution.id
    return item_id, execution_id


def _audit_response(actions: list[str]):
    response = MagicMock(status_code=200)
    response.content = b"{}"
    response.json.return_value = {
        "data": [{"action": action, "objectType": "intake"} for action in actions],
        "meta": {},
    }
    return response


def _new_route_404():
    """MW intake status route (GET /intakes/{id}) returning 404.

    sync_execution now tries this route first and only reads the legacy
    audit trail as a fallback. Tests that exercise the audit-trail-derived
    status mapping stub this as the first httpx.get() call so the second
    call reaches the audit-shaped mock response as before.
    """
    return MagicMock(status_code=404)


def _intake_status_response(data: dict):
    """Simulate GET /api/v1/intakes/{intakeId} -> {"data": {...}}."""
    response = MagicMock(status_code=200)
    response.content = b"{}"
    response.json.return_value = {"data": data, "meta": {}}
    return response


# --- bind -> running ---


def test_bound_intake_advances_execution_to_running(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    item_id, execution_id = _create_dispatched_execution(client, intake_id="int_bound1")
    app = client.app
    response = _audit_response(["bind", "analyze", "create"])
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        side_effect=[_new_route_404(), response],
    ) as get:
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.checked == 1
    assert summary.updated == 1
    assert summary.failed == 0
    outcome = summary.outcomes[0]
    assert outcome.outcome == "updated"
    assert outcome.new_state == "running"
    call = get.call_args
    assert call.args[0] == "http://127.0.0.1:4310/api/v1/audit"
    assert call.kwargs["params"]["objectType"] == "intake"
    assert call.kwargs["params"]["objectId"] == "int_bound1"
    assert call.kwargs["headers"]["Authorization"] == "Bearer mw-owner-token"

    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        item = db.get(ActionItem, item_id)
        assert execution.state == "running"
        assert item.state == ItemState.RUNNING.value


# --- discard -> failed ---


def test_discarded_intake_marks_execution_failed(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    item_id, execution_id = _create_dispatched_execution(client, intake_id="int_disc1")
    app = client.app
    response = _audit_response(["discard", "bind", "analyze", "create"])
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        side_effect=[_new_route_404(), response],
    ):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.updated == 1
    assert summary.outcomes[0].new_state == "failed"
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        item = db.get(ActionItem, item_id)
        assert execution.state == "failed"
        assert execution.error == "MW intake was discarded"
        assert item.state == ItemState.FAILED.value


# --- still pending (create/analyze only) -> unchanged, no state mutation ---


@pytest.mark.parametrize("actions", [["create"], ["analyze", "create"]])
def test_pending_intake_leaves_execution_dispatched(client, settings, tmp_path, actions):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_pending1")
    app = client.app
    response = _audit_response(actions)
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        side_effect=[_new_route_404(), response],
    ):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.unchanged == 1
    assert summary.updated == 0
    assert summary.outcomes[0].new_state is None
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


def test_no_audit_history_is_unchanged_not_failed(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _create_dispatched_execution(client, intake_id="int_none1")
    app = client.app
    response = _audit_response([])
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        side_effect=[_new_route_404(), response],
    ):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.unchanged == 1
    assert summary.failed == 0


# --- skip: dispatch_id is not an MW intake reference (dry-run / foreign) ---


def test_non_mw_dispatch_id_is_skipped_without_http_call(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id=None)
    app = client.app
    with app.state.database.session_factory() as db:
        exec_row = db.get(WorkerExecution, execution_id)
        exec_row.dispatch_id = "dry-master-worker-abc"
        db.commit()
    with patch("action_hub.services.workers.master_worker_sync.httpx.get") as get:
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.skipped == 1
    get.assert_not_called()


# --- fail-closed: MW unreachable / 401 / 404 leave state untouched ---


def test_mw_unreachable_is_fail_closed(client, settings, tmp_path):
    import httpx

    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_unreach1")
    app = client.app
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.failed == 1
    assert summary.updated == 0
    assert "unreachable" in summary.outcomes[0].reason.lower()
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


def test_mw_401_is_fail_closed(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_401")
    app = client.app
    response = MagicMock(status_code=401)
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.failed == 1
    assert "401" in summary.outcomes[0].reason
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


def test_mw_404_is_fail_closed(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_404")
    app = client.app
    response = MagicMock(status_code=404)
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.failed == 1
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


def test_credential_file_missing_is_fail_closed(client, settings, tmp_path):
    missing = tmp_path / "missing-credential.json"
    route = {
        "master-worker": {"kind": "local_webhook", "baseUrl": "http://127.0.0.1:4310", "credentialFile": str(missing)}
    }
    live = settings.model_copy(update={"worker_routes_json": json.dumps(route), "execution_mode": "live"})
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_nocred")
    app = client.app
    with patch("action_hub.services.workers.master_worker_sync.httpx.get") as get:
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.failed == 1
    assert "credential" in summary.outcomes[0].reason.lower()
    get.assert_not_called()
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


def test_non_loopback_base_url_is_fail_closed(client, settings, tmp_path):
    route = {
        "master-worker": {"kind": "local_webhook", "baseUrl": "http://example.com:4310", "credentialFile": "/tmp/x.json"}
    }
    live = settings.model_copy(update={"worker_routes_json": json.dumps(route), "execution_mode": "live"})
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_badhost")
    app = client.app
    with patch("action_hub.services.workers.master_worker_sync.httpx.get") as get:
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.failed == 1
    get.assert_not_called()
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


# --- partial failure does not abort the batch ---


def test_partial_failure_does_not_abort_other_executions(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _create_dispatched_execution(client, intake_id="int_ok1")
    _create_dispatched_execution(client, intake_id="int_ok2")
    app = client.app
    # exec 1: new route 404s -> fall back to audit trail -> "bind" -> updated.
    # exec 2: new route itself returns 401 -> failed (no fallback on a non-404 error).
    responses = [_new_route_404(), _audit_response(["bind"]), MagicMock(status_code=401)]
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", side_effect=responses):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.checked == 2
    assert summary.updated == 1
    assert summary.failed == 1


# --- sync_execution direct unit coverage: already-reflected state is a no-op ---


def test_already_running_execution_is_unchanged_when_still_bound(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_stable", state="running")
    app = client.app
    response = _audit_response(["bind", "analyze", "create"])
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        side_effect=[_new_route_404(), response],
    ):
        with app.state.database.session_factory() as db:
            execution = db.get(WorkerExecution, execution_id)
            outcome = sync_execution(db, execution, live)
            db.commit()
    assert outcome.outcome == "unchanged"
    assert outcome.new_state is None
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "running"


# --- new route: GET /api/v1/intakes/{intakeId} (CARD B-01b) ---


def test_new_route_is_tried_first_and_used_when_available(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    item_id, execution_id = _create_dispatched_execution(client, intake_id="int_newbound")
    app = client.app
    response = _intake_status_response(
        {"intakeId": "int_newbound", "state": "bound", "boundProjectId": "prj_1", "updatedAt": "t"}
    )
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response) as get:
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert get.call_count == 1
    call = get.call_args
    assert call.args[0] == "http://127.0.0.1:4310/api/v1/intakes/int_newbound"
    assert call.kwargs["headers"]["Authorization"] == "Bearer mw-owner-token"
    assert summary.updated == 1
    assert summary.outcomes[0].new_state == "running"
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        item = db.get(ActionItem, item_id)
        assert execution.state == "running"
        assert item.state == ItemState.RUNNING.value


def test_new_route_discarded_intake_marks_execution_failed(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    item_id, execution_id = _create_dispatched_execution(client, intake_id="int_newdisc")
    app = client.app
    response = _intake_status_response({"intakeId": "int_newdisc", "state": "discarded", "updatedAt": "t"})
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.updated == 1
    assert summary.outcomes[0].new_state == "failed"
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        item = db.get(ActionItem, item_id)
        assert execution.state == "failed"
        assert execution.error == "MW intake was discarded"
        assert item.state == ItemState.FAILED.value


@pytest.mark.parametrize("intake_state", ["draft", "analyzed"])
def test_new_route_intake_still_pending_leaves_execution_unchanged(client, settings, tmp_path, intake_state):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_newpending")
    app = client.app
    response = _intake_status_response({"intakeId": "int_newpending", "state": intake_state, "updatedAt": "t"})
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.unchanged == 1
    assert summary.updated == 0
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


# --- new route: Objective state mapping (packages/contracts/src/types.ts ObjectiveState) ---


@pytest.mark.parametrize(
    "objective_state",
    [
        "captured", "identified", "scoped", "compiled", "planned",
        "awaiting_approval", "executing", "verifying", "resolving", "packaging",
    ],
)
def test_new_route_objective_in_progress_states_map_to_running(client, settings, tmp_path, objective_state):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_objprog")
    app = client.app
    response = _intake_status_response(
        {
            "intakeId": "int_objprog", "state": "bound", "boundProjectId": "prj_1",
            "objectiveId": "obj_1", "objectiveState": objective_state, "updatedAt": "t",
        }
    )
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.updated == 1
    assert summary.outcomes[0].new_state == "running"
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "running"


# NOTE: the following Objective-state tests seed the execution in a non-"dispatched"
# starting state (to prove existing "running"/"human_review" state is left alone or
# advanced correctly), so they call sync_execution directly -- sync_master_worker_executions
# only selects WorkerExecution rows with state == "dispatched" and would silently skip them.


@pytest.mark.parametrize("objective_state", ["delivered", "closed"])
def test_new_route_objective_delivered_or_closed_maps_to_completed(client, settings, tmp_path, objective_state):
    live = _live_settings(settings, tmp_path)
    item_id, execution_id = _create_dispatched_execution(client, intake_id="int_objdone", state="running")
    app = client.app
    response = _intake_status_response(
        {
            "intakeId": "int_objdone", "state": "bound", "boundProjectId": "prj_1",
            "objectiveId": "obj_2", "objectiveState": objective_state, "updatedAt": "t",
        }
    )
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            execution = db.get(WorkerExecution, execution_id)
            outcome = sync_execution(db, execution, live)
            db.commit()
    assert outcome.outcome == "updated"
    assert outcome.new_state == "completed"
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        item = db.get(ActionItem, item_id)
        assert execution.state == "completed"
        assert execution.completed_at is not None
        assert item.state == ItemState.COMPLETED.value


def test_new_route_objective_blocked_maps_to_human_review(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    item_id, execution_id = _create_dispatched_execution(client, intake_id="int_objblocked", state="running")
    app = client.app
    response = _intake_status_response(
        {
            "intakeId": "int_objblocked", "state": "bound", "boundProjectId": "prj_1",
            "objectiveId": "obj_3", "objectiveState": "blocked", "updatedAt": "t",
        }
    )
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            execution = db.get(WorkerExecution, execution_id)
            outcome = sync_execution(db, execution, live)
            db.commit()
    assert outcome.outcome == "updated"
    assert outcome.new_state == "human_review"
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        item = db.get(ActionItem, item_id)
        assert execution.state == "human_review"
        assert item.state == ItemState.HUMAN_REVIEW.value


def test_new_route_objective_cancelled_maps_to_failed(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    item_id, execution_id = _create_dispatched_execution(client, intake_id="int_objcancel", state="running")
    app = client.app
    response = _intake_status_response(
        {
            "intakeId": "int_objcancel", "state": "bound", "boundProjectId": "prj_1",
            "objectiveId": "obj_4", "objectiveState": "cancelled", "updatedAt": "t",
        }
    )
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            execution = db.get(WorkerExecution, execution_id)
            outcome = sync_execution(db, execution, live)
            db.commit()
    assert outcome.outcome == "updated"
    assert outcome.new_state == "failed"
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        item = db.get(ActionItem, item_id)
        assert execution.state == "failed"
        assert execution.error == "MW objective was cancelled"
        assert item.state == ItemState.FAILED.value


def test_new_route_objective_paused_leaves_execution_unchanged(client, settings, tmp_path):
    """Owner explicitly paused the Objective in MW -- not a completion signal, must not clobber state."""
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_objpaused", state="running")
    app = client.app
    response = _intake_status_response(
        {
            "intakeId": "int_objpaused", "state": "bound", "boundProjectId": "prj_1",
            "objectiveId": "obj_5", "objectiveState": "paused", "updatedAt": "t",
        }
    )
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            execution = db.get(WorkerExecution, execution_id)
            outcome = sync_execution(db, execution, live)
            db.commit()
    assert outcome.outcome == "unchanged"
    assert outcome.new_state is None
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "running"


def test_new_route_unrecognized_objective_state_is_fail_closed(client, settings, tmp_path):
    """A future MW ObjectiveState value this module doesn't know yet must not be guessed at."""
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_objunknown", state="running")
    app = client.app
    response = _intake_status_response(
        {
            "intakeId": "int_objunknown", "state": "bound", "boundProjectId": "prj_1",
            "objectiveId": "obj_6", "objectiveState": "some_future_state", "updatedAt": "t",
        }
    )
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            execution = db.get(WorkerExecution, execution_id)
            outcome = sync_execution(db, execution, live)
            db.commit()
    assert outcome.outcome == "unchanged"
    assert outcome.new_state is None
    assert "unrecognized" in outcome.reason.lower()
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "running"


def test_new_route_objective_id_present_without_state_is_fail_closed(client, settings, tmp_path):
    """Defensive edge case: objectiveId key present but objectiveState missing/falsy."""
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_objnostate", state="running")
    app = client.app
    response = _intake_status_response(
        {
            "intakeId": "int_objnostate", "state": "bound", "boundProjectId": "prj_1",
            "objectiveId": "obj_7", "objectiveState": None, "updatedAt": "t",
        }
    )
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=response):
        with app.state.database.session_factory() as db:
            execution = db.get(WorkerExecution, execution_id)
            outcome = sync_execution(db, execution, live)
            db.commit()
    assert outcome.outcome == "unchanged"
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "running"


# --- new route 404 fallback (older MW without GET /intakes/{id}) ---


def test_new_route_404_falls_back_to_audit_and_records_it(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    item_id, execution_id = _create_dispatched_execution(client, intake_id="int_fallback1")
    app = client.app
    audit_response = _audit_response(["bind", "analyze", "create"])
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        side_effect=[_new_route_404(), audit_response],
    ) as get:
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert get.call_count == 2
    first_call, second_call = get.call_args_list
    assert first_call.args[0] == "http://127.0.0.1:4310/api/v1/intakes/int_fallback1"
    assert second_call.args[0] == "http://127.0.0.1:4310/api/v1/audit"
    assert summary.updated == 1
    outcome = summary.outcomes[0]
    assert outcome.new_state == "running"
    assert "fell back" in outcome.reason.lower()
    assert "404" in outcome.reason
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        item = db.get(ActionItem, item_id)
        assert execution.state == "running"
        assert item.state == ItemState.RUNNING.value


def test_new_route_404_then_audit_401_is_fail_closed_and_records_fallback(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_fallback2")
    app = client.app
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        side_effect=[_new_route_404(), MagicMock(status_code=401)],
    ):
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert summary.failed == 1
    assert summary.updated == 0
    outcome = summary.outcomes[0]
    assert "fell back" in outcome.reason.lower()
    assert "401" in outcome.reason
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


# --- new route reachable but malformed: fail-closed without attempting a fallback ---


def test_new_route_malformed_response_is_fail_closed_without_fallback(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_malformed")
    app = client.app
    response = MagicMock(status_code=200)
    response.content = b"{}"
    response.json.return_value = {"data": ["not", "an", "object"], "meta": {}}
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get", return_value=response
    ) as get:
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert get.call_count == 1  # malformed body is not a 404; no fallback is attempted
    assert summary.failed == 1
    assert summary.updated == 0
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


def test_new_route_401_is_fail_closed_without_fallback(client, settings, tmp_path):
    live = _live_settings(settings, tmp_path)
    _item_id, execution_id = _create_dispatched_execution(client, intake_id="int_new401")
    app = client.app
    with patch(
        "action_hub.services.workers.master_worker_sync.httpx.get",
        return_value=MagicMock(status_code=401),
    ) as get:
        with app.state.database.session_factory() as db:
            summary = sync_master_worker_executions(db, live)
    assert get.call_count == 1
    assert summary.failed == 1
    assert "401" in summary.outcomes[0].reason
    with app.state.database.session_factory() as db:
        execution = db.get(WorkerExecution, execution_id)
        assert execution.state == "dispatched"


# --- CLI wiring ---


def test_cli_worker_sync_reports_summary_and_exit_code(tmp_path, capsys, monkeypatch):
    from action_hub import cli
    from action_hub.config import Settings

    credential_path = tmp_path / "owner-credential.json"
    _write_credential(credential_path)
    route = {
        "master-worker": {
            "kind": "local_webhook",
            "baseUrl": "http://127.0.0.1:4310",
            "credentialFile": str(credential_path),
        }
    }
    cli_settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'cli.db'}",
        data_dir=tmp_path,
        execution_mode="live",
        worker_routes_json=json.dumps(route),
    )
    monkeypatch.setattr(cli, "get_settings", lambda: cli_settings)
    monkeypatch.setattr(sys, "argv", ["action-hub", "worker-sync"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"checked": 0, "updated": 0, "unchanged": 0, "skipped": 0, "failed": 0, "outcomes": []}


def test_cli_worker_sync_exits_nonzero_on_failed_sync(tmp_path, capsys, monkeypatch):
    from action_hub import cli
    from action_hub.config import Settings
    from action_hub.database import Database
    from action_hub.models import ActionItem, ActionPlan, InboxEntry, utcnow

    credential_path = tmp_path / "owner-credential.json"
    _write_credential(credential_path)
    route = {
        "master-worker": {
            "kind": "local_webhook",
            "baseUrl": "http://127.0.0.1:4310",
            "credentialFile": str(credential_path),
        }
    }
    cli_settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'cli2.db'}",
        data_dir=tmp_path,
        execution_mode="live",
        worker_routes_json=json.dumps(route),
    )
    database = Database(cli_settings.database_url)
    database.create_schema(use_migrations=cli_settings.run_migrations)
    with database.session_factory() as db:
        inbox = InboxEntry(raw_text="x", timezone="Asia/Seoul", fingerprint="i" * 64)
        db.add(inbox)
        db.flush()
        plan = ActionPlan(inbox_id=inbox.id, reference_time=utcnow())
        db.add(plan)
        db.flush()
        item = ActionItem(
            plan_id=plan.id,
            item_type="todo",
            destination="none",
            title="t",
            fingerprint="f" * 64,
        )
        db.add(item)
        db.flush()
        execution = WorkerExecution(
            action_item_id=item.id, worker="master-worker", state="dispatched", dispatch_id="mw-intake-int_x"
        )
        db.add(execution)
        db.commit()
    database.engine.dispose()

    monkeypatch.setattr(cli, "get_settings", lambda: cli_settings)
    monkeypatch.setattr(sys, "argv", ["action-hub", "worker-sync"])
    with patch("action_hub.services.workers.master_worker_sync.httpx.get", return_value=MagicMock(status_code=401)):
        with pytest.raises(SystemExit) as exc:
            cli.main()
    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["failed"] == 1
