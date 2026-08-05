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

## 12. Master Worker 역채널 (`worker-sync`, CARD B-01 / B-01b)

`master-worker` Route가 `kind: local_webhook`으로 설정되면 `LocalWebhookWorker`가 GitHub Workflow 대신 로컬 JM-AI Master Worker(MW)에 `POST /api/v1/intakes`로 Goal Intake만 생성한다(§4~§5의 GitHub Workflow 계약과는 별개 경로). MW는 완료를 Action Hub로 통지하지 않으므로, 이 경로로 만든 Execution은 기본적으로 `dispatched`에 머문다.

**명령**: `action-hub worker-sync`

- `worker="master-worker"` 이면서 `state="dispatched"`인 Execution만 대상으로 한다.
- `dispatch_id`(형식 `mw-intake-{intakeId}`)에서 intake id를 추출하고, MW의 전용 진행 상태 조회 라우트를 우선 사용한다: `GET /api/v1/intakes/{intakeId}` (MW commit `a46c988`, `docs/API.md` "Intake progress lookup"). 응답 `data`는 `{intakeId, state, boundProjectId?, objectiveId?, objectiveState?, updatedAt}`이며, `objectiveId`/`objectiveState`는 Intake가 아직 Objective로 승격되지 않았으면 **키 자체가 없다**(null이 아님 — MW `getIntakeStatus`가 `objective?.id`/`objective?.state`를 spread하고 `JSON.stringify`가 `undefined` 값 키를 통째로 제거하기 때문). 이 모듈은 반드시 `"objectiveId" in data`로 존재 여부를 판단한다.
- MW 인증은 `LocalWebhookWorker`와 동일한 `worker_routes.master-worker.baseUrl`(loopback 전용) + `credentialFile`(0600, `{"token": ...}`)을 재사용한다. 별도 자격증명 체계를 두지 않는다.
- **Owner 명시 실행 전용**: 자동 백그라운드 폴러가 아니다. `worker-once`/`action-hub-worker`의 정기 루프에 포함되지 않으며, Owner가 CLI를 직접 실행할 때만 동작한다.

**구버전 MW 호환(자동 폴백)**: `GET /intakes/{id}`가 `404`를 반환하면(구버전 MW에 이 라우트가 없는 경우) 이 모듈이 원래 쓰던 감사 로그 경로로 자동 폴백한다: `GET /api/v1/audit?objectType=intake&objectId=<id>&result=success&limit=200`, 감사 로그의 가장 최근 status-relevant `action`(`create`/`analyze`/`bind`/`discard`)으로 상태를 판단한다. 폴백이 발생했다는 사실은 항상 해당 outcome의 `reason`에 `"fell back to legacy audit route (MW intake status route returned 404): ..."` 형태로 기록된다. 404가 아닌 다른 오류(인증 실패, 형식 오류 등)는 폴백하지 않고 바로 fail-closed 처리한다 — 신규 라우트가 도달 가능한데 응답이 이상한 경우까지 감사 로그로 넘기지 않기 위함이다.

상태 매핑 1) **Objective가 아직 없을 때** (`"objectiveId" not in data`) — MW Intake 상태(`packages/contracts/src/types.ts` `IntakeDraft.status`) 기준:

| MW intake `state` | Execution 상태 |
|---|---|
| `bound` | `running` (Objective가 생기기 전까지 가장 강한 전진 신호) |
| `discarded` | `failed` (`execution.error = "MW intake was discarded"`) |
| `draft` / `analyzed` | 변경 없음(`dispatched` 유지) |

상태 매핑 2) **Objective가 생성된 뒤** (`"objectiveId" in data`) — MW Objective 상태(`packages/contracts/src/types.ts` `ObjectiveState`, 전이 그래프는 `packages/core/src/state-machines.ts` `objectiveTransitions`로 실측 확인, 2026-08-05):

| MW `objectiveState` | Execution 상태 | 비고 |
|---|---|---|
| `captured`/`identified`/`scoped`/`compiled`/`planned`/`awaiting_approval`/`executing`/`verifying`/`resolving`/`packaging` | `running` | 아직 진행 중 |
| `delivered` | `completed` | 릴리스 완료 |
| `closed` | `completed` | delivered 이후 최종 아카이브, 성공 결과로 취급 |
| `blocked` | `human_review` | Owner/human 개입 필요 (AH가 GitHub check-suite 실패에 쓰는 것과 동일한 의미) |
| `cancelled` | `failed` | 종결, `execution.error = "MW objective was cancelled"` |
| `paused` | 변경 없음 | Owner가 명시적으로 일시정지(체크포인트)한 것으로, 전진/완료 신호가 아니며 재개 시 원래 상태로 돌아가므로 AH 쪽 상태를 덮어쓰지 않는다 |
| 위 목록에 없는 값(향후 MW가 추가할 수 있는 상태) | 변경 없음 | fail-closed — 추측하지 않고 원문 값을 `reason`에 남긴다 |

`objectiveId`는 있는데 `objectiveState`가 문자열이 아니거나(예: `null`) 매핑표에 없는 값이면 동일하게 fail-closed(변경 없음 + 사유 기록)로 처리한다.

**알려진 한계**: `GET /intakes/{id}`는 MW 문서상 "목표 본문이나 후보 스코어링을 노출하지 않고 진행 상태만" 반환하도록 의도적으로 최소화되어 있다. Objective의 개별 WorkItem/Run/Release 단위 진행 상황은 여전히 이 경로로 보이지 않고, 위 표의 굵은 단위(Objective 전체 lifecycle 상태) 로만 관찰 가능하다.

**Fail-closed**: MW 도달 불가, 401, (폴백하지 않는) 형식 오류 등은 Execution 상태를 그대로 두고 사유만 기록한다. 개별 Execution 실패가 배치 전체를 중단시키지 않는다. CLI는 하나 이상 실패가 있으면 종료 코드 1을 반환한다(요약 JSON은 성공 여부와 무관하게 stdout에 출력).
