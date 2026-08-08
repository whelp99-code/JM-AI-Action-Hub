# Wave 03 revision report

- Recorded at: `2026-08-02T21:51:08Z`
- Repository HEAD: `9c8f28d5a9eb34a2c30a869be620885023171977`
- Delivery state: `UNCOMMITTED_WORKTREE`
- Initial independent review: `evidence/lunamax-wave03-final-review.md`
- Final independent review: `evidence/lunamax-wave03-final-r2-review.md`
- Initial orchestration: Orca `run_b7a9c71893ad`; CARD-03-01 `task_495193c49cb3`; CARD-03-02 `task_16bbc9c94240`; first revision `task_3ca365053205`
- R2 implementation: exact collaboration worker `/root/wave03_r2_terra` using `gpt-5.6-terra`; the provider-mismatched Orca attempt was fenced and not accepted

## Findings and closure

| Severity | ID | Finding | Correction | State |
|---|---|---|---|---|
| HIGH | SOL-W3-01 | SHA-256 helper failure could leave criteria as PASS with empty hashes | SHA failure now records `FAIL` with null hash, returns nonzero, suppresses success sentinel, and emits `LOCAL_FAIL_EXTERNAL_PENDING` | CLOSED |
| HIGH | SOL-W3-02 | Caller-controlled symlink ancestors could redirect backup/restore paths | Source, output, archive, and target ancestors now reject caller-writable symlinks before mutation while preserving the root-managed macOS `/var` alias | CLOSED |
| MEDIUM | BR-OUT-01 | Preexisting hardlink output could overwrite protected content | Explicit backup output must be a new path; staged archive publication uses a no-clobber hardlink and rejects regular, symlink, and hardlink collisions | CLOSED |
| MEDIUM | ACC-SMOKE-01 | Atomic close-day smoke checked only the mixed-request 404 | Smoke snapshots item state plus decision/audit counts and proves all values unchanged after the mixed 404 | CLOSED |

## Revision verification

- Terra: shell syntax exit `0`; focused tests `21 passed`/exit `0`; exact backup/restore rehearsal exit `0`; `verify.sh` exit `0` with `174 passed`; `make verify` exit `0` with `174 passed`; local acceptance criteria 1–5 PASS; diff-check exit `0`.
- Sol independent rerun: `syntax=0`, `focused=0`, `verify_script=0`, `make_verify=0`, `acceptance_local=0`, `diff_check=0`; S1/S3 remained passing.
- Canonical receipt: criteria 1–5 `PASS`, exitCode `0`, 64-character lowercase SHA-256, `externalStatus=LOCAL_PASS_EXTERNAL_PENDING`.
- After the master LOCAL COMPLETE traceability sync, canonical local acceptance was rerun with raw exit `0`; receipt `planSha256=45d329c26e6902f74f6d9d5838d21d4fb6ca6b12367d71cbaa2b0f55f774a510` matches the final plan bytes.
- Adversarial probes: SHA helper injection returns nonzero with no local-success sentinel; caller-writable symlink ancestors return `64` without mutation; existing regular/symlink/hardlink outputs return `64` with protected bytes unchanged; failed restore check returns `1` and restores the original manifest.

## LunaMax final re-verification

- Model: `gpt-5.6-luna`
- Reasoning effort requested: `max`
- Headless session: `019fc468-fa77-78a1-a5e6-a1274593b640`
- Process exit: `0`
- Verdict: `PASS`
- Severity: `CRITICAL 0 / HIGH 0 / MEDIUM 0 / LOW 0`
- `verify.sh`: exit `0`, `174 passed`, coverage `83.17%`, `VERIFY_OK`.
- `make verify`: exit `0`, `174 passed`, coverage `83.17%`, compile/OpenAPI/Node checks PASS.
- Local acceptance and receipt validation: exit `0`; criteria 1–5 PASS; `LOCAL_PASS_EXTERNAL_PENDING`.
- S1-S3 focused regression: exit `0`.
- iOS release verification: exit `1` only for `no such module 'XCTest'` after Xcodeproj/OpenAPI/static PASS.
- Repository diff-check: exit `0`; staged index empty; HEAD unchanged.
- Plan machine check: exit `0`, `vague=0`, `incomplete=0`, `pending=0`; all extracted repository commands/targets exist.

## Preserved boundaries

- CARD-03-03 was not started: `LIVE-ACCEPTANCE PENDING (사용자 인프라 필요)`.
- `iOS-XCTEST PENDING (Full Xcode 필요)`; rerun under Full Xcode.
- `LICENSE/NOTICE 부재 — 소유자 제공 대기`; no legal file was invented.
- No stage, commit, push, PR, merge, deployment, external provider live call, Xcode installation, or iOS device signing.
