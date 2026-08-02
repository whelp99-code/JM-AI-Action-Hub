# Hermes 구축 작업지시서 — JM-AI Action Hub v0.7.0

## 1. 목표

`JM-AI Action Hub v0.7.0`을 별도 경로에 구축하고, 기존 v0.1 데이터가 있으면 백업·마이그레이션한다. 최초에는 dry-run으로 검증한 뒤 Todoist → GitHub → Google Calendar → Fireflies 순으로 Live 인수한다.

## 2. 절대 금지

- 기존 프로젝트·DB·`.env`를 백업 없이 덮어쓰지 말 것
- Token, API Key, Webhook Secret, Refresh Token을 Git에 기록하지 말 것
- 최초 검증 전에 `ACTION_HUB_EXECUTION_MODE=live`로 전환하지 말 것
- 8787 포트를 인터넷에 직접 노출하지 말 것
- API와 Worker가 동시에 Migration을 실행하도록 구성하지 말 것
- 자동 Merge·운영 배포·고객 발송 기능을 추가하지 말 것
- 자체 Todo·Calendar·Kanban을 추가하지 말 것

## 3. 패키지와 무결성

```bash
sha256sum -c SHA256SUMS-jm-ai-action-hub-v0.7.0.txt --ignore-missing
unzip jm-ai-action-hub-v0.7.0.zip
cd jm-ai-action-hub
```

macOS에서는 다음을 사용할 수 있다.

```bash
shasum -a 256 -c SHA256SUMS-jm-ai-action-hub-v0.7.0.txt
```

## 4. 기존 v0.1 데이터가 있는 경우

```bash
cd 기존_jm-ai-action-hub
./scripts/backup.sh
```

새 소스와 환경을 준비한 뒤:

```bash
./scripts/upgrade.sh
```

확인:

```bash
./.venv/bin/action-hub check
./.venv/bin/alembic current
curl http://127.0.0.1:8787/readiness
```

상세 절차는 `docs/19_UPGRADE_V010_TO_V070_KR.md`를 따른다.

## 5. 신규 로컬 구축

```bash
./scripts/bootstrap.sh
cp -n .env.example .env
./scripts/run.sh
```

별도 터미널:

```bash
./scripts/run-worker.sh
```

권장 설정:

```dotenv
ACTION_HUB_APP_ENV=production
ACTION_HUB_API_KEY=<32자 이상 임의 값>
ACTION_HUB_EXECUTION_MODE=dry_run
ACTION_HUB_WORKER_INLINE=false
ACTION_HUB_RUN_MIGRATIONS=true
```

Worker 프로세스에서는 Migration을 실행하지 않는다.

## 6. Docker/PostgreSQL 구축

```bash
cp .env.example .env
python3 scripts/generate_api_key.py
# 생성 값을 .env에 반영

docker compose \
  -f docker-compose.yml \
  -f docker-compose.postgres.yml \
  up -d --build
```

검증:

```bash
docker compose ps
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/readiness
```

API와 Worker 로그에서 Token·Secret이 출력되지 않는지 확인한다.

## 7. 자동 검증

```bash
./scripts/verify.sh
```

Ruff 설치가 차단된 환경에서는 다음을 최소 수행하고, Ruff 미실행 사실을 보고한다.

```bash
PYTHONPATH=. python -m pytest -W error --cov=action_hub --cov-fail-under=80
python -W error -m compileall -q action_hub tests
node --check action_hub/web/app.js
node --check action_hub/web/share-target.js
```

기대 기준: 53 tests passed, coverage 80% 이상.

## 8. PWA·dry-run 인수

1. `/` 접속
2. PWA 설정에 Action Hub API Key 저장
3. 복합 자연어 입력
4. 일정·Todo·GitHub 분리 확인
5. 모호한 일정의 검토 차단 확인
6. 승인·실행 후 Outbox/등록 상태 확인
7. ICS 보호 다운로드 확인
8. `/api/v1/connectors/status?probe=true` 확인
9. `/api/v1/control/run-once` 확인
10. Today 화면의 가용량·위험·AI 후보·Follow-up 확인

## 9. Provider별 Live 인수 순서

### 9.1 Todoist

- 최소 권한 Token과 Webhook App Secret 설정
- 테스트 프로젝트 작업 1개 등록
- Todoist에서 완료·미완료
- Action Hub 상태 전환과 Delivery 기록 확인

### 9.2 GitHub

- 테스트 저장소로 제한한 Fine-grained Token 또는 GitHub App
- Issues, Pull requests, Workflow runs, Check suites Webhook 등록
- Webhook Secret 설정
- Issue 등록·close/reopen 확인
- 테스트 Worker Workflow를 통해 PR·Check·Merge 확인

### 9.3 Google Calendar

- 단기 Access Token 또는 Refresh Token Broker 설정
- 테스트 Calendar에 일정 1개 등록
- 401 갱신과 중복 Event ID 동작 확인

### 9.4 Fireflies

- API Key와 Webhook Secret 설정
- `meeting.summarized`를 Action Hub로 전달
- Meeting Intake와 Draft Plan 생성 확인
- 외부 원장에는 승인 전 쓰이지 않는지 확인

## 10. 네트워크·보안

권장 노출 순서:

```text
Tailscale/WireGuard
→ HTTPS Reverse Proxy
→ Action Hub API
```

Nginx 예시는 `deploy/nginx/action-hub.conf`를 사용한다. DB 포트는 외부에 공개하지 않는다.

## 11. 운영 등록

- API와 Worker systemd/Compose 자동 시작
- 매일 Backup, 주기적 복구 시험
- `/health`, `/readiness`, failed Outbox, failed Webhook, Sync Conflict 모니터링
- Provider Token 만료·Webhook Delivery 실패 알림
- PostgreSQL 사용 시 별도 `pg_dump` 정책

## 12. 최종 보고 형식

```text
설치 경로:
버전/Commit:
접속 URL:
실행 방식: local / Docker / systemd
DB: SQLite / PostgreSQL
Migration Head:
API 상태:
Worker 상태:
Execution mode:
Todoist Live/Webhook:
GitHub Live/Webhook/Workflow:
Google OAuth/Calendar:
Fireflies Webhook/GraphQL:
자동 테스트/coverage:
PWA 실제 기기:
백업 경로·복구 시험:
잔여 이슈:
```
