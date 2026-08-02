# JM-AI Action Hub v0.1.0 → v0.7.0 업그레이드 가이드

## 1. 사전 조건

- 기존 프로젝트 디렉터리 접근 가능
- `.env`와 `data/action_hub.db` 백업 권한
- Python 3.12 이상
- 업그레이드 동안 API와 Worker 중지

## 2. 업그레이드 전 백업

```bash
cd /path/to/jm-ai-action-hub
./scripts/backup.sh
```

백업 파일은 `umask 077`로 생성되며 `.env`가 포함될 수 있으므로 외부 공유 금지다.

수동 백업:

```bash
cp -a data data.backup-$(date +%Y%m%d-%H%M%S)
cp .env .env.backup-$(date +%Y%m%d-%H%M%S)
```

## 3. 서비스 중지

systemd:

```bash
sudo systemctl stop jm-ai-action-hub-worker
sudo systemctl stop jm-ai-action-hub
```

Docker:

```bash
docker compose down
```

## 4. 새 소스 배치

새 ZIP을 별도 디렉터리에 풀고 기존 `.env`와 `data`를 복사한다.

```bash
unzip jm-ai-action-hub-v0.7.0.zip -d /opt/jm-ai-action-hub-v0.7.0
cp /old/.env /opt/jm-ai-action-hub-v0.7.0/.env
cp -a /old/data /opt/jm-ai-action-hub-v0.7.0/
cd /opt/jm-ai-action-hub-v0.7.0
```

기존 디렉터리에서 Git Pull 방식으로 갱신했다면 다음을 실행한다.

```bash
./scripts/upgrade.sh
```

## 5. 환경변수 병합

기존 `.env`를 유지하고 `.env.example`의 신규 항목을 추가한다.

필수 권장:

```dotenv
ACTION_HUB_RUN_MIGRATIONS=true
ACTION_HUB_WORKER_INLINE=false
ACTION_HUB_OUTBOX_MAX_ATTEMPTS=5
ACTION_HUB_PROCESSING_LOCK_TIMEOUT_SECONDS=300
ACTION_HUB_RECONCILIATION_INTERVAL_SECONDS=300
```

Webhook을 사용할 때:

```dotenv
ACTION_HUB_TODOIST_CLIENT_SECRET=
ACTION_HUB_GITHUB_WEBHOOK_SECRET=
ACTION_HUB_FIREFLIES_WEBHOOK_SECRET=
```

## 6. Python 패키지 업그레이드

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[dev]'
```

## 7. DB 마이그레이션

```bash
.venv/bin/action-hub migrate
```

v0.1.0은 `alembic_version` 없이 SQLAlchemy가 직접 테이블을 생성했다. v0.7.0은 다음 절차를 자동 수행한다.

1. v0.1 기본 테이블 존재 확인
2. `0001_initial_v010`으로 Stamp
3. `0002_action_control_loop` 적용
4. `0003_operational_hardening` 적용

검증:

```bash
.venv/bin/action-hub check
```

정상 예:

```text
version=0.7.0
database=ready
schema=0003_operational_hardening
```

## 8. API·Worker 실행

터미널 1:

```bash
.venv/bin/action-hub serve
```

터미널 2:

```bash
.venv/bin/action-hub-worker
```

또는 Docker Compose/systemd를 사용한다.

## 9. Dry-run 인수

```bash
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/readiness
```

API Key가 설정되어 있다면:

```bash
export KEY='...'
curl -H "X-Action-Hub-Key: $KEY" \
  'http://127.0.0.1:8787/api/v1/connectors/status?probe=true'
```

다음 흐름을 확인한다.

```text
입력 → 승인 → 실행 → queued/registered
→ control run-once
→ Today/Weekly report
```

## 10. Live 전환 순서

1. `dry_run` 유지
2. Todoist Token만 설정하고 테스트 작업 1건
3. Todoist Webhook 서명/완료 1건
4. GitHub 테스트 Repository Issue 1건
5. GitHub Workflow/PR 1건
6. Google Calendar 테스트 Calendar 1건
7. Fireflies 테스트 회의 1건
8. 그 후 `ACTION_HUB_EXECUTION_MODE=live`

서비스별로 순차 활성화하며 한 번에 모든 Connector를 Live로 바꾸지 않는다.

## 11. 롤백

1. API·Worker 중지
2. 신규 data 디렉터리 보존
3. 업그레이드 전 backup 복구
4. v0.1.0 소스와 환경으로 실행

```bash
./scripts/restore.sh backups/action-hub-YYYYmmdd-HHMMSS.tar.gz
```

DB downgrade는 새 데이터 손실 위험이 있으므로 권장하지 않는다. 백업 복구가 기본 롤백 방식이다.

## 12. 주의사항

- v0.7.0은 등록 상태와 완료 상태를 분리하므로 v0.1 UI의 “completed” 의미와 다르다.
- 외부 Webhook URL은 HTTPS로 공개되어야 한다.
- SQLite로 API와 Worker를 분리할 수 있으나 지속 운영은 PostgreSQL을 권장한다.
- AI Worker Route는 기존 GitHub Workflow가 준비된 경우에만 Live Dispatch가 가능하다.
- v0.1의 기존 Action은 자동으로 ExternalState를 소급 생성하지 않는다. 새 실행 또는 Reconciliation 대상부터 Mirror가 생성된다.
