# macOS·실기기·TestFlight 인수 작업지시서

## 1. 사전 조건

- macOS와 호환 Xcode
- Apple Developer Program 계정
- App Store Connect 접근
- 실제 iPhone
- HTTPS Action Hub Server v0.8.0
- 고유 Bundle ID와 App Group
- APNs Key는 Push 검증 시 필요

## 2. Signing 설정

```bash
cp Config/Local.xcconfig.example Config/Local.xcconfig
```

```xcconfig
DEVELOPMENT_TEAM = <TEAM_ID>
ACTION_HUB_BUNDLE_PREFIX = com.<organization>.jmactionhub
ACTION_HUB_APP_GROUP = group.com.<organization>.jmactionhub.shared
```

Apple Developer Portal/App Store Connect에서 다음 Identifier를 일치시킨다.

```text
com.<organization>.jmactionhub.ios
com.<organization>.jmactionhub.ios.share
com.<organization>.jmactionhub.ios.widget
group.com.<organization>.jmactionhub.shared
```

Main App Capability:

- App Groups
- Push Notifications
- Background Modes: Background fetch

> v0.1은 alert push 후 사용자가 앱을 열면 동기화하는 구조다. Silent `content-available` push를 구현하기 전에는 `Remote notifications` Background Mode를 활성화하지 않는다.

Share/Widget:

- App Groups

## 3. 자동 Preflight

```bash
bash scripts/testflight_preflight.sh
```

검증:

- deterministic project
- OpenAPI
- static privacy/entitlement
- core tests
- Release device archive

## 4. Simulator

```bash
xcodebuild \
  -project JM-AI-Action-Hub-iOS.xcodeproj \
  -scheme ActionHubApp \
  -configuration Debug \
  -destination '<xcodebuild -showdestinations에서 확인한 iOS Simulator>' \
  build
```

Simulator 검증:

- Pairing URL 붙여넣기
- Text Capture
- Review/Edit/Approve/Execute
- Today/Activity
- Deep Link
- Dark Mode
- Dynamic Type

카메라, 실제 APNs, Face ID, 일부 Share Host 동작은 실기기에서 검증한다.

## 5. 실기기 시나리오

### P0 연결

1. 서버 Production Readiness 확인
2. Pairing QR 생성
3. 카메라 권한 허용
4. QR 스캔
5. Device 목록에 Active 확인
6. 관리자 API Key가 앱/로그에 없는지 확인

### P0 Share

호스트 앱:

- 카카오톡
- 메시지
- Mail
- Safari
- Notes

각각 텍스트/URL을 `Action Hub에 추가`로 공유한다.

검증:

- 네트워크 OFF에서도 성공 표시
- Main App에서 Pending Count
- 네트워크 ON 후 자동/수동 Flush
- 동일 Capture Plan 중복 없음

### P0 Review

- Item 수정
- 다른 브라우저에서 동시 수정
- iOS 저장 시 409 Conflict 표시
- 최신 Plan 재조회
- 승인
- 실행
- Provider 원장 링크 확인

### P1 Speech

- 권한 거부
- 권한 허용
- 한국어 3개 Action 말하기
- 중간 취소
- View 닫기 시 녹음 중지
- 서버에는 텍스트만 도착

### P1 Security

- 앱 Background 후 재진입 Face ID/Passcode
- Remote Device Revoke
- 기존 Access Token으로 동기화 실패 후 Disconnected
- HTTP Remote Pairing 거부
- QR 만료/재사용 거부

### P1 Widget/App Intents

- Small/Medium Widget
- 빠른 입력 Deep Link
- Siri “Action Hub에 추가”
- 단축어에서 Text 전달
- App Group Queue 반영

### P1 APNs

- Sandbox Push Token 등록
- Review Required
- AI Status
- Follow-up Due
- 앱 Foreground/Background/Terminated 수신
- 알림에 원문 없음
- Tap Route 확인
- 앱 재실행 후 Token 재등록

### P2 Background

- Capture Pending 상태에서 앱 Background
- BG Refresh 기회 부여
- 시스템이 실행하지 않아도 데이터 유실 없음
- Foreground 시 최종 Flush

## 6. TestFlight

1. Archive Organizer에서 Validate App
2. Distribute App → App Store Connect
3. Export Compliance 답변
4. Build Processing 완료
5. Internal Testing Group 생성
6. What to Test 작성
7. iPhone TestFlight 설치
8. 위 실기기 시나리오 반복

## 7. 승인 기준

GO:

- Crash-free P0 시나리오
- Share 무손실/무중복
- Pairing/Revocation
- Review/Approval/Execution
- 원장 링크
- 개인정보 Push
- Release Archive

NO-GO:

- 관리자 키 앱 포함
- Remote HTTP 허용
- Share 데이터 유실
- 중복 Action 생성
- Silent Revision Overwrite
- Push에 원문 노출
- Device Revoke 후 계속 접근
