# JM-AI Action Hub 실운영 개선계획서 v1

- 문서 상태: `PLAN_ONLY — MASTER APPROVAL REQUIRED`
- 작성일: 2026-08-03 (Asia/Seoul)
- 대상 저장소: `/Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1`
- 기준 HEAD: `9c8f28d` (`main`, `origin/main`과 동일)
- 승인 게이트: Fable5가 `APPROVED`를 발행하기 전에는 이 문서 외 코드·설정·테스트·릴리스 산출물을 변경하지 않는다.
- 계획 티어: `XL` — MUST 14개, 예상 직접 변경 42~55파일, DB migration 0개, 최고 위험 R4(인증 기본값 전환). 사용자 지정 산출물이 단일 파일이므로 XL 섹션을 이 문서에 통합한다.

## 1. 사용자-visible outcome

Action Hub의 관리 API와 Webhook이 설정 누락 시 닫히고, 모바일 토큰 키가 관리 키와 암호학적으로 분리되며, 대량 Matrix·오프라인 캡처·일마감이 데이터 규모와 실패에 안전하게 동작한다. 소스 배포본은 개발 산출물과 로컬 DB를 포함하지 않고, 문서대로 신규 설치·실데이터 smoke·백업/복구를 재현할 수 있어야 한다.

## 2. 조사 범위와 상태 라벨

상태 라벨은 다음 의미로 사용한다.

- `CONFIRMED`: 현재 HEAD의 파일 또는 이번 조사에서 실행한 명령으로 직접 확인.
- `INFERRED`: 확인된 호출·데이터 흐름에서 도출했으나 변경 후 실행으로 재검증해야 함.
- `ASSUMED`: 승인 후 진행을 위한 안전 기본값. 근거·영향·롤백을 명시.
- `UNKNOWN`: 자격증명·외부 Provider·실기기 등 현재 환경에서 판정 불가.

### 2.1 환경 기준선

| 상태 | 항목 | 증거 |
|---|---|---|
| CONFIRMED | 브랜치/HEAD | `git status --short --branch` → `main...origin/main`; `git log -5 --oneline` → HEAD `9c8f28d` |
| CONFIRMED | 사용자 변경 | 저장소 상위에 untracked `../.serena/` 1개. 본 작업에서 읽기·수정·삭제·stage하지 않는다. |
| CONFIRMED | Server unit baseline | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q` → exit 0, 전체 수집 테스트 통과 |
| CONFIRMED | Server release gate | `cd server && make verify` → exit 2; 첫 단계 `ruff check .`에서 72건/32파일 실패, 뒤 단계 미실행 |
| CONFIRMED | iOS static baseline | `cd ios && make check` → exit 0; `XCODEPROJ_CHECK_OK`, OpenAPI 80 operations/status ok, `IOS_PROJECT_STATIC_OK sources=30` |
| CONFIRMED | Swift package baseline | `cd ios && make test` → exit 2; macOS에서 `ActivityKit.ActivityAttributes` unavailable로 `FocusActivityAttributes.swift:5` compile 실패 |
| CONFIRMED | Canonical release scripts | `test -x server/scripts/verify.sh && test -x ios/scripts/verify_release.sh` → exit 0; 두 script는 현재 HEAD에 존재하고 executable |
| UNKNOWN | 실제 Provider·운영 호스트·실기기 | Todoist/GitHub/Google/Fireflies 자격증명, 운영 URL, iPhone signing 환경은 제공되지 않음 |

기준선 실패는 이번 개선의 회귀로 계산하지 않는다. 다만 최종 실운영 판정은 Server `make verify`와 iOS 검증 경로가 모두 exit 0이 될 때까지 `BLOCKED`다.

### 2.2 지시서 주장 대조

| ID | 실제 코드 확인 | 판정과 계획 보정 |
|---|---|---|
| S1 | CONFIRMED — `Settings.host` 기본값은 `0.0.0.0`; `require_api_key()`는 production 이외에서 `api_key`가 없으면 즉시 return | 지시서 유효. test 환경도 런타임 우회를 두지 않고 테스트 fixture에 키를 주입한다. 기본 host는 `127.0.0.1`. |
| S2 | CONFIRMED — `receive_webhook()`은 secret이 없을 때 production만 거부하고 development/test는 `signature_valid=False`로 저장 | 지시서 유효. `ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS=false`를 추가하고 production에서는 true도 거부한다. |
| S3 | CONFIRMED — `_secret()`은 development에서 secure `api_key` 원문 bytes를 모바일 access/refresh/pairing HMAC에 재사용 | 지시서 유효. HKDF-SHA256 도메인 분리 fallback을 사용한다. 명시 모바일 secret이 있으면 그것을 우선한다. |
| C1 | CONFIRMED — API와 service 인자에는 `limit_per_quadrant`가 있으나 `matrix()`가 모든 non-terminal `ActionItem`을 먼저 materialize한 뒤 Python에서 잘라냄 | 지시서의 “상한 부재” 표현은 응답 상한 관점에서는 부정확하다. 해결 대상은 DB row load 상한이며, 정확한 total count는 aggregate query로 분리한다. |
| C2 | CONFIRMED — iOS queue는 성공/duplicate만 삭제하고 failed receipt는 같은 정렬 위치에 남음. Server는 실패 행을 `failed`로 저장해 무제한 재claim 가능 | 실패 횟수와 DLQ 소유자는 iOS queue로 고정한다. transport-level 실패는 횟수를 올리지 않고, receipt `failed`만 올린다. |
| C3 | CONFIRMED — `refreshAll()`이 7개 전체 조회를 완료한 뒤 `synchronizeChanges()`가 delta payload를 버리고 cursor만 기록 | “사용 또는 제거”가 미결정인 지시서 문제를 해소한다. v1은 호출과 전용 cursor 저장을 제거하며 서버 `/changes` 계약은 다른 client 호환을 위해 유지한다. |
| C4 | CONFIRMED — 존재하지 않는 item은 warning+continue, 조건 누락은 `ValueError`, commit은 loop 종료 후 1회 | API 결과를 atomic all-or-nothing으로 고정한다. 사전 검증 실패 시 어떤 item도 변경하지 않는다. |
| P2-UA | CONFIRMED — Core package `HTTPTransport.swift`가 `0.1` 하드코딩. `AppConfiguration`은 App target이므로 Core에서 직접 참조 불가 | 지시서의 직접 참조는 target dependency를 역전시킨다. `URLSessionTransport(appVersion:)` 주입 후 App composition root에서 `AppConfiguration.appVersion`을 전달한다. |
| P2-doc | CONFIRMED — Server known limitations는 v0.7.0이며 Native Mobile App을 제외로 표기; iOS 문서도 v0.1.0 중심 | 두 문서를 v0.9.0/server 및 v0.2.1/iOS 기준으로 각각 갱신한다. 과거 upgrade 문서는 역사 자료로 유지한다. |
| P2-release | CONFIRMED — `.gitignore`/`.dockerignore`는 일부 제외하지만 release archive의 금지 path를 검사하는 target 없음 | source archive 생성/검사 target을 Server Makefile에 추가하고 실제 archive listing으로 금지 path 0건을 증명한다. |
| OPS | CONFIRMED — backup/restore 스크립트는 있으나 archive traversal·대상 검증·복구 후 DB check가 없음 | 마스터 프로토콜의 백업/복구 실증 기준을 별도 카드로 추가한다. 임시 복제 data에서만 rehearsal한다. |
| LINT | CONFIRMED — 지시서의 “ruff 미실행”과 달리 현재 실행 가능하며 72건 실패 | 32파일 mechanical lint 카드로 격리한다. 기능 카드와 섞지 않고 full gate 전에 수행한다. |

## 3. 목표와 비범위

### 3.1 목표

1. 인증·Webhook·모바일 signing의 fail-closed 기본값과 독립 key domain을 코드·설정·문서·테스트에서 일치시킨다.
2. Matrix 조회량, offline queue 실패, day-close transaction의 운영 한계를 명시적 계약으로 만든다.
3. iOS network identity와 refresh 흐름의 불필요한 작업을 제거하고 호환 테스트를 둔다.
4. release archive, 신규 설치, smoke, backup/restore의 재현 가능한 명령과 exit code 0 증거를 만든다.
5. 기존 lint·Swift package 기준선 실패를 기능 결함과 분리해 해소하거나 정확한 blocker로 보고한다.

### 3.2 Non-goals

- iOS 실기기 build, code signing, TestFlight upload, App Store 제출.
- 다중 사용자 로그인, OIDC/OAuth 사용자 인증, RBAC, tenant 분리.
- `/api/v1/mobile/changes` server endpoint나 OpenAPI contract 제거.
- PostgreSQL migration 또는 SQLite schema migration.
- Provider production 자격증명 생성·회전·외부 콘솔 webhook 등록.
- 자동 production 배포, 외부 메시지 발송, Git commit/push/PR/merge.
- 과거 버전 upgrade 문서의 역사적 버전 문자열 일괄 치환.

## 4. 원자 요구사항과 인수 기준

### REQ-SEC-001 — 관리 API fail-closed (P0, MUST)

Actor: admin client. Trigger: protected route request. Precondition: application started. Input: `X-Action-Hub-Key`. Validation: `normalized = key.strip()`이고 원문과 normalized가 같으며 control character가 없고 길이 32 이상이고 `normalized.casefold()`가 정확한 denylist `{change-me, change-me-before-exposing-to-network, secret, password}`에 없을 때만 secure. Authorization: constant-time comparison. Processing: key가 없거나 insecure하면 development/production/test 모두 503, 잘못된 header는 401, 일치하면 요청 수행. Output: 기존 success response 또는 FastAPI detail error. State change: unauthorized request는 없음. Side effects: 없음. Performance: O(key length). Security: environment 이름으로 bypass 금지. Excluded: `/health`, `/readiness`, mobile public pairing claim/refresh. Dependencies: Settings, router dependency, test fixtures.

- ACCEPT-SEC-001-A: Given secure API key와 matching header, When protected endpoint 호출, Then 기존 2xx 동작을 유지한다.
- ACCEPT-SEC-001-B: Given API key 미설정, When protected endpoint 호출, Then 503이고 handler/DB write가 실행되지 않는다.
- ACCEPT-SEC-001-C: Given configured key와 missing/wrong header, When protected endpoint 호출, Then 401이고 secret 값이 response/log에 나오지 않는다.

### REQ-SEC-002 — loopback 기본 binding (P0, MUST)

Actor: local operator. Trigger: default Settings/`.env.example`/`make dev`. Input: host override optional. Processing: default `127.0.0.1`, explicit `ACTION_HUB_HOST=0.0.0.0`만 LAN bind. Output: uvicorn bind address. Security: 무의식적 LAN 노출 금지.

- ACCEPT-SEC-002-A: Given host env 없음, When Settings 생성과 dev command 검사, Then 둘 다 `127.0.0.1`이다.
- ACCEPT-SEC-002-B: Given explicit `ACTION_HUB_HOST=0.0.0.0`, When Settings 생성, Then override를 보존하고 문서가 API key 선행 조건을 경고한다.

### REQ-SEC-003 — unsigned webhook opt-in (P0, MUST)

Actor: webhook provider/operator. Input: provider body/header/secret and `allow_unsigned_webhooks`. Processing: secret 없음+flag false는 503-class configuration error; development/test+flag true만 unsigned 수용; production+flag true도 거부. State: 허용된 경우 delivery `signature_valid=false`. Security: default false.

- ACCEPT-SEC-003-A: Given development와 secret 없음과 flag false, When webhook 수신, Then delivery 미생성 및 configuration error.
- ACCEPT-SEC-003-B: Given development와 explicit flag true, When unsigned webhook 수신, Then pending delivery 생성 및 `signature_valid=false`.
- ACCEPT-SEC-003-C: Given production와 flag true, When unsigned webhook 수신, Then 거부 및 delivery 미생성.

### REQ-SEC-004 — mobile signing key domain 분리 (P0, MUST)

Actor: mobile auth service. Input: explicit mobile secret 또는 development API key. Processing: explicit secret은 UTF-8 bytes로 사용; development fallback은 `IKM = api_key.encode("utf-8")`, SHA-256, `salt = b"jm-ai-action-hub/mobile-auth/salt/v1"`, `info = b"jm-ai-action-hub/mobile-auth/v1"`, output length 32인 HKDF 결과 사용; API key raw bytes 반환 금지. Output: bytes. Security: deterministic, domain-separated, log 금지. Rollback: explicit mobile secret 설정으로 HKDF fallback 우회.

Explicit mobile secret validator는 §REQ-SEC-001의 공통 denylist에 mobile 전용 exact normalized/casefold deny value `change-me-mobile-token-secret-before-use`를 추가한다. 이 value는 32자 이상이어도 insecure이며 mobile auth 503으로 처리한다.

Explicit mobile secret과 API key를 각각 §REQ-SEC-001 방식으로 normalize한 뒤 둘 다 존재하고 `hmac.compare_digest()`가 true이면 mobile auth는 503, error code `mobile_secret_reuses_admin_key`로 fail closed한다. equality check 전에 secret 값을 log/response에 넣지 않는다.

- ACCEPT-SEC-004-A: Given explicit mobile secret, When access/refresh/pairing signing, Then 그 secret domain을 사용한다.
- ACCEPT-SEC-004-B: Given development secure API key만 존재, When `_secret()` 실행, Then 32-byte deterministic result이고 API key bytes와 다르다.
- ACCEPT-SEC-004-C: Given production에서 mobile secret 없음, When mobile auth 호출, Then `mobile_auth_not_configured`로 fail closed.
- ACCEPT-SEC-004-D: Given API key가 ASCII `a` 32개, When 위 HKDF contract로 derive, Then lowercase hex는 `bf1d6bcac5a2cc5e9780c35384e7f5115c28342167c111dee1e7c42f69896e18`이다.
- ACCEPT-SEC-004-E: Given explicit mobile secret과 API key가 normalized equality, When pairing/token operation, Then 503 `mobile_secret_reuses_admin_key`이고 token/device state change 0건이다.
- ACCEPT-SEC-004-F: Given `.env.example`의 `change-me-mobile-token-secret-before-use`, When pairing/token operation, Then 503 `mobile_auth_not_configured`이고 token/device state change 0건이다.

### REQ-PERF-001 — Matrix query-level bound (P1, MUST)

Actor: admin/mobile dashboard. Input: `limit_per_quadrant` 1..500. Processing: aggregate count query로 전체 count/untriaged를 계산하고, q1..q4 item 조회는 각 SQL `LIMIT limit_per_quadrant`; 전체 ActionItem ORM materialization 금지. Output schema unchanged. Performance: executed SELECT count ≤6, materialized `ActionItem` rows ≤`4 * limit`, 10,000 non-terminal fixture에서 response list 상한 유지.

- ACCEPT-PERF-001-A: Given quadrant별 limit 초과 data, When `limit=25`, Then 각 list ≤25이며 counts는 전체 정확한 값이다.
- ACCEPT-PERF-001-B: Given 10,000 rows, When Matrix 호출, Then unbounded `select(ActionItem)` statement가 없고 response schema는 unchanged다.
- ACCEPT-PERF-001-C: Given SQLAlchemy event/ORM load counters, When Matrix `limit=25`, Then SELECT ≤6이고 loaded ActionItem ≤100이다.

### REQ-MOB-001 — offline capture retry cap와 DLQ (P1, MUST)

Actor: iOS app/share extension. Input: capture receipt. Processing: processed/duplicate 삭제; failed receipt는 persisted attempt count 증가; count가 5에 도달하면 capture와 last error/timestamps를 `dead-letter/`로 atomic move; transport exception은 attempt 증가 없음. 모든 enqueue/read/apply/move/restore/purge는 App Group의 `.offline-capture.lock`에 대한 exclusive advisory file lock 안에서 수행하고 file lock은 actor instance가 아니라 filesystem file descriptor로 app/share-extension process 사이를 직렬화한다. Output: pending queue에서 poison capture 제외, `deadLetterCount()`/`deadLetters()`로 진단 가능. Retention: 자동 삭제 없음.

- ACCEPT-MOB-001-A: Given 첫 capture가 5회 failed이고 뒤 capture가 성공, When 반복 flush, Then 첫 capture는 DLQ에 보존되고 뒤 capture는 업로드·삭제된다.
- ACCEPT-MOB-001-B: Given network transport exception, When flush 실패, Then attempt count와 DLQ count는 변하지 않는다.
- ACCEPT-MOB-001-C: Given legacy array와 raw CaptureInput file, When queue open, Then capture 손실 없이 versioned queue record로 읽힌다.
- ACCEPT-MOB-001-D: Given 같은 App Group URL을 사용하는 queue instance 2개, When enqueue와 flush/restore를 동시에 100회 수행, Then clientCaptureId 손실·중복·손상 0건이고 pending+DLQ+processed 합계가 input unique ID 수와 같다.

### REQ-MOB-002 — unused delta sync 제거 (P1, MUST)

Actor: connected iOS user. Processing: `refreshAll()`은 canonical 7개 resource 조회만 수행; 그 후 `/changes` 호출과 cursor file write 없음. Server delta API/Core client method는 호환을 위해 유지. State: 기존 cursor file은 무해하게 남겨두며 삭제하지 않는다.

- ACCEPT-MOB-002-A: Given connected session, When refreshAll, Then dashboard/review/activity/focus state가 갱신되고 `/changes` request는 0회다.
- ACCEPT-MOB-002-B: Given old cursor file, When upgraded app starts, Then crash·credential loss 없이 full refresh한다.

### REQ-DAY-001 — atomic close-day (P1, MUST)

Actor: admin/mobile user. Input: DayCloseRequest. Validation: 모든 action ID 존재, ID 중복 금지, 아래 decision matrix를 schema 단계에서 검증. Processing: 전 항목 validation 후 한 transaction에서 mutation/audit/commit. Failure: 422 validation 또는 404 missing entity; write 0건. Output: success에서는 processed=request decision count, warnings empty.

| decision | required | optional/default | forbidden |
|---|---|---|---|
| `reschedule` | N/A | `to_date: date` default target day+1, `reason` | waiting_for, follow_up_at, executor |
| `split` | N/A | reason | to_date, waiting_for, follow_up_at, executor |
| `delegate` | N/A | `executor: ExecutorType` default AI, reason | to_date, waiting_for, follow_up_at |
| `deadline_change` | `to_date: date` | reason | waiting_for, follow_up_at, executor |
| `cancel` | N/A | reason | to_date, waiting_for, follow_up_at, executor |
| `waiting` | nonblank `waiting_for: str`, timezone-aware `follow_up_at: datetime` | reason | to_date, executor |

중복 ID는 FastAPI 422 `value_error`와 message `duplicate action_item_id: <id>`; missing item은 404 `{"detail":{"code":"action_item_not_found","action_item_id":"<id>"}}`. forbidden field가 non-null이면 422이며 field 이름을 message에 포함한다.

- ACCEPT-DAY-001-A: Given 모두 유효한 2개 decision, When close-day, Then 두 변경·audit가 한 commit으로 저장된다.
- ACCEPT-DAY-001-B: Given 유효 1개 뒤 missing ID 1개, When close-day, Then 4xx이고 첫 item도 변경되지 않는다.
- ACCEPT-DAY-001-C: Given deadline_change without to_date 또는 waiting field 누락, When request validation, Then 422이고 service mutation은 0건이다.
- ACCEPT-DAY-001-D: Given 각 decision row의 forbidden field 하나가 non-null, When request validation, Then decision별 422이고 service 호출 0회다.

### REQ-IOS-001 — current User-Agent injection (P2, MUST)

Actor: server/operator. Input: AppConfiguration.appVersion. Processing: App target composition root가 `URLSessionTransport(appVersion:)`에 version을 전달; Core는 app target import 금지. Output header: `JM-AI-Action-Hub-iOS/<version>`. Validation: 공백/개행 없는 semantic version string.

- ACCEPT-IOS-001-A: Given version `0.2.1`, When request 전송, Then User-Agent가 정확히 `JM-AI-Action-Hub-iOS/0.2.1`이다.
- ACCEPT-IOS-001-B: Given Core unit test의 injected version, When transport 생성, Then header 검증이 network 없이 통과한다.
- ACCEPT-IOS-001-C: Given production `AppModel.swift`, When iOS static validator 실행, Then `MobileSession(store: credentialStore, appVersion: AppConfiguration.appVersion)` composition이 정확히 1건이다.

### REQ-DOC-001 — current limitations/operations docs (P2, MUST)

Server 문서는 v0.9.0과 native iOS v0.2.1 존재, single-user API key 경계, unsigned opt-in 위험, DLQ 운영, delta removal을 반영한다. iOS 문서는 현재 구현된 Live Activity/Focus/Widget과 실제 검증 경계를 반영한다. 역사 upgrade 문서는 보존한다. `server/scripts/validate_current_docs.py`가 required claims와 canonical stale patterns를 검사한다.

- ACCEPT-DOC-001-A: Given 두 known limitations 문서, When docs validator 실행, Then 아래 file/heading-aware assertions가 모두 pass한다.

| File/section | Forbidden exact regex or line | Required exact regex or line |
|---|---|---|
| `server/docs/13_KNOWN_LIMITATIONS_KR.md` title H1 | `^# .*v0\.7\.0` | `^# .*v0\.9\.0` |
| same, H2 `의도적으로 제외한 기능` body until next H2 | full line `Native Mobile App` | N/A |
| same, H2 `현재 제약` body | N/A | `ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS=false`, `native iOS v0.2.1` |
| `ios/docs/12_KNOWN_LIMITATIONS_KR.md` all headings | `^## v0\.1\.0 제한$`, `^## v0\.2 후보$` | `^## v0\.2\.1 현재 제한$` |
| same, all bullet lines | `^- Live Activity 없음$` | bullet containing `dead-letter`, bullet containing `full refresh` |

