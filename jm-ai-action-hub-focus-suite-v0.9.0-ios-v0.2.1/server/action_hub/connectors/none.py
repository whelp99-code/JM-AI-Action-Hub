from __future__ import annotations

from ..config import Settings
from ..models import ActionItem
from .base import ConnectorResult, ConnectorSnapshot


class NoneConnector:
    name = "none"

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return True

    def execute(self, item: ActionItem) -> ConnectorResult:
        return ConnectorResult(success=True, external_id=item.id, external_url=None, payload={"local": True}, simulated=True)

    def find_existing(self, item: ActionItem) -> ConnectorResult | None:
        return ConnectorResult(success=True, external_id=item.id, payload={"local": True, "recovered": True}, simulated=True)

    def fetch_state(self, external_id: str, item: ActionItem | None = None) -> ConnectorSnapshot:
        return ConnectorSnapshot(success=True, state="completed", external_id=external_id, payload={"local": True})

    def healthcheck(self) -> tuple[bool, str]:
        return True, "Local note connector ready"
