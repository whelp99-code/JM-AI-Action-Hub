# PRD — JM-AI Action Hub v0.7.0

## 1. 제품 비전

업무 요청이 발생하는 순간부터 실제 완료 증거가 확인되는 순간까지의 수작업을 줄인다.

> 한 번 수집한 원문을 일정·개인 업무·개발 작업으로 구조화하고, 사용자가 승인한 Action만 기존 원장에 등록한 뒤 사람·AI·외부 상대의 실행 상태를 실제 완료까지 추적한다.

## 2. 문제 정의

- 업무 요청이 카카오톡·이메일·회의·전화·웹에 흩어져 누락된다.
- 긴 원문에서 일정, 개인 후속 업무, 개발 요청을 다시 입력해야 한다.
- 외부 앱에 작업이 생성됐다는 사실과 실제 완료됐다는 사실이 혼동된다.
- Todoist·GitHub·Calendar의 상태가 달라지면 중앙 브리핑이 오래된 정보가 된다.
- AI 코딩 작업을 시작한 뒤 Workflow·PR·검증·Merge 상태를 별도로 확인한다.
- 상대방에게 문의한 업무는 “내가 할 일” 목록에서 사라져 후속 확인을 놓친다.
- 하루 가용시간보다 많은 업무를 계획하고도 과부하를 늦게 인지한다.
- 회의 Action Item이 프로젝트·저장소 맥락 없이 자동 등록되면 잡음과 중복이 생긴다.

## 3. 핵심 가치 제안

1. **One Capture, Many Actions**: 한 번 입력으로 여러 실행 항목을 생성한다.
2. **Approval Before Write**: 실제 외부 변경 전 사람이 검토한다.
3. **Closed-loop State**: 등록과 완료를 분리하고 외부 원장의 완료 증거를 회수한다.
4. **Human–AI Allocation**: 사람·AI·혼합·외부 대기로 실행 주체를 구분한다.
5. **Commitment Control**: 응답 대기와 Follow-up을 일반 Todo와 함께 관리한다.
6. **Decision, Not Another Planner**: 새 Calendar를 만들지 않고 오늘의 용량·위험·우선순위만 계산한다.
7. **Learning With Approval**: 반복 수정 패턴을 규칙으로 제안하되 사용자 승인 후 적용한다.
8. **Reuse First**: Todoist, GitHub, Calendar, Fireflies, 기존 AI Worker를 재사용한다.

## 4. 목표 사용자

### P1. 1인 대표·기술 컨설턴트

여러 고객·제안·개발 프로젝트를 동시에 운영하며 스마트폰 메시지에서 업무가 많이 발생한다.

### P2. AI 기반 개발 리드

요구사항을 GitHub Issue로 만들고 Codex·Claude·Copilot 등의 작업을 PR·검증·Merge까지 추적하고 싶다.

### P3. 소규모 팀 관리자

회의와 외부 문의에서 Action을 추출하되 잘못된 자동 등록과 책임 불명확을 피하고 싶다.

## 5. 핵심 Job To Be Done

- “메시지를 받았을 때 잊기 전에 한 번의 붙여넣기로 Action을 만들고 싶다.”
- “AI가 해석한 일정과 업무를 확인한 뒤에만 실제 앱에 등록하고 싶다.”
- “외부 앱에서 완료·재오픈된 상태가 자동으로 반영되길 원한다.”
- “개발 작업을 적합한 AI Worker에 맡기고 PR Merge까지 한 흐름으로 보고 싶다.”
- “상대방 답변을 기다리는 업무와 다음 연락 시점을 놓치지 않고 싶다.”
- “오늘 가능한 시간보다 업무가 많은지 즉시 알고 조정하고 싶다.”
- “회의 Action Item을 프로젝트 맥락으로 다시 검토한 후 등록하고 싶다.”

## 6. 기능 요구사항