Validator는 Markdown H1/H2 boundaries를 parse하고 assertion별 file/section/match count를 출력한다; substring-only global heuristic 금지.
- ACCEPT-DOC-001-B: Given 운영자, When 문서만 읽음, Then DLQ 위치·복구/삭제 수동 절차와 unsigned flag 제약을 실행할 수 있다.

### REQ-REL-001 — clean source archive (P2, MUST)

Actor: release operator. Input: current worktree. Processing: repository root의 `server`, `ios`, `contracts`, `docs`, `LICENSE`, `NOTICE`, `RELEASE_INFO.json`, `RELEASE_MANIFEST.sha256`만 allowlist로 순회한다. Canonical directory matcher는 `(^|/)(\.git|\.serena|\.venv|\.build|__pycache__|\.pytest_cache|\.ruff_cache|DerivedData|backups|dist)(/|$)`; file matcher는 `(^|/)data/.*\.db$|\.(ipa|xcarchive|dSYM)$`; basename이 `.env`로 시작하면 exact `.env.example`만 허용하고 다른 `.env*`는 제외한다. 모든 symlink를 제외한다. Archive root는 `jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/`; normalized mode/mtime/uid/gid로 deterministic gzip을 생성한다. Output은 repository root `dist/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1-source.tar.gz`와 adjacent `.sha256`. Security: secret/local DB 포함 금지.

- ACCEPT-REL-001-A: Given dirty local build/data dirs, When release target 실행, Then archive listing의 금지 path가 0건이다.
- ACCEPT-REL-001-B: Given archive, When extract to temp and install, Then server package install/check가 exit 0이다.
- ACCEPT-REL-001-C: Given archive listing, When config template 검사, Then `server/.env.example` exact 1건이고 basename `.env`/다른 `.env*` 0건이다. Template parser는 아래 `EXPECTED_ENV_KEYS`와 assignment key set의 exact equality를 요구해 unknown/missing key를 모두 reject한다. Credential-like key가 regex `(API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY)`에 match할 때 exact non-secret typed configuration exceptions는 `ACTION_HUB_MOBILE_ACCESS_TOKEN_MINUTES`, `ACTION_HUB_MOBILE_REFRESH_TOKEN_DAYS`, `ACTION_HUB_GOOGLE_OAUTH_TOKEN_URL` 세 개뿐이다. 이 예외를 제외한 nonempty 허용 map은 정확히 `ACTION_HUB_API_KEY=change-me-before-exposing-to-network`, `ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET=change-me-mobile-token-secret-before-use`, `POSTGRES_PASSWORD=change-this-postgres-password` 세 개이며 다른 matching key는 empty여야 한다. 새 credential-like key는 exhaustive key set에 추가되더라도 default nonempty를 fail-closed reject한다. Key suffix가 `_URL`, `_BASE`, `_DATABASE_URL`인 모든 nonempty value는 URL parser의 username/password가 둘 다 nil이어야 한다.

```text
EXPECTED_ENV_KEYS = {
ACTION_HUB_APP_ENV,ACTION_HUB_HOST,ACTION_HUB_PORT,ACTION_HUB_LOG_LEVEL,ACTION_HUB_TIMEZONE,
ACTION_HUB_API_KEY,ACTION_HUB_ALLOWED_ORIGINS,ACTION_HUB_DATABASE_URL,ACTION_HUB_DATA_DIR,
ACTION_HUB_RUN_MIGRATIONS,ACTION_HUB_EXECUTION_MODE,ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS,
ACTION_HUB_WORKER_INLINE,ACTION_HUB_WORKER_POLL_SECONDS,ACTION_HUB_OUTBOX_BATCH_SIZE,
ACTION_HUB_OUTBOX_MAX_ATTEMPTS,ACTION_HUB_RETRY_BASE_SECONDS,ACTION_HUB_WEBHOOK_BATCH_SIZE,
ACTION_HUB_RECONCILIATION_BATCH_SIZE,ACTION_HUB_RECONCILIATION_INTERVAL_SECONDS,
ACTION_HUB_PROCESSING_LOCK_TIMEOUT_SECONDS,ACTION_HUB_DEFAULT_ESTIMATED_MINUTES,
ACTION_HUB_DEFAULT_WORKDAY_MINUTES,ACTION_HUB_PLANNING_BUFFER_PERCENT,ACTION_HUB_FOLLOWUP_DEFAULT_DAYS,
ACTION_HUB_PERSONAL_RULE_MIN_OBSERVATIONS,ACTION_HUB_IMPORTANCE_THRESHOLD,ACTION_HUB_URGENCY_THRESHOLD,
ACTION_HUB_BIG3_LIMIT,ACTION_HUB_FOCUS_DEFAULT_MINUTES,ACTION_HUB_FOCUS_WARNING_PERCENT,
ACTION_HUB_FOCUS_MAX_MINUTES,ACTION_HUB_FOCUS_WEEKLY_WINDOW_DAYS,ACTION_HUB_MOBILE_ENABLED,
ACTION_HUB_MOBILE_PUBLIC_BASE_URL,ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET,
ACTION_HUB_MOBILE_ACCESS_TOKEN_MINUTES,ACTION_HUB_MOBILE_REFRESH_TOKEN_DAYS,
ACTION_HUB_MOBILE_REFRESH_REUSE_GRACE_SECONDS,ACTION_HUB_MOBILE_PAIRING_TTL_SECONDS,
ACTION_HUB_MOBILE_PAIRING_MAX_ATTEMPTS,ACTION_HUB_MOBILE_CAPTURE_BATCH_SIZE,
ACTION_HUB_MOBILE_CHANGE_BATCH_SIZE,ACTION_HUB_MOBILE_MIN_IOS_APP_VERSION,
ACTION_HUB_MOBILE_RECOMMENDED_IOS_APP_VERSION,ACTION_HUB_APNS_TEAM_ID,ACTION_HUB_APNS_KEY_ID,
ACTION_HUB_APNS_BUNDLE_ID,ACTION_HUB_APNS_PRIVATE_KEY_PATH,ACTION_HUB_APNS_ENVIRONMENT,
ACTION_HUB_APNS_BATCH_SIZE,ACTION_HUB_APNS_MAX_ATTEMPTS,ACTION_HUB_PARSER_MODE,
ACTION_HUB_LLM_BASE_URL,ACTION_HUB_LLM_API_KEY,ACTION_HUB_LLM_MODEL,ACTION_HUB_LLM_TIMEOUT_SECONDS,
ACTION_HUB_REQUEST_TIMEOUT_SECONDS,ACTION_HUB_MAX_INPUT_CHARS,ACTION_HUB_MAX_REQUEST_BODY_BYTES,
ACTION_HUB_DEFAULT_EVENT_MINUTES,ACTION_HUB_TODOIST_TOKEN,ACTION_HUB_TODOIST_DEFAULT_PROJECT_ID,
ACTION_HUB_TODOIST_CLIENT_SECRET,ACTION_HUB_GITHUB_TOKEN,ACTION_HUB_GITHUB_DEFAULT_REPO,
ACTION_HUB_GITHUB_WEBHOOK_SECRET,ACTION_HUB_PROJECT_ROUTES_JSON,ACTION_HUB_WORKER_ROUTES_JSON,
ACTION_HUB_GOOGLE_CALENDAR_ACCESS_TOKEN,ACTION_HUB_GOOGLE_CALENDAR_ID,
ACTION_HUB_GOOGLE_OAUTH_CLIENT_ID,ACTION_HUB_GOOGLE_OAUTH_CLIENT_SECRET,
ACTION_HUB_GOOGLE_OAUTH_REFRESH_TOKEN,ACTION_HUB_GOOGLE_OAUTH_TOKEN_URL,
ACTION_HUB_FIREFLIES_API_KEY,ACTION_HUB_FIREFLIES_WEBHOOK_SECRET,
ACTION_HUB_FIREFLIES_GRAPHQL_URL,POSTGRES_PASSWORD
}
```
- ACCEPT-REL-001-D: Given unchanged worktree, When source release를 isolated temp output 2개로 연속 build, Then 두 tar.gz byte SHA-256가 동일하다.

