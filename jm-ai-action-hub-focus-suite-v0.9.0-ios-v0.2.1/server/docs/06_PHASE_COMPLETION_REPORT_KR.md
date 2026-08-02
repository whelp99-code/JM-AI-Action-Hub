# JM-AI Action Hub v0.7.0 단계별 개발 완료 보고서

- 완료 기준일: 2026-07-29
- 기준선: v0.1.0
- 현재 릴리스: v0.7.0

## 1. 단계별 완료 현황

| 단계 | 구현 내용 | 상태 |
|---|---|---|
| v0.1.1 운영 기반 | Alembic, Transactional Outbox, Retry, 별도 Worker, Connector probe, Google OAuth Broker | 완료 |
| v0.2.0 상태 동기화 | Todoist/GitHub/Fireflies Webhook, HMAC, Delivery 중복 차단, External State, Reconciliation, Conflict | 완료 |
| v0.3.0 Human–AI Router | executor, Worker Registry, GitHub Workflow dispatch, PR/CI/Merge 추적, Human Review | 완료 |
| v0.4.0 Commitment | Waiting-for, Follow-up 만료·응답·후속 연락·해결 | 완료 |
| v0.5.0 Planning | 예상시간, Deadline, Work mode, 가용시간, 버퍼, 과부하, Top·Deferred·AI 후보 | 완료 |
| v0.6.0 Meeting Intake | Fireflies V2 Webhook·GraphQL Action Item·Draft Plan·재처리 | 완료 |
| v0.7.0 Learning & ROI | 개인 규칙 제안·승인·안전 필드, Weekly ROI | 완료 |

## 2. 운영 기반 완료 내용

- v0.1.0의 비-Alembic DB를 자동 감지해 baseline stamp 후 최신 Head로 승격
- 외부 등록 요청과 Outbox를 동일 트랜잭션에 기록
- `pending/retry → processing → completed/failed` 상태와 지수형 재시도
- 다중 Worker 선점과 stale lock 복구
- API와 Worker 프로세스 분리
- Google Refresh Token 기반 Access Token 메모리 갱신
- Connector 설정 상태와 실제 probe 결과 분리

## 3. 폐쇄형 상태 동기화 완료 내용

- Todoist 완료·미완료·수정·삭제 이벤트 수신
- GitHub Issue close/reopen, PR open/ready/merge, Workflow Run, Check Suite 수신
- Fireflies meeting 이벤트 수신
- Provider별 HMAC 검증과 Delivery ID 중복 제거
- 외부 상태 원장과 로컬 Action 상태 연결
- Webhook 누락 보완 Reconciliation
- 404를 데이터 삭제로 단정하지 않고 Sync Conflict로 격리
- PR Merge 이후 늦게 도착한 Workflow/Check 이벤트가 완료 상태를 되돌리지 않음

## 4. Human–AI 실행 완료 내용

- `human`, `ai`, `hybrid`, `external` 실행자 분류
- Codex·Claude·Copilot·Orca·Hermes·Master Worker를 GitHub Workflow Adapter로 재사용
- 동일 Action의 활성 Worker 중복 위임 차단
- Workflow 성공은 `human_review`, PR Merge 확인 후 `completed`
- 강한 Action 상관키가 없을 때 임의 실행 연결 금지
- 자동 Merge·운영 배포·외부 발송 제외

## 5. Follow-up·Planning·Meeting·Learning 완료 내용

- 상대방 응답 대기와 만료 Follow-up 표시
- 응답 수신·후속 연락·다음 확인일·해결 상태
- 일일 가용시간과 보호 Buffer, 과부하, Top 업무, 연기 후보, AI 위임 후보
- Fireflies Action Item을 외부 앱에 직접 쓰지 않고 승인 가능한 Plan으로 변환
- 반복 수정 패턴을 Proposed Rule로 만들고 사용자 승인 후에만 적용
- 안전 필드 allowlist와 주간 실행·지연·대기·AI 위임·절감시간 지표

## 6. UI·API·운영 완료 내용

- 모바일 PWA의 오늘 판단, AI 위임, Follow-up, Connector/Worker 상태
- REST API와 MCP 도구 확장
- `action-hub-worker`, `worker-once`, `/control/run-once`
- Docker Compose API/Worker 분리와 PostgreSQL overlay
- systemd API/Worker 서비스
- Backup, Restore, Upgrade, Verify 스크립트
- CSP·no-store·HSTS·요청 본문 제한·보호된 ICS

## 7. 자동 검증 결과

```text
54 passed
warnings treated as errors
statement coverage >= 80%
Python compile: PASS
JavaScript syntax: PASS
Git diff whitespace: PASS
```

최종 Wheel·HTTP·압축본 검증 결과와 SHA-256은 `docs/20_RELEASE_VERIFICATION_V070_KR.md` 및 배포 Checksum 파일에 기록한다.

## 8. 완료의 정확한 경계

코드와 로컬 통합 검증은 완료했다. 다음은 사용자 계정이나 대상 인프라가 있어야 하는 운영 인수다.

- 실제 Todoist 테스트 프로젝트 생성·완료·미완료 Webhook
- 실제 GitHub 테스트 저장소 Issue·Workflow·PR·Merge
- 실제 Google OAuth·Calendar 이벤트
- 실제 Fireflies Workspace Webhook·Transcript
- Docker daemon과 PostgreSQL 서버 기동
- HTTPS 주소와 실제 iPhone/Android 공유 흐름

따라서 판정은 다음과 같다.

> v0.7.0 소프트웨어 개발과 자동 검증 완료. 외부 Provider는 사용자 자격증명으로 1회 Live 인수 후 활성화한다.
