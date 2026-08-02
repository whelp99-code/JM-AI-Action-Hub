# v0.7.0 외부 Connector와 Webhook 설정

## 1. 공통 안전 절차

처음에는 반드시 다음을 유지한다.

```dotenv
ACTION_HUB_EXECUTION_MODE=dry_run
```

1. API/Worker 실행
2. `GET /api/v1/connectors/status?probe=true`
3. 입력·승인·실행 Payload 검토
4. 서비스 하나씩 Token 설정
5. 테스트 원장 1건 Live 인수
6. Webhook 서명과 완료 상태 확인
7. 다음 Connector 활성화

모든 Connector를 한 번에 Live로 전환하지 않는다.

## 2. Todoist

### API

```dotenv
ACTION_HUB_TODOIST_TOKEN=
ACTION_HUB_TODOIST_DEFAULT_PROJECT_ID=
```

Action Hub는 작업 본문에 `Action-Hub-ID` Marker를 남겨 응답 유실 후 기존 작업을 회수한다.

### Webhook

```dotenv
ACTION_HUB_TODOIST_CLIENT_SECRET=
```

URL:

```text
https://YOUR_HOST/api/v1/webhooks/todoist
```

권장 이벤트:

```text
item:added
item:updated
item:completed
item:uncompleted
item:deleted
```

Production에서는 Secret 미설정 또는 HMAC 불일치 요청을 거부한다.

## 3. GitHub

### Fine-grained Token

Repository를 필요한 저장소로 제한한다. 필요한 기능에 따라 최소 권한을 부여한다.

- Issues: Read and write
- Actions: Read and write — Workflow dispatch 사용 시
- Pull requests: Read — 상태 조회 또는 관련 API 확장 시
- Metadata: Read

```dotenv
ACTION_HUB_GITHUB_TOKEN=
ACTION_HUB_GITHUB_DEFAULT_REPO=
ACTION_HUB_PROJECT_ROUTES_JSON={"proof-graph":"owner/Proof-Graph"}
```

기본 저장소는 비우고 프로젝트 라우팅 또는 입력의 `repo:owner/repository`를 권장한다.

### Webhook

```dotenv
ACTION_HUB_GITHUB_WEBHOOK_SECRET=
```

URL:

```text
https://YOUR_HOST/api/v1/webhooks/github
```

Content type은 `application/json`, Secret은 충분히 긴 난수로 설정한다.

수신 이벤트:

```text
Issues
Pull requests
Workflow runs
Check suites
Ping
```

### AI Worker Workflow

```dotenv
ACTION_HUB_WORKER_ROUTES_JSON={"codex":{"repository":"owner/repo","workflow":"codex.yml","ref":"main"}}
```

Workflow의 Run name/Branch/PR Body에 Action UUID 또는 `Action-Hub-ID`를 유지한다.

## 4. Google Calendar

### Access Token 단기 테스트

```dotenv
ACTION_HUB_GOOGLE_CALENDAR_ACCESS_TOKEN=
ACTION_HUB_GOOGLE_CALENDAR_ID=primary
```

### Refresh Token 지속 운영

```dotenv
ACTION_HUB_GOOGLE_OAUTH_CLIENT_ID=
ACTION_HUB_GOOGLE_OAUTH_CLIENT_SECRET=
ACTION_HUB_GOOGLE_OAUTH_REFRESH_TOKEN=
ACTION_HUB_GOOGLE_OAUTH_TOKEN_URL=https://oauth2.googleapis.com/token
```

Access Token은 메모리에서만 캐시되고 DB에는 저장되지 않는다. 401 응답 시 한 번 강제 갱신 후 재시도한다.

Google OAuth를 구성하지 않으면 Local ICS를 사용한다.

## 5. Local ICS

설정 없이 동작한다.

```text
data/exports/<action-id>.ics
/api/v1/exports/<action-id>.ics
```

다운로드 API는 Action Hub API Key로 보호되고 `Cache-Control: private, no-store`를 사용한다.

ICS는 Calendar 동기화가 아니라 표준 파일 Export이므로 일정 수정 후 다시 가져와야 한다.

## 6. Fireflies

```dotenv
ACTION_HUB_FIREFLIES_API_KEY=
ACTION_HUB_FIREFLIES_WEBHOOK_SECRET=
ACTION_HUB_FIREFLIES_GRAPHQL_URL=https://api.fireflies.ai/graphql
```

Webhook URL:

```text
https://YOUR_HOST/api/v1/webhooks/fireflies
```

대상 이벤트:

```text
meeting.summarized
```

Action Hub는 회의 ID로 Transcript Summary의 Action Items를 조회한 뒤 Draft Plan을 생성한다. 외부 Task로 즉시 자동 등록하지 않는다.

## 7. LLM Parser

```dotenv
ACTION_HUB_PARSER_MODE=hybrid
ACTION_HUB_LLM_BASE_URL=https://YOUR-ENDPOINT/v1
ACTION_HUB_LLM_API_KEY=
ACTION_HUB_LLM_MODEL=
```

- OpenAI-compatible `/chat/completions` 필요
- JSON 구조화 응답 사용
- `hybrid`는 LLM 오류 시 Rule Parser로 Fallback
- 민감 원문 외부 전송 여부를 운영자가 승인

## 8. MCP

```bash
pip install -e '.[mcp]'
export ACTION_HUB_MCP_BASE_URL=http://127.0.0.1:8787
export ACTION_HUB_API_KEY=...
action-hub-mcp
```

설정 예: `examples/mcp_config.json`

## 9. 진단

```bash
curl -H "X-Action-Hub-Key: $KEY" \
  'https://YOUR_HOST/api/v1/connectors/status?probe=true'

curl https://YOUR_HOST/readiness
```

Worker 1회 처리:

```bash
action-hub-worker --once --reconcile
```