### REQ-OPS-001 — backup/restore rehearsal (P1, MUST)

Actor: operator. Input: explicit `--source-data`, `--archive`, `--target-data`; optional `.env`는 backup에 포함하지 않고 operator가 별도 secret store에서 복구한다. Processing: backup archive path 검증; restore는 absolute/`..`/symlink/hardlink member를 거부; target의 sibling pre-restore snapshot 후 extract; 복구 후 `action-hub check`. Rehearsal은 temp copy에서 seed marker 생성→backup→mutation→restore→marker 확인.

- ACCEPT-OPS-001-A: Given seeded temp SQLite, When backup/restore rehearsal, Then marker와 schema head가 복원되고 command exit 0.
- ACCEPT-OPS-001-B: Given `../` 또는 absolute member archive, When restore, Then extraction 전 nonzero exit이고 data unchanged.

### REQ-QUAL-001 — existing lint/Swift baseline closure (P2, MUST)

Actor: release verifier. Processing: 72 Ruff findings을 behavior-preserving mechanical changes로 별도 diff에서 해소; `FocusActivityAttributes`를 iOS-only availability guard로 package test 가능하게 변경. Output: Server make verify와 iOS verify_release exit 0. Excluded: assertion 완화, test skip, lint rule disable.

- ACCEPT-QUAL-001-A: Given current 32 lint files, When ruff check, Then 0 finding.
- ACCEPT-QUAL-001-B: Given macOS Swift package test, When `swift test`, Then ActivityKit availability compile error가 없고 all tests pass.

### REQ-ACC-001 — real-operation acceptance receipt (P0, MUST)

Actor: master verifier. Input: approved implementation, credentials supplied by owner. Processing: install, auth negative/positive smoke, representative real-format capture, backup/restore, docs check. Output: timestamped receipt with commands, exit codes, redacted identifiers. Secrets/raw personal content 금지.

Five production criteria and canonical evidence:

| # | Criterion | Canonical local command | Invariant |
|---|---|---|---|
| 1 | auth/webhook integrity | `cd server && make acceptance-security` | missing server key 503, missing/wrong header 401, correct key 2xx, bind 127.0.0.1; signed webhook 2xx/signature_valid true, invalid signature 401/delivery 0 |
| 2 | reproducible install | CARD-02-03 exact temp archive command | extracted archive install/check exit 0 |
| 3 | real-format smoke | `cd server && make acceptance-smoke` | Korean capture→plan/items, Matrix bounded, atomic day-close; synthetic identifiers only |
| 4 | backup/restore proof | `cd server && make rehearse-backup-restore` | marker/schema checksum restored; malicious cases rejected |
| 5 | current operations docs | `cd server && make docs-check` | stale_count=0, required_claims all present |

Runbook: `docs/operations/ACTION_HUB_PRODUCTION_ACCEPTANCE.md`. Receipt: `evidence/production-acceptance-<UTC YYYYMMDDTHHMMSSZ>.json` with schema `{schemaVersion, repoHead, planSha256, startedAt, finishedAt, criteria:{id,status,command,exitCode,stdoutSha256,evidence}, externalStatus, blockers:[{code,message}], redactions:[{field,method}]}`. `status` is `PASS|FAIL|BLOCKED`; evidence stores redacted IDs only; secret/header/raw capture text fields are never serialized.

- ACCEPT-ACC-001-A: Given no external credentials, When autonomous gates pass, Then status는 `LOCAL_PASS_EXTERNAL_PENDING`이고 production-ready로 과장하지 않는다.
- ACCEPT-ACC-001-B: Given owner credentials/host, When manual live smoke pass, Then five master production criteria가 evidence path와 1:1 mapping된다.

## 5. 고정 아키텍처 결정

### ADR-001 — 인증 우회 없는 runtime

Status: Proposed, 승인 시 Accepted. Options: test env bypass 유지 / explicit insecure flag / 모든 runtime fail-closed. Decision: 모든 runtime fail-closed, test client가 secure key/header 사용. Reason: 배포자가 APP_ENV=test를 설정해도 보호가 유지된다. Consequence: 기존 tests fixture와 local curl이 header를 보내야 한다. Rollback: 이전 commit revert; production에서 bypass flag 도입은 금지.

### ADR-002 — unsigned webhook은 non-production explicit opt-in

Decision: `allow_unsigned_webhooks=false`; true는 development/test만. Secret이 있으면 flag와 무관하게 signature 검증. Consequence: local fixture가 secret 또는 explicit flag를 지정. Rollback: flag false로 즉시 차단.

### ADR-003 — mobile key HKDF domain separation

Decision: explicit mobile secret 우선, development secure API key는 HKDF-SHA256으로 32-byte key 파생. Test 전용 fixed secret은 fixture에서 explicit 주입하는 방향으로 축소. Consequence: 기존 development mobile tokens는 무효화될 수 있다. Rollback: `ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET`에 이전 API key와 다른 stable secret을 설정하고 재pairing.

### ADR-004 — Matrix counts와 page rows 분리

Decision: aggregate count 1회 + quadrant별 bounded select 최대 4회. Reason: SQLite/PostgreSQL portable하고 exact counts 유지. Consequence: query 수는 늘지만 loaded rows가 bounded. Rollback: feature commit revert; schema migration 없음.

### ADR-005 — offline DLQ는 client-owned durable queue

Decision: server response contract는 유지하고 iOS queue record에 attempt metadata를 둔다. failed receipt 5회만 DLQ; transport exception 제외. Consequence: queue file decoder가 legacy formats를 지원해야 한다. Rollback: DLQ record를 pending directory로 복원하는 API/문서 제공.

### ADR-006 — v1 delta call 제거, server contract 유지

Decision: full refresh 뒤 payload를 버리는 call/cursor write만 제거. Reason: user-visible state correctness 변화 없이 network/IO 제거. Consequence: future real delta UI는 새 요구/설계가 필요. Rollback: synchronizeChanges 호출 복원.

### ADR-007 — day-close atomicity

Decision: 전체 사전 검증 후 all-or-nothing commit. Reason: day close는 서로 연관된 batch이며 silent partial success가 audit 신뢰를 훼손. Consequence: missing item 하나가 전체 request를 실패시킴. Rollback: transaction commit 전이라 data rollback; API semantics revert는 별도 승인 필요.

### ADR-008 — App version은 composition root injection

Decision: Core transport에 string injection, App target에서 AppConfiguration 전달. Reason: Core→App dependency 금지. Consequence: initializer call sites 업데이트. Rollback: default user agent는 package-safe fallback으로 유지하되 app production path는 injection test로 고정.

## 6. 계약

### 6.1 Configuration contract

| Env | Type/default | Invariant | Failure |
|---|---|---|---|
| `ACTION_HUB_HOST` | string / `127.0.0.1` | explicit override only | invalid host는 uvicorn startup failure |
| `ACTION_HUB_API_KEY` | optional string | protected route 사용 시 secure 32+ non-placeholder | 503 before handler |
| `ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS` | bool / false | production에서 true 금지 | unsigned request configuration error |
| `ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET` | optional string | production mobile enabled이면 secure 32+ | mobile auth 503 |

### 6.2 API/error contract

- Protected admin route: missing insecure server key → 503; missing/wrong client key → 401; matching → 기존 status.
- Webhook: missing signing secret and unsigned disabled → 503; invalid signature → 401; malformed JSON → 422. 기존 FastAPI detail shape를 v1에서 유지한다.
- Matrix: method/path/schema 유지. `limit_per_quadrant` default 100, min 1, max 500.
- Day close: request validation error 422; missing ActionItem 404; success 200. 실패 시 DB mutation/audit 0건.
- Stack trace, API key, derived key, webhook secret, raw personal capture text를 response/log에 포함하지 않는다.

### 6.3 Queue/state transition contract

Swift storage contract:

```swift
public struct OfflineCaptureQueueRecord: Codable, Sendable, Equatable {
  public let version: Int                 // exactly 1
  public let capture: CaptureInput
  public var attemptCount: Int            // 0...maxAttempts
  public var lastError: String?            // server-safe receipt error, max 1024 chars
  public var lastAttemptAt: Date?          // ActionHubJSON ISO-8601
}
public struct OfflineCaptureDeadLetter: Codable, Sendable, Equatable, Identifiable {
  public var id: String { record.capture.clientCaptureId }
  public let record: OfflineCaptureQueueRecord
  public let deadLetteredAt: Date
}
public actor OfflineCaptureQueue {
  public init(fileURL: URL, maxAttempts: Int = 5) // fileURL is legacy captures/pending.json
  public func deadLetterCount() async throws -> Int
  public func deadLetters(limit: Int = 100) async throws -> [OfflineCaptureDeadLetter]
  public func restoreDeadLetter(clientCaptureId: String) async throws
  public func purgeDeadLetter(clientCaptureId: String) async throws
}
```

- Base/layout: initializer `fileURL`은 exact legacy array path `<AppGroup>/captures/pending.json`. Base directory는 `fileURL.deletingLastPathComponent()` 즉 `<AppGroup>/captures`. Versioned pending은 `<AppGroup>/captures/pending/<clientCaptureId>.json`; DLQ는 `<AppGroup>/captures/dead-letter/<clientCaptureId>.json`; corrupt는 `<AppGroup>/captures/corrupt/<generated>.json`; lock은 `<AppGroup>/captures/.offline-capture.lock`.
- Legacy array migration: `<AppGroup>/captures/pending.json`의 `[CaptureInput]`을 lock 안에서 decode하고 각 ID를 versioned pending record로 atomic write한다. 동일 ID/same content destination이면 one copy로 처리; 동일 ID/different content이면 legacy file 전체를 corrupt로 move하고 pending destination을 보존하며 error를 throw. 모든 element write 성공 후에만 legacy array source를 삭제한다.
- Legacy per-file migration: 기존 `<AppGroup>/captures/pending/<id>.json`이 raw `CaptureInput`이면 read 시 same ID의 QueueRecord(attempt 0)로 same-path atomic replace한다. Decode/write 실패 시 source를 delete하지 않고 corrupt로 atomic move한다.
- Write/move: exclusive filesystem lock → temp file in same directory → `.atomic` replace/move → unlock. Lock/open/write/move errors throw `ActionHubAPIError.encoding` and preserve source.
- Restore: pending ID가 이미 있으면 source/destination 둘 다 보존하고 `ActionHubAPIError.encoding("capture already pending")`; 없으면 attemptCount 0, lastError/lastAttemptAt nil로 reset 후 atomic move.
- Purge: exact ID의 DLQ file만 삭제; missing ID는 idempotent success. UI에서 호출하지 않고 운영자-confirmed diagnostic path만 사용.

| Current | Event | Next | Side effect |
|---|---|---|---|
| pending(attempt 0..4) | processed/duplicate receipt | removed | capture file delete |
| pending(attempt 0..3) | failed receipt | pending(attempt+1) | last error/time atomic persist |
| pending(attempt 4) | failed receipt | dead-letter(attempt 5) | DLQ atomic move |
| pending | transport exception | pending(same attempt) | no metadata mutation |
| dead-letter | operator restore | pending(attempt 0) | explicit API/operation only |
| dead-letter | operator purge | deleted | explicit irreversible command only |

### 6.4 UI/event contract

- UI: SettingsView의 diagnostic section에 DLQ rows와 `모두 복원`/`모두 삭제` controls를 추가한다. `모두 복원`은 `@MainActor AppModel.restoreAllDeadLetters() async`를 호출해 `deadLetters(limit: 100)`을 empty가 될 때까지 반복 조회하고 각 ID를 restore하며 첫 collision에서 중단해 error를 표시한다. `모두 삭제`는 destructive confirmation alert에서 count와 “복구 불가”를 표시한 뒤 `@MainActor AppModel.purgeAllDeadLetters(confirmed: Bool) async`를 호출하며 confirmed=false이면 no-op, true이면 `deadLetters(limit: 100)`을 empty까지 반복해 각 ID를 purge한다. 각 loop는 이전 page보다 DLQ count가 감소하지 않으면 error로 중단한다. 처리 후 pending/DLQ count를 다시 읽는다.
- Event: 새 server event 없음. iOS local queue record schema version `1`; delivery ordering은 capture reference time then ID.
- Data migration: DB migration N/A — schema 변경 없음. iOS local file lazy migration만 수행.

## 7. Phase와 작업 카드

