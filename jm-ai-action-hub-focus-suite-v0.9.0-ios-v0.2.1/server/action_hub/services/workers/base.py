from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ...models import ActionItem, WorkerExecution


@dataclass(slots=True)
class WorkerDispatchResult:
    success: bool
    dispatch_id: str | None = None
    payload: dict = field(default_factory=dict)
    error: str | None = None
    simulated: bool = False


class WorkerAdapter(Protocol):
    name: str

    def can_handle(self, item: ActionItem) -> bool: ...

    def dispatch(self, item: ActionItem, execution: WorkerExecution) -> WorkerDispatchResult: ...
