from __future__ import annotations

import json
import sys
import types
from unittest.mock import patch

import pytest

from action_hub.config import Settings
from action_hub.database import Database


def test_cli_parse_serve_migrate_check_and_worker_once(tmp_path, capsys, monkeypatch):
    from action_hub import cli

    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'cli.db'}",
        data_dir=tmp_path,
        execution_mode="dry_run",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    monkeypatch.setattr(sys, "argv", ["action-hub", "parse", "내일 오전 10시 회의", "--reference-time", "2026-07-28T10:00:00+09:00"])
    cli.main()
    parsed = json.loads(capsys.readouterr().out)
    assert parsed[0]["item_type"] == "event"

    with patch("action_hub.cli.uvicorn.run") as run:
        monkeypatch.setattr(sys, "argv", ["action-hub", "serve", "--host", "127.0.0.1", "--port", "9999"])
        cli.main()
        run.assert_called_once()

    monkeypatch.setattr(sys, "argv", ["action-hub", "migrate"])
    cli.main()
    assert "MIGRATION_OK" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["action-hub", "check", "--json"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert json.loads(capsys.readouterr().out)["database"] is True

    monkeypatch.setattr(sys, "argv", ["action-hub", "worker-once", "--reconcile", "--provider", "todoist"])
    cli.main()
    assert "outbox_processed" in json.loads(capsys.readouterr().out)


def test_mcp_entrypoint_registers_and_calls_control_tools(monkeypatch):
    registered: dict[str, object] = {}

    class FakeMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def decorator(func):
                registered[func.__name__] = func
                return func
            return decorator

        def run(self):
            registered["ran"] = True

    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = FakeMCP
    server_module = types.ModuleType("mcp.server")
    mcp_module = types.ModuleType("mcp")
    monkeypatch.setitem(sys.modules, "mcp", mcp_module)
    monkeypatch.setitem(sys.modules, "mcp.server", server_module)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp_module)

    requests: list[tuple] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def request(self, method, url, headers=None, json=None):
            requests.append((method, url, headers, json))
            return FakeResponse()

    from action_hub import mcp_server

    monkeypatch.setattr(mcp_server.httpx, "Client", FakeClient)
    monkeypatch.setenv("ACTION_HUB_API_KEY", "mcp-key")
    mcp_server.main()
    assert registered["ran"] is True

    assert registered["parse_actions"]("할 일") == {"ok": True}
    assert registered["get_action_plan"]("plan") == {"ok": True}
    assert registered["approve_action_plan"]("plan", ["item"], True) == {"ok": True}
    assert registered["execute_action_plan"]("plan") == {"ok": True}
    assert registered["today_action_brief"]() == {"ok": True}
    assert registered["build_daily_decision"](240, 5, False) == {"ok": True}
    assert registered["dispatch_action_to_worker"]("item", "claude", True) == {"ok": True}
    assert registered["list_due_followups"]() == {"ok": True}
    assert registered["resolve_followup"]("follow", "resolved", "done") == {"ok": True}
    assert registered["weekly_action_report"]() == {"ok": True}
    assert len(requests) == 10
    assert requests[0][2]["X-Action-Hub-Key"] == "mcp-key"


def test_worker_loop_runs_one_cycle_and_stops(tmp_path, monkeypatch):
    from action_hub import worker

    settings = Settings(
        app_env="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'loop.db'}",
        data_dir=tmp_path,
        worker_poll_seconds=0.2,
        reconciliation_interval_seconds=0.2,
    )
    database = Database(settings.database_url)
    database.create_schema()
    calls = []

    class StopAfterOne:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _seconds):
            self.stopped = True
            return True

    def fake_run_once(_db, _settings, *, reconcile=False, providers=None):
        calls.append((reconcile, providers))
        return worker.RunOnceResult(reconciled=1 if reconcile else 0)

    monkeypatch.setattr(worker, "run_once", fake_run_once)
    worker.run_forever(database, settings, stop_event=StopAfterOne(), poll_seconds=0.2, reconciliation_seconds=0.2)
    assert calls == [(True, None)]
    database.engine.dispose()
