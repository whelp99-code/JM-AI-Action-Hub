from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import uvicorn
from sqlalchemy import select

from .config import get_settings
from .database import Database
from .models import MobileDevice
from .schemas import MobileDeviceRead
from .services.mobile_auth import create_pairing, get_device, revoke_device
from .services.parser import build_parser
from .services.qr import print_qr_ascii, write_qr_svg
from .worker import run_once


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="action-hub")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the API and PWA")
    serve.add_argument("--host", default=settings.host)
    serve.add_argument("--port", type=int, default=settings.port)

    parse = sub.add_parser("parse", help="Parse text without writing to the database")
    parse.add_argument("text")
    parse.add_argument("--timezone", default=settings.timezone)
    parse.add_argument("--reference-time")

    sub.add_parser("migrate", help="Upgrade the database schema to the packaged Alembic head")

    check = sub.add_parser("check", help="Check database and production configuration readiness")
    check.add_argument("--json", action="store_true", dest="as_json")

    worker = sub.add_parser("worker-once", help="Run one durable queue/webhook/follow-up cycle")
    worker.add_argument("--reconcile", action="store_true")
    worker.add_argument("--provider", action="append", dest="providers")

    pairing = sub.add_parser("mobile-pairing", help="Create a one-time iOS pairing payload")
    pairing.add_argument("--base-url", default=settings.mobile_public_base_url)
    pairing.add_argument("--scope", action="append", dest="scopes")
    pairing.add_argument("--created-by", default="cli")
    pairing.add_argument("--qr-output", help="Write a scan-ready SVG QR to this path")
    pairing.add_argument("--print-qr", action="store_true", help="Print a scannable terminal QR")

    sub.add_parser("mobile-devices", help="List paired mobile devices")
    revoke = sub.add_parser("mobile-revoke", help="Revoke a paired mobile device")
    revoke.add_argument("device_id")

    args = parser.parse_args()
    if args.command == "serve":
        uvicorn.run("action_hub.main:app", host=args.host, port=args.port, reload=False)
        return
    if args.command == "parse":
        tz = ZoneInfo(args.timezone)
        reference = datetime.fromisoformat(args.reference_time) if args.reference_time else datetime.now(tz)
        items = build_parser(settings).parse(args.text, reference, args.timezone)
        print(json.dumps([x.model_dump(mode="json") for x in items], ensure_ascii=False, indent=2))
        return

    settings.ensure_directories()
    database = Database(settings.database_url)
    try:
        if args.command == "migrate":
            database.create_schema(use_migrations=True)
            print("MIGRATION_OK")
            return
        if args.command == "check":
            database.create_schema(use_migrations=settings.run_migrations)
            payload = {
                "database": database.ping(),
                "production_ready": settings.is_production_ready,
                "api_key_secure": settings.api_key_is_secure,
                "mobile_token_secret_secure": settings.mobile_token_secret_is_secure,
                "apns_configured": settings.apns_configured,
                "execution_mode": settings.execution_mode,
                "version": settings.version,
            }
            print(json.dumps(payload, ensure_ascii=False) if args.as_json else "\n".join(f"{k}={v}" for k, v in payload.items()))
            raise SystemExit(0 if payload["database"] and payload["production_ready"] else 1)
        if args.command == "worker-once":
            database.create_schema(use_migrations=settings.run_migrations)
            with database.session_factory() as db:
                result = run_once(db, settings, reconcile=args.reconcile, providers=args.providers)
            print(json.dumps(result.as_dict(), ensure_ascii=False))
            return
        if args.command == "mobile-pairing":
            if not args.base_url:
                raise SystemExit("--base-url or ACTION_HUB_MOBILE_PUBLIC_BASE_URL is required")
            database.create_schema(use_migrations=settings.run_migrations)
            with database.session_factory() as db:
                result = create_pairing(
                    db,
                    settings,
                    scopes=args.scopes,
                    created_by=args.created_by,
                    public_base_url=args.base_url,
                )
            print(result.model_dump_json(indent=2))
            if args.qr_output:
                target = write_qr_svg(result.qr_payload, args.qr_output)
                print(f"PAIRING_QR_SVG={target}")
            if args.print_qr:
                print_qr_ascii(result.qr_payload, sys.stdout)
            return
        if args.command == "mobile-devices":
            database.create_schema(use_migrations=settings.run_migrations)
            with database.session_factory() as db:
                rows = list(db.scalars(select(MobileDevice).order_by(MobileDevice.created_at.desc())))
                payload = [MobileDeviceRead.from_device(row).model_dump(mode="json") for row in rows]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        if args.command == "mobile-revoke":
            database.create_schema(use_migrations=settings.run_migrations)
            with database.session_factory() as db:
                try:
                    device = get_device(db, args.device_id)
                except LookupError as exc:
                    raise SystemExit(str(exc)) from exc
                revoke_device(db, device)
            print("MOBILE_DEVICE_REVOKED")
            return
    finally:
        database.engine.dispose()


if __name__ == "__main__":
    main()
