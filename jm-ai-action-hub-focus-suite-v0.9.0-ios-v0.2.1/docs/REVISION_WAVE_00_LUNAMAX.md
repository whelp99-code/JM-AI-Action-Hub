# Wave 00 LunaMax 검증 기반 수정안

## 1. 제출 판정

- 대상: Phase 0 `CARD-00-01`, `CARD-00-02`, `CARD-00-03`
- 독립 검증: Codex `gpt-5.6-luna`, effort `max`, headless session `019fc371-11e2-7563-8d3f-8dbca8c5fa7f`
- 검증 프로세스 raw exit: `0`
- 결과: `PASS_WITH_FINDINGS`
- 결함 수: `MEDIUM 1`, `LOW 1` (`CRITICAL 0`, `HIGH 0`)
- 결론: S1과 S3는 수정 불필요. S2는 신규 ingress뿐 아니라 큐 처리 시점에도 현재 서명 정책을 재검증해야 완전한 fail-closed가 된다.
- 원본 검증 근거: `evidence/lunamax-wave00-verification.md`

이 문서는 수정 제안만 정의한다. 마스터 승인 전 코드, 테스트, 문서를 수정하지 않는다.

## 2. 독립 재현 결과

| Card | VERIFY | Raw exit | 독립 결과 |
|---|---|---:|---|
| CARD-00-01 | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_security.py` | 0 | 11 passed; S1 우회 없음 |
| CARD-00-02 | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_control_loop.py tests/test_hardening.py -k webhook` | 0 | 5 passed; 신규 ingress는 닫혔으나 backlog 우회 발견 |
| CARD-00-03 | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_mobile.py -k 'secret or token or pairing or refresh'` | 0 | 19 passed; S3 우회 없음 |
| Regression | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q` | 0 | 101 passed |
| Static | `git diff --check -- server` | 0 | whitespace error 없음 |

## 3. 수정 카드

### CARD-00-R1 — queued unsigned webhook의 처리 시점 fail-closed

**TASK**

개발/테스트 환경에서 명시적 opt-in으로 저장된 `signature_valid=false` delivery가 설정 변경 또는 production 전환 후 처리되지 않도록, webhook batch의 공통 처리 경계에서 현재 환경과 `ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS` 정책을 다시 검사한다.

**DELIVERABLE**

- `process_webhook_delivery()` 진입 즉시 persisted `signature_valid`와 현재 설정을 검사한다.
- `signature_valid=false`이고 현재 환경이 production이거나 unsigned opt-in이 꺼져 있으면 provider handler와 모든 업무/감사/push mutation 전에 보안 오류로 종료한다.
- production에서는 `ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS=true`여도 unsigned delivery를 처리하지 않는다.
- non-production에서 opt-in이 계속 true인 경우에만 기존 unsigned fixture 동작을 유지한다.
- 기존 signed delivery 처리, 중복 처리, retry/lock 상태 기계는 변경하지 않는다.
- 이전 opt-in으로 생성한 pending GitHub delivery를 동일 DB에서 production 설정으로 처리하는 회귀 테스트를 추가하고, ActionItem/WorkerExecution/ExternalState/Audit/Push 등 도메인 mutation이 0임을 검증한다.

**SCOPE**

- 수정 허용:
  - `server/action_hub/services/webhooks.py`
  - `server/tests/test_control_loop.py`
  - 필요할 때만 `server/tests/test_hardening.py`
- 수정 금지:
  - route path/response schema
  - DB schema 및 migration
  - webhook signature algorithm/header contract
  - worker retry/lock 상한
  - S1/S3 구현
  - iOS, 배포, git metadata, `.serena/`
- 권장 최소 변경: `process_webhook_delivery()`의 provider dispatch 전 단일 guard. `_claim_webhook_deliveries()` 쿼리에서 단순 제외만 해 pending row를 영구 정체시키는 방식은 사용하지 않는다.
- 오류는 기존 `WebhookSecurityError` 또는 동등한 명시적 보안 오류를 사용하고 secret/raw payload를 메시지나 로그에 노출하지 않는다.

