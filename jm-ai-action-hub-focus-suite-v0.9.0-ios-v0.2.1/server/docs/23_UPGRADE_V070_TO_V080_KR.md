# JM-AI Action Hub v0.7.0 → v0.8.0 업그레이드

## 1. 변경 범위

v0.8.0은 기존 Closed-loop 기능을 삭제하지 않는 Additive Upgrade다.

추가되는 항목:

- Plan/Item `revision`
- Native Mobile Device/Pairing/Auth
- Offline Capture Receipt
- APNs Push Queue
- Mobile API/OpenAPI

## 2. 사전 백업

### SQLite

```bash
./scripts/backup.sh
cp data/action_hub.db data/action_hub-v070-before-v080.db
```

### PostgreSQL

```bash
pg_dump "$ACTION_HUB_DATABASE_URL" > action_hub_v070_before_v080.sql
```

환경변수와 외부 Secret은 별도 보관한다. `.p8`, Provider Token, GitHub/Todoist Token을 백업 ZIP에 넣지 않는다.

## 3. 중지 순서

```text
API 요청 중지
→ Worker 중지
→ DB 백업
→ 소스 교체
→ Migration
→ API 시작
→ Readiness
→ Worker 시작
```

## 4. 설치

```bash
unzip jm-ai-action-hub-server-v0.8.0.zip
cd jm-ai-action-hub-server
python -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e .
```

기존 `.env`에 추가:

```dotenv
ACTION_HUB_MOBILE_ENABLED=true
ACTION_HUB_MOBILE_PUBLIC_BASE_URL=https://YOUR_HOST
ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET=<32자 이상 별도 랜덤값>
ACTION_HUB_MOBILE_REFRESH_REUSE_GRACE_SECONDS=30
```

APNs는 초기 업그레이드에 필수가 아니다.

## 5. Migration

```bash
action-hub migrate
```

예상 Head:

```text
0004_mobile_foundation
```

확인:

```bash
action-hub check --json
```

## 6. 보존 확인

업그레이드 전후 다음을 비교한다.

```sql
SELECT COUNT(*) FROM action_plans;
SELECT COUNT(*) FROM action_items;
SELECT id, title FROM action_items ORDER BY created_at LIMIT 20;
```

새 테이블 확인:

```sql
SELECT name FROM sqlite_master
WHERE type='table' AND name LIKE 'mobile_%';
SELECT name FROM sqlite_master
WHERE type='table' AND name='push_notifications';
```

## 7. Dry-run 인수

```bash
ACTION_HUB_EXECUTION_MODE=dry_run ./scripts/run.sh
```

다른 터미널:

```bash
./scripts/run-worker.sh
python scripts/mobile_http_smoke.py \
  --base-url http://127.0.0.1:8787 \
  --admin-key "$ACTION_HUB_API_KEY"
```

## 8. 첫 iPhone Pairing

Production 공개 주소는 HTTPS여야 한다.

```bash
action-hub mobile-pairing \
  --base-url https://YOUR_HOST \
  --qr-output pairing.svg \
  --print-qr
```

QR은 5분 내 한 번만 사용한다. 사용 후 `pairing.svg`를 안전하게 삭제한다.

## 9. Rollback

Migration Downgrade는 Mobile 테이블과 Revision 컬럼을 제거한다. 운영 데이터가 생성된 뒤에는 단순 Downgrade보다 **백업 DB 복원**을 권장한다.

```text
API/Worker 중지
→ v0.8 DB 격리
→ v0.7 백업 복원
→ v0.7 패키지 복원
→ Readiness 확인
```

## 10. 실제 검증된 업그레이드

릴리스 검증에서는 원본 v0.7.0 소스로 실제 Plan과 Item 2건을 생성한 DB를 v0.8.0 코드로 업그레이드했다.

- 기존 Plan ID 보존
- 기존 Item ID/제목 보존
- `revision=1` 부여
- Alembic Head `0004_mobile_foundation`
- 5개 Mobile/Push 테이블 생성