모든 카드는 `SEQUENTIAL`이다. 같은 파일 충돌을 피하기 위해 카드 순서를 유지한다. 각 카드 완료 후 diff를 관리자/Sol이 독립 검토하고 다음 카드로 진행한다.

### Phase 0 — P0 배포·보안

#### CARD-00-01 — S1 admin fail-closed와 loopback default

STATUS: `DONE` — final focused 11 passed/exit 0, full 101 passed/exit 0; evidence `evidence/wave-00-phase0.json`.

TASK: runtime 환경 이름과 무관한 관리 API 인증 및 loopback 기본 binding 구현.

DELIVERABLE:
- MODIFY `server/action_hub/config.py`, `server/action_hub/security.py`, `server/.env.example`, `server/Makefile`, `server/scripts/smoke_test.sh`.
- MODIFY `server/tests/conftest.py`, `server/tests/test_security.py`, `server/tests/test_control_loop.py`, `server/tests/test_features.py`, `server/tests/test_hardening.py`, `server/tests/test_mobile.py`.
- 증거: key 없음 503, wrong 401, correct success, default host assertion.

SCOPE:
- 허용: 위에 열거한 11개 파일만. `conftest.py` shared client와 열거한 5개 custom TestClient 파일에 secure key/header를 주입한다.
- 금지: route path/response schema, mobile bearer auth, production deployment.
- 구현 순서: Settings host 변경 → security dependency fail-closed → test client secure key/header → smoke script가 key 누락을 명시 실패 → env/docs example.
- 계약: `require_api_key(...) -> None`; server key misconfiguration 503, client mismatch 401.

VERIFY: `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_security.py` → exit 0, security tests all pass. `PYTHONPATH=. .venv/bin/python -m pytest -q` → exit 0, full suite pass.

#### CARD-00-02 — S2 signed webhook default

STATUS: `DONE` — final focused 5 passed/exit 0, full 101 passed/exit 0; evidence `evidence/wave-00-phase0.json`.

TASK: unsigned webhook explicit non-production opt-in 구현.

DELIVERABLE:
- MODIFY `server/action_hub/config.py`, `server/action_hub/services/webhooks.py`, `server/.env.example`.
- MODIFY `server/tests/test_control_loop.py`, `server/tests/test_hardening.py`.
- unsigned flag true/false/production matrix tests.

SCOPE:
- 허용: `server/action_hub/config.py`, `server/action_hub/services/webhooks.py`, `server/.env.example`, `server/tests/test_control_loop.py`, `server/tests/test_hardening.py` only.
- 금지: provider signature algorithm, delivery dedup ID, webhook payload schema.
- 계약: secret 없음+flag false/production → `WebhookConfigurationError`; non-production+true → delivery `signature_valid=false`.

VERIFY: `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_control_loop.py tests/test_hardening.py -k webhook` → exit 0, unsigned negative/opt-in/production cases pass.

#### CARD-00-03 — S3 HKDF mobile key separation

STATUS: `DONE` — final focused 19 passed/exit 0, full 101 passed/exit 0; evidence `evidence/wave-00-phase0.json`.

TASK: development API key fallback을 HKDF-derived mobile signing key로 교체.

DELIVERABLE:
- MODIFY `server/action_hub/services/mobile_auth.py`, `server/action_hub/config.py`, `server/.env.example`.
- MODIFY `server/action_hub/api/mobile.py`, `server/tests/conftest.py`, `server/tests/test_mobile.py`, `server/docs/27_MOBILE_SECURITY_OPERATIONS_KR.md`.
- derived key deterministic/domain-separated test와 existing token flow regression tests.

SCOPE:
- 허용: `server/action_hub/services/mobile_auth.py`, `server/action_hub/config.py`, `server/action_hub/api/mobile.py`, `server/.env.example`, `server/tests/conftest.py`, `server/tests/test_mobile.py`, `server/docs/27_MOBILE_SECURITY_OPERATIONS_KR.md` only.
- 금지: JWT/refresh wire format, DB schema, token TTL.
- 계약: `_secret(settings: Settings) -> bytes`; HKDF SHA-256, length 32, versioned salt/info constants; mobile placeholder는 insecure; equal explicit secrets raise `MobileAuthError(code="mobile_secret_reuses_admin_key")`; 두 config failure API mapping 503; secret bytes log 금지.
- test vector: API key `a`×32 → `bf1d6bcac5a2cc5e9780c35384e7f5115c28342167c111dee1e7c42f69896e18`.

VERIFY: `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_mobile.py -k 'secret or token or pairing or refresh'` → exit 0. `PYTHONPATH=. .venv/bin/python -m pytest -q` → exit 0.

### Phase 1 — P1 데이터·모바일 일관성

#### CARD-01-01 — C1 bounded Matrix queries

TASK: exact counts를 유지하면서 ActionItem ORM load를 quadrant별 limit으로 제한.

DELIVERABLE:
- MODIFY `server/action_hub/services/focus.py`.
- MODIFY `server/tests/test_focus.py`.
- aggregate counts/untriaged test, 10,000-row stress fixture, compiled SELECT limit assertion.

SCOPE:
- 허용: `server/action_hub/services/focus.py`, `server/tests/test_focus.py` only.
- 금지: MatrixResponse schema, endpoint paths, limit max 500.
- 구현 순서: aggregate query helper → bounded quadrant helper → response assembly → dashboard regression.
- 계약: `matrix(db, settings, *, limit_per_quadrant=100) -> MatrixResponse`; SQLAlchemy `before_cursor_execute` SELECT counter ≤6, ORM `load` event ActionItem counter ≤4*limit.

VERIFY: `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_focus.py -k matrix` → exit 0, exact count and bounded rows pass.

#### CARD-01-02 — C2 offline retry metadata와 DLQ

TASK: poison capture가 pending batch를 영구 점유하지 않도록 versioned queue record와 DLQ 구현.

DELIVERABLE:
- MODIFY `ios/Packages/ActionHubCore/Sources/ActionHubCore/OfflineCaptureQueue.swift`.
- MODIFY `ios/Packages/ActionHubCore/Tests/ActionHubCoreTests/OfflineCaptureQueueTests.swift`.
- MODIFY `ios/ActionHubApp/App/AppModel.swift`, `ios/ActionHubApp/Features/Settings/SettingsView.swift`, `ios/scripts/validate_ios_project.py` to expose count plus confirmed restore/purge controls and assert their production composition.
- MODIFY `ios/Packages/ActionHubCore/Package.swift`; CREATE `ios/Packages/ActionHubCore/Sources/OfflineCaptureQueueProbe/main.swift`, `ios/scripts/test_offline_queue_multiprocess.sh`.
- MODIFY `ios/docs/12_KNOWN_LIMITATIONS_KR.md`; ADD DLQ recovery steps.
- MODIFY `server/tests/test_mobile.py` for server receipt behavior proof; production server code 변경 없음.

SCOPE:
- 허용: 위에 열거한 9개 existing/CREATE iOS files와 `server/tests/test_mobile.py` only.
- 금지: capture HTTP schema, server DB migration, automatic DLQ purge.
- 계약: §6.3의 exact Swift types/signatures/path/lock/restore/purge; maxAttempts default 5.
- legacy decode: versioned record → raw CaptureInput → legacy array migration 순서.
- concurrency: Swift executable product `offline-capture-queue-probe`는 `enqueue|apply-failed|restore|purge|inventory|hold-lock` subcommands와 `--legacy-file <absolute pending.json> --prefix <string> --count <int> [--rounds <int>] [--milliseconds <int>]`를 받는다. Shell test는 같은 temp legacy file을 대상으로 독립 process 2개로 각 50건 enqueue; 독립 process 2개로 각 prefix에 failed 5 rounds를 apply해 DLQ 100; 독립 process 2개로 deterministic odd 50 restore/even 50 purge를 동시에 수행한다. Final inventory는 pending=50, dlq=0, corrupt=0이고 probe-reported purged=50이며 `pending+dlq+purged=100` conservation을 assert한다. 별도 same-record contention case는 process A가 production lock file을 `hold-lock --milliseconds 2000`으로 잡고 `LOCK_HELD`를 출력한 뒤 process B가 같은 ID를 enqueue하게 하며, B elapsed ≥1500ms, final unique=1, corrupt=0을 assert한다.

VERIFY: `cd ios && swift test --package-path Packages/ActionHubCore --filter OfflineCaptureQueueTests` → exit 0, success/removal, 5 failures→DLQ, network failure no increment, legacy migration/restore/purge pass. `bash scripts/test_offline_queue_multiprocess.sh` → exit 0/`OFFLINE_QUEUE_MULTIPROCESS_OK pending=50 dlq=0 purged=50 corrupt=0 lock_wait_ms>=1500 same_record_unique=1`. `python3 scripts/validate_ios_project.py` → exit 0 and Settings restore/purge confirmation composition assertions pass. `cd ../server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_mobile.py -k capture` → exit 0.

#### CARD-01-03 — C3 no-op delta path removal

TASK: full refresh 뒤 결과를 버리는 delta request/cursor write 제거.

DELIVERABLE:
- CREATE `ios/Packages/ActionHubCore/Sources/ActionHubCore/MobileRefreshSnapshot.swift` with exact dashboard/review/activity/triage/matrix/big3/activeFocus fields.
- MODIFY `ios/Packages/ActionHubCore/Sources/ActionHubCore/MobileSession.swift` to add `refreshSnapshot(currentAppVersion:) async throws -> MobileRefreshSnapshot` issuing exactly seven requests.
- MODIFY `ios/ActionHubApp/App/AppModel.swift`, `ios/ActionHubApp/Infrastructure/AppGroupStore.swift` to use snapshot and remove sync cursor symbol access.
- CREATE `ios/Packages/ActionHubCore/Tests/ActionHubCoreTests/MobileRefreshSnapshotTests.swift` with ClosureTransport path spy.
- 기존 cursor file 삭제 logic은 추가하지 않는다.

SCOPE:
- 허용: 위에 열거한 5개 files only.
- 금지: `ActionHubAPIClient.changes`, `MobileSession.changes`, server endpoint/OpenAPI.
- 계약: request spy의 normalized paths multiset은 dashboard/review/activity/focus/triage/focus/matrix/focus/commitments/focus/sessions/active에 해당하는 현재 exact seven client paths로 고정하고 `/changes` 0; AppGroupStore cursor read/write 0. 구현 전 ActionHubAPIClient의 seven method path를 기록해 test fixture expected set에 literal로 넣는다.

VERIFY: `cd ios && swift test --package-path Packages/ActionHubCore --filter MobileRefreshSnapshotTests` → exit 0, exact seven-path multiset/zero changes pass. `python3 scripts/validate_ios_project.py` → exit 0. `rg -n 'synchronizeChanges|readSyncCursor|writeSyncCursor' ActionHubApp` → exit 1, active app references 0건.

#### CARD-01-04 — C4 atomic close-day

TASK: DayCloseRequest를 전부 검증한 후 한 transaction으로 적용.

DELIVERABLE:
- MODIFY `server/action_hub/focus_schemas.py`, `server/action_hub/services/focus.py`, `server/action_hub/api/focus.py`.
- MODIFY `server/tests/test_focus.py`.
- Generator 실행 후 exact output이 바뀌면 generated OpenAPI snapshots 3개를 함께 갱신한다.

SCOPE:
- 허용: `server/action_hub/focus_schemas.py`, `server/action_hub/services/focus.py`, `server/action_hub/api/focus.py`, `server/tests/test_focus.py`, `server/openapi/action-hub.openapi.json`, `ios/OpenAPI/action-hub.openapi.json`, `contracts/action-hub.openapi-v0.9.0.json` only.
- 금지: carry_over_decisions DB schema, unrelated focus endpoints.
- 계약: duplicate IDs 422; missing ID 404; condition fields schema validation 422; any failure write/audit 0.

VERIFY: `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_focus.py -k close_day` → exit 0, atomic rollback assertions pass. `.venv/bin/python scripts/export_openapi.py --check` → exit 0.

### Phase 2 — P2 client identity·문서·release hygiene

#### CARD-02-01 — User-Agent version injection

TASK: AppConfiguration version을 composition root에서 Core transport로 주입.

DELIVERABLE:
- MODIFY `ios/Packages/ActionHubCore/Sources/ActionHubCore/HTTPTransport.swift`.
- MODIFY `ios/Packages/ActionHubCore/Sources/ActionHubCore/MobileSession.swift`, `ios/ActionHubApp/App/AppModel.swift`, `ios/scripts/validate_ios_project.py`.
- CREATE `ios/Packages/ActionHubCore/Tests/ActionHubCoreTests/HTTPTransportTests.swift`.

SCOPE:
- 허용: 위에 열거한 5개 files only.
- 금지: Core가 App target을 import하는 변경, URL timeout changes.
- 계약: `URLSessionTransport(configuration: URLSessionConfiguration = .ephemeral, appVersion: String? = nil)`; nonempty version은 semantic `^[0-9]+\.[0-9]+\.[0-9]+$`, whitespace/control/newline이면 `preconditionFailure` 대신 safe fallback `unknown`; header exact `JM-AI-Action-Hub-iOS/<version-or-unknown>`. `MobileSession.init(store:transport:appVersion:)`는 explicit transport 우선, nil transport이면 versioned URLSessionTransport 생성. AppModel production line은 `MobileSession(store: credentialStore, appVersion: AppConfiguration.appVersion)`.

VERIFY: `cd ios && swift test --package-path Packages/ActionHubCore --filter HTTPTransportTests` → exit 0. `python3 scripts/validate_ios_project.py` → exit 0 and composition assertion 1건. `rg -n 'JM-AI-Action-Hub-iOS/0\.1' .` → exit 1.

#### CARD-02-02 — Known limitations와 운영 문서 최신화

TASK: current release truth와 보안/DLQ/검증 경계를 문서화.

DELIVERABLE:
- MODIFY `server/docs/13_KNOWN_LIMITATIONS_KR.md`, `ios/docs/12_KNOWN_LIMITATIONS_KR.md`, `server/README.md`, `ios/README.md`, `server/docs/27_MOBILE_SECURITY_OPERATIONS_KR.md`, `server/Makefile`.
- CREATE `server/scripts/validate_current_docs.py` with §REQ-DOC-001 canonical stale/required lists.
- 현재 release/version, implemented mobile features, manual acceptance boundary, flags, DLQ operation 표.

