from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..models import ActionItem


@dataclass(slots=True)
class ConnectorResult:
    success: bool
    external_id: str | None = None
    external_url: str | None = None
    payload: dict = field(default_factory=dict)
    error: str | None = None
    simulated: bool = False


@dataclass(slots=True)
class ConnectorSnapshot:
    success: bool
    state: str | None = None
    external_id: str | None = None
    external_url: str | None = None
    payload: dict = field(default_factory=dict)
    external_updated_at: datetime | None = None
    error: str | None = None


class Connector(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    def execute(self, item: ActionItem) -> ConnectorResult: ...

    def fetch_state(self, external_id: str, item: ActionItem | None = None) -> ConnectorSnapshot: ...

    def healthcheck(self) -> tuple[bool, str]: ...
