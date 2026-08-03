# v0.9.0 알려진 제약과 운영 경계

## 현재 제약

### 단일 사용자 관리 경계

서버는 개인 사용을 위한 단일 관리자 API Key 모델이다. 사용자별 로그인, 조직, RBAC, tenant 분리와 감사 주체 검증은 구현 범위 밖이며, 외부 공개 전에 OIDC/OAuth와 tenant별 secret 경계를 별도 설계해야 한다.

### 네이티브 iOS 동반 앱

native iOS v0.2.1은 QR 페어링, 기기별 scope와 회전형 refresh token, Capture, Focus, Live Activity, Widget, App Intent를 제공한다. 앱의 통상 새로고침은 full refresh이며 서버의 delta endpoint와 cursor는 호환성 계약으로 남아 있지만 iOS 앱은 이를 저장하거나 해석하지 않는다.

오프라인 Capture는 App Group의 durable queue에 보관된다. 서버가 `failed` 영수증을 연속 5회 반환하면 해당 record는 dead-letter로 이동하며, transport 예외는 retry count를 올리지 않는다. 사용자는 Settings > 오프라인 수집 진단에서 `모두 복원` 또는 확인 대화상자 뒤 `모두 삭제`를 실행하며, 자동 삭제는 없다.

### 보안 플래그와 외부 수신

관리 API는 모든 환경에서 secure `X-Action-Hub-Key`가 필요하다. `ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS=false`가 기본값이며, provider signing secret이 없을 때 unsigned 수신은 production에서 항상 거부되고 development/test에서 이 플래그를 명시적으로 켠 경우에만 허용된다. unsigned delivery는 queue 처리 시점에도 현재 정책을 다시 확인한다.

모바일 bearer 인증은 별도 `ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET`을 우선 사용한다. development에서만 secure admin key로 HKDF 파생이 가능하며, production에서는 별도 secret이 필요하다. 누락·template placeholder·admin key 재사용은 claim, refresh, bearer 요청을 credential 처리 전에 503으로 차단한다.

### 외부 Provider와 기기 인수

Todoist, GitHub, Google Calendar, Fireflies의 mock/contract 경로와 webhook 방어는 코드와 자동 테스트 범위에 있다. 실제 계정 token, webhook 등록, OAuth consent, reverse proxy/WAF, TLS, APNs `.p8`, Apple signing, TestFlight와 실기기 수신은 운영자 인수가 필요하다.

### 통합·자동화의 현재 제한

Google Calendar는 조회와 reconciliation을 사용하며 Calendar Push Channel·Subscription은 구현하지 않았다. Todoist·GitHub·Fireflies webhook endpoint와 서명 검증은 제공하지만, provider app 생성·webhook 등록과 실제 credential의 live 인수는 계정 소유자가 각 provider console에서 수행해야 한다.

AI worker route는 Action Hub 안에 Codex·Claude Code·Copilot·Orca·Hermes를 설치하거나 실행하는 기능이 아니다. 설정된 repository의 기존 GitHub Actions workflow와 그 workflow가 소유한 secret·권한을 호출하므로, route별 workflow/secret 준비가 필요하다.

Waiting-for와 follow-up 상태는 관리하지만 Gmail/Outlook/IMAP mailbox를 읽어 회신을 자동 감지하지 않는다. 규칙 parser는 일반적인 날짜·시간·action 추출을 지원하지만 장문의 대명사 해소, 조건부 계약, 여러 메시지의 전후 문맥은 제한적이며, `hybrid`/`llm` parser mode는 입력을 외부 LLM endpoint로 보낼 수 있으므로 비용·전송 경계를 운영자가 확인해야 한다.

Weekly ROI의 `estimated_minutes_saved`는 structured capture 같은 event에서 기록한 추정 metric이다. 자동 stopwatch, browser activity, calendar 실제 소요시간 수집으로 측정한 값이 아니다.

### 저장소와 배포 경계

SQLite WAL은 개인용 API와 worker를 위한 기본값이다. 다중 host·고빈도 webhook·여러 worker로 확장할 경우 PostgreSQL과 운영 관측을 검증해야 한다. source code와 로컬 정적 검사만으로 production deploy, 백업 복구, 외부 credential 인증, Apple device/build 검증을 주장하지 않는다.

## 의도적으로 제외한 기능

```text
자체 Todo/Kanban
자체 Calendar 월간 화면
자체 회의 녹음·전사
자체 이메일 Client
자체 코딩 Agent
범용 Workflow Builder
무승인 자동 Merge/배포
무승인 외부 메시지 발송
다중 Tenant/RBAC
```

## 운영자 점검 순서

1. `ACTION_HUB_API_KEY`와 모바일 signing secret을 별도로 secure 값으로 설정한다.
2. unsigned webhook이 필요하면 development/test에서만 명시적으로 opt-in하고, production에서는 provider signing secret을 설정한다.
3. `action-hub check --json`으로 구성을 확인하고 provider와 mobile device를 별도 인수한다.
4. 변경 전 backup/restore rehearsal과 `make docs-check`를 실행한다. 실제 production acceptance는 외부 credential과 기기 환경이 있어야 완료된다.

## 후속 착수 조건

| 후속 기능 | 착수 조건 |
|---|---|
| OIDC/RBAC | 실제 사용자 2명 이상 또는 외부 공개 |
| PostgreSQL 전환 | 동시 worker 2개 이상, lock 지연 또는 다중 host |
| Calendar Push | reconciliation 지연으로 일정 오류가 반복 |
| Gmail/Outlook response adapter | waiting-for 수동 종료 누락이 반복 |
| OCR·첨부 수집 | 이미지/문서 기반 Capture가 반복 |
| App Attest/MDM | 외부 사용자 또는 조직 보안 요구 상승 |
