# Closed-loop 상태 동기화 설계

## 1. 목적

v0.1.0은 외부 시스템에 생성 요청을 보내는 데 성공하면 작업을 완료로 취급했다. v0.7.0에서는 다음을 분리한다.

```text
등록 성공 = registered
실제 업무 완료 = completed
```

완료 여부는 각 원장의 최신 상태 또는 완료 증거가 결정한다.

## 2. 원장 정책

| 정보 | 최종 원장 |
|---|---|
| Todo 완료 | Todoist |
| 개발 Issue 상태 | GitHub Issues |
| AI 실행·PR·CI·Merge | GitHub Actions/PR/Checks |
| 실제 일정 시간 | Google Calendar 또는 사용자의 Calendar |
| 원문·승인·감사 | Action Hub |
| 응답 대기·후속 확인 | Action Hub |
| 개인 규칙 | Action Hub |

## 3. 내구성 실행

### 3.1 Transactional Outbox

승인된 Action과 외부 실행 요청을 같은 DB 트랜잭션에 기록한다.

```text
ActionItem state=queued
OutboxEvent state=pending
COMMIT
```

외부 API는 Worker가 호출한다. API 응답 유실이나 프로세스 종료가 발생해도 Outbox가 남는다.

### 3.2 상태

```text
pending
  ↓ claim
processing
  ├→ completed
  ├→ retry(next_attempt_at)
  └→ failed(max attempts)
```

### 3.3 동시 실행

- PostgreSQL: `FOR UPDATE SKIP LOCKED`
- SQLite: 짧은 Claim 트랜잭션과 WAL/busy timeout
- Claim 후 즉시 Commit
- `locked_at`이 제한시간을 넘으면 Retry로 복구

## 4. Webhook 수신

### 4.1 공개 경로

```text
POST /api/v1/webhooks/todoist
POST /api/v1/webhooks/github
POST /api/v1/webhooks/fireflies
```

Webhook 경로는 Action Hub API Key 대신 Provider Secret 서명을 사용한다.

### 4.2 검증

| Provider | 검증 방식 |
|---|---|
| Todoist | HMAC-SHA256 digest를 Base64로 비교 |
| GitHub | `X-Hub-Signature-256: sha256=<hex>` |
| Fireflies | `sha256=<hex>` HMAC 헤더 |

Production에서 Secret이 없으면 503으로 거부한다. Development/Test에서는 로컬 Fixture를 위해 unsigned 수신을 허용하되 `signature_valid=false`로 기록한다.

### 4.3 중복 방지

```text
UNIQUE(provider, delivery_id)
```

Provider Delivery ID가 없을 때는 Body SHA-256을 대체키로 사용한다.

## 5. External State Mirror

각 외부 객체를 별도 Mirror로 보관한다.

```text
provider
external_id
external_url
state
payload_json
external_updated_at
last_synced_at
source_version
sync_error
```

ActionItem의 `external_id`는 v0.1 호환 필드이며, 다중 외부 객체는 ExternalState가 담당한다.

예:

```text
ActionItem A
├─ github issue owner/repo#42
├─ github workflow owner/repo#501
├─ github check suite owner/repo#777
└─ github PR owner/repo#12
```

## 6. 상태 적용 규칙

### Todoist

| 외부 상태 | 로컬 상태 |
|---|---|
| open | registered |
| completed | completed |
| uncompleted | registered + conflict 기록 가능 |
| deleted/missing | 즉시 삭제하지 않고 conflict |

### GitHub Issue

| 외부 상태 | 로컬 상태 |
|---|---|
| open/reopened | registered |
| closed | completed |
| deleted/missing | conflict |

### AI Worker

```text
queued → dispatched → running
                   → needs_input
                   → human_review
                   → failed
PR merged          → completed
```

Workflow/Check 성공만으로 완료하지 않는다. 사람이 검토할 산출물이 있다는 뜻이므로 `human_review`다.

## 7. 이벤트 순서 역전

Webhook은 발생 순서와 도착 순서가 다를 수 있다.

예:

```text
10:00 PR merged
10:01 Action completed
10:03 과거 check_suite queued 이벤트 도착
```

v0.7.0은 `completion_evidence`가 있는 merged Action을 최종 상태로 보고, 늦은 Workflow/Check/PR open 이벤트가 상태를 하향하지 못하게 한다. 외부 이벤트 자체는 Mirror에 기록해 감사 가능성을 유지한다.

## 8. Reconciliation

Webhook만으로는 누락·전송 실패를 완전히 제거할 수 없다.

Worker가 일정 주기로 ExternalState를 조회한다.

```text
Todoist task/completed endpoint
GitHub issue endpoint
Google Calendar event endpoint
ICS file existence
```

결과:

- 변경됨: State 적용
- 동일함: last_synced_at 갱신
- 404/missing: SyncConflict 생성
- API 오류: sync_error 기록, 로컬 상태 보존

## 9. 복구 Marker

### Todoist/GitHub

외부 설명/본문에 다음 Marker를 삽입한다.

```text
Action-Hub-ID: <uuid>
```

외부 등록 성공 후 응답이 유실되면 재시도 전에 Marker를 검색해 기존 객체를 회수한다.

### Google Calendar

Action fingerprint 기반 결정적 Event ID를 사용한다. Insert 409가 발생하면 동일 ID를 조회해 기존 이벤트를 복구한다.

## 10. 충돌

`SyncConflict`는 다음을 기록한다.

```text
provider
conflict_type
local_value
external_value
resolution
resolved_at
```

현재 정책:

- 완료 후 외부 재오픈: external source wins
- 외부 객체 missing: 자동 삭제 금지, unresolved
- PR Merge: completion evidence 기준 final

## 11. 운영 API

```text
POST /api/v1/control/run-once?reconcile=true
POST /api/v1/control/outbox/drain
POST /api/v1/control/webhooks/drain
POST /api/v1/control/reconcile
GET  /api/v1/control/webhooks
GET  /api/v1/connectors/status?probe=true
```

## 12. 검증 시나리오

- 같은 Delivery 두 번 수신
- 잘못된 서명
- Worker 처리 중 강제 종료
- 외부 생성 후 HTTP 응답 유실
- Todoist completed→uncompleted
- GitHub closed→reopened
- PR merge 후 과거 check event
- 외부 404
- v0.1 DB 업그레이드