SCOPE:
- 허용: 위에 열거한 7개 files only.
- 금지: historical upgrade/release reports, evidence 조작.

VERIFY: `cd server && make docs-check` → exit 0, `DOCS_CHECK_OK stale_count=0 required_count=6`. Target는 `.venv/bin/python scripts/validate_current_docs.py`, `bash -n scripts/backup.sh scripts/restore.sh scripts/smoke_test.sh`를 순서대로 실행한다. `cd ../ios && python3 scripts/validate_ios_project.py` → exit 0/`IOS_PROJECT_STATIC_OK`.

#### CARD-02-03 — source archive exclusion gate

TASK: local env/build/cache/DB/secret가 없는 source archive 생성·검사 workflow 추가.

DELIVERABLE:
- CREATE `server/scripts/build_source_release.py`, `server/scripts/verify_source_release.py`, `server/tests/test_source_release.py`.
- MODIFY `server/Makefile`, root `RELEASE_MANIFEST.sha256` generation workflow documentation.

SCOPE:
- 허용: 위에 열거한 4개 files plus root `RELEASE_MANIFEST.sha256` only.
- 금지: 실제 `.env`, DB, backup archive content 읽기/복사, git clean/reset.
- 계약: REQ-REL-001의 exact allowlist, forbidden matcher, no-symlink policy, root/name/layout. 두 Python scripts가 `FORBIDDEN_PATH_PATTERN`을 한 module에서 import해 matcher가 하나만 존재한다.
- archive verifier는 `server/.env.example` exact 1건, basename `.env` 및 `.env.example` 이외 `.env*` 0건을 assert한다. Template parser는 ACCEPT-REL-001-C의 exhaustive key set, exact three-entry non-secret typed configuration exception set, exact three-entry nonempty credential map, all-other credential-empty rule, future credential fail-closed rule, URL-userinfo prohibition을 그대로 사용한다.

VERIFY: 아래 ordered sequence 전체 exit 0. `RELEASE_TMP` 생성이 모든 output reference보다 먼저이며, build/compare/extract/install이 같은 block에 있다.

```bash
set -euo pipefail
cd /Volumes/DevSpace/Playground/JM\ AI-OS\ Pack/JM-AI\ Action\ Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1
RELEASE_TMP="$(mktemp -d)"
SOURCE_RELEASE_OUTPUT="$RELEASE_TMP/first.tar.gz" make -C server source-release
SOURCE_RELEASE_OUTPUT="$RELEASE_TMP/second.tar.gz" make -C server source-release
FIRST_SHA="$(shasum -a 256 "$RELEASE_TMP/first.tar.gz" | awk '{print $1}')"
SECOND_SHA="$(shasum -a 256 "$RELEASE_TMP/second.tar.gz" | awk '{print $1}')"
test "$FIRST_SHA" = "$SECOND_SHA"
printf 'SOURCE_RELEASE_REPRODUCIBLE_OK sha256=%s\n' "$FIRST_SHA"
make -C server verify-source-release SOURCE_RELEASE_INPUT="$RELEASE_TMP/second.tar.gz"
mkdir "$RELEASE_TMP/extracted"
tar -xzf "$RELEASE_TMP/second.tar.gz" -C "$RELEASE_TMP/extracted"
cd "$RELEASE_TMP/extracted/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/server"
case "$PWD" in "$RELEASE_TMP"/*) ;; *) exit 65 ;; esac
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/action-hub migrate
.venv/bin/action-hub check
```

기대 sentinel은 `SOURCE_RELEASE_REPRODUCIBLE_OK`, `SOURCE_RELEASE_OK forbidden_count=0`, `version=0.9.0`, `database=ready`. Scripts/Makefile은 SHA equality 후 reproducible sentinel을 출력한다. temp path는 receipt에 기록하고 검증 종료 후 operator가 해당 exact path만 삭제한다.

#### CARD-02-04 — Ruff 72 findings와 Swift availability baseline

TASK: 기능 카드와 분리된 mechanical quality closure.

DELIVERABLE:
- MODIFY Ruff가 현재 보고한 32파일만: `server/action_hub/api/{control,features,mobile,routes,webhooks}.py`, `server/action_hub/connectors/{github,local_ics,todoist}.py`, `server/action_hub/{focus_schemas,main,models,schemas,security}.py`, `server/action_hub/migrations/env.py`, `server/action_hub/services/{date_parser,decision,executor,focus,followups,meetings,metrics,mobile,mobile_auth,parser,rules,state_sync,webhooks}.py`, `server/scripts/{export_openapi,mobile_http_smoke}.py`, `server/tests/{test_control_loop,test_features,test_mobile}.py`.
- MODIFY `ios/Packages/ActionHubCore/Sources/ActionHubCore/FocusActivityAttributes.swift` only; `#if canImport(ActivityKit) && os(iOS)`로 iOS declaration을 guard하고 non-iOS target에는 symbol을 export하지 않는다.
- behavior change 금지; auto-fix 후 diff inspection.

SCOPE:
- 허용: listed files only.
- 금지: Ruff config ignore 확대, test skip, assertion 삭제/약화, unsafe-fixes 무검토 적용.

VERIFY: `cd server && .venv/bin/ruff check .` → exit 0, 0 finding. `PYTHONPATH=. .venv/bin/python -m pytest -q` → exit 0. `make verify` → exit 0; lint/coverage/compileall/OpenAPI/node stages all run. `cd ../ios && swift test --package-path Packages/ActionHubCore` → exit 0. `bash scripts/verify_release.sh` → exit 0/`IOS_RELEASE_SOURCE_CHECK_OK`.

### Phase 3 — 운영 증거와 독립 검증

#### CARD-03-01 — backup/restore hardening 및 rehearsal

TASK: archive path 안전성·복구 후 DB check를 갖춘 temp rehearsal 구현.

DELIVERABLE:
- MODIFY `server/scripts/backup.sh`, `server/scripts/restore.sh`, `server/Makefile`, `server/docs/07_SECURITY_OPERATIONS_KR.md`.
- CREATE `server/scripts/rehearse_backup_restore.sh`, `server/tests/test_backup_restore_scripts.py`.
- CREATE fixed receipt `evidence/backup-restore-rehearsal.json` with command/exit/marker/schema/manifests and no secrets.

SCOPE:
- 수정 허용: `server/scripts/backup.sh`, `server/scripts/restore.sh`, `server/Makefile`, `server/docs/07_SECURITY_OPERATIONS_KR.md`, `server/scripts/rehearse_backup_restore.sh`, `server/tests/test_backup_restore_scripts.py`, `evidence/backup-restore-rehearsal.json` only.
- runtime write 허용: `mktemp -d`가 반환하고 receipt에 기록한 exact temp data/archive directory only.
- 금지: 현재 운영 data 직접 overwrite, broad recursive delete, secret 출력.
- 계약: `backup.sh --source-data <absolute-dir> --output <absolute-tar.gz>`; `restore.sh --archive <absolute-tar.gz> --target-data <absolute-dir>`. test가 Python `tarfile`로 safe, `../escape`, `/absolute`, symlink, hardlink archives를 각각 temp dir에 생성한다. Reject exit code는 64. 각 reject 전후 `sha256` manifest를 `find <target> -type f -print0 | sort -z | xargs -0 shasum -a 256`로 비교한다.

VERIFY: `cd server && make rehearse-backup-restore` → exit 0, `BACKUP_RESTORE_OK marker=restored schema=0005_decision_focus_foundation`. `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_backup_restore_scripts.py` → exit 0, safe roundtrip 1건과 absolute/parent/symlink/hardlink reject 4건이 각각 exit 64/target manifest unchanged로 pass.

#### CARD-03-02 — full local release gate

TASK: 변경 boundary부터 full gate까지 한 번 실행하고 receipt 작성.

DELIVERABLE:
- Server: `./scripts/verify.sh` raw exit/output, archive install/check, authenticated smoke.
- iOS: `bash scripts/verify_release.sh` raw exit/output; App target build는 non-signing simulator 가능 시만.
- CREATE `server/scripts/acceptance_local.sh`, `docs/operations/ACTION_HUB_PRODUCTION_ACCEPTANCE.md`; MODIFY `server/Makefile`; CREATE receipt at `evidence/production-acceptance-<UTC>.json` using REQ-ACC-001 schema.
- Git diff scope, `git diff --check`, final `git status --short`, generated contract consistency.
- `LOCAL_PASS_EXTERNAL_PENDING` 또는 precise `BLOCKED` verdict.

SCOPE:
- 허용: 위 3개 code/doc paths, one timestamped evidence JSON, read-only verification and temp dirs.
- 금지: production deployment, external Provider writes, TestFlight.

VERIFY: `cd server && make verify` → exit 0. `./scripts/verify.sh` → exit 0/`VERIFY_OK`. `make acceptance-local` → exit 0 and criteria 1..5 each PASS in receipt. `cd ../ios && bash scripts/verify_release.sh` → exit 0/`IOS_RELEASE_SOURCE_CHECK_OK`; repository root `git diff --check` → exit 0.

#### CARD-03-03 — manual live acceptance

TASK: Fable5/owner가 제공한 isolated test credentials와 approved host에서 real-format smoke 수행.

DELIVERABLE:
- auth missing/wrong/correct, signed webhook, one mobile capture, Matrix, close-day, backup/restore receipt.
- Provider별 destructive write는 owner가 별도 승인한 isolated project/calendar/repo에만 수행.
- identifiers와 secrets redacted.

SCOPE:
- MANUAL only. credentials/host가 없으면 `BLOCKED: isolated credentials and approved host required`.
- iOS physical device/TestFlight는 Non-goal이므로 server real-operation 판정과 분리.

VERIFY: `docs/operations/ACTION_HUB_PRODUCTION_ACCEPTANCE.md`의 manual section에서 `ACTION_HUB_URL`과 redacted credential aliases를 주입해 five criteria command를 재실행한다. Criterion 1의 `make acceptance-security`는 isolated Provider secret으로 valid HMAC webhook 2xx/receipt `signature_valid=true`와 one-bit-invalid signature 401/delivery count unchanged를 모두 기록한다. Final receipt는 `externalStatus=PASS`, blockers empty, criteria 1..5 PASS. 이 카드 전에는 `PRODUCTION PASS`를 선언하지 않는다.

## 8. 의존 그래프와 file ownership

```text
CARD-00-01 → CARD-00-02 → CARD-00-03
      ↓             ↓             ↓
CARD-01-01 → CARD-01-02 → CARD-01-03 → CARD-01-04
      ↓             ↓             ↓             ↓
CARD-02-01 → CARD-02-02 → CARD-02-03 → CARD-02-04
                                              ↓
CARD-03-01 → CARD-03-02 → CARD-03-03(MANUAL)
```

- `config.py` ownership: CARD-00-01이 host/key contract, CARD-00-02가 unsigned flag, CARD-00-03이 mobile config를 순차 반영한다.
- `focus.py` ownership: CARD-01-01 matrix 구역 완료 후 CARD-01-04 close_day 구역 변경. 병렬 금지.
- `AppModel.swift` ownership: CARD-01-02 diagnostic가 필요할 때 먼저, CARD-01-03 delta removal, CARD-02-01 transport injection 순서.
- 문서 ownership: 기능 카드의 정확한 계약 문구를 먼저 반영하고 CARD-02-02가 version/교차 링크만 정리한다.
- Change Budget: 각 기능 카드 직접 수정 ≤12파일, 신규 ≤8파일, 논리 변경 ≤500줄, migration 0. CARD-02-04는 exact 33파일(현재 Ruff report의 Python 32 + Swift availability 1) mechanical 예외이며 기능 변경 0줄이어야 한다.

## 9. 위험과 실패 모드

Risk score = Probability × Impact × Detectability. 1~15 R1, 16~35 R2, 36~75 R3, 76~125 R4.

| ID | 위험 | P | I | D | 점수/등급 | 예방 | 복구 |
|---|---|---:|---:|---:|---|---|---|
| R-SEC-01 | fail-closed 전환으로 기존 local/tests가 전부 503 | 5 | 4 | 4 | 80/R4 | fixture/header inventory, focused tests first | secure key/header 설정; code bypass 복원 금지 |
| R-SEC-02 | HKDF 전환으로 기존 mobile token 무효 | 4 | 4 | 3 | 48/R3 | release note와 re-pairing 절차 | explicit mobile secret 설정 후 devices re-pair |
| R-WEB-01 | unsigned dev webhook fixture 중단 | 4 | 3 | 2 | 24/R2 | secret fixture 또는 explicit flag | local flag true; production 금지 유지 |
| R-PERF-01 | aggregate count와 list filter 불일치 | 3 | 4 | 4 | 48/R3 | 동일 predicate helper, seeded boundary tests | feature revert; schema migration 없음 |
| R-MOB-01 | queue format migration 중 capture 손실 | 3 | 5 | 4 | 60/R3 | original file preserved until atomic new write, legacy tests | quarantined/raw file restore operation |
| R-MOB-02 | transient server failure가 DLQ로 오분류 | 3 | 4 | 3 | 36/R3 | transport exception 제외, 5회 threshold, last error 보존 | explicit restoreDeadLetter |
| R-MOB-03 | app/share extension 동시 file operation으로 capture 손실 | 3 | 5 | 5 | 75/R3 | filesystem lock, same-directory atomic replace, two-instance stress test | source-preserving error, queue/DLQ inventory reconciliation |
| R-DAY-01 | API partial semantics 의존 client regression | 3 | 4 | 3 | 36/R3 | contract tests, mobile error handling check | revert card; no migration |
| R-REL-01 | archive에 secret/DB 포함 | 2 | 5 | 5 | 50/R3 | allowlist, listing scan, temp fixture | archive 폐기 및 credential rotate 판단 |
| R-OPS-01 | restore가 현재 data overwrite | 2 | 5 | 4 | 40/R3 | explicit temp target, pre-snapshot, traversal test | pre-restore snapshot 복귀 |
| R-QUAL-01 | mechanical Ruff fix behavior change | 3 | 4 | 3 | 36/R3 | safe fix only, diff review, full tests | offending hunk revert |

