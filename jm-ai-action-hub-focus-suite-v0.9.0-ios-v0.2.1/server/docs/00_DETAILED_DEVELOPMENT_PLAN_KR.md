# JM-AI Action Hub 상세 개발 계획서

- 문서 버전: 2.0
- 제품 버전: 0.7.0
- 기준일: 2026-07-29
- 시간대: Asia/Seoul
- 상세 단계 문서: `15_V070_SEQUENTIAL_DEVELOPMENT_PLAN_KR.md`

## 1. 제품 정의

JM-AI Action Hub는 새 Todo·Calendar·Kanban을 만드는 제품이 아니다.

> 스마트폰과 PC에서 수집한 자연어·음성·복사/붙여넣기 요청을 실행 가능한 Action으로 구조화하고, 사용자가 승인한 결과만 Todoist·GitHub·Calendar에 등록한 뒤 사람·AI·외부 응답의 실제 완료까지 추적하는 Action Control System이다.

핵심 흐름은 다음과 같다.

```text
수집 → 구조화 → 검토·승인 → 내구성 등록
    → 외부 상태 회수 → 사람/AI 실행 → 완료 증거 → 후속·학습
```

## 2. 제품 원칙

1. **Build Less, Integrate More**: 기존 제품이 잘하는 기능은 재개발하지 않는다.
2. **System of Record 분리**: 개인 업무는 Todoist, 개발 작업은 GitHub, 실제 일정은 Calendar가 최종 원장이다.
3. **Review Before Write**: 외부 등록, AI 위임, 고위험 실행은 사람 승인을 통과한다.
4. **Registered Is Not Completed**: 외부 API 등록 성공과 실제 업무 완료를 분리한다.
5. **At-least-once + Idempotency**: 재시도 가능하되 같은 외부 항목을 중복 생성하지 않는다.
6. **No Fake Precision**: 날짜·시간·저장소·담당자가 모호하면 검토 대상으로 남긴다.
7. **Traceability**: 원문, 수정, 승인, 등록, 외부 상태, AI 결과, 완료 증거를 연결한다.
8. **Mobile First**: PWA·공유·클립보드·받아쓰기를 우선하고 네이티브 앱은 필요성이 입증될 때만 검토한다.

## 3. 기존 솔루션 재사용 경계

| 책임 | 재사용 제품 | Action Hub의 역할 |
|---|---|---|
| 개인 Todo·모바일 알림 | Todoist | 추출·승인·등록·완료 상태 회수 |
| 일정 UI·알림 | Google/Outlook Calendar 또는 ICS | 일정 후보·중복 안전 등록·상태 대조 |
| 개발 Issue·PR·CI | GitHub | Issue 생성, Worker/PR/Check/Merge 연결 |
| AI 코딩 | Codex·Claude Code·Copilot·Orca·Hermes·Master Worker | 기존 Workflow 호출과 상태 추적 |
| 회의 녹음·전사 | Fireflies | Action Item을 다시 분류하고 승인 Plan 생성 |
| 일일 시간표 | 기존 Calendar/Planner | 가용량·과부하·우선순위 Decision Layer |

개발하지 않는 기능:

- 자체 Todo·Calendar·Kanban·Gantt
- 자체 회의 녹음·전사
- 자체 이메일 클라이언트
- 자체 음성 인식 모델
- 범용 Workflow Builder
- 자동 Merge·자동 운영 배포
- 승인 없는 고객 메시지·메일 발송
- 모든 필드를 복제하는 범용 양방향 동기화

## 4. 아키텍처

```text
Capture
  ├─ PWA / Share Target / Clipboard / Voice
  ├─ REST / MCP
  └─ Fireflies Webhook
        │
        ▼
Action Parser
  ├─ Rules
  ├─ Optional LLM JSON Parser
  └─ Approved Personal Rules
        │
        ▼
Review & Approval
        │
        ▼
Transactional Outbox ──► Todoist / GitHub / Calendar / ICS
        │                         │
        │                         ▼
        └──────────── Signed Webhooks + Reconciliation
                                  │
                                  ▼
                         External State Mirror
                                  │
                   ┌──────────────┼──────────────┐
                   ▼              ▼              ▼
              Follow-up      Daily Decision   AI Worker Router
                                                   │
                                                   ▼
                                           Workflow / PR / Check
                                                   │
                                                   ▼
                                              Human Review
                                                   │
                                                   ▼
                                                Completed
```

## 5. 데이터와 상태 모델

### 주요 엔터티

```text
InboxMessage
ActionPlan
ActionItem
OutboxEvent
WebhookDelivery
ExternalState
SyncConflict
WorkerExecution
FollowUp
MeetingIntake
PersonalRule
MetricEvent
AuditEvent
```

### Action 상태

