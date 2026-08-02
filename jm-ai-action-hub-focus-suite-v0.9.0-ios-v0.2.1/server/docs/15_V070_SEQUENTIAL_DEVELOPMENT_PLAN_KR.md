# JM-AI Action Hub v0.7.0 단계별 개발 계획 및 완료 기준

- 작성일: 2026-07-29
- 기준선: v0.1.0
- 목표 릴리스: v0.7.0
- 제품 정의: 외부 앱을 대체하지 않고 사람·AI·외부 응답을 실제 완료까지 연결하는 Action Control System

## 1. 개발 전략

### 1.1 재사용 우선

다음 기능은 기존 제품이 제공하므로 개발하지 않는다.

| 기능 | 재사용 대상 | 개발하지 않는 이유 |
|---|---|---|
| 개인 Todo·모바일 입력 | Todoist | 자연어·모바일·알림·완료 상태가 이미 존재 |
| 일정 UI·알림 | Google/Outlook Calendar | Calendar 원장을 다시 만들면 동기화 충돌 발생 |
| 개발 이슈·PR·CI | GitHub | 코드와 실행 결과의 최종 원장이 GitHub |
| 코딩 에이전트 | Codex·Claude Code·Copilot·Orca·Hermes | 각 제품의 실행 하네스와 모델을 재개발할 필요 없음 |
| 회의 녹음·전사 | Fireflies | Action Hub는 전사보다 Action 품질·승인이 핵심 |
| 범용 자동화 빌더 | Activepieces/n8n | 현재 반복 흐름은 명시적 Adapter로 충분하며 운영 복잡도만 증가 |

Action Hub만의 개발 범위는 다음이다.

```text
Action 이해
+ 승인
+ 내구성 실행
+ 외부 상태 회수
+ 사람/AI 배정
+ 완료 증거
+ 후속 확인
+ 개인화 학습
```

### 1.2 상태 정확성 우선

기능 추가 전에 다음 의미를 분리한다.

```text
외부 앱에 등록됨 ≠ 실제 업무 완료
```

따라서 `registered`와 `completed`를 별도 상태로 정의하고, 외부 원장의 이벤트가 완료를 확정한다.

## 2. 단계별 개발

## Phase 1 — 운영 기반 강화 (`v0.1.1`)

### 목표

프로세스 중단과 외부 API 응답 유실에도 등록 요청이 사라지거나 중복되지 않도록 한다.

### 구현

- Alembic 마이그레이션
- v0.1.0 직접 생성 DB 자동 감지·Stamp·Upgrade
- Transactional Outbox
- Idempotency Key unique constraint
- 지수형 Retry 및 최대 시도
- `pending/retry → processing → completed/failed`
- `SELECT FOR UPDATE SKIP LOCKED` 선점
- stale processing lock 복구
- 별도 `action-hub-worker`
- API/Worker 분리 Docker Compose
- Connector active probe
- Google OAuth refresh-token broker

### 완료 기준

- v0.1.0 데이터가 유지된 채 최신 Head로 승격된다.
- 등록 요청과 DB 상태가 같은 트랜잭션으로 기록된다.
- Worker 중단 후 다시 실행하면 미완료 이벤트를 처리한다.
- 동일 Outbox 이벤트를 두 Worker가 동시에 실행하지 않는다.
- 외부 Token을 DB에 저장하지 않는다.

### 완료 상태

**구현·자동 검증 완료**

---

## Phase 2 — Closed-loop State Sync (`v0.2.0`)

### 목표

Todoist·GitHub의 실제 변경을 Action Hub에 반영하고 Webhook 누락을 복구한다.

### 구현

- Todoist Webhook 서명 검증
- GitHub Webhook `sha256=` 서명 검증
- Fireflies HMAC 서명 검증
- Provider + Delivery ID 중복 차단
- Webhook Queue와 별도 처리 Worker
- Todoist 완료·미완료·삭제
- GitHub Issue close·reopen·delete
- GitHub PR opened·ready·closed·merged
- GitHub Workflow Run
- GitHub Check Suite
- External State Mirror
- Sync Conflict
- Provider Reconciliation
- 외부 404 비파괴 격리
- 이벤트 순서 역전 시 Merge 완료 상태 보존

