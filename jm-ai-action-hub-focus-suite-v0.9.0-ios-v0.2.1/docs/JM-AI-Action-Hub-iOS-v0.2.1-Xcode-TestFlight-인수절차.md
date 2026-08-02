# JM-AI Action Hub iOS v0.2.1
## Xcode·실기기·TestFlight 최종 인수 절차

# 1. 준비

- macOS
- 최신 안정 Xcode
- Apple Developer Program Team
- iOS 18 이상 iPhone
- HTTPS Action Hub Server v0.9.0
- App Group 식별자
- Push Notification Capability
- APNs Auth Key는 서버에만 보관

# 2. 압축 해제

```bash
unzip jm-ai-action-hub-ios-v0.2.1.zip
cd jm-ai-action-hub-ios-v0.2.1
```

# 3. 로컬 설정

```bash
cp Config/Local.xcconfig.example Config/Local.xcconfig
```

```xcconfig
DEVELOPMENT_TEAM = YOUR_TEAM_ID
ACTION_HUB_BUNDLE_PREFIX = com.yourcompany.jmactionhub
ACTION_HUB_APP_GROUP = group.com.yourcompany.jmactionhub.shared
```

관리자 API Key·Todoist/GitHub Token·APNs `.p8`를 앱 저장소에 넣지 않는다.

# 4. Apple Developer Portal

다음 Identifier를 등록한다.

- Main App
- Share Extension
- Widget Extension
- App Group

Capabilities:

- App Groups
- Push Notifications
- Associated entitlement required by project

# 5. Source Gate

```bash
bash scripts/verify_release.sh
```

Xcode build 포함:

```bash
ACTION_HUB_RUN_XCODE=1 bash scripts/verify_release.sh
```

# 6. Simulator 인수

- 앱 기동
- Server 연결 화면
- Today/Focus/Review/Activity/Capture/Settings
- Dynamic Type
- Dark Mode
- offline queue
- Triage/Matrix/Big3/Micro Steps/Focus/Day Close

Camera, Face ID, Push, Live Activity는 실기기에서 확인한다.

# 7. 실기기 P0 시나리오

## Pairing

1. Server에서 5분 QR 생성
2. iPhone에서 스캔
3. 표시된 HTTPS Server 검토
4. 명시적 연결
5. Dashboard 조회

## Capture

1. 카카오톡·Mail·Safari에서 Share
2. Airplane mode에서 저장
3. 앱 실행 후 네트워크 복구
4. 중복 없이 Plan 1개 생성

## Focus

1. 미분류 업무 생성
2. Triage에서 Q1
3. Human Big3 등록
4. Micro Steps 생성
5. 10분 Focus 시작
6. Lock Screen/Dynamic Island 확인
7. Pause/Resume/+10분
8. Complete
9. Live Activity 종료
10. 주간 리포트 반영

## 접근성

- VoiceOver로 Q1~Q4 분류
- 큰 글자
- 색상 없이 Traffic 구분
- Reduce Motion

## 보안

- Remote HTTP 거부
- Server revoke 후 앱 접근 거부
- Push/Widget/Live Activity에 원문 없음
- Clipboard는 사용자 탭 때만 읽음

# 8. APNs

- Server에 Key ID, Team ID, Bundle ID, `.p8` 안전 저장
- Sandbox에서 device token 등록
- generic review/focus notification 전송
- Payload에 원문·고객명·금액 없음 확인
- Production 환경 전환 후 재검증

# 9. Archive·TestFlight

- Version: 0.2.1
- Build: 21 이상
- Generic iOS Device
- Product → Archive
- Validate App
- Distribute App → App Store Connect
- Internal TestFlight Group 배포

# 10. TestFlight GO 기준

- P0 Crash 0
- Pairing/Refresh/Revoke 정상
- Offline Capture 손실·중복 0
- Focus 동시 시작 0
- Live Activity orphan 0
- Q4 외부 삭제 0
- Big3 중복 0
- Widget/App Intents 직접 실행 0
- 개인정보 노출 0
- VoiceOver 핵심 Flow 완료

# 11. 실패 시

- 앱 배포 중단
- Server v0.9.0은 기존 PWA/iOS v0.1 경로 유지
- Device revoke
- Xcode Organizer log와 앱 진단 로그 수집
- 데이터 원장(Todoist/GitHub/Calendar)은 변경하지 않고 Focus 내부 상태만 복구
