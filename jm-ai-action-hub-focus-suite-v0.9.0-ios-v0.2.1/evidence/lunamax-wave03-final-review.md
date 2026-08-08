# Wave 03 독립 검증 보고서

결론: **FAIL**

- 모델/노력: `gpt-5.6-sol` 검증 라우트, LunaMax read-only verifier, max/adversarial effort
- CRITICAL 0 / HIGH 2 / MEDIUM 2 / LOW 0
- 서버·local gate는 통과했지만, SOL-W3-01·02와 acceptance false-pass/data-loss 문제가 남았습니다.
- 코드 수동 수정, stage, commit, push, deploy, 외부 provider 호출은 하지 않았습니다. 필수 명령이 prescribed evidence/temp 파일을 생성·갱신했습니다.

## 명령 결과

| # | 명령 | Raw exit | 결정적 출력 |
|---:|---|---:|---|
| 1 | `cd server && bash -n scripts/backup.sh scripts/restore.sh scripts/rehearse_backup_restore.sh scripts/acceptance_local.sh scripts/verify.sh` | 0 | 출력 없음 |
| 2 | `cd server && PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_backup_restore_scripts.py tests/test_acceptance_local.py` | 0 | `............. [100%]` |
| 3 | `cd server && ./scripts/verify.sh` | 0 | `166 passed`, coverage `83.28%`, `OPENAPI_CONTRACT_OK`, `VERIFY_OK` |
| 4 | `cd server && make verify` | 0 | `166 passed`, coverage `83.28%`, `OPENAPI_CONTRACT_OK` |
| 5 | `ACCEPTANCE_RECEIPT_PATH=.../evidence/production-acceptance-20260802T203926Z.json make acceptance-local` | 0 | criteria 1–5 local checks, `DOCS_CHECK_OK stale_count=0 required_count=6`, `LOCAL_ACCEPTANCE_OK externalStatus=LOCAL_PASS_EXTERNAL_PENDING` |
| 6 | repository root `git diff --check` | 0 | 출력 없음 |
| 7 | `cd ios && bash scripts/verify_release.sh` | 1 | `XCODEPROJ_CHECK_OK`, `IOS_PROJECT_STATIC_OK sources=30`, 이후 `error: no such module 'XCTest'` |

7번은 static/OpenAPI/Xcodeproj 검증 후 발생한 승인된 **Full Xcode 환경 pending**으로 분류합니다.

## Findings

| ID | Severity | Status | Evidence / impact |
|---|---|---|---|
| SOL-W3-01 | HIGH | **OPEN** | [`acceptance_local.sh:36-57`](</Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/server/scripts/acceptance_local.sh:36>)의 stdout `shasum` 실패가 검사되지 않습니다. 실패 주입 결과 acceptance exit 0, `LOCAL_ACCEPTANCE_OK`, criteria 1–5 `PASS`, stdout SHA 빈 문자열이 함께 기록되었습니다. |
| SOL-W3-02 | HIGH | **OPEN** | [`backup.sh:17-23`](</Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/server/scripts/backup.sh:17>) 및 [`restore.sh:17-20`](</Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/server/scripts/restore.sh:17>)가 직접 parent만 검사합니다. `symlink-ancestor/nested/target` 경로가 exit 0으로 허용되어 실제 real path target을 교체했습니다. |
| BR-OUT-01 | MEDIUM | **OPEN** | [`backup.sh:21-23`](</Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/server/scripts/backup.sh:21>)는 기존 hardlink output을 허용합니다. probe에서 backup exit 0과 함께 보호된 hardlink 대상 파일이 tar 데이터로 덮어써졌습니다. |
| ACC-SMOKE-01 | MEDIUM | **OPEN** | [`acceptance_local.sh:178-185`](</Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/server/scripts/acceptance_local.sh:178>)는 mixed day-close의 `404`만 검사하고 domain/audit row 불변을 확인하지 않습니다. 현재 `test_focus.py`의 atomic 테스트는 통과했지만 acceptance 자체는 부분 mutation 회귀를 false-pass할 수 있습니다. |

## SOL-W3 closure

- **SOL-W3-01: OPEN — HIGH**. 일반 helper exit 전파는 개선됐지만 receipt hash 내부 실패 false-pass가 재현되었습니다.
- **SOL-W3-02: OPEN — HIGH**. absolute/parent/direct symlink archive rejection은 통과했으나 symlink ancestor explicit path가 허용됩니다.
- **SOL-W3-03: CLOSED**. `backup-restore-rehearsal.json`에 redacted command contracts 3개, exit codes, pre/post manifest hash와 `manifestsEqual=true`가 있고 실제 archive SHA도 일치했습니다.
- **SOL-W3-04: CLOSED**. exact Starlette warning invocation은 exit 0 및 `EXACT_STARLETTE_WARNING_SUPPRESSED`; 동일 category의 unrelated warning은 exit 1로 실패했습니다.

추가 probe:

- restore check 실패: inner restore exit `1`, 기존 marker `original`, target manifest 보존.
- security/smoke helper 포트 실패: 각각 exit `1`, `ACCEPTANCE_FAILED`.
- S1–S3 focused tests: exit `0`, 전체 테스트 통과.
- backup/restore malicious archive의 absolute, parent, symlink, hardlink rejection과 target 불변: focused tests 통과.

## Receipt 및 traceability

- production receipt schema 검증: `criteria=1..5 PASS`, 각 exit `0`, SHA-256 형식 정상, `repoHead`/`planSha256` 현재 값 일치.
- `externalStatus=LOCAL_PASS_EXTERNAL_PENDING`.
- known API key, webhook secret, raw Korean capture text는 receipt에 없음.
- `LIVE-ACCEPTANCE PENDING (사용자 인프라 필요)` 유지.
- `iOS-XCTEST PENDING (Full Xcode 필요)` 유지.
- `LICENSE/NOTICE 부재 — 소유자 제공 대기` 유지.
- [`docs/IMPROVEMENT_PLAN_V1.md`](</Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub/jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1/docs/IMPROVEMENT_PLAN_V1.md>) traceability에서 `REQ-OPS-001`, `REQ-ACC-001`은 여전히 `PLANNED`입니다. 이를 완료로 과장하지 않았습니다.
- CARD-03-03 manual/live acceptance는 실행하지 않았습니다. local loopback·synthetic acceptance만 수행했습니다.

## HEAD / worktree

- Git root: `/Volumes/DevSpace/Playground/JM AI-OS Pack/JM-AI Action Hub`
- `HEAD`: `9c8f28d5a9eb34a2c30a869be620885023171977`
- branch: `main`, `origin/main`과 동일
- staged index: 비어 있음
- 최종 `git diff --check`: exit 0
- worktree: modified 62, untracked 39; Wave 0–2 dirty 변경은 Wave 03으로 귀속하지 않았습니다.
- commit/push/deploy는 수행하지 않았습니다.

최종 판정은 **FAIL**이며, PASS 전 SOL-W3-01·02, BR-OUT-01, ACC-SMOKE-01 수정 및 독립 재검증이 필요합니다.