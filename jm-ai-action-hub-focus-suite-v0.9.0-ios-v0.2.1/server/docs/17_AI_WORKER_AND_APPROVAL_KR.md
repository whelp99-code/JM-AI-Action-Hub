# Human–AI Worker Router와 승인 경계

## 1. 설계 목적

Action Hub는 코딩 에이전트를 새로 만들지 않는다. 이미 존재하는 Codex·Claude Code·GitHub Copilot·Orca·Hermes·Master Worker의 실행 Workflow를 호출하고 결과를 통합 추적한다.

```text
Action Hub = 배정·승인·추적
Existing Worker = 실제 코드/문서 실행
GitHub = Issue·Branch·PR·CI 원장
```

## 2. 실행자

| executor | 의미 |
|---|---|
| human | 사람이 직접 수행 |
| ai | AI Worker가 초안 또는 구현 |
| hybrid | AI 실행 후 사람 검토가 필수 |
| external | 고객·직원·협력사 응답 대기 |

## 3. Dispatch 조건

기본적으로 다음을 모두 만족해야 한다.

- Action이 존재한다.
- `executor`가 `ai` 또는 `hybrid`다.
- 구조적 검토 오류가 없다.
- Action이 승인·등록·재검토 가능 상태다.
- Repository 또는 Worker Route가 `owner/repo` 형식이다.
- 같은 Action에 활성 WorkerExecution이 없다.

`force`는 관리자성 API 동작이며 일반 PWA 흐름에서는 사용하지 않는다.

## 4. Worker Route

```json
{
  "codex": {
    "repository": "owner/repo",
    "workflow": "codex.yml",
    "ref": "main"
  },
  "claude": {
    "repository": "owner/repo",
    "workflow": "claude.yml",
    "ref": "main"
  }
}
```

Provider별 SDK를 Action Hub에 직접 넣지 않고 GitHub Actions를 공통 Adapter로 사용한다.

## 5. Workflow 입력 계약

```json
{
  "ref": "main",
  "inputs": {
    "action_id": "uuid",
    "title": "작업 제목",
    "description": "완료 기준 포함 설명",
    "source_fragment": "원문 근거",
    "issue_number": "42",
    "issue_url": "https://github.com/.../issues/42",
    "repository": "owner/repo",
    "worker": "codex",
    "completion_evidence_required": "true"
  }
}
```

Workflow는 Branch, Run name, PR body 중 하나 이상에 `action_id` 또는 `Action-Hub-ID`를 보존해야 한다.

## 6. 상관관계 규칙

강한 상관키 우선순위:

1. Workflow Run ID가 기존 Execution에 연결됨
2. Run name/display title/head branch의 Action UUID
3. PR body/title/head branch의 Action UUID
4. PR body의 linked Issue 번호
5. 같은 Repository에 활성 Execution이 정확히 1개

활성 Execution이 2개 이상인데 강한 상관키가 없으면 임의 연결하지 않는다.

## 7. 상태 전이

```text
queued
  ↓ workflow_dispatch
 dispatched
  ↓ workflow_run/check_suite
 running
  ├→ failed
  ├→ needs_input
  └→ human_review
         ↓ 사람이 검토·승인
       PR merged
         ↓
      completed
```

## 8. 완료 증거

개발 Action의 권장 완료 증거:

- PR URL
- Merge timestamp
- Check/Workflow 상태
- 해당 Issue/Repository

현재 구현은 PR Merge URL을 `completion_evidence`에 기록한다.

## 9. 승인 경계

### 반드시 사람 승인

- 외부 Issue 생성
- AI Worker Dispatch
- Worker 결과 검토
- PR Merge
- 운영 배포
- 고객·협력사 메시지 발송
- 데이터 삭제·결제·계약

### 자동 처리 가능

- Webhook 서명 검증
- 상태 Mirror 갱신
- Retry
- Follow-up Due 표시
- 주간 지표 계산
- 승인된 개인 규칙의 안전 필드 적용

## 10. 실패 처리

| 실패 | 처리 |
|---|---|
| Workflow dispatch HTTP 오류 | Outbox Retry |
| 잘못된 Route | Dispatch 409 |
| 활성 Worker 중복 | 기존 Execution 반환 |
| Workflow failed | Action failed, 오류 기록 |
| PR closed without merge | Action failed |
| 상관키 불명확 | Webhook unmatched |
| 늦은 CI 이벤트 | Merge 완료 상태 보존 |

## 11. 기존 Worker 예시

Action Hub는 각 Provider Workflow의 내부 명령을 고정하지 않는다. 조직의 기존 보안 정책과 Agent 설정을 그대로 사용한다.

```yaml
name: action-hub-codex
on:
  workflow_dispatch:
    inputs:
      action_id: {required: true, type: string}
      title: {required: true, type: string}
      description: {required: true, type: string}
      issue_number: {required: false, type: string}
run-name: "Action Hub ${{ inputs.action_id }}"
```

Workflow 내부에서는 최소 권한, 제한된 Secret, 테스트, PR 생성까지만 수행하고 자동 Merge를 하지 않는 구성이 권장된다.