### 완료 기준

- Todoist에서 완료한 작업이 로컬 `completed`가 된다.
- GitHub Issue 재오픈 시 외부 원장 우선으로 상태가 복구된다.
- 동일 Webhook을 여러 번 보내도 한 번만 처리된다.
- 서명 위조 요청은 401로 거부된다.
- Webhook 누락 후 Reconciliation이 상태를 회복한다.
- PR Merge 후 늦은 Workflow/Check 이벤트가 완료를 되돌리지 않는다.

### 완료 상태

**구현·자동 검증 완료**

---

## Phase 3 — Human–AI Executor Router (`v0.3.0`)

### 목표

업무를 사람·AI·혼합·외부 대기로 구분하고 기존 AI Worker에 위임한다.

### 구현

- `executor`: human / ai / hybrid / external
- `preferred_worker`
- Worker Registry
- GitHub `workflow_dispatch` Adapter
- Codex·Claude·Copilot·Orca·Hermes·Master Worker route
- WorkerExecution 상태
- Action ID correlation
- Workflow/Check/PR Artifact 수집
- Human Review Gate
- PR Merge를 완료 증거로 사용

### 안전 경계

다음은 자동화하지 않는다.

- 자동 Merge
- 자동 운영 배포
- 고객 메일 자동 발송
- 계약·결제·삭제와 같은 고위험 실행
- Action ID 상관관계가 불명확한 실행의 임의 연결

### 완료 기준

- 승인된 AI/Hybrid 작업만 위임된다.
- 같은 작업의 활성 Worker가 있으면 중복 위임하지 않는다.
- Workflow 성공은 `human_review`이고 완료가 아니다.
- PR Merge URL이 completion evidence가 된다.
- 저장소 내 활성 실행이 여러 개이고 강한 상관키가 없으면 `unmatched` 처리한다.

### 완료 상태

**구현·자동 검증 완료**

---

## Phase 4 — Commitment & Follow-up (`v0.4.0`)

### 목표

내가 해야 할 일뿐 아니라 상대방의 응답을 기다리는 일을 관리한다.

### 구현

- Waiting-for 대상
- Channel
- Expected-by
- Follow-up-at
- Reminder count
- 응답 도착
- 후속 연락 완료
- 다음 확인일 재설정
- resolved/cancelled
- Today Due Follow-up

### 완료 기준

- 응답 대기 Action이 일반 Todo와 구분된다.
- 만료된 Follow-up이 Today 화면에 나타난다.
- 응답 도착 시 후속 알림이 종료된다.
- 후속 연락 처리 시 다음 확인 시각을 생성할 수 있다.

### 완료 상태

**구현·자동 검증 완료**

---

## Phase 5 — Planning Decision Layer (`v0.5.0`)

### 목표

새 Calendar를 만들지 않고 오늘의 가용량과 우선순위 결정을 지원한다.

### 구현

- `estimated_minutes`
- `deadline_at`
- `earliest_start_at`
- `latest_finish_at`
- `work_mode`
- `energy_level`
- `depends_on`
- `reschedule_count`
- 가용시간
- 보호 Buffer
- 계획시간
- Overload
- Top items
- Deferred items
- AI delegation candidates
- Risk messages

### 완료 기준

- 오늘 가용시간보다 계획량이 많으면 초과분을 표시한다.
- Deadline·Priority·Overdue·Dependency를 반영한다.
- AI 위임 후보를 별도 표시한다.
- 시간표 UI나 Calendar 원장을 복제하지 않는다.

### 완료 상태

**구현·자동 검증 완료**

---

## Phase 6 — Meeting Action Intake (`v0.6.0`)

### 목표

회의 전사 기능을 만들지 않고 Fireflies 결과를 승인 가능한 Action으로 변환한다.

### 구현

- Fireflies V2 Webhook
- `meeting.summarized`
- GraphQL Transcript 조회
- Summary Action Item 추출
- MeetingIntake 감사 상태
- ActionPlan 연결
- 실패 재처리
- 중복 회의 이벤트 방지

