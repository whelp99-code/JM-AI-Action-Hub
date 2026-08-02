from __future__ import annotations

import os

import httpx


def main() -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise SystemExit("Install MCP support first: pip install -e '.[mcp]'") from exc

    base_url = os.getenv("ACTION_HUB_MCP_BASE_URL", "http://127.0.0.1:8787").rstrip("/")
    api_key = os.getenv("ACTION_HUB_API_KEY", "")
    timezone = os.getenv("ACTION_HUB_TIMEZONE", "Asia/Seoul")
    mcp = FastMCP("JM-AI Action Hub")

    def call(method: str, path: str, payload: dict | None = None):
        headers = {"X-Action-Hub-Key": api_key} if api_key else {}
        with httpx.Client(timeout=30) as client:
            response = client.request(method, f"{base_url}{path}", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    def parse_actions(text: str, source: str = "mcp") -> dict:
        """Parse natural language into a reviewable action plan. Does not execute it."""
        return call("POST", "/api/v1/inbox/parse", {"text": text, "source": source, "timezone": timezone})

    @mcp.tool()
    def get_action_plan(plan_id: str) -> dict:
        """Read an action plan and proposed items, external states, workers, and follow-ups."""
        return call("GET", f"/api/v1/plans/{plan_id}")

    @mcp.tool()
    def approve_action_plan(plan_id: str, item_ids: list[str] | None = None, force_review_items: bool = False) -> dict:
        """Approve selected items. Review-required items stay blocked unless explicitly forced."""
        return call("POST", f"/api/v1/plans/{plan_id}/approve", {
            "item_ids": item_ids, "actor": "mcp", "force_review_items": force_review_items,
        })

    @mcp.tool()
    def execute_action_plan(plan_id: str, item_ids: list[str] | None = None) -> dict:
        """Queue previously approved items through configured connectors."""
        return call("POST", f"/api/v1/plans/{plan_id}/execute", {
            "item_ids": item_ids, "actor": "mcp", "retry_failed": True,
        })

    @mcp.tool()
    def today_action_brief() -> dict:
        """Return today's events, due tasks, overdue work, waiting items, and AI candidates."""
        return call("GET", "/api/v1/brief/today")

    @mcp.tool()
    def build_daily_decision(available_minutes: int = 480, max_items: int = 12, include_ai: bool = True) -> dict:
        """Prioritize today's work within a time budget without modifying source systems."""
        return call("POST", "/api/v1/planning/decision", {
            "available_minutes": available_minutes, "max_items": max_items, "include_ai": include_ai,
        })

    @mcp.tool()
    def dispatch_action_to_worker(action_item_id: str, worker: str = "codex", force: bool = False) -> dict:
        """Queue one approved AI/hybrid action to an existing configured worker workflow."""
        return call("POST", f"/api/v1/items/{action_item_id}/dispatch", {
            "worker": worker, "actor": "mcp", "force": force,
        })

    @mcp.tool()
    def list_due_followups() -> list[dict]:
        """List external responses that require follow-up now."""
        return call("GET", "/api/v1/followups/due")

    @mcp.tool()
    def resolve_followup(followup_id: str, state: str, note: str = "") -> dict:
        """Mark a follow-up response_received, followed_up, resolved, or cancelled."""
        return call("POST", f"/api/v1/followups/{followup_id}/resolve", {
            "state": state, "actor": "mcp", "note": note,
        })

    @mcp.tool()
    def weekly_action_report() -> dict:
        """Return measured weekly completion, waiting, AI-dispatch, and saved-time metrics."""
        return call("GET", "/api/v1/reports/weekly")

    mcp.run()


if __name__ == "__main__":
    main()
