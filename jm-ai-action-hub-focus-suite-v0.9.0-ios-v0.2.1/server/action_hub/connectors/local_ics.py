from __future__ import annotations

import os
import re
from datetime import timedelta, timezone
from pathlib import Path

from ..config import Settings
from ..models import ActionItem
from .base import ConnectorResult, ConnectorSnapshot


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _stamp(value) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(item: ActionItem, timezone_name: str) -> str:
    if not item.start_at:
        raise ValueError("ICS event requires start_at")
    uid = f"{item.id}@jm-ai-action-hub"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//JM-AI//Action Hub//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_stamp(item.created_at)}",
        f"SUMMARY:{_escape(item.title)}",
        f"DESCRIPTION:{_escape(item.description or '')}",
    ]
    if item.is_all_day:
        start_date = item.start_at.date()
        lines.extend(
            [
                f"DTSTART;VALUE=DATE:{start_date.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(start_date + timedelta(days=1)).strftime('%Y%m%d')}",
            ]
        )
    else:
        end_at = item.end_at or item.start_at + timedelta(hours=1)
        lines.extend([f"DTSTART:{_stamp(item.start_at)}", f"DTEND:{_stamp(end_at)}"])
    lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
    return "\r\n".join(lines)


class LocalICSConnector:
    name = "local_ics"

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return True

    def execute(self, item: ActionItem) -> ConnectorResult:
        try:
            content = build_ics(item, self.settings.timezone)
            export_dir = Path(self.settings.data_dir) / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            safe_id = re.sub(r"[^a-zA-Z0-9-]", "", item.id)
            path = export_dir / f"{safe_id}.ics"
            path.write_text(content, encoding="utf-8", newline="")
            return ConnectorResult(
                success=True,
                external_id=safe_id,
                external_url=f"/api/v1/exports/{safe_id}.ics",
                payload={"path": str(path), "timezone": self.settings.timezone},
                simulated=False,
            )
        except (OSError, ValueError) as exc:
            return ConnectorResult(success=False, error=str(exc))

    def find_existing(self, item: ActionItem) -> ConnectorResult | None:
        safe_id = re.sub(r"[^a-zA-Z0-9-]", "", item.id)
        path = self.settings.data_dir / "exports" / f"{safe_id}.ics"
        if not path.exists():
            return None
        return ConnectorResult(
            success=True,
            external_id=safe_id,
            external_url=f"/api/v1/exports/{safe_id}.ics",
            payload={"path": str(path), "recovered": True},
        )

    def fetch_state(self, external_id: str, item: ActionItem | None = None) -> ConnectorSnapshot:
        path = self.settings.data_dir / "exports" / f"{external_id}.ics"
        return ConnectorSnapshot(success=True, state="scheduled" if path.exists() else "missing", external_id=external_id, payload={"path": str(path)})

    def healthcheck(self) -> tuple[bool, str]:
        export_dir = Path(self.settings.data_dir) / "exports"
        try:
            export_dir.mkdir(parents=True, exist_ok=True)
            writable = export_dir.is_dir() and os.access(export_dir, os.W_OK)
            return writable, "ICS export directory writable" if writable else "ICS export directory is not writable"
        except OSError as exc:
            return False, str(exc)
