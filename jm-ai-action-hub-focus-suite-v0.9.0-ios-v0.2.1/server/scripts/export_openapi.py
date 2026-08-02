#!/usr/bin/env python3
"""Export or verify the deterministic OpenAPI document used by native clients."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from action_hub.config import Settings
from action_hub.main import create_app


def render_document() -> str:
    app = create_app(
        Settings(
            app_env="test",
            database_url="sqlite+pysqlite:///:memory:",
            data_dir=ROOT / "data",
            mobile_access_token_secret="openapi-export-secret-000000000000000000",
        )
    )
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail when the checked-in contract has drifted")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "openapi" / "action-hub.openapi.json",
        help="output/contract path",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    rendered = render_document()
    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

    if args.check:
        if not output.exists():
            raise SystemExit(f"OPENAPI_CONTRACT_MISSING path={output}")
        if output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(f"OPENAPI_CONTRACT_DRIFT path={output}")
        print(f"OPENAPI_CONTRACT_OK sha256={digest}")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
