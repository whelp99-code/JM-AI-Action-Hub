# 기존 앱·오픈소스 재사용 결정

## 결정 기준

- 동일 기능이 이미 안정적으로 존재하는가
- 스마트폰 UX가 검증되었는가
- API 또는 표준 export가 있는가
- 데이터 원장 역할이 명확한가
- 운영 비용이 직접 개발보다 낮은가

## 최종 결정표

| 기능 | 선택 | 직접 개발 | 근거 |
|---|---|---:|---|
| 개인 Todo | Todoist | 안 함 | 모바일, 자연어, 알림, API |
| 일정 화면·알림 | Google/기존 Calendar | 안 함 | 공유·알림·반복 일정·OS 연동 |
| 개발 작업 관리 | GitHub Issues/Projects | 안 함 | 저장소·PR·agent 흐름과 동일 원장 |
| 자연어 분류·승인 | Action Hub | 함 | 세 제품 사이에 공통으로 없는 연결 계층 |
| 모바일 입력 앱 | PWA/OS 기능 | 최소 | 네이티브 앱 유지비 회피 |
| 워크플로 엔진 | 초기 미도입 | 안 함 | 현재 흐름에는 과도한 운영 복잡성 |
| 일반 프로젝트 관리 | Todoist 우선 | 안 함 | 1인·소규모 업무에 충분 |
| 대규모 협업 PM | Plane/OpenProject 후보 | 조건부 | 실제 조직 요구가 생길 때만 |
| 공동 지식 DB | 기존 별도 프로젝트 | 안 함 | Action Hub 범위 밖 |

## Todoist를 사용하는 이유

Todoist 공식 개발자 페이지는 API token과 Bearer 인증으로 `/api/v1/tasks`에 task를 생성하는 예시를 제공한다. Action Hub는 Todoist가 이미 제공하는 task 저장·알림·모바일 관리를 재구현하지 않고 승인된 개인 행동만 전달한다.

## GitHub를 사용하는 이유

GitHub Issues API는 title, body, labels, assignees를 포함한 issue 생성을 제공하며 fine-grained token의 Issues write 권한으로 제한할 수 있다. 개발 작업의 실제 결과인 branch, PR, CI와 가장 가까운 원장이다.

## Google Calendar와 ICS를 함께 두는 이유

Google Calendar의 `events.insert`는 start/end를 기반으로 event를 생성한다. 하지만 OAuth 구성은 개인 MVP에서 가장 복잡한 요소다. 따라서 Google 연결 전에도 즉시 사용할 수 있도록 표준 ICS 파일을 fallback으로 제공한다.

## Activepieces를 넣지 않은 이유

오픈소스 자동화 엔진은 훌륭하지만 다음 운영 요소를 추가한다.

- 별도 서버와 업데이트
- webhook 보안
- credential 관리
- workflow 재처리
- Action Hub 승인 상태와의 이중 추적

동일한 자동화가 반복된다는 운영 데이터가 생긴 후에만 추가한다.

## Plane을 기본에서 제외한 이유

현재 사용자의 주요 개발 흐름은 GitHub에 존재한다. Plane을 추가하면 작업과 issue를 동기화해야 한다. 비개발 인력이 늘거나 고객용 포트폴리오·roadmap이 필요할 때 도입한다.

## 재평가 규칙

분기별로 다음 질문만 확인한다.

1. 사용자가 외부 앱을 다시 입력하고 있는가?
2. Action Hub에서 반복적으로 고치는 필드는 무엇인가?
3. GitHub를 사용하지 못하는 협업자가 실제로 있는가?
4. 자동화 엔진 없이는 처리할 수 없는 반복 흐름이 주 5회 이상인가?
5. 네이티브 앱이 없어서 입력을 포기한 사례가 있는가?

증거가 없으면 제품을 추가하지 않는다.

## v0.7.0 추가 조사 결과

| 요구 | 기존 제품 검토 | 최종 결정 |
|---|---|---|
| 자동 시간 배치 | Reclaim, Akiflow, Motion | Action Hub 자체 Scheduler 미개발. Decision만 제공 |
| 수동 일일 계획 | Sunsama, Akiflow | 기존 UX를 우선 검증 |
| 오픈소스 집중·시간추적 | Super Productivity | 개발 집중 계층 후보, Todoist 원장 대체는 보류 |
| 회의 Action 추출 | Fireflies | 전사 미개발, Webhook/GraphQL Intake만 개발 |
| 이메일 작업화 | Todoist Gmail/Outlook Add-on | Mail Client 미개발 |
| 코딩 Agent | Codex Action, Claude Code Action, Copilot Agent | 공통 GitHub Workflow Adapter만 개발 |
| 스케줄 최적화 | Google OR-Tools | 기존 Planner 실패가 입증될 때만 도입 |

## 재사용 판단의 결과

v0.7.0에서 새로 만든 것은 “또 하나의 관리 화면”이 아니라 다음 공백이다.

```text
외부 등록 후 상태 회수
사람·AI 실행자 배정
PR/CI/Merge 완료 증거
응답 대기와 후속 확인
기존 Planner 위의 과부하 판단
회의 Action의 승인형 Intake
반복 수정의 승인형 Rule
```

이 기능들은 개별 Todo·Calendar·GitHub·회의 도구 안에서는 하나의 흐름으로 제공되지 않으므로 Action Hub의 독자 개발 범위로 유지한다.
