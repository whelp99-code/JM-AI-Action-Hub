from __future__ import annotations

import argparse
import json
import logging
import signal
import threading
import time
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import Database
from .services.followups import process_due_followups
from .services.outbox import process_outbox_batch
from .services.push import process_push_batch
from .services.reconciliation import reconcile_external_states
from .services.webhooks import process_webhook_batch

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunOnceResult:
    outbox_processed: int = 0
    webhooks_processed: int = 0
    followups_due: int = 0
    reconciled: int = 0
    push_processed: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def run_once(
    db: Session,
    settings: Settings,
    *,
    reconcile: bool = False,
    providers: list[str] | None = None,
) -> RunOnceResult:
    """Run one durable control-loop cycle.

    Registration/AI dispatch is drained first so newly created external mirrors
    exist before provider webhooks are applied. Every service commits each unit
    independently, so a failure in one queue does not block the others.
    """

    outbox = process_outbox_batch(db, settings)
    webhooks = process_webhook_batch(db, settings)
    due = process_due_followups(db, settings)
    pushes = process_push_batch(db, settings)
    reconciliation = {"checked": 0, "failed": 0}
    if reconcile:
        reconciliation = reconcile_external_states(db, settings, providers=providers)
    return RunOnceResult(
        outbox_processed=outbox["processed"],
        webhooks_processed=webhooks["processed"],
        followups_due=len(due),
        reconciled=reconciliation["checked"],
        push_processed=pushes["processed"],
        failed=outbox["failed"] + webhooks["failed"] + reconciliation["failed"] + pushes["failed"],
    )


def run_forever(
    database: Database,
    settings: Settings,
    *,
    stop_event: threading.Event | None = None,
    poll_seconds: float | None = None,
    reconciliation_seconds: float | None = None,
) -> None:
    stop_event = stop_event or threading.Event()
    poll = max(0.2, poll_seconds or settings.worker_poll_seconds)
    reconcile_every = max(poll, reconciliation_seconds or settings.reconciliation_interval_seconds)
    next_reconcile = time.monotonic()

    while not stop_event.is_set():
        should_reconcile = time.monotonic() >= next_reconcile
        with database.session_factory() as db:
            result = run_once(db, settings, reconcile=should_reconcile)
        if should_reconcile:
            next_reconcile = time.monotonic() + reconcile_every
        if any(result.as_dict().values()):
            logger.info("Control-loop cycle: %s", result.as_dict())
        stop_event.wait(poll)


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def stop(_signum, _frame) -> None:
        stop_event.set()

    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            signal.signal(signum, stop)


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="action-hub-worker")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    parser.add_argument("--reconcile", action="store_true", help="Include provider reconciliation in --once")
    parser.add_argument("--provider", action="append", dest="providers", help="Limit reconciliation provider")
    parser.add_argument("--poll-seconds", type=float, default=settings.worker_poll_seconds)
    parser.add_argument("--reconciliation-seconds", type=float, default=settings.reconciliation_interval_seconds)
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings.ensure_directories()
    database = Database(settings.database_url)
    database.create_schema(use_migrations=settings.run_migrations)
    try:
        if args.once:
            with database.session_factory() as db:
                result = run_once(db, settings, reconcile=args.reconcile, providers=args.providers)
            print(json.dumps(result.as_dict(), ensure_ascii=False))
            return
        stop_event = threading.Event()
        _install_signal_handlers(stop_event)
        run_forever(
            database,
            settings,
            stop_event=stop_event,
            poll_seconds=args.poll_seconds,
            reconciliation_seconds=args.reconciliation_seconds,
        )
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