R3/R4 failure mode:

- Trigger: focused test 또는 negative auth smoke 실패.
- Failure: security bypass, data loss, API incompatibility, release leak.
- Detection: card VERIFY command, archive listing, DB checksum, independent review.
- Recovery: 해당 카드만 revert 가능한 commit boundary 유지; migration이 없으므로 code/config rollback. mobile key와 day-close semantics는 release note와 operator action 필요.

## 10. Rollback matrix

| Change | Rollback | Data handling |
|---|---|---|
| S1/S2 config | previous binary로 rollback하고 loopback/firewall 유지 | DB change 없음 |
| S3 HKDF | explicit independent mobile secret 설정, devices re-pair | refresh tokens revoke 가능; DB delete 금지 |
| C1 Matrix | service commit revert | DB change 없음 |
| C2 DLQ | dead-letter records를 restore API로 pending 전환 | files 보존, 자동 purge 없음 |
| C3 delta removal | app method/call restore | old cursor file preserved |
| C4 atomic close | service/schema commit revert after client compatibility check | DB schema 없음; completed transactions 유지 |
| release scripts | generated archive 폐기 | source/data untouched |
| backup/restore | pre-restore snapshot restore | checksum 확인 후 전환 |

## 11. AUTONOMOUS / MANUAL

[AUTONOMOUS]
- 승인 후 CARD-00-01부터 CARD-03-02까지 local code/test/docs/temp rehearsal 수행 가능.
- 각 카드 후 수행자 보고: changed files, diff stat, exact VERIFY command, raw exit code, output summary, adjustment list.

[MANUAL]
- M-01: Fable5 approval — CARD-00-01 시작 전. authoritative master channel의 verified sender `Fable5`가 exact line `APPROVED: /Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/docs/IMPROVEMENT_PLAN_V1.md SHA256=<64 lowercase hex>`를 보내야 한다. 관리자는 `shasum -a 256 docs/IMPROVEMENT_PLAN_V1.md`와 hex를 비교하고 `evidence/approval-receipt.json`에 `{sender:"Fable5",channelId,receivedAt,planPath,planSha256}`를 기록한다. sender/channel identity를 검증할 수 없거나 hash mismatch이면 모든 구현 `BLOCKED: authoritative approval receipt required`.
- M-02: isolated Provider credentials와 approved host — CARD-03-03 전. 없으면 external live acceptance만 BLOCKED.
- M-03: real operator가 API key/mobile secret 생성·보관·주입 — CARD-03-03 전. secret 값은 보고/저장 금지.
- M-04: iOS signing/device/TestFlight — 이 계획의 Non-goal; 별도 승인 계획 필요.
- M-05: commit/push/PR/merge — 사용자의 별도 명시 요청 전 금지.

## 12. 알려진 조정 지점

| # | 계획 기준 | 달라질 수 있는 이유 | 실행 에이전트 확인 방법 |
|---|---|---|---|
| 1 | protected tests는 shared client fixture에 header 주입 | custom TestClient가 파일 내부에서 생성됨 | graph `search_code('TestClient(')` 후 모든 protected call inventory |
| 2 | HKDF는 installed `cryptography` 사용 | 현재 import surface에 HKDF 없음 | installed version과 `cryptography.hazmat.primitives.kdf.hkdf.HKDF` import test |
| 3 | Matrix executed SELECT ≤6, loaded ActionItem ≤4*limit | ORM eager load가 additional query 발생 가능 | SQLAlchemy event listener와 ORM load event로 두 counter 측정 |
| 4 | queue record를 same directory에 저장 | app/share extension 동시 접근 규칙 영향 | existing file-per-capture atomic write와 concurrency tests 유지 |
| 5 | App composition root transport initializer location | default `MobileSession` initializer 내부일 수 있음 | graph trace `URLSessionTransport` inbound call sites 확인 |
| 6 | generated OpenAPI snapshots change | schema validator implementation에 따라 schema diff 발생 | export script check; diff가 contract 변경이면 세 snapshot 동기화 |
| 7 | source archive root | Server-only와 combined server+iOS release 경계가 다를 수 있음 | 현재 release manifest와 README distribution commands 대조; combined archive를 기본으로 사용 |
| 8 | evidence directory tracked 여부 | existing evidence policy가 문서화되지 않음 | `git ls-files evidence server/evidence`로 확인; untracked evidence를 자동 stage하지 않음 |

위 지점에서 실제 코드가 계획과 다르면 질문하지 말고 graph/grep/read로 실제를 확인해 조정하고, 조정 내용을 결과 보고에 포함한다. 계약 자체가 모순되거나 일반 카드가 12파일/500논리줄을 넘으면 중단하고 `BLOCKED`를 보고한다. CARD-02-04만 §8의 exact 33파일 mechanical exception을 적용하며 33파일을 넘거나 behavior change가 생기면 `BLOCKED`다.

## 13. 요구사항 추적표

| REQ | Acceptance | Card | 구현 파일 핵심 | VERIFY | 상태 |
|---|---|---|---|---|---|
| REQ-SEC-001/002 | SEC-001 A-C, SEC-002 A-B | 00-01 | config.py, security.py, tests | pytest test_security + full | DONE |
| REQ-SEC-003 | SEC-003 A-C | 00-02 | config.py, webhooks.py | webhook focused pytest | DONE |
| REQ-SEC-004 | SEC-004 A-F | 00-03 | mobile_auth.py | mobile auth focused pytest including HKDF vector/equal-secret/template-placeholder 503 | DONE |
| REQ-PERF-001 | PERF-001 A-C | 01-01 | focus.py, test_focus.py | matrix pytest with SELECT/load counters | DONE |
| REQ-MOB-001 | MOB-001 A-D | 01-02 | OfflineCaptureQueue.swift, probe/script | Swift filtered + multiprocess shell + server capture | LOCAL PASS — code IMPLEMENTED; iOS-XCTEST PENDING (Full Xcode 필요) |
| REQ-MOB-002 | MOB-002 A-B | 01-03 | AppModel.swift, AppGroupStore.swift | iOS static/Swift/rg | LOCAL PASS — code IMPLEMENTED; iOS-XCTEST PENDING (Full Xcode 필요) |
| REQ-DAY-001 | DAY-001 A-D | 01-04 | focus_schemas.py, focus.py, api/focus.py | close_day decision-matrix pytest + OpenAPI | DONE |
| REQ-IOS-001 | IOS-001 A-C | 02-01 | HTTPTransport.swift, MobileSession.swift, AppModel.swift | Swift filtered + iOS static composition + rg | LOCAL PASS — implementation complete; iOS-XCTEST PENDING (Full Xcode 필요) |
| REQ-DOC-001 | DOC-001 A-B | 02-02 | two limitation docs/readmes | stale claim scan | DONE — Sol MEDIUM documentation-coverage regression CLOSED by CARD-02-02-R1 |
| REQ-REL-001 | REL-001 A-D | 02-03 | release scripts/Makefile + approved `.env.example` line | archive double-build SHA equality/create/verify/install + `.env.example` assertion | DONE — LunaMax HIGH `.coverage` false-pass CLOSED; deterministic install PASS |
| REQ-QUAL-001 | QUAL-001 A-B | 02-04/03-02 | 32 Python + ActivityKit file | ruff/pytest/make verify/swift/ios verify_release | LOCAL PASS — Ruff 0, server 174 passed, guard verified; iOS-XCTEST PENDING (Full Xcode 필요) |
| REQ-OPS-001 | OPS-001 A-B | 03-01 | backup/restore/rehearsal | make rehearsal | DONE — hardened backup/restore and isolated rehearsal PASS |
| REQ-ACC-001 | ACC-001 A-B | 03-02/03-03 | evidence only | full local/manual gates | LOCAL PASS — CARD-03-02 DONE; LIVE-ACCEPTANCE PENDING (사용자 인프라 필요) |

> 최종 상태: `LOCAL COMPLETE / EXTERNAL GATES PENDING (사용자 제공 대기)`

## 14. 수행자 디스패치 프롬프트

첫 승인은 Phase 0 전체가 아니라 CARD-00-01 한 장으로 시작한다.

```text
TASK: CARD-00-01 — 관리 API fail-closed와 loopback 기본 binding 구현

DELIVERABLE:
- 승인된 파일의 변경 diff와 파일 목록
- 검증 명령 실행 출력과 raw 종료코드
- 계획과 다르게 조정한 지점 목록; 없으면 "없음"

SCOPE:
- 먼저 읽기: docs/IMPROVEMENT_PLAN_V1.md의 REQ-SEC-001, REQ-SEC-002,
  ADR-001, CARD-00-01, 위험 R-SEC-01
- 수정 허용: server/action_hub/config.py, server/action_hub/security.py,
  server/.env.example, server/Makefile, server/scripts/smoke_test.sh,
  server/tests/conftest.py, server/tests/test_security.py,
  server/tests/test_control_loop.py, server/tests/test_features.py,
  server/tests/test_hardening.py, server/tests/test_mobile.py
- 수정 금지: mobile bearer auth, route path/response schema, production deployment,
  ../.serena/, git metadata
- 계획과 실제 코드가 다르면 graph search/read로 확인해 조정하고 DELIVERABLE에 기록한다.
  계약 모순 또는 12파일/500논리줄 초과면 BLOCKED 보고한다.
- test skip/삭제/assertion 약화/Ruff ignore/빈 catch로 gate를 우회하지 않는다.

VERIFY:
cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_security.py
→ 기대 exit 0, key 없음 503/wrong 401/correct success/default host tests 통과
cd server && PYTHONPATH=. .venv/bin/python -m pytest -q
→ 기대 exit 0, 전체 test suite 통과

보고 규칙: WORKING: <현재 카드> / BLOCKED: <필요한 것>
```

후속 카드도 각 CARD의 TASK/DELIVERABLE/SCOPE/VERIFY 본문을 그대로 단일 dispatch 단위로 사용한다. 두 카드를 한 수행자 turn에 결합하지 않는다.

## 15. 계획 승인 후 검증 ladder

1. Static: changed Python에 Ruff, Swift parse/static project, `git diff --check`.
2. Focused: 각 카드 VERIFY test.
3. Affected integration: server full pytest, Swift package test, OpenAPI contract.
4. Release: server `./scripts/verify.sh`, iOS `verify_release.sh`, clean archive install.
5. Real surface: authenticated HTTP smoke, real-format capture/matrix/day-close, temp backup/restore.
6. Manual external: approved host/provider credentials. 없으면 `LOCAL_PASS_EXTERNAL_PENDING`.

파이프 사용 시 `set -o pipefail`을 켜고 원 명령 exit code를 보존한다. test count, archive forbidden count, SHA-256, git status를 receipt에 기록한다.

## 16. ASSUMED 목록

| ID | 가정 | 근거 | 영향 | Rollback/default |
|---|---|---|---|---|
| A-01 | test 환경도 runtime auth bypass 금지 | APP_ENV 오배포 방어가 fail-closed 목표와 일치 | test fixture 수정량 증가 | secure key/header fixture |
| A-02 | unsigned true는 production 금지 | explicit opt-in만으로 production risk를 정당화할 수 없음 | local dev만 unsigned 가능 | provider secret 설정 |
| A-03 | mobile retry 상한 5 | server outbox/APNs max attempt 기존값과 일관 | 5회 후 manual recovery | restoreDeadLetter |
| A-04 | delta client path 제거, server API 유지 | 현재 app은 full refresh 후 payload discard | network 감소, external clients 호환 | app call restore |
| A-05 | day-close all-or-nothing | batch audit/data consistency 우선 | partial success client behavior 변경 | contract release note/revert |
| A-06 | combined server+iOS source archive | repository release manifest가 양쪽을 포함 | archive script scope 확대 | master가 server-only를 지시하면 allowlist 축소 |

배치 질문은 0개다. 위 안전 기본값은 데이터 보존→보안→호환성→가역성 순으로 선택했다. 승인자가 다른 선택을 지정하면 해당 ADR/REQ/Card를 먼저 개정하고 구현을 시작한다.

## 17. REVIEW LOG

초안 작성자 자체 검사는 문서 생성 후 별도 fresh reviewer와 기계 검사로 수행한다. 납품 조건은 다음과 같다.

- forbidden vague terms 0건 또는 인용 맥락 사유 기록.
- placeholder markers 0건.
- 존재하지 않는 VERIFY 명령 0건; 새 target은 해당 카드가 먼저 생성함을 명시.
- CRITICAL/HIGH review finding 0건.
- 현재 기준선 실패와 구현 후 기대값을 혼동한 문장 0건.

리뷰 결과와 수정 내역은 아래 표에 기록한다.

