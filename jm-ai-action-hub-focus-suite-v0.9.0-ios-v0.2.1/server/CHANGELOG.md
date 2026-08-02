# Changelog

## 0.9.0 — 2026-08-01

### Decision and focus foundation

- Added explainable importance/urgency assessment with user-confirmed Q1/Q2/Q3/Q4 classification.
- Added independent attention-state tracking so focus decisions do not overwrite execution state.
- Added persistent daily capacity, human Big3, AI Big3, overload warnings, and ranked commitments.
- Added deterministic 3–5 step decomposition with per-step human/AI/hybrid/external ownership.
- Added single-active Focus Sessions with pause, resume, extend, abandon, complete, elapsed-time accounting, and green/yellow/red traffic state.
- Added explicit day-close decisions for reschedule, split, delegate, cancel, and waiting-for; Q4 never deletes an item.
- Added weekly focus analytics for session minutes, Big3 completion, Q2 investment, carry-over, traffic distribution, and estimate accuracy.

### Mobile and contract

- Added mobile triage, matrix, commitments, microstep, focus-session, day-close, and focus-report APIs.
- Added dashboard focus summary and backward-compatible mobile API v1 additions.
- Added Alembic revision `0005_decision_focus_foundation` with additive migration from v0.8.0.
- Updated the frozen OpenAPI contract to server v0.9.0.

### Verification

- 86 Python tests pass.
- Statement coverage is 82.72%, above the enforced 80% release gate.
- Live HTTP and Swift clients completed the full focus control flow.
- A real v0.8.0 SQLite database preserved Plan and Action identifiers and titles after migration.

## 0.8.0 — 2026-07-31

### Native mobile foundation

- Added administrator-created, five-minute QR pairing sessions with HMAC-only code storage and one-time compare-and-set claiming.
- Added device-scoped HMAC access tokens, short access lifetime, rotating refresh-token families, bounded lost-response retry, reuse detection, and remote device revocation.
- Added mobile capabilities, dashboard, review, plan mutation, approval, execution, activity, and HMAC-signed cursor-based delta-change endpoints.
- Added optimistic `revision` checks for plans and action items with explicit HTTP 409 conflicts.
- Added mobile devices, pairing sessions, refresh tokens, offline captures, APNs notifications, and revision columns through Alembic migration `0004_mobile_foundation`.

### Offline capture and push

- Added per-device batch capture idempotency, content-hash conflict detection, concurrent request protection, and stale processing-lock recovery.
- Added APNs token registration and a transactional push outbox with generic privacy-preserving alerts, HTTP/2 ES256 provider authentication, retry, and stale-lock recovery.
- Added push events for review, AI status, follow-up, deadline, and connector failures without embedding source text in notifications.

### iOS contract and interoperability

- Added stable OpenAPI operation IDs and a checked-in `0.8.0` OpenAPI contract.
- Added production HTTPS enforcement, explicit/configured public pairing URL enforcement, minimum iOS app version negotiation, scope isolation, and mobile capability discovery.
- Added QR SVG/terminal output and mobile device administration commands.
- Added HTTP/Swift end-to-end smoke tooling covering pairing, capture, revisioned edits, approval, execution, activity, and changes.
- Preserved all v0.7.0 plans and items in the verified `0004_mobile_foundation` upgrade path.

### Verification

- 78 Python tests pass with warnings treated as errors.
- Statement coverage is 81.27%, above the enforced 80% threshold.
- Fresh v0.7.0 database migration preserves existing plans and action items.
- The Swift client completed a live FastAPI end-to-end flow against the v0.8.0 server.


## 0.7.0 — 2026-07-29

### Closed-loop operations

- Added Alembic baseline and additive upgrade path from the direct-created v0.1.0 schema.
- Added transactional outbox, exponential retry, row claiming, stale-lock recovery, and a separate control-loop worker.
- Split external registration (`registered`) from real-world completion (`completed`).
- Added external state mirrors, sync conflicts, reconciliation, and non-destructive missing-item handling.

### Provider state sync

- Added signed Todoist, GitHub, and Fireflies webhook ingestion with delivery deduplication.
- Added Todoist complete/uncomplete/delete handling.
- Added GitHub Issue close/reopen, Pull Request, Workflow Run, and Check Suite handling.
- Added monotonic completion protection so late CI events cannot downgrade a merged action.
- Added Todoist/GitHub recovery markers and Google Calendar OAuth refresh-token broker.

### Human–AI execution

- Added human/AI/hybrid/external executor metadata.
- Added GitHub workflow adapters for Codex, Claude, Copilot, Orca, Hermes, and Master Worker routes.
- Added dispatch, workflow, check, PR, human-review, and merge state tracking.
- Kept merge, deployment, external communication, and high-impact actions behind human approval.

### Commitments, planning, meetings, and learning

- Added waiting-for and follow-up lifecycle.
- Added duration, deadline, work mode, energy, preferred worker, dependencies, and completion evidence.
- Added daily capacity/overload decisions and AI-delegation candidates.
- Added Fireflies V2 meeting intake and retry.
- Added approval-only personal rules and weekly ROI metrics.

### Interface and security

- Expanded the PWA with Today decision, AI dispatch, and due follow-up panels.
- Expanded REST and MCP tools.
- Added connector active probes and readiness database checks.
- Added CSP, API no-store policy, external share-target script, HSTS in production, request-body limits, and stricter event correlation.
- Added Docker API/worker split, PostgreSQL overlay, systemd worker, and upgrade/verification scripts.

### Verification

- 53 automated tests pass with warnings treated as errors.
- Statement coverage remains above the enforced 80% threshold.
- Python compile and JavaScript syntax checks pass.

## 0.1.0 — 2026-07-28

- Added mobile-first PWA capture and approval UI.
- Added Korean/English rule parser and optional LLM-compatible parser.
- Added Todoist, GitHub Issues, Google Calendar, and ICS connectors.
- Added approval gate, audit log, idempotency, partial failure, and retry.
- Added daily brief and optional MCP adapter.
- Added SQLite/PostgreSQL support, Docker, CI, backup scripts, and Korean documentation.
- Added secure plan-link handoff, deterministic Google event IDs, protected ICS downloads, and server-side validation.
