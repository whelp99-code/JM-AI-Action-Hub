from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_ROOT.parent
RECEIPT = REPO_ROOT / "evidence" / "production-acceptance-20260802T203926Z.json"


def test_forced_archive_failure_cannot_produce_pass_criterion(tmp_path: Path) -> None:
    real_make = shutil.which("make")
    assert real_make is not None
    original_receipt = RECEIPT.read_bytes()
    fake_make = tmp_path / "make"
    fake_make.write_text(
        f'#!/usr/bin/env bash\nif [[ "$*" == *source-release* ]]; then exit 73; fi\nexec "{real_make}" "$@"\n',
        encoding="utf-8",
    )
    fake_make.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "ACCEPTANCE_RECEIPT_PATH": str(RECEIPT),
    }
    try:
        result = subprocess.run(
            ["make", "acceptance-local"],
            cwd=SERVER_ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    finally:
        RECEIPT.write_bytes(original_receipt)

    assert result.returncode != 0
    assert "LOCAL_ACCEPTANCE_OK" not in result.stdout
    assert "LOCAL_ACCEPTANCE_FAILED" in result.stderr
    assert receipt["criteria"]["2"]["status"] == "FAIL"
    assert receipt["criteria"]["2"]["exitCode"] == 73


def test_stdout_hash_failure_fails_closed_without_pass_receipt(tmp_path: Path) -> None:
    original_receipt = RECEIPT.read_bytes()
    failing_sha = tmp_path / "shasum"
    failing_sha.write_text("#!/usr/bin/env bash\nexit 91\n", encoding="utf-8")
    failing_sha.chmod(0o755)
    environment = {
        **os.environ,
        "SHA256_BIN": str(failing_sha),
        "ACCEPTANCE_RECEIPT_PATH": str(RECEIPT),
    }
    try:
        result = subprocess.run(
            ["make", "acceptance-local"],
            cwd=SERVER_ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    finally:
        RECEIPT.write_bytes(original_receipt)

    assert result.returncode != 0
    assert "LOCAL_ACCEPTANCE_OK" not in result.stdout
    assert "LOCAL_ACCEPTANCE_FAILED" in result.stderr
    assert receipt["externalStatus"] == "LOCAL_FAIL_EXTERNAL_PENDING"
    assert receipt["criteria"]["1"]["status"] == "FAIL"
    assert receipt["criteria"]["1"]["stdoutSha256"] is None
    assert not all(criterion["status"] == "PASS" for criterion in receipt["criteria"].values())
    assert not any(
        criterion["status"] == "PASS" and not criterion["stdoutSha256"]
        for criterion in receipt["criteria"].values()
    )