| Finding | Severity | 조치 | 최종 상태 |
|---|---|---|---|
| F-001 archive install이 live checkout을 검사할 수 있음 | CRITICAL | exact archive name, temp extract, extracted server cwd와 install/migrate/check sequence 명시 | RESOLVED |
| F-002 final `make verify` 미실행 | HIGH | CARD-02-04/03-02와 trace에 `make verify` exit 0 추가 | RESOLVED |
| F-003 canonical verify script 존재 증거 누락 | HIGH | baseline에 executable 확인 exit 0 기록 | RESOLVED |
| F-004 wildcard/conditional file scope | HIGH | 모든 지적 카드의 CREATE/MODIFY path를 열거하고 wildcard 제거 | RESOLVED |
| F-005 placeholder/HKDF bytes 불명확 | HIGH | denylist/normalization과 HKDF IKM/salt/info/length/test vector 고정 | RESOLVED |
| F-006 queue signature/storage/purge 불명확 | HIGH | §6.3에 Swift signatures, schema, paths, errors, restore collision, purge 계약 추가 | RESOLVED |
| F-007 cross-process queue coordination 누락 | HIGH | filesystem lock contract, two-instance stress acceptance, R-MOB-03 추가 | RESOLVED |
| F-008 day-close variant contract 누락 | HIGH | six decision required/optional/forbidden matrix와 exact 422/404 추가 | RESOLVED |
| F-009 docs semantic/command oracle 누락 | HIGH | canonical stale/required lists와 `make docs-check` exact stages 추가 | RESOLVED |
| F-010 malicious restore test 불실행 | HIGH | exact CLI, exit 64, five pytest cases, before/after manifest 추가 | RESOLVED |
| F-011 production criteria/receipt 불명확 | HIGH | five criteria command/invariant, runbook path, JSON schema/redaction/blocker 추가 | RESOLVED |
| F-012 approval authority/receipt 불명확 | HIGH | Fable5 exact token+plan SHA-256, verified channel/sender, receipt schema 추가 | RESOLVED |
| F-013 delta zero-request test conditional | HIGH | exact Core snapshot files와 ClosureTransport seven-path spy test 고정 | RESOLVED |
| F-014 App version composition 미검증 | HIGH | exact AppModel initializer와 iOS static composition assertion 추가 | RESOLVED |
| F-015 archive algorithm/layout/matcher 미결정 | HIGH | allowlist, regex, no-symlink, normalized root/output layout 고정 | RESOLVED |
| F-016 Matrix query ceiling 불일치 | MEDIUM | SELECT ≤6/loaded rows ≤4*limit로 통일하고 counter acceptance 추가 | RESOLVED |
| F-004R backup card deliverable/scope 모순 | CRITICAL | 7개 repository paths와 exact temp runtime write scope를 분리 열거 | RESOLVED |
| F-017 quality card 32/33 budget 모순 | CRITICAL | Python 32+Swift 1=33 exception과 global stop-rule exception을 일치 | RESOLVED |
| F-018 explicit mobile/admin secret equality 허용 | HIGH | constant-time inequality, 503 code, negative acceptance/API mapping 추가 | RESOLVED |
| F-006R legacy queue base/migration 경로 불명확 | HIGH | initializer legacy path, pending/DLQ/corrupt/lock, collision/source timing 고정 | RESOLVED |
| F-007R same-process concurrency만 검증 | HIGH | executable probe 두 process와 conservation shell gate 추가 | RESOLVED |
| F-019 DLQ operator call surface 없음 | HIGH | Settings confirmed restore/purge controls, AppModel signatures, static composition gate 추가 | RESOLVED |
| F-011R signed webhook manual criterion 누락 | HIGH | criterion 1을 auth/webhook integrity로 확장하고 valid/invalid invariants 매핑 | RESOLVED |
| F-016R 새 acceptance trace 누락 | HIGH | SEC-D/PERF-C/MOB-D/DAY-D/IOS-C/REL-C를 trace와 명령에 추가 | RESOLVED |
| F-015R `.env.example`도 archive에서 제외 | HIGH | `.env.example` exact exception과 archive presence/safe-placeholder assertion 추가 | RESOLVED |
| F-009R docs pattern/section heuristic 불명확 | HIGH | exact file/H1/H2/bullet assertion matrix와 heading parser 고정 | RESOLVED |
| F-009R-1 docs required assertion 6 vs sentinel 5 | CRITICAL | sentinel을 exact `required_count=6`으로 정정 | RESOLVED |
| F-007R-1 multiprocess가 enqueue만 검사 | HIGH | probe/apply-failed/restore/purge mixed two-process gate와 conservation 추가 | RESOLVED |
| F-019-1 “모두”가 첫 100건만 처리 | HIGH | empty까지 deterministic page loop와 progress guard 추가 | RESOLVED |
| F-020 deterministic archive 이중-build 검증 누락 | HIGH | isolated output 2개 SHA-256 equality gate/acceptance 추가 | RESOLVED |
| F-021 iOS verify_release trace 누락 | HIGH | CARD-02-04 VERIFY와 REQ-QUAL trace에 canonical release script 추가 | RESOLVED |
| F-020R RELEASE_TMP 생성 전 reference | CRITICAL | temp 생성→2 builds→SHA compare→verify→extract→install 단일 ordered block으로 교체 | RESOLVED |
| F-007R-2 disjoint IDs라 lock 증명 불가 | HIGH | 2초 lock hold + same-record second-process elapsed/unique assertion 추가 | RESOLVED |
| F-015R-2 template secret heuristic 불명확 | HIGH | credential-key regex와 exact 3-entry nonempty allow map 고정 | RESOLVED |
| F-020R-2 archive block fail-fast/sentinel 누락 | CRITICAL | `set -euo pipefail`과 equality 직후 explicit sentinel 추가 | RESOLVED |
| F-015R-3 credential-like key 범위 비포괄 | HIGH | exhaustive assignment key set, unknown-key reject, credential map, URL userinfo reject 추가 | RESOLVED |
| F-022 shipped mobile placeholder가 secure 판정 가능 | CRITICAL | mobile 전용 exact deny value와 pairing/token 503 acceptance/trace 추가 | RESOLVED |
| F-023 credential regex가 typed non-secret `TOKEN` 설정도 credential로 분류 | HIGH | exact 3개 non-secret typed exception만 허용하고 미래 credential-like key nonempty rejection 회귀테스트 추가 | RESOLVED |
| F-024 archive verifier가 extraction 전 non-normal/duplicate/root/link 경로를 포괄 검증하지 않음 | HIGH | traversal, absolute, duplicate-normalized, root exact-one, trailing slash, symlink, hardlink, FIFO 회귀테스트와 fail-closed 검증 추가 | RESOLVED |
| F-025 source archive가 `make verify` 산출물 `.coverage`를 포함하고 verifier가 false-pass | HIGH | shared canonical matcher에 `.coverage`, `.coverage.*`, `coverage.xml`, `htmlcov` 차단 추가; builder no-read와 malicious archive 회귀테스트 추가 | CLOSED |
| F-026 User-Agent 테스트가 literal escape/helper만 검증 | MEDIUM | 실제 newline/control Swift 입력과 URLSessionTransport request header 직접 검증 추가 | CLOSED |
| F-027 AppModel composition static gate가 존재만 검사 | LOW | exact composition string count `== 1`로 강화 | CLOSED |
| F-028 `.env.example` header가 v0.8.0으로 stale | LOW | current server header를 v0.9.0으로 동기화 | CLOSED |
| Machine scan 2026-08-03 | N/A | vague terms 0, placeholder markers 0 (2 lexical matches were Todoist environment identifiers), pending markers 0, ambiguous scope patterns 0; existing referenced paths/commands missing 0 | PASS |
| Fresh zero-finding re-review after sixth corrections | N/A | independent Sol verdict `CRITICAL=0: YES`, `HIGH=0: YES` | PASS |

## 18. APPROVAL CHECKPOINT

- Received at: `2026-08-02T16:26:58Z`
- Authority: current authoritative master channel, sender identified by the direct message as `Fable5`.
- Decision: `[마스터 판정] APPROVED` and explicit instruction to start Phase 0 CARD-00-01/02/03.
- M-01 resolution: this task-specific direct approval overrides the stricter path+SHA token syntax in §11; `evidence/approval-receipt.json` records the approved plan hash before dispatch.
- Authorized scope: Phase 0 only; sequential CARD-00-01 → CARD-00-02 → CARD-00-03.
- Still prohibited: commit, push, PR, merge, iOS device signing, external production changes.

### CHECKPOINT-2026-08-03-CARD-00-03

- Drift: shared `tests/conftest.py` used `app_env=test` without an explicit mobile signing secret, while CARD-00-03 removes the runtime test-secret bypass.
- Decision: add `server/tests/conftest.py` to CARD-00-03 ownership and inject an explicit independent test mobile secret; do not retain the hardcoded test fallback.
- Budget: CARD-00-03 ownership changes from 6 to 7 files, within the 12-file limit.
- Requirement impact: REQ-SEC-004 is unchanged; this adjustment makes test execution follow the same explicit-secret contract.

### CHECKPOINT-2026-08-03-PHASE-0-REVIEW-FIX

- Independent review verdict: `CRITICAL=0`, `HIGH=0`, `MEDIUM=2`, `LOW=2`; Phase 0 completion is withheld until all four findings are corrected.
- Fix scope: `server/action_hub/services/mobile_auth.py`, `server/action_hub/security.py`, `server/Makefile`, `server/.env.example`, `server/tests/test_mobile.py`, `server/tests/test_security.py`, `server/docs/04_DATA_AND_API_KR.md`, `server/docs/27_MOBILE_SECURITY_OPERATIONS_KR.md` only.
- Required corrections: validate mobile signing configuration before claim/refresh lookup or mutation; return 503 for missing/placeholder/equal-secret on bearer routes before credential processing; preserve explicit `ACTION_HUB_HOST=0.0.0.0` override through `make dev` with LAN warning/test; remove stale documentation that allowed missing keys in development/test.
- Verification addition: focused mobile configuration tests must cover missing/existing claim and refresh identifiers plus bearer routes with unchanged state; CARD-00-01/02/03 VERIFY commands and full pytest must remain exit 0.
- Budget: 8 files, within the 12-file limit. No route/schema/DB/token-format change is authorized.

### CHECKPOINT-2026-08-03-WAVE-00-DONE

- Baseline → current HEAD: `9c8f28d5a9eb34a2c30a869be620885023171977` → same HEAD; all Phase 0 delivery remains an uncommitted worktree by master prohibition.
- State changes: CARD-00-01 `DONE`; CARD-00-02 `DONE`; CARD-00-03 `DONE`; REQ-SEC-001/002/003/004 `DONE`.
- Verification: security 11 passed/exit 0; webhook 5 passed/exit 0; mobile security 19 passed/exit 0; full server suite 101 passed/exit 0; server diff-check exit 0.
- Independent review: initial `CRITICAL=0/HIGH=0/MEDIUM=2/LOW=2`; corrections applied; final `CRITICAL=0/HIGH=0/MEDIUM=0`.
- Evidence: `evidence/wave-00-phase0.json`.
- Drift: two bounded plan adjustments were recorded above (explicit test mobile secret fixture and review-fix scope); no contract, route, DB schema, token wire format, TTL, or external system changed.
- Next task: CARD-01-01 remains `PLANNED` and is not authorized by the current Phase 0 approval.

### CHECKPOINT-2026-08-03-WAVE-00-FINAL

- Revision approval: the authoritative master channel approved `CARD-00-R1` and `CARD-00-R2` after LunaMax found the S2 queued unsigned-delivery development-to-production TOCTOU path.
- Baseline → current HEAD: `9c8f28d5a9eb34a2c30a869be620885023171977` → same HEAD; Phase 0 and its revisions remain an uncommitted worktree.
- State changes: `CARD-00-R1 DONE`; `CARD-00-R2 DONE`; REQ-SEC-001/002/003/004 remain `DONE`.
- Implementation: `process_webhook_delivery()` revalidates unsigned delivery policy before provider handlers; signed production and explicit non-production opt-in paths remain valid; the closed-loop operations document matches the runtime contract.
- Sol review: initial verification-selection defect found and corrected by renaming four R1 tests to match `-k webhook`; final `CRITICAL=0/HIGH=0/MEDIUM=0`.
- Final verification: webhook 9 tests/exit 0; security 11 tests/exit 0; mobile security 19 tests/exit 0; full server suite 105 tests/exit 0; server diff-check exit 0.
- LunaMax re-verification: `gpt-5.6-luna`, effort `max`, verdict `PASS`, `CRITICAL=0/HIGH=0/MEDIUM=0/LOW=0`; previous MEDIUM and LOW findings closed.
- Evidence: `evidence/wave-00-final.json` and `evidence/lunamax-wave00-r1r2-final.md`.
- Prohibited actions: no commit, push, PR, merge, iOS signing, deployment, or external production change.
- Residual risk: live provider, production deployment, and external-network acceptance remain unrun.
- Next task: `CARD-01-01` remains `PLANNED` and is not authorized by this Wave 00 revision approval.

### CHECKPOINT-2026-08-03-CARD-02-04-GUARD-EARLY

- CARD-02-04 guard: early-applied in Wave 01, remainder deferred to Phase 2.
- Authorized early prerequisite: only `FocusActivityAttributes.swift` changed from `#if canImport(ActivityKit)` to `#if canImport(ActivityKit) && os(iOS)` so the iOS-only ActivityKit model is excluded from macOS package builds.
- Remaining CARD-02-04 scope is unchanged and stays deferred: Ruff baseline cleanup, documentation synchronization, and all other Phase 2 verification.
- Verification at this checkpoint: guard-only `git diff --check` exit 0; CARD-01-02 Swift verification progressed past the ActivityKit failure and exposed separate C2 probe/toolchain defects for the normal revision loop.

### CHECKPOINT-2026-08-03-WAVE-01-VERIFY-BLOCKED

- Repository baseline/current HEAD: `9c8f28d5a9eb34a2c30a869be620885023171977`; delivery remains an uncommitted worktree.
- State changes: `CARD-01-01 DONE`; `CARD-01-02 IMPLEMENTED_VERIFY_BLOCKED`; `CARD-01-03 IMPLEMENTED_VERIFY_BLOCKED`; `CARD-01-04 DONE`.
- CARD-02-04 guard: early-applied in Wave 01, remainder deferred to Phase 2.
- Sol revision loop: corrected the C2 probe public-construction/path handling defects, then found and closed a HIGH source-loss risk in pending-to-DLQ collision handling; corrected the C4 focused-test selector so `-k close_day` exercises all three new cases.
- LunaMax verification: `gpt-5.6-luna`, effort `max`, process exit 0, verdict `PASS_WITH_ENVIRONMENT_BLOCKER`, implementation findings `CRITICAL=0/HIGH=0/MEDIUM=0/LOW=0`.
- Passed raw exits: matrix focused `0` (`1 passed`); close_day focused `0` (`3 passed`); capture focused `0` (`5 passed`); OpenAPI `0`; full server `0` (`108 passed`); ActionHubCore source build `0`; offline multiprocess `0` with exact sentinel; iOS static `0`; active cursor scan expected `1` with zero matches; `git diff --check` `0`.
- Blocked raw exits: `swift test --package-path Packages/ActionHubCore --filter OfflineCaptureQueueTests` = `1`; `swift test --package-path Packages/ActionHubCore --filter MobileRefreshSnapshotTests` = `1`; both stop before test execution with `no such module 'XCTest'`.
- Environment evidence: `xcode-select -p` reports `/Library/Developer/CommandLineTools`; `xcodebuild -version` exit `1`; no Xcode application or alternate XCTest module was found.
- Completion rule: Wave 01 is not `DONE` until both blocked Swift test commands run under full Xcode/XCTest and return exit `0`.
- Evidence: `evidence/wave-01-revision-report.md`, `evidence/lunamax-wave01-final-review.md`, and `evidence/wave-01-final-blocked.json`.
- Prohibited actions observed: no commit, push, PR, merge, deployment, or iOS device signing.

