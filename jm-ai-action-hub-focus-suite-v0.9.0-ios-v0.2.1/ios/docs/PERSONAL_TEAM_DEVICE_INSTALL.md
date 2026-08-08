# Personal Team 실기기 설치 절차 (무료 Apple ID)

2026-08-05 iPhone 16 Pro / iOS 26.x / Xcode 26.6에서 실측한 절차다. 유료 Apple Developer Program 없이 본인 기기에 설치할 때 사용한다. TestFlight·App Store 배포는 유료 프로그램이 필요하며 이 문서의 범위가 아니다.

## Personal Team의 제약

Personal Team은 **Push Notifications capability를 지원하지 않는다.** `Config/ActionHubApp.entitlements`의 `aps-environment`가 있으면 프로비저닝 프로파일 생성이 다음과 같이 실패한다:

```text
Cannot create a iOS App Development provisioning profile for "<bundle id>".
Personal development teams do not support the Push Notifications capability.
```

저장소 파일은 유료 팀 기준(푸시 포함)이 정본이므로 수정하지 않는다. 대신 빌드 시점에 entitlements를 덮어쓴다.

APNs를 제외하면 오프라인 캡처 큐, Share Extension, Widget, App Intents는 정상 동작한다. 서버 푸시 알림만 수신되지 않는다.

## 절차

1. **Xcode 계정 등록** — Xcode → Settings → Accounts → Apple ID 로그인 → Manage Certificates → `+` → Apple Development 인증서 생성.

2. **Team ID 확인** — Personal Team의 ID는 Accounts 화면에 표시되지 않는다. 생성한 인증서의 OU 필드에서 읽는다:

   ```bash
   security find-certificate -a -c "Apple Development" | grep '"alis"'
   ```

   subject의 `OU` 10자리 값이 Team ID다.

3. **로컬 설정** — `Config/Local.xcconfig` (git-ignored):

   ```xcconfig
   DEVELOPMENT_TEAM = <10자리 Team ID>
   ACTION_HUB_BUNDLE_PREFIX = com.<your>.jmactionhub
   ACTION_HUB_APP_GROUP = group.com.<your>.jmactionhub.shared
   ```

4. **기기 준비** — iPhone에서 설정 → 개인정보 보호 및 보안 → 개발자 모드 → 켬 → 재시동. 케이블 연결 후 "이 컴퓨터를 신뢰" 승인.

5. **푸시 제외 entitlements 준비** (저장소 밖, 예: `/tmp/ah-personal-team/ActionHubApp-nopush.entitlements`) — `com.apple.security.application-groups`만 남기고 `aps-environment`를 제거한 사본.

6. **서명 빌드**

   ```bash
   xcrun devicectl list devices          # UDID 확인
   xcodebuild -project JM-AI-Action-Hub-iOS.xcodeproj -scheme ActionHubApp \
     -configuration Debug -destination 'id=<device UDID>' \
     -allowProvisioningUpdates \
     CODE_SIGN_ENTITLEMENTS=/tmp/ah-personal-team/ActionHubApp-nopush.entitlements \
     build
   ```

7. **설치·실행**

   ```bash
   xcrun devicectl device install app --device <UDID> \
     ~/Library/Developer/Xcode/DerivedData/JM-AI-Action-Hub-iOS-*/Build/Products/Debug-iphoneos/ActionHubApp.app
   xcrun devicectl device process launch --device <UDID> com.<your>.jmactionhub.ios
   ```

8. **개발자 앱 신뢰** — 첫 실행은 `FBSOpenApplicationErrorDomain error 3` (Security)로 거부된다. iPhone에서 설정 → 일반 → VPN 및 기기 관리 → 개발자 앱 → 해당 인증서 → 신뢰. 이후 launch가 성공한다.

## 유효기간

Personal Team으로 서명한 앱은 **7일 후 만료**된다. 만료되면 6~7단계를 다시 실행한다. 유료 Developer Program은 1년이며 TestFlight 배포가 가능하다.