```text
draft → approved → queued → executing → registered
                                  ├→ waiting
                                  ├→ dispatched → running → human_review → completed
                                  ├→ needs_input / blocked
                                  └→ failed → retry
```

외부 등록 성공은 `registered`이며, 다음 증거 중 하나가 확인될 때 `completed`가 된다.

- Todoist 완료 이벤트
- GitHub Issue close
- AI 개발 작업의 PR merge
- 사용자의 명시적 완료 처리
- 승인된 외부 완료 증거

## 6. 단계별 개발 범위

| 단계 | 릴리스 | 핵심 결과 | 상태 |
|---|---|---|---|
| 기반 MVP | 0.1.0 | Inbox, Parser, 승인, Connector, PWA | 완료 |
| 운영 기반 | 0.1.1 | Alembic, Outbox, Retry, Worker, OAuth Broker | 완료 |
| 폐쇄형 상태 | 0.2.0 | Webhook, 서명, Delivery 중복, Reconciliation | 완료 |
| Human–AI Router | 0.3.0 | 실행자·Worker Adapter·PR/CI/Merge 추적 | 완료 |
| Commitment | 0.4.0 | Waiting-for와 Follow-up | 완료 |
| Planning | 0.5.0 | 예상시간·Deadline·가용량·과부하·Top 업무 | 완료 |
| Meeting Intake | 0.6.0 | Fireflies Action Item 승인 Plan | 완료 |
| Learning & ROI | 0.7.0 | 개인 규칙 제안·주간 효과 측정 | 완료 |

단계별 상세 구현과 인수 기준은 `docs/15`~`docs/18`을 따른다.

## 7. 비기능 요구사항

### 신뢰성

- 등록 요청과 Outbox를 동일 DB 트랜잭션으로 기록
- 지수형 재시도와 최대 시도 제한
- Outbox/Webhook 선점과 stale-lock 복구
- Provider Delivery ID 고유 제약
- 외부 응답 유실 시 Action ID 표식으로 복구
- Webhook 누락 시 Reconciliation
- 외부 404를 즉시 삭제로 확정하지 않고 Conflict로 격리
- PR Merge 이후 늦은 이벤트가 완료 상태를 하향하지 않음

### 보안

- Production API Key 32자 이상 강제
- Provider Webhook HMAC 검증
- Token·Secret DB 저장 금지
- Google Refresh Token은 환경변수, Access Token은 메모리 캐시
- CSP, frame 차단, nosniff, no-store, Production HSTS
- 공유 원문을 URL query가 아닌 POST 본문으로 전달
- 요청 본문 크기 제한
- 외부 쓰기와 AI 위임에 사람 승인 게이트 유지

### 운영

- `/health`, `/readiness`, Connector active probe
- API와 Worker 분리 실행
- SQLite 개인 모드, PostgreSQL 다중 프로세스 권장
- Docker Compose와 systemd 구성
- Alembic upgrade, backup/restore, release checksum

## 8. 완료 기준

소프트웨어 완료:

- v0.1 DB를 데이터 손실 없이 v0.7 Head로 승격
- Parse → Review → Approve → Outbox → Connector 흐름
- Todoist/GitHub 상태 회수와 재조정
- AI Workflow → PR/Check → Merge 폐쇄 루프
- Waiting-for, Daily Decision, Fireflies, Personal Rule, Weekly ROI
- REST, MCP, PWA, CLI, API/Worker 분리
- 자동 테스트·컴파일·JavaScript·HTTP·Wheel·압축본 검증

운영 인수:

- 사용자 Todoist/GitHub/Google/Fireflies 자격증명으로 테스트 원장 1회 Live 확인
- 대상 서버의 Docker/PostgreSQL 실제 기동
- HTTPS/VPN과 실제 스마트폰 공유 흐름 확인
- Webhook URL 등록과 Provider Delivery 확인

## 9. 향후 개발 판단 기준

| 후보 | 착수 조건 |
|---|---|
| Calendar 자동 시간 블록 | Reclaim/Akiflow 등 기존 솔루션으로 해결되지 않는 제약이 20% 이상 |
| 이메일 회신 자동 감지 | Waiting-for 누락이 주 5건 이상 |
| 네이티브 모바일 | PWA/단축어로 인한 입력 포기율이 5% 초과 |
| 다중 사용자·RBAC | 실제 공동 운영자가 2명 이상 |
| Plane/OpenProject | 비개발 협업자가 GitHub/Todoist를 사용하기 어려움 |
| 범용 자동화 엔진 | 같은 다단계 흐름이 5종 이상 반복 |

## 10. 최종 정의

> JM-AI Action Hub v0.7.0은 할 일을 저장하는 앱이 아니라, 원문에서 Action을 만들고 사람·AI·외부 상대에게 배분한 뒤 외부 원장의 완료 증거까지 회수하는 개인용 Action Control System이다.