**VERIFY**

```bash
cd server && PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/test_control_loop.py tests/test_hardening.py -k webhook
cd server && PYTHONPATH=. .venv/bin/python -m pytest -q
git diff --check -- server
```

기대값:

- 모든 명령 raw exit `0`.
- 새 테스트는 development + explicit opt-in에서 unsigned pending row 생성 성공을 먼저 증명한다.
- 같은 DB와 row를 production 설정으로 처리하면 business handler 실행 전 거부되고, 도메인 상태 before/after가 동일하다.
- signed pending row는 production에서 정상 처리된다.
- development라도 opt-in을 false로 바꾼 뒤에는 기존 unsigned pending row가 처리되지 않는다.
- 기존 5개 focused webhook test와 전체 101개 이상 test가 회귀 없이 통과한다.

### CARD-00-R2 — unsigned webhook 문서 계약 동기화

**TASK**

운영 문서의 unconditional Development/Test unsigned 허용 문구를 현재 명시적 opt-in 계약과 일치시킨다.

**DELIVERABLE**

- `server/docs/16_CLOSED_LOOP_SYNC_KR.md`에 다음 계약을 명시한다.
  - 기본값은 모든 환경에서 unsigned 거부.
  - development/test에서만 `ACTION_HUB_ALLOW_UNSIGNED_WEBHOOKS=true`의 명시적 opt-in 허용.
  - production은 flag 값과 관계없이 unsigned 거부.
  - 큐에 저장된 delivery도 처리 시점의 현재 정책을 다시 적용.
- 기존 HMAC header 형식과 signed webhook 설명은 유지한다.

**SCOPE**

- 수정 허용: `server/docs/16_CLOSED_LOOP_SYNC_KR.md`
- 수정 금지: 다른 문서의 대규모 정리, API/OpenAPI 계약, 코드 동작

**VERIFY**

```bash
rg -n "ALLOW_UNSIGNED_WEBHOOKS|unsigned|서명" server/docs/16_CLOSED_LOOP_SYNC_KR.md
! rg -n "Development/Test에서는 로컬 Fixture를 위해 unsigned 수신을 허용" \
  server/docs/16_CLOSED_LOOP_SYNC_KR.md
git diff --check -- server/docs/16_CLOSED_LOOP_SYNC_KR.md
```

기대값: 각 명령 raw exit `0`; 기본 거부, non-production explicit opt-in, production 강제 거부, dequeue 재검사가 모두 문서에 존재한다.

## 4. 승인 후 수행 순서와 완료 조건

1. `CARD-00-R1`을 먼저 구현하고 focused + full pytest를 실행한다.
2. `CARD-00-R2` 문서를 동기화하고 stale-claim scan을 실행한다.
3. Sol 관리자가 diff를 독립 검토하고 S2 ingress/dequeue 양쪽의 fail-closed를 판정한다.
4. LunaMax에 동일 모델/effort로 재검증을 요청한다.
5. 다음 조건이 모두 충족될 때만 Wave 00 수정 완료로 보고한다.
   - LunaMax finding `CRITICAL=0`, `HIGH=0`, `MEDIUM=0`.
   - focused/full/static raw exit 모두 `0`.
   - S1/S3 기존 결과 유지.
   - commit/push/PR/merge/iOS signing/외부 production 변경 없음.

## 5. 잔여 위험과 비범위

- live GitHub provider와 production deployment acceptance는 수행하지 않았으므로 별도 외부 승인 게이트로 남는다.
- Docker의 명시적 `0.0.0.0` bind는 이번 수정 카드의 대상이 아니다. 컨테이너 배포에는 secure API key와 방화벽/VPN/reverse proxy가 계속 필요하다.
- verifier 과정에서 관찰된 repository-local `.serena/`는 Phase 0 산출물이 아니며 삭제·stage하지 않는다.
- 현재 HEAD는 `9c8f28d5a9eb34a2c30a869be620885023171977`이고, Phase 0 및 이 수정안은 계속 `UNCOMMITTED` 상태다.

