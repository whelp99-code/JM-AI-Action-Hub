# JM-AI Action Hub iOS v0.1.0 릴리스 검증 보고서

검증 기준일: **2026-07-31 (Asia/Seoul)**

## 1. 판정

> SwiftUI App, Share Extension, Widget, App Intents, Swift Core, 서버 계약 및 실제 FastAPI E2E의 **소스 구현과 비-Apple SDK 검증은 통과**했다.

현재 환경에는 Xcode와 Apple SDK가 없으므로 App Target의 실제 SDK Link, Code Signing, Simulator, 실기기, APNs Live, TestFlight는 완료라고 주장하지 않는다. 따라서 판정은 다음과 같다.

```text
서버 v0.8.0                     Release Candidate 통과
ActionHubCore                   Build/Test 통과
iOS App/Extension Source        구현·정적검증 통과
iOS Signed Binary/TestFlight    macOS·Apple 계정 인수 대기
```

## 2. 자동 결과

```text
ActionHubCore XCTest: 30 passed
Swift Testing smoke: 1 passed
Swift source parse: 42 files passed
swift-format strict: passed
Swift release build: passed
Xcode project generation check: passed
OpenAPI contract: 56 operations / version 0.8.0 / passed
Static project/privacy/entitlement check: passed
Plist/Entitlement syntax: passed
```

## 3. 실제 Swift→Server E2E

Swift 실행 파일이 실제 FastAPI 서버에서 다음을 완료했다.

```text
Capabilities
→ Pairing
→ Dashboard
→ Offline Capture
→ Plan Fetch
→ Revisioned Item Patch
→ Approve
→ Execute
→ Activity
→ Delta Changes
```

결과:

```text
capture_status: processed
execution_completed: 1
execution_failed: 0
activity_count: 10
change_count: 10
server_version: 0.8.0
```

## 4. 검증된 보안·신뢰성

- Remote HTTP 차단, loopback HTTP만 개발 예외
- Minimum App Version fail-closed
- Pairing Claim 전 Capability 확인
- 사용자 조작 없는 외부 Custom URL 자동 Pairing 금지
- Bearer Header와 동적 Path Segment Encoding
- 401에서 Refresh single-flight 후 1회 재시도
- Remote Revoke 실패 시에도 Local Keychain 세션 삭제
- Capture별 Atomic App Group Queue
- 독립 Process 동시 Enqueue 무손실
- Legacy Queue Migration과 Corrupt File 격리
- Delta Change 최대 페이지 제한
- Revision 409 Conflict 표시
- Camera Permission 상태 처리
- Speech AudioSession/Tap Cleanup
- 앱 소스에 관리자 `X-Action-Hub-Key` 없음
- App Group/Entitlement 일치
- Widget 상세 제목·카운트에 `privacySensitive()` 적용
- Privacy Tracking `false`
- Silent Push를 구현하지 않은 v0.1에서는 `remote-notification` Background Mode 비활성

## 5. Apple Framework 사용 경계

- App Groups: App, Share, Widget 사이의 최소 공유 데이터
- Keychain: 기기별 모바일 세션과 Refresh Token
- LocalAuthentication: 민감 화면 잠금
- Speech: 마이크 실시간 전사, 원본 음성 서버 미보관
- App Intents: Shortcuts/Siri/Action Button 진입점
- WidgetKit: 조회·앱 열기 중심의 최소 위젯
- BackgroundTasks: 기회형 Queue Flush; 정확한 실행시각 보장 수단으로 사용하지 않음
- UserNotifications/APNs: 민감 원문 없는 상태 알림

## 6. 정적 검증 한계

Linux의 `swiftc -parse`는 UIKit/SwiftUI iOS Target을 Apple SDK에 Link하지 않는다. 따라서 다음은 macOS Xcode에서 확정한다.

- `xcodebuild` App/Share/Widget 전체 Build
- Extension Embedding
- App Group 실제 Container 공유
- Push Entitlement와 Provisioning
- Camera/Speech/Face ID 권한
- Share Host App별 동작
- Siri/App Intents 등록
- Widget Timeline과 잠금화면 Privacy

## 7. 현재 릴리스 경계

```text
개발 완료:
- Server Mobile Foundation
- Swift Core
- Native App/Extensions source
- Static/Contract/Security tests
- Live Swift↔Server contract

운영 인수 필요:
- Xcode archive
- Apple signing
- real-device acceptance
- APNs live
- TestFlight install
```

## 최종 보안 회귀 검증 추가

- QR 스캔 후 자동 Claim 금지 및 사용자 서버 확인 단계
- `jmactionhub://` 전용 앱 등록
- legacy `actionhub://`는 수동 파서 호환만 유지
- 중복/알 수 없는 Query Item 거부
- 잘못된 host/type/version/code/원격 HTTP 거부