| ID | 요구사항 | 우선순위 | 상태 |
|---|---|---|---|
| FR-001 | 텍스트·붙여넣기·공유·음성 입력 | Must | 완료 |
| FR-002 | 다중 Action 분리와 한국어 상대 날짜 | Must | 완료 |
| FR-003 | 일정/Todo/개발 작업/알림/메모 분류 | Must | 완료 |
| FR-004 | 항목 편집·선택 승인·거부·검토 차단 | Must | 완료 |
| FR-005 | Todoist·GitHub·Google Calendar·ICS 등록 | Must | 완료 |
| FR-006 | Transactional Outbox·Retry·Idempotency | Must | 완료 |
| FR-007 | Todoist/GitHub Signed Webhook·중복 Delivery 차단 | Must | 완료 |
| FR-008 | External State Mirror·Reconciliation·Conflict | Must | 완료 |
| FR-009 | 사람/AI/Hybrid/External 실행자 | Must | 완료 |
| FR-010 | 기존 AI Worker Workflow 위임과 PR/CI/Merge 추적 | Must | 완료 |
| FR-011 | Waiting-for·Follow-up·응답·후속 연락 | Must | 완료 |
| FR-012 | 예상시간·Deadline·Work mode·가용량·과부하 | Should | 완료 |
| FR-013 | Fireflies Action Item Intake·재처리 | Should | 완료 |
| FR-014 | 개인 규칙 제안·승인·안전 필드 적용 | Should | 완료 |
| FR-015 | 주간 실행/지연/대기/AI 위임/절감시간 보고 | Should | 완료 |
| FR-016 | REST·MCP·CLI·별도 Worker | Should | 완료 |
| FR-017 | 모바일 PWA와 Today Decision UI | Should | 완료 |
| FR-018 | 선택적 LLM JSON Parser | Could | 완료 |

## 7. 라우팅과 원장 정책

| 데이터 | 최종 원장 | Action Hub 책임 |
|---|---|---|
| 개인 작업 완료 상태 | Todoist | 등록·Webhook·대조·감사 |
| 개발 Issue·PR·CI·Merge | GitHub | Issue 생성·Worker 연결·증거 회수 |
| 실제 일정 시간 | Google/Outlook Calendar | 후보·중복 안전 등록·대조 |
| 원문·승인·연결·충돌 | Action Hub | 감사 가능한 실행 맥락 |
| 회의 전사 | Fireflies | Action 후보 Intake만 수행 |
| AI 실행 결과 | 기존 Worker/GitHub | 위임·상태·Artifact 연결 |

## 8. 비기능 요구사항

### 보안

- Production API Key는 32자 이상이며 placeholder를 거부한다.
- Provider Webhook은 HMAC 서명을 검증한다.
- Token·Refresh Token·Webhook Secret을 DB에 저장하지 않는다.
- 외부 쓰기·AI 위임·고위험 실행은 사람 승인 후 수행한다.
- PWA 공유 원문을 URL에 포함하지 않는다.
- API·공유 응답은 no-store이며 CSP·frame 차단·HSTS를 제공한다.
- 입력과 HTTP 요청 본문 크기를 제한한다.

### 신뢰성

- At-least-once 전달과 idempotent 처리를 사용한다.
- 외부 등록 요청은 Outbox와 같은 트랜잭션에 기록한다.
- 다중 Worker 선점과 stale-lock 복구를 제공한다.
- Webhook 누락은 Reconciliation으로 복구한다.
- 외부 404는 즉시 삭제 처리하지 않고 Conflict로 격리한다.
- 상태 이벤트가 순서와 다르게 도착해도 완료 상태를 하향하지 않는다.

### 운영

- SQLite 개인 모드와 PostgreSQL 운영 모드를 지원한다.
- API와 Worker를 분리할 수 있다.
- Alembic Migration, Backup, Restore, Upgrade를 제공한다.
- Health, Readiness, Connector probe를 제공한다.
- 기본 실행 모드는 dry-run이다.

## 9. 성공 지표

- Capture→Plan 중앙값 5초 이내(규칙 Parser 기준)
- 후보 Action 승인률 70% 이상
- 날짜·라우팅 수정률 20% 이하
- 외부 중복 생성률 0.5% 미만
- Webhook/Reconciliation 후 상태 불일치율 5% 미만
- Waiting-for 장기 누락 건수 50% 이상 감소
- 일일 계획 수동 조작시간 50% 이상 감소
- AI 위임 작업의 PR 생성률과 Merge율 추적 가능
- 사람이 입력·복사·상태 확인·후속 조치에 쓰는 시간 50% 이상 감소

## 10. 비목표

- 자체 Todo·Calendar·Kanban·Gantt
- 자체 회의 녹음·전사
- 자체 이메일 클라이언트
- 범용 자동화 빌더
- 자동 Merge·자동 운영 배포
- 승인 없는 외부 발송·계약·결제·삭제
- 모든 외부 필드를 복제하는 범용 동기화 플랫폼
- 초기 다중 조직·결제·고급 RBAC

## 11. 릴리스 판정

v0.7.0은 개인용 Closed-loop 소프트웨어로 개발·자동 검증을 완료했다. 실제 Provider 계정·Webhook·OAuth·물리 스마트폰·대상 서버는 운영 환경에서 한 번의 Live 인수가 필요하다.
