from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from action_hub.connectors.github import GitHubConnector
from action_hub.connectors.google_calendar import GoogleCalendarConnector
from action_hub.connectors.todoist import TodoistConnector
from action_hub.models import ActionItem


def item(**overrides):
    base = dict(
        plan_id="plan",
        item_type="todo",
        destination="todoist",
        title="제안서 작성",
        description="원문",
        priority=3,
        labels=["sales"],
        confidence=0.9,
        needs_review=False,
        fingerprint="x" * 64,
    )
    base.update(overrides)
    return ActionItem(**base)


def test_todoist_payload(settings):
    due = datetime(2026, 7, 29, 18, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = TodoistConnector(settings).build_payload(item(due_at=due))
    assert payload["content"] == "제안서 작성"
    assert payload["due_datetime"].startswith("2026-07-29T18:00:00")


def test_github_payload(settings):
    repository, payload = GitHubConnector(settings).build_payload(item(
        item_type="project_task", destination="github", repository="owner/repo", assignee="octocat"
    ))
    assert repository == "owner/repo"
    assert payload["assignees"] == ["octocat"]


def test_google_calendar_payload(settings):
    start = datetime(2026, 7, 29, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    payload = GoogleCalendarConnector(settings).build_payload(item(
        item_type="event", destination="google_calendar", start_at=start, end_at=start + timedelta(hours=1)
    ))
    assert payload["start"]["dateTime"].startswith("2026-07-29T10:00:00")
    assert payload["id"] == "x" * 32


def test_todoist_live_request_is_bearer_authenticated(settings):
    from unittest.mock import MagicMock, patch

    live = settings.model_copy(update={"execution_mode": "live", "todoist_token": "todo-token"})
    response = MagicMock(status_code=200)
    response.json.return_value = {"id": "123", "url": "https://todoist.example/task/123"}
    with patch("action_hub.connectors.todoist.httpx.post", return_value=response) as post:
        result = TodoistConnector(live).execute(item())
    assert result.success is True
    assert result.external_id == "123"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer todo-token"
    assert post.call_args.args[0].endswith("/api/v1/tasks")


def test_github_live_issue_request_uses_configured_version(settings):
    from unittest.mock import MagicMock, patch

    live = settings.model_copy(update={"execution_mode": "live", "github_token": "gh-token"})
    response = MagicMock(status_code=201)
    response.json.return_value = {"number": 42, "html_url": "https://github.example/owner/repo/issues/42"}
    work_item = item(item_type="project_task", destination="github", repository="owner/repo")
    with patch("action_hub.connectors.github.httpx.post", return_value=response) as post:
        result = GitHubConnector(live).execute(work_item)
    assert result.success is True
    assert result.external_id == "42"
    assert post.call_args.kwargs["headers"]["X-GitHub-Api-Version"] == live.github_api_version
    assert post.call_args.args[0].endswith("/repos/owner/repo/issues")


def test_google_calendar_conflict_is_recovered_by_event_id(settings):
    from unittest.mock import MagicMock, patch

    live = settings.model_copy(update={
        "execution_mode": "live",
        "google_calendar_access_token": "calendar-token",
    })
    start = datetime(2026, 7, 29, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    event = item(
        item_type="event",
        destination="google_calendar",
        start_at=start,
        end_at=start + timedelta(hours=1),
    )
    conflict = MagicMock(status_code=409)
    recovered = MagicMock(status_code=200)
    recovered.json.return_value = {"id": "x" * 32, "htmlLink": "https://calendar.example/event"}
    with patch("action_hub.connectors.google_calendar.httpx.post", return_value=conflict), patch(
        "action_hub.connectors.google_calendar.httpx.get", return_value=recovered
    ) as get:
        result = GoogleCalendarConnector(live).execute(event)
    assert result.success is True
    assert result.external_id == "x" * 32
    assert get.call_args.args[0].endswith("/events/" + "x" * 32)
