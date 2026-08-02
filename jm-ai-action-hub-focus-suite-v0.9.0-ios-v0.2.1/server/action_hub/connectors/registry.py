from __future__ import annotations

from ..config import Settings
from ..models import Destination
from .base import Connector
from .github import GitHubConnector
from .google_calendar import GoogleCalendarConnector
from .local_ics import LocalICSConnector
from .none import NoneConnector
from .todoist import TodoistConnector


class ConnectorRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._connectors: dict[str, Connector] = {
            Destination.TODOIST.value: TodoistConnector(settings),
            Destination.GITHUB.value: GitHubConnector(settings),
            Destination.GOOGLE_CALENDAR.value: GoogleCalendarConnector(settings),
            Destination.LOCAL_ICS.value: LocalICSConnector(settings),
            Destination.NONE.value: NoneConnector(settings),
        }

    def get(self, destination: str) -> Connector:
        try:
            return self._connectors[destination]
        except KeyError as exc:
            raise KeyError(f"Unsupported destination: {destination}") from exc

    def statuses(self, *, probe: bool = False) -> list[dict]:
        descriptions = {
            "todoist": "Personal tasks and reminders",
            "github": "Development project issues",
            "google_calendar": "Calendar events through Google Calendar API",
            "local_ics": "Local .ics export fallback",
            "none": "Local note only",
        }
        statuses: list[dict] = []
        for name, connector in self._connectors.items():
            configured = connector.configured
            healthy: bool | None = None
            detail = descriptions[name]
            if probe:
                healthy, probe_detail = connector.healthcheck()
                detail = f"{detail} · {probe_detail}"
            statuses.append(
                {
                    "name": name,
                    "configured": configured,
                    "execution_mode": self.settings.execution_mode,
                    "detail": detail,
                    "healthy": healthy,
                }
            )
        return statuses
