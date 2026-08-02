# Xcode·TestFlight 인수 절차

## 1. 선행조건

- macOS와 Xcode 16+
- Apple Developer Program Team
- iPhone iOS 18+
- HTTPS Action Hub Server 0.8.0+
- App Store Connect 접근

## 2. Identifier 생성

다음 Identifier를 조직 Prefix로 등록한다.

```text
com.jmactionhub.ios
com.jmactionhub.ios.share
com.jmactionhub.ios.widget
group.com.jmactionhub.shared
```

세 App ID에 같은 App Group을 연결한다. Main App에는 Push Notifications를 활성화한다.

## 3. Xcode 설정

1. `Config/Shared.xcconfig` Bundle Prefix/App Group 변경
2. `DEVELOPMENT_TEAM` 지정
3. 세 Target Signing Team 일치
4. App Groups 확인
5. Main App Push Notifications 확인
6. Background Modes: Remote Notifications, Background Fetch 확인
7. `python3 scripts/generate_xcodeproj.py --check`

## 4. Build Gate

```bash
xcodebuild \
  -project JM-AI-Action-Hub-iOS.xcodeproj \
  -scheme ActionHubApp \
  -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

실기기:

```bash
xcodebuild \
  -project JM-AI-Action-Hub-iOS.xcodeproj \
  -scheme ActionHubApp \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  archive \
  -archivePath build/ActionHub.xcarchive
```

## 5. 실기기 시험

### Pairing

- 정상 QR
- 5분 만료 QR
- 잘못된 Code 5회
- 외부 Custom URL 사용자 확인
- 다른 Server 연결 시 기존 연결 해제 요구

### Share

- 카카오톡 Text
- Safari URL
- Mail Text/URL
- Airplane Mode Share
- 재연결 후 Queue Flush
- App/Extension 동시 수집

### 보안

- Face ID 성공/실패
- Passcode Fallback
- Background→Foreground 재잠금
- Server Remote Revoke
- Local Disconnect Network Failure

### Push

- Debug/Sandbox Token
- TestFlight/Production Token
- Review Required
- AI Status
- Follow-up Due
- Push Tap Deep Link
- 민감한 Title/원문 미포함

### Speech

- Permission Allow/Deny
- Korean Recognition
- On-device 지원 여부
- Cancel 후 Audio Session 종료

### Widget/Intent

- Small/Medium Widget
- Snapshot 갱신
- Shortcut Text Capture
- Siri Phrase
- Widget Quick Capture Deep Link

## 6. TestFlight

1. Release Archive
2. Validate App
3. Upload
4. Internal Testing Group
5. Privacy Nutrition Label 일치 확인
6. Crash/Metric/Feedback 확인
7. Server 최소 앱 버전은 초기 `0.1.0` 유지

## 7. RC 승인 기준

- Xcode Build/Archive 성공
- 세 Target Provisioning 성공
- Share Extension 노출
- App Group 데이터 공유
- APNs Sandbox 및 Production 성공
- Remote Revoke 즉시 401
- Offline Capture 유실/중복 없음
- Critical Crash 0
