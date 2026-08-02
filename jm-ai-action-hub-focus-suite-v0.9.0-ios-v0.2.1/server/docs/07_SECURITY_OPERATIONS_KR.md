# 운영·보안 계획

## 운영 전 P0 체크리스트

- [ ] `.env`의 API 키를 32자 이상의 임의 값으로 변경 — placeholder나 짧은 키는 production API에서 503으로 거부
- [ ] `ACTION_HUB_APP_ENV=production`
- [ ] HTTPS 또는 VPN 뒤에서만 노출
- [ ] 외부 토큰에 최소 권한 적용
- [ ] `ACTION_HUB_EXECUTION_MODE=dry_run`으로 최초 검증
- [ ] 테스트 항목 하나씩 Todoist·GitHub·Calendar live 검증
- [ ] 백업 경로와 복구 테스트
- [ ] 로그에 `.env`나 token이 출력되지 않는지 확인
- [ ] 방화벽에서 DB 포트 외부 차단
- [ ] ICS export API가 운영 API 키 없이 열리지 않는지 확인

## 비밀정보

저장 위치:

- `.env` 또는 컨테이너 secret
- 운영에서는 Vault/1Password Connect/Kubernetes Secret 권장

금지:

- Git commit
- DB payload
- 감사 로그
- PWA localStorage에 외부 서비스 token 저장

PWA localStorage에는 Action Hub API key만 저장할 수 있다. 공용 기기에서는 저장하지 않는다. ICS 파일은 공개 static 경로가 아니라 API-key 보호 경로에서 내려받는다.

## 권한 최소화

### GitHub

Fine-grained PAT 또는 GitHub App을 사용하고 대상 저장소를 제한한다. 필요한 권한은 Issues write이다. Contents write는 필요 없다.

### Todoist

개인 사용은 personal API token으로 시작할 수 있다. 다중 사용자 제품이 되면 OAuth로 전환한다.

### Google Calendar

사용자의 calendar 쓰기 OAuth scope와 대상 Calendar write access가 필요하다. v0.7.0의 Token Broker는 Refresh Token을 환경변수에서 읽고 Access Token을 프로세스 메모리에만 캐시하며, 401 응답 시 한 번 강제 갱신한다. Token은 DB에 저장하지 않는다.

## 네트워크

권장 순서:

1. Tailscale/WireGuard 사설 접속
2. HTTPS reverse proxy + SSO
3. 인터넷 공개 + Action Hub API key — 최후 선택

Nginx 예시는 `deploy/nginx/action-hub.conf`에 포함한다.

## 데이터 백업

SQLite:

```bash
./scripts/backup.sh
./scripts/restore.sh backups/action-hub-YYYYmmdd-HHMMSS.tar.gz
```

운영 백업 정책:

- 매일 증분 또는 volume snapshot
- 매주 별도 저장소 복사
- 30일 보존
- 월 1회 복구 테스트

PostgreSQL:

- `pg_dump --format=custom`
- 복구는 별도 DB에서 먼저 검증

## 모니터링

최소 지표:

- `/health` 응답
- `/readiness` 상태
- 최근 5분 5xx 수
- connector failure 수
- failed item 체류 시간
- DB 디스크 사용량
- 백업 마지막 성공 시각

## 장애 대응

### Todoist/GitHub API 장애

- Outbox 항목이 retry 또는 failed로 남음
- 다른 Connector와 Action은 계속 처리
- 지수형 재시도 후 수동 `control/run-once` 또는 Worker 재처리
- 응답 유실 시 Action-Hub-ID와 Reconciliation으로 외부 생성 여부 확인

### 잘못 생성

- 외부 원장에서 직접 수정 또는 삭제
- Action Hub audit에서 원문과 payload 확인
- MVP에는 외부 삭제 API를 의도적으로 넣지 않음

### token 유출

1. 즉시 공급자에서 token 폐기
2. `.env` 교체
3. Action Hub API key 교체
4. 감사 로그에서 비정상 실행 확인
5. GitHub/Todoist/Google 활동 로그 검토

## 보안 잔여 과제

다중 사용자로 확장할 때 필요:

- OIDC/OAuth 로그인
- 사용자·조직별 tenant isolation
- RBAC
- token envelope encryption
- CSRF와 session 관리
- 감사 로그 immutable storage
- rate limiting
