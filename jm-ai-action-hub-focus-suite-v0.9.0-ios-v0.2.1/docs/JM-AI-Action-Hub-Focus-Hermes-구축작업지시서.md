# Hermes 작업지시서
## JM-AI Action Hub Focus Control Suite v0.9.0 / iOS v0.2.1

# 목적

제공된 릴리스 패키지를 macOS/운영 호스트에 구축하고, Server v0.9.0과 Native iOS v0.2.1의 실제 Apple 환경 인수를 수행한다.

# 절대 원칙

1. 소스 변경 전 SHA-256과 RELEASE_MANIFEST를 검증한다.
2. 기존 v0.8.0 DB를 백업한다.
3. 최초 실행은 dry_run이다.
4. Todoist/GitHub/Calendar 원장을 복제하지 않는다.
5. 관리자 API Key와 외부 Token을 iOS에 넣지 않는다.
6. Q4·Day Close·Focus 기능이 외부 Provider를 삭제하지 않는지 확인한다.
7. 자동 Merge·배포·고객 발송을 활성화하지 않는다.
8. Apple `.p8`와 Signing 정보는 Git에 저장하지 않는다.

# 입력 산출물

```text
jm-ai-action-hub-focus-suite-v0.9.0-ios-v0.2.1.zip
jm-ai-action-hub-server-v0.9.0.zip
jm-ai-action-hub-ios-v0.2.1.zip
jm_ai_action_hub-0.9.0-py3-none-any.whl
action-hub.openapi-v0.9.0.json
SHA256SUMS-jm-ai-action-hub-focus-suite.txt
```

# Phase A — 무결성

```bash
sha256sum -c SHA256SUMS-jm-ai-action-hub-focus-suite.txt
unzip <package>
sha256sum -c RELEASE_MANIFEST.sha256
```

실패 시 즉시 중단한다.

# Phase B — Server Upgrade

```bash
./scripts/backup.sh
python -m pip install --upgrade jm_ai_action_hub-0.9.0-py3-none-any.whl
alembic upgrade head
```

확인:

```text
Alembic Head = 0005_decision_focus_foundation
기존 Plan/Action ID 보존
/health 200
/readiness 200
/api/v1/focus/triage 200
```

설정:

```dotenv
ACTION_HUB_EXECUTION_MODE=dry_run
ACTION_HUB_IMPORTANCE_THRESHOLD=60
ACTION_HUB_URGENCY_THRESHOLD=60
ACTION_HUB_BIG3_LIMIT=3
ACTION_HUB_FOCUS_DEFAULT_MINUTES=25
ACTION_HUB_FOCUS_WARNING_PERCENT=80
ACTION_HUB_FOCUS_MAX_MINUTES=240
```

# Phase C — Server Acceptance

1. Action 생성
2. Q1~Q4 분류
3. Q4 후 외부 작업 유지 확인
4. Human/AI Big3
5. 3~5 Micro Steps
6. Focus start/pause/resume/extend/complete
7. 중복 Focus start 거부
8. stale revision 409
9. Day Close 전체 결정
10. Weekly report

# Phase D — iOS Xcode

```bash
cp Config/Local.xcconfig.example Config/Local.xcconfig
# Team/Bundle/App Group 설정
bash scripts/verify_release.sh
ACTION_HUB_RUN_XCODE=1 bash scripts/verify_release.sh
```

각 Target Signing과 App Group을 설정한다.

# Phase E — 실기기

- QR Pairing
- Share Extension offline capture
- Triage swipe/button/VoiceOver
- Matrix
- Dual Big3
- Micro Steps
- Focus Live Activity
- Widget
- App Intents
- Day Close
- APNs
- Device Revoke

# Phase F — TestFlight

- Version 0.2.1
- Build 21 이상
- Archive/Validate/Upload
- Internal Group
- P0 시나리오 통과

# 보고 형식

```text
환경
Server commit/hash
iOS commit/hash
Package SHA-256
Migration before/after
Python test result
Xcode build result
Physical device model/iOS
APNs result
TestFlight build number
P0 case table
잔여 제한
최종 GO/NO-GO
```

# 금지된 완료 주장

다음 증거 없이 완료라고 보고하지 않는다.

- Xcode build log
- 실제 iPhone 설치 화면
- Live Activity 실기기 확인
- APNs delivery evidence
- TestFlight build 상태