### CHECKPOINT-2026-08-03-WAVE-01-CONDITIONAL-COMPLETE

- Master decision: Wave 01 conditionally completed as `LOCAL PASS`; the prior environment blocker is explicitly classified as a non-code host constraint and does not block Phase 2.
- State changes: `CARD-01-01 DONE`; `CARD-01-02 code IMPLEMENTED / LOCAL PASS`; `CARD-01-03 code IMPLEMENTED / LOCAL PASS`; `CARD-01-04 DONE`.
- Deferred verification: `iOS-XCTEST PENDING (Full Xcode 필요)` for both `OfflineCaptureQueueTests` and `MobileRefreshSnapshotTests`; rerun when full Xcode is available.
- Preserved evidence: Sol HIGH DLQ-collision finding remains `CLOSED`; LunaMax implementation findings remain `CRITICAL=0/HIGH=0/MEDIUM=0/LOW=0`; server full suite remains `108 passed`, raw exit `0`.
- CARD-02-04 guard remains early-applied; only the Ruff/documentation/remaining quality work belongs to Wave 02.
- Evidence: `evidence/wave-01-conditional-complete.json`; historical `evidence/wave-01-final-blocked.json` is retained unchanged as the pre-decision environment record.
- Next task: Phase 2 starts with `CARD-02-01`; no commit, push, deployment, or iOS device signing is authorized.

### CHECKPOINT-2026-08-03-WAVE-02-CARD-02-03-BLOCKED

- Repository baseline/current HEAD: `9c8f28d5a9eb34a2c30a869be620885023171977`; delivery remains an uncommitted worktree.
- State changes: `CARD-02-01 LOCAL PASS`; `CARD-02-02 DONE`; `CARD-02-02-R1 DONE`; `CARD-02-03 BLOCKED`; `CARD-02-04 remainder PENDING`.
- CARD-02-01 verification: ActionHubCore source build `0`; iOS static `0`; stale User-Agent scan expected `1` with zero matches; diff-check `0`; filtered Swift test `1` before execution due the preserved `iOS-XCTEST PENDING (Full Xcode 필요)` constraint.
- CARD-02-02 verification: `make docs-check` `0` with `DOCS_CHECK_OK stale_count=0 required_count=6`; iOS static `0`; diff-check `0`.
- Sol CARD-02-02 finding: `MEDIUM` because still-current known limitations were deleted while the structural gate passed; CARD-02-02-R1 restored the current Calendar/provider/workflow/mailbox/parser/ROI/BackgroundTasks/manual-client boundaries and closed the finding.
- CARD-02-03 blocker: runtime config defines `mobile_recommended_ios_app_version = "0.2.1"`, and REQ-REL-001 requires `ACTION_HUB_MOBILE_RECOMMENDED_IOS_APP_VERSION` in the exhaustive `.env.example` key set, but `server/.env.example` lacks that key and is outside CARD-02-03 ownership.
- Allowlist clarification needed: root `LICENSE` and `NOTICE` do not exist. Recommended interpretation is to include allowed root entries only when present; do not invent legal text and do not fail solely because optional allowlist candidates are absent.
- Recommended bounded prerequisite: authorize exactly one template line, `ACTION_HUB_MOBILE_RECOMMENDED_IOS_APP_VERSION=0.2.1`, in `server/.env.example`; then retry CARD-02-03 without weakening exact-key validation and continue CARD-02-04.
- Routing correction: an initial Orca `--agent omp` dispatch exposed Qwen rather than the mandated Terra model and was stopped/abandoned; its partial in-scope User-Agent hunk was retained, inspected, completed, and independently verified by the actual `gpt-5.6-terra` retry. No Qwen result was accepted as a completed card.
- Evidence: `evidence/wave-02-card-02-03-blocker.json`.
- Prohibited actions observed: no commit, stage, push, PR, merge, deployment, Xcode installation, or iOS device signing.

### CHECKPOINT-2026-08-03-WAVE-02-CARD-02-03-UNBLOCKED

- Master decision: the recommended bounded prerequisite is approved.
- Scope expansion: CARD-02-03 may add exactly `ACTION_HUB_MOBILE_RECOMMENDED_IOS_APP_VERSION=0.2.1` to `server/.env.example` in addition to its original files.
- Archive policy: include root `LICENSE` and `NOTICE` only when they exist; if absent, skip them without weakening any forbidden-path, no-symlink, `.env`, credential-map, URL-userinfo, deterministic-layout, or install verification.
- LICENSE/NOTICE 부재 — 소유자 제공 대기.
- Legal-content guard: no agent may create or infer license/notice text.
- Deferred verification remains unchanged: `iOS-XCTEST PENDING (Full Xcode 필요)`; it does not block Wave 02 local completion.
- Execution resumes at CARD-02-03, followed by CARD-02-04 remainder, Sol review, and LunaMax full Wave 02 verification.
- Delivery constraints remain: uncommitted worktree; no commit, stage, push, PR, merge, deployment, Xcode installation, or iOS device signing.

### CHECKPOINT-2026-08-03-WAVE-02-CARD-02-03-COMPLETE

- State change: `CARD-02-03 DONE`; `CARD-02-04 remainder` is ready to start.
- Approved scope extension applied: `server/.env.example` includes `ACTION_HUB_MOBILE_RECOMMENDED_IOS_APP_VERSION=0.2.1`.
- LICENSE/NOTICE 부재 — 소유자 제공 대기. No legal file was created; the source builder includes either file only when owner-supplied content exists.
- Contract correction: the credential regex also matches three current non-secret typed configuration keys. The verifier now exempts only those exact three keys, retains the exact three-entry nonempty credential map for all remaining matches, and rejects a future nonempty credential-like key.
- Archive hardening: verification rejects traversal, absolute and non-normal paths, duplicate normalized paths, missing/duplicate root, trailing-slash regular files, symlinks, hardlinks, nonregular entries, forbidden paths, and unsafe `.env*` before extraction.
- Terra verification: focused source-release tests `35 passed`/exit `0`; ordered archive block exit `0`; first/second SHA-256 both `d1862a2b5c112b7a939d889667e3c06d22cc96a73f88546c56006f535f24f005`; temp `/var/folders/f0/tbqwy3mn7rj7vy2j7ts0gxhr0000gn/T/tmp.PV9sCC2ouF` preserved.
- Sol independent reproduction: focused `35 passed`/exit `0`; both builds, SHA comparison, verify (`forbidden_count=0`, version `0.9.0`), extraction, venv, pip install, migrate, check, OpenAPI validator, and iOS static validator each exit `0`; temp `/var/folders/f0/tbqwy3mn7rj7vy2j7ts0gxhr0000gn/T/tmp.5nGaQffuSM` preserved.
- Deferred verification remains `iOS-XCTEST PENDING (Full Xcode 필요)` and does not block Wave 02 local completion.
- Evidence: `evidence/wave-02-card-02-03-complete.json`.
- Delivery constraints observed: no commit, stage, push, PR, merge, deployment, Xcode installation, or iOS device signing.

### CHECKPOINT-2026-08-03-WAVE-02-FINAL

- Repository HEAD remains `9c8f28d5a9eb34a2c30a869be620885023171977`; Wave 02 remains an uncommitted worktree as required.
- State changes: `CARD-02-01 LOCAL PASS`; `CARD-02-02 DONE`; `CARD-02-03 DONE`; `CARD-02-04 remainder DONE / LOCAL PASS`.
- Initial LunaMax review found `CRITICAL=0/HIGH=1/MEDIUM=1/LOW=2`: coverage artifacts could enter the source archive, User-Agent injection tests did not exercise actual control characters/request headers, and two static/document labels were weak or stale.
- Revision: Orca Terra task `task_27be9217c61c` added shared coverage-artifact exclusions and fail-closed tests, direct User-Agent request-header tests with actual control characters, exact-one AppModel composition validation, and the v0.9.0 template header.
- Sol independent verification: source-release `44 passed`/exit `0`; `make verify` `153 passed`, coverage `83.07%`, exit `0`; iOS static and ActionHubCore build exit `0`; deterministic archive/verifier/coverage scan exit `0`; SHA-256 `b9596c2b7cd1825395df982ca04e98394f1346616289661e99a82cd4a12e409d`; temp `/var/folders/f0/tbqwy3mn7rj7vy2j7ts0gxhr0000gn/T/tmp.oRsMrqIeeM` preserved.
- LunaMax re-verification: `gpt-5.6-luna`, effort `max`, process exit `0`, verdict `PASS`, `CRITICAL=0/HIGH=0/MEDIUM=0/LOW=0`; previous HIGH/MEDIUM/LOW findings all `CLOSED`; archive install/migrate/check and all non-environment gates exit `0`.
- Environment trace remains `iOS-XCTEST PENDING (Full Xcode 필요)`: filtered Swift test and `verify_release.sh` exit `1` only because `XCTest` is unavailable after static/OpenAPI/Xcodeproj stages pass.
- Legal trace remains `LICENSE/NOTICE 부재 — 소유자 제공 대기`; no legal text was created.
- Evidence: `evidence/wave-02-revision-report.md`, `evidence/lunamax-wave02-final-r2-review.md`, and `evidence/wave-02-final.json`.
- Prohibited actions observed: no commit, stage, push, PR, merge, deployment, Xcode installation, or iOS device signing.

### CHECKPOINT-2026-08-03-WAVE-03-FINAL

- Repository HEAD remains `9c8f28d5a9eb34a2c30a869be620885023171977`; Wave 03 remains an uncommitted worktree as required.
- State changes: `CARD-03-01 DONE`; `CARD-03-02 DONE / LOCAL PASS`; `CARD-03-03 NOT STARTED` with `LIVE-ACCEPTANCE PENDING (사용자 인프라 필요)`.
- Implementation: backup/restore now require normal absolute paths, reject caller-writable symlink ancestors and existing explicit output inodes before mutation, publish backup archives atomically, reject unsafe archive members, validate restored state, and roll back on failed restore checks. The isolated rehearsal records command exits, archive SHA-256, schema/marker, and matching pre/post manifests.
- Initial LunaMax review found `CRITICAL=0/HIGH=2/MEDIUM=2/LOW=0`: SHA helper failure could false-pass acceptance, caller-controlled symlink ancestors were accepted, preexisting hardlink outputs could be overwritten, and atomic close-day smoke lacked state/count invariants.
- Revision: exact `gpt-5.6-terra` worker closed all four findings with fail-closed receipt handling, trusted-ancestor checks, new-output atomic publication, and before/after close-day invariants. A provider-mismatched Orca worker was fenced before adoption; no substituted result was accepted.
- Sol independent verification: script syntax, focused tests, `verify.sh`, `make verify`, canonical local acceptance, S1-S3 regression, and diff-check all exit `0`; full server suite is `174 passed`. SHA failure and adversarial backup/restore probes fail closed with expected nonzero/exit `64` results.
- LunaMax re-verification: `gpt-5.6-luna`, effort `max`, process exit `0`, verdict `PASS`, `CRITICAL=0/HIGH=0/MEDIUM=0/LOW=0`; previous two HIGH and two MEDIUM findings are `CLOSED`; server coverage is `83.17%`.
- Environment trace remains `iOS-XCTEST PENDING (Full Xcode 필요)`: `verify_release.sh` exit `1` only because `XCTest` is unavailable after Xcodeproj/OpenAPI/static stages pass.
- Legal trace remains `LICENSE/NOTICE 부재 — 소유자 제공 대기`; no legal text was created.
- Evidence: `evidence/wave-03-revision-report.md`, `evidence/lunamax-wave03-final-r2-review.md`, `evidence/wave-03-final.json`, `evidence/backup-restore-rehearsal.json`, and the single canonical `evidence/production-acceptance-20260802T203926Z.json`.
- Prohibited actions observed: no commit, stage, push, PR, merge, deployment, external provider live call, Xcode installation, or iOS device signing.

### CHECKPOINT-2026-08-03-LOCAL-COMPLETE

- Master verdict: `LOCAL COMPLETE / EXTERNAL GATES PENDING (사용자 제공 대기)`.
- Local phase closure: Wave 00 `FINAL PASS`; Wave 01 `CONDITIONAL COMPLETE / LOCAL PASS`; Wave 02 `FINAL PASS / LOCAL PASS`; Wave 03 `FINAL PASS / LOCAL PASS`.
- Local scope completed: deployment security S1-S3, Focus query/offline/delta/atomic close-day consistency, current iOS/docs/release hygiene, hardened backup/restore rehearsal, and the full local acceptance gate.
- External gate 1: `CARD-03-03 LIVE-ACCEPTANCE PENDING (사용자 provider 인프라 필요)`; execute only after approved provider credentials, host, and operator authority are supplied.
- External gate 2: `iOS-XCTEST PENDING (Full Xcode 필요)`; rerun the preserved XCTest commands only after Full Xcode is available.
- External gate 3: `LICENSE/NOTICE 부재 — 소유자 제공 대기`; no legal text may be invented.
- External gate 4: `PRODUCTION DEPLOY PENDING (사용자 인프라·권한 필요)`; no deployment was attempted.
- Evidence: `evidence/wave-00-final.json`, `evidence/wave-01-conditional-complete.json`, `evidence/wave-02-final.json`, `evidence/wave-03-final.json`, and `ops/status/AH-LOCAL-COMPLETE.md`.
- Waiting-state boundary: no implementation or external gate starts until the user supplies the corresponding infrastructure, environment, legal documents, and authority.
- Delivery remains an uncommitted worktree at HEAD `9c8f28d5a9eb34a2c30a869be620885023171977`; no commit, stage, push, PR, merge, deployment, or iOS signing is authorized.
