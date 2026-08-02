# v0.8.0 → v0.9.0 업그레이드 가이드

## 1. 백업

```bash
./scripts/backup.sh
```

SQLite 사용 시 DB 파일과 `.env`를 별도 보관한다. PostgreSQL은 pg_dump를 수행한다.

## 2. Dry-run 상태 확인

```bash
python -m action_hub.cli status
```

외부 Connector를 실수로 변경하지 않도록 첫 업그레이드는 `ACTION_HUB_EXECUTION_MODE=dry_run`에서 수행한다.

## 3. 패키지 교체

Wheel:

```bash
python -m pip install --upgrade jm_ai_action_hub-0.9.0-py3-none-any.whl
```

Source:

```bash
unzip jm-ai-action-hub-server-v0.9.0.zip
cd jm-ai-action-hub-server-v0.9.0
```

## 4. Migration

```bash
alembic upgrade head
```

기대 Head:

```text
0005_decision_focus_foundation
```

신규 변경은 additive다.

- ActionItem.attention_state 추가, 기본 untriaged
- priority_assessments
- daily_focus_plans
- daily_commitments
- micro_steps
- focus_sessions
- carry_over_decisions

## 5. 설정

`.env` 선택값:

```dotenv
ACTION_HUB_IMPORTANCE_THRESHOLD=60
ACTION_HUB_URGENCY_THRESHOLD=60
ACTION_HUB_BIG3_LIMIT=3
ACTION_HUB_FOCUS_DEFAULT_MINUTES=25
ACTION_HUB_FOCUS_WARNING_PERCENT=80
ACTION_HUB_FOCUS_MAX_MINUTES=240
ACTION_HUB_FOCUS_WEEKLY_WINDOW_DAYS=7
```

## 6. 점검

```bash
python -m pytest -q
python -m compileall -q action_hub tests scripts
python scripts/export_openapi.py --check
```

API:

```text
GET /health
GET /readiness
GET /api/v1/focus/triage
GET /api/v1/focus/matrix
GET /api/v1/focus/commitments
```

## 7. iOS 호환

- 최소 권장 앱: v0.2.1
- 서버 Mobile API major는 v1 유지
- v0.1 앱은 기존 모바일 기능을 계속 사용할 수 있으나 Focus 화면은 없음
- v0.2.1 앱은 server capabilities에서 focus feature를 확인한다

## 8. Rollback

앱 코드만 v0.8.0으로 되돌리는 것은 신규 DB를 모르는 구버전에서 안전하지 않을 수 있다. 문제가 있으면 서비스 중지 후 백업 DB를 복원한다.

```bash
./scripts/restore.sh <backup>
```