### 완료 기준

- 회의 완료 이벤트를 서명 검증한다.
- Action Item을 즉시 외부 앱에 쓰지 않고 Draft Plan으로 만든다.
- 실패한 회의 Intake를 재처리할 수 있다.
- 같은 회의 이벤트가 중복 계획을 만들지 않는다.

### 완료 상태

**구현·자동 검증 완료**

---

## Phase 7 — Personal Learning & ROI (`v0.7.0`)

### 목표

사용자의 반복 수정 패턴을 승인형 규칙으로 제안하고 자동화 효과를 측정한다.

### 구현

- Project 기준 반복 패턴 수집
- 최소 관찰 횟수
- 80% 이상 안정값
- Proposed Rule
- 사용자 승인 후 Active
- 안전 필드 allowlist
- Rule 적용 감사 로그
- 등록·완료·지연·대기·AI 위임 지표
- 추정 절감시간
- 주간 개선 추천

### 안전 필드

```text
project
repository
assignee
priority
labels
estimated_minutes
work_mode
executor
preferred_worker
energy_level
waiting_for
```

외부 등록·삭제·승인 우회·토큰·API URL 등은 규칙으로 변경할 수 없다.

### 완료 기준

- 반복 수정 3회 이상에서 규칙 후보를 만든다.
- 사용자가 승인하지 않은 규칙은 자동 적용하지 않는다.
- Allowlist 밖의 필드는 API가 거부한다.
- 주간 보고서가 Action 흐름의 효과와 병목을 보여준다.

### 완료 상태

**구현·자동 검증 완료**

## 3. 비기능 요구사항

### 신뢰성

- At-least-once 전달 + idempotent 처리
- 외부 상태와 로컬 상태 분리
- Webhook + Polling Reconciliation 병행
- 부분 실패 격리
- 재시작 복구

### 보안

- Production API Key 강제
- Webhook HMAC 검증
- Secret 환경변수 관리
- API no-store
- CSP·Frame 차단
- 감사 로그
- Human approval gate

### 운영

- `/health`
- `/readiness`
- Connector probe
- `action-hub check`
- `action-hub-worker --once --reconcile`
- Docker Compose
- PostgreSQL overlay
- systemd API/Worker 분리
- Backup·Upgrade script

## 4. 최종 완료 판정

| 구분 | 판정 |
|---|---|
| v0.1.0 호환 DB 업그레이드 | 완료 |
| Outbox와 Worker | 완료 |
| Todoist/GitHub/Fireflies Webhook | 완료 |
| Reconciliation·Conflict | 완료 |
| AI Worker Adapter | 완료 |
| Follow-up | 완료 |
| Daily Decision | 완료 |
| Meeting Intake | 완료 |
| Personal Rule·Weekly ROI | 완료 |
| PWA·REST·MCP | 완료 |
| 자동 테스트·패키징 | 완료 |
| 실제 외부 계정 Live 인수 | 사용자 자격증명 필요 |
| 실제 Docker/PostgreSQL 기동 | 대상 호스트 인수 필요 |
| 실제 스마트폰 공유 시트 | 물리 기기 인수 필요 |

## 5. 다음 개발 기준

다음 기능은 실제 사용 데이터가 기준을 넘을 때만 개발한다.

| 후보 | 착수 조건 |
|---|---|
| Calendar 자동 시간 블록 | 기존 Reclaim/Akiflow 연동으로 해결 불가한 제약이 20% 이상 |
| 이메일 회신 자동 감지 | Waiting-for 누락이 주 5건 이상이고 Gmail/Outlook 기존 기능으로 해결 불가 |
| Native Mobile | PWA/단축어 때문에 Capture 포기율 5% 초과 |
| 다중 사용자·RBAC | 실제 2명 이상 공동 운영 |
| Plane/OpenProject | 비개발 협업자에게 GitHub/Todoist가 부적합 |
| 범용 Workflow Builder | 동일 다단계 흐름이 5종 이상 반복 |
