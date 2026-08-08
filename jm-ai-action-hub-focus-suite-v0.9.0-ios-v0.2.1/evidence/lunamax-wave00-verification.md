# Wave 00 LunaMax Independent Verification

- Verifier: Codex `gpt-5.6-luna`
- Reasoning effort: `max`
- Headless session: `019fc371-11e2-7563-8d3f-8dbca8c5fa7f`
- CLI process exit code: `0`
- Sandbox: `workspace-write` (pytest temporary files only; verifier was instructed not to modify project files)
- Verdict: `PASS_WITH_FINDINGS`
- Repository HEAD: `9c8f28d5a9eb34a2c30a869be620885023171977`

## Command evidence

| # | Command | Raw exit | Result |
|---|---|---:|---|
| 1 | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_security.py` | 0 | `11 passed` |
| 2 | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_control_loop.py tests/test_hardening.py -k webhook` | 0 | `5 passed` |
| 3 | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_mobile.py -k 'secret or token or pairing or refresh'` | 0 | `19 passed` |
| 4 | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q` | 0 | `101 passed` |
| 5 | `git diff --check -- server` | 0 | no output; no whitespace errors |

## Independent findings

1. **MEDIUM — S2 queued unsigned-delivery bypass.** A non-production process with explicit unsigned opt-in can persist a delivery with `signature_valid=false` in `server/action_hub/services/webhooks.py:124-127`. The batch processor later claims and processes pending/retry rows at `server/action_hub/services/webhooks.py:683-719` without rechecking the persisted signature result against the current environment/policy. If the same database is reused after switching to production, an old unsigned GitHub delivery can reach a business handler. Fresh production ingress remains blocked, but the end-to-end queued path is not fully fail-closed.
2. **LOW — stale webhook operations documentation.** `server/docs/16_CLOSED_LOOP_SYNC_KR.md:78` says Development/Test accept unsigned webhooks unconditionally. The implementation instead requires explicit `ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS=true`, whose default is false, and production rejects unsigned input even when the flag is true.

## Fail-closed verdict

- S1 admin API: `PASS`; no unprotected admin mutation route was found.
- S2 webhook: `CONDITIONAL PASS`; fresh ingress is closed, queued unsigned delivery processing needs a second policy guard.
- S3 mobile authentication: `PASS`; missing/placeholder/equal secret fails before claim, refresh, or bearer credential processing, and development fallback is domain-separated HKDF.

## Scope and residual risk

- The verifier observed the same 16 server changes and no route/schema/DB/token-TTL change.
- Existing untracked `.serena/`, plan, and evidence paths were preserved. The Luna CLI/indexing integration also exposed a repository-local `.serena/` directory; it is not part of Phase 0 and was not removed or staged.
- No live GitHub provider, production deployment, network acceptance, commit, push, PR, merge, or iOS signing was performed.
- Docker's explicit `0.0.0.0` bind remains outside this correction card; secure API key and network controls remain required for that deployment surface.

