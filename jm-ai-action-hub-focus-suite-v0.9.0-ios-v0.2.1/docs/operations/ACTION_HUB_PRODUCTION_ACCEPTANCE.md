# Action Hub production acceptance

## Local gate

Run `cd server && make acceptance-local`. It uses only a `mktemp -d` root, loopback dry-run servers, a temporary SQLite database, synthetic Korean input, and no external credentials or provider writes. The receipt is `evidence/production-acceptance-<UTC>.json`; it records redacted commands, exit codes, and SHA evidence but never headers, secrets, or raw capture text.

Local success is `LOCAL_PASS_EXTERNAL_PENDING`, not a production declaration. Roll back a failed restore using its sibling pre-restore snapshot; preserve the exact receipt and temporary path for inspection.

## Manual live acceptance

CARD-03-03 requires owner-provided isolated credentials and an approved host. Do not run it against production accounts, physical iOS devices, TestFlight, or an unapproved provider project.

LIVE-ACCEPTANCE PENDING (사용자 인프라 필요)

iOS-XCTEST PENDING (Full Xcode 필요)

LICENSE/NOTICE 부재 — 소유자 제공 대기
