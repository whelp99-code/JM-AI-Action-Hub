# iOS v0.2.1 알려진 제한과 운영 경계

## v0.2.1 현재 제한

- iOS/iPadOS 18 이상만 지원하며 Android와 Apple Watch 전용 앱은 없다.
- Share Extension은 Text/URL Capture만 받는다. 사진, OCR, PDF 본문과 첨부 upload는 구현하지 않았다.
- Focus Triage, Matrix, Dual Big3, Micro Step, Focus Session, Live Activity, Home Screen Widget, Siri/App Intent는 구현되어 있다. Live Activity·Widget의 실제 잠금화면 표시와 알림 전달은 실기기 인수 대상이다.
- 앱의 정규 동기화는 dashboard·review·activity·triage·matrix·big3·active focus를 full refresh한다. 서버 delta endpoint/cursor는 호환성을 위해 남아 있으나 앱은 delta payload나 cursor를 저장하지 않는다.
- 오프라인 Capture는 서버의 `failed` 영수증이 5회 연속일 때 dead-letter로 이동한다. 네트워크/전송 예외는 attempt count를 올리지 않으며, queue는 App Group `captures/` 아래 pending·dead-letter·corrupt record를 분리한다.
- Settings > 오프라인 수집 진단에서 `모두 복원`은 dead-letter record를 retry metadata 없이 pending으로 되돌린다. 같은 ID가 pending에 있으면 복원을 중단하고, `모두 삭제`는 복구 불가 확인 대화상자 후에만 가능하다.
- 서버 미연결 중에는 Capture 저장이 주 기능이며, Offline Plan Editing은 제공하지 않는다.
- BackgroundTasks는 기회형 queue flush만 요청하며 실제 실행 시각이나 즉시 upload를 보장하지 않는다. foreground 동기화와 APNs가 상태 갱신의 주 경로다.
- Certificate pinning/App Attest, multi-user tenant/RBAC, screenshot/voice 원본의 장기 보관은 현재 범위가 아니다.

## 운영과 보안

- 관리자 `X-Action-Hub-Key`와 provider token은 iPhone에 저장하지 않는다. 기기별 scope의 회전형 refresh token만 Keychain에 보관한다.
- Remote server는 HTTPS가 필요하며 localhost 개발만 HTTP를 허용한다. production QR은 서버 구성의 공개 HTTPS URL이 있어야 발급된다.
- Push는 원문 대신 generic 이벤트와 내부 ID만 사용한다. `remote-notification` background mode는 silent delivery 처리가 구현될 때까지 켜지 않는다.
- Widget snapshot은 개인정보 노출을 줄이는 제한된 상태만 저장한다. device passcode, jailbroken device, OS 전체 장악은 앱만으로 완전히 방어할 수 없다.

## 검증과 수동 인수 경계

- `python3 scripts/validate_ios_project.py`는 Xcode project, source wiring, plist/privacy/entitlement와 정적 composition을 검사할 뿐 App Target/Extension build나 device 동작을 검증하지 않는다.
- Swift API model은 OpenAPI snapshot과 contract script에 맞춰 수동으로 유지한다. generated client는 아직 도입하지 않았으므로 API 변경 시 snapshot·model·contract를 함께 검토해야 한다.
- 현재 이 작업 환경에서는 XCTest module이 없어 Core `swift test`는 iOS-XCTEST PENDING 상태다. Full Xcode 환경에서 `swift test --package-path Packages/ActionHubCore`와 Xcode build를 다시 실행해야 한다.
- Apple Developer signing, provisioning, simulator/device build, Share Sheet, Camera QR, microphone/speech, Face ID, Widget/App Intents, APNs sandbox/production, background refresh, TestFlight install은 수동 인수가 필요하다.
- App Store Privacy Label과 실제 배포의 entitlement/notification 정책은 signing 및 실기기 검증과 함께 최종 확정한다.

## 후속 도입 조건

| 기능 | 착수 조건 |
|---|---|
| OCR/첨부 upload | 이미지 또는 문서 Capture가 반복 |
| Apple Watch | iPhone을 꺼내지 못해 Capture 누락이 반복 |
| iPad 전용 UX | split view 작업 수요 확인 |
| Offline Plan Editing | 네트워크 단절 중 Review 필요가 반복 |
| App Attest | 외부 사용자 또는 조직 보안 요구 상승 |
