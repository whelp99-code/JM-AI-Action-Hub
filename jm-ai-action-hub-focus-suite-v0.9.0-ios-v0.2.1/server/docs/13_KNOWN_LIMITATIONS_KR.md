# v0.7.0 알려진 제약과 후속 개발 기준

## 1. 현재 제약

### 1. 단일 사용자 인증

개인 사용을 위한 단일 API Key 구조다. 사용자별 로그인, 조직, RBAC, 감사 주체 검증은 없다. 공개 서비스로 확장하려면 OIDC/OAuth 로그인, 사용자별 Secret Vault, Tenant 분리가 먼저 필요하다.

### 2. 외부 Provider Live 인수

Todoist·GitHub·Google Calendar·Fireflies의 코드, Payload, 서명, Mock, Retry는 검증됐지만 실제 사용자 계정의 Token과 Webhook은 각 서비스별 1회 인수가 필요하다.

### 3. SQLite 운영 경계

SQLite WAL로 개인용 API+Worker를 지원하지만 다중 Host, 고빈도 Webhook, 동시 Worker 확대에는 PostgreSQL을 사용한다.

### 4. Calendar 양방향 실시간 Push

Google Calendar는 Event 조회 기반 Reconciliation을 제공한다. Calendar Push Channel과 Outlook Graph Subscription은 아직 없다. 일정 변경 지연이 실제 업무 장애가 될 때만 추가한다.

### 5. Todoist/GitHub Webhook 등록 자동화

Webhook 수신 Endpoint와 검증은 구현했지만 Provider App/Webhook 생성 절차 자체를 Action Hub가 자동 수행하지 않는다. 계정 소유자가 공식 Console에서 등록해야 한다.

### 6. AI Worker 내부 구현

Action Hub는 GitHub Workflow를 호출할 뿐 Codex·Claude·Copilot·Orca·Hermes의 설치와 명령을 포함하지 않는다. Worker Route마다 기존 Workflow와 Secret이 필요하다.

### 7. 이메일 회신 자동 감지

Waiting-for와 Follow-up은 구현했지만 Gmail/Outlook Mailbox를 읽어 회신을 자동 판별하지 않는다. IMAP Client를 새로 만들지 않으며, 실제 필요 시 Provider 공식 API와 최소 Scope를 검토한다.

### 8. 일정 자동 최적화

Daily Decision은 가용량·과부하·우선순위를 계산하지만 Calendar에 시간 블록을 자동 배치하지 않는다. Reclaim·Akiflow 같은 기존 Planner를 먼저 사용한다.

### 9. Fireflies 범위

Fireflies의 회의 녹음·전사를 재구현하지 않는다. 현재 Adapter는 `meeting.summarized`와 Summary Action Item을 대상으로 한다. 조직별 Custom Summary 구조는 추가 Mapping이 필요할 수 있다.

### 10. 개인 규칙 학습 범위

Project 기준 안정값만 제안하며 사용자의 승인 후 적용한다. 통계적 모델이나 자동 실행 정책은 포함하지 않는다. 잘못된 Rule은 사용자가 비활성화해야 한다.

### 11. Parser의 복잡한 담화

규칙 Parser는 상대 날짜, 시간, 다중 Action, 프로젝트·Repository·실행자·기간·Follow-up을 처리하지만 장문의 대명사 해소, 조건부 계약, 여러 메시지의 전후 관계는 제한적이다. `hybrid` LLM 모드 사용 시 비용과 외부 전송 고지가 필요하다.

### 12. 실제 시간 측정

Weekly ROI의 절감시간은 Metric Event 기반 추정치다. 자동 Stopwatch, Browser Activity, Calendar 실제 소요시간은 수집하지 않는다.

## 2. 의도적으로 제외한 기능

```text
자체 Todo/Kanban
자체 Calendar 월간 화면
자체 회의 녹음·전사
자체 이메일 Client
자체 코딩 Agent
범용 Workflow Builder
무승인 자동 Merge/배포
무승인 외부 메시지 발송
Native Mobile App
다중 Tenant/RBAC
```

## 3. 개발 트리거

| 후속 기능 | 착수 조건 |
|---|---|
| OIDC/RBAC | 실제 사용자 2명 이상 또는 외부 공개 |
| PostgreSQL 전환 | 동시 Worker 2개 이상, Lock 지연, 다중 Host |
| Calendar Push | Reconciliation 지연 때문에 일정 오류가 주 3회 이상 |
| Gmail/Outlook Response Adapter | Waiting-for 수동 종료 누락이 주 5건 이상 |
| Native Mobile | PWA/단축어 Capture 포기율 5% 초과 |
| Planner Adapter | 기존 Planner로 배치할 수 없는 업무가 20% 이상 |
| Plane/OpenProject | 비개발 협업자가 GitHub/Todoist를 사용할 수 없음 |
| Activepieces/n8n | 같은 승인형 다단계 Flow가 5종 이상 반복 |
| Vector/Knowledge Retrieval | Action 분류에 과거 문서 문맥이 필수인 오류가 15% 이상 |
| 자동 규칙 승격 | Proposed Rule 오승인율이 충분히 낮다는 데이터 축적 후 |

## 4. 운영 우선순위

1. 실제 Todoist 테스트 프로젝트 Live 1건
2. GitHub 테스트 Repository Issue→Workflow→PR 1건
3. Google 테스트 Calendar 1건
4. Fireflies 테스트 회의 1건
5. 14일 실사용 KPI 수집
6. 오류·수정 패턴을 기반으로 다음 기능 결정
