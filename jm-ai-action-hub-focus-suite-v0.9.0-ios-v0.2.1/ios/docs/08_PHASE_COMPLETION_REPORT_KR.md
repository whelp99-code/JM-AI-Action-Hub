# 단계별 개발 완료 보고서 — JM-AI Action Hub iOS v0.1.0

## 1. 단계별 결과

| Phase | 구현 결과 | 상태 |
|---|---|---|
| Research/제품 경계 | 기존 Todo·Calendar·GitHub를 재개발하지 않는 Companion 경계 | 완료 |
| Server Mobile Foundation | Pairing, Auth, Scope, Revision, Mobile API | 완료 |
| Server Offline/Push | Batch, Idempotency, Stale Lock Recovery, APNs Outbox | 완료 |
| Swift Core | Typed Model/API, Session, Refresh, Queue, Pairing, Version | 완료 |
| Native App UI | Today, Review, Plan Edit, Activity, Settings, Capture | 소스 완료 |
| Native Capture | 직접 입력, Clipboard, 한국어 Speech, QR Pairing | 소스 완료 |
| Extensions | Share, Widget, App Intents, Deep Link | 소스 완료 |
| Hardening | Keychain cleanup, URL confirmation, paging, permission, privacy | 완료 |
| Cross-platform Verification | Swift Test/Release/Format/Parse | 완료 |
| Live Contract | Swift Client → 실제 FastAPI E2E | 완료 |
| Xcode App Build | Apple SDK가 필요한 인수 | 대기 |
| Physical Device | Signing/APNs/Face ID/Share/Siri/Widget | 대기 |
| TestFlight | Apple Developer 계정과 App Store Connect | 대기 |

## 2. 순차적으로 구현한 기능

### S1 — 서버 모바일 인증

- 5분 만료 관리자 발급 Pairing Session
- Pairing Code 원문 미저장, HMAC 비교
- 원자적 1회 Claim과 최대 실패 횟수
- 기기별 Scope
- 단기 Access Token
- 회전형 Refresh Token Family
- 응답 유실 재시도 유예와 Reuse Detection
- 원격 Device Revoke

### S2 — 모바일 데이터·동기화

- Dashboard, Review, Plan, Activity
- Capture Batch Upload
- Capture ID와 Content Hash 기반 Idempotency
- 동시 요청 보호
- Stale Processing Lock 회수
- Plan/Item revision과 HTTP 409
- HMAC 서명 Delta Cursor와 변조 400

### S3 — Push

- APNs Device Token 등록
- Privacy-safe Push Outbox
- ES256 Provider Token/HTTP2 Adapter
- Retry, Max Attempts, Stale Lock Recovery
- Review/AI/Follow-up/Deadline/Connector event
- 원문·고객명·작업 제목을 Push Payload에 미포함

### I1 — ActionHubCore

- HTTPS 정책
- Typed API Client
- Capability/Minimum Version Preflight
- MobileSession Restore/Refresh/Disconnect
- QR JSON/Custom URL Parser
- Semantic Version
- Process-safe Offline Capture Queue
- Live Contract Smoke Executable

### I2 — SwiftUI 앱

- Today Decision
- Review List와 Plan Detail
- Action Item Editor
- Approve/Reject/Execute
- Activity/Waiting/AI 상태
- Capture/Clipboard/Speech
- QR Pairing
- Settings/Server/Device/Notification
- Face ID 또는 Device Authentication 잠금

### I3 — iOS 시스템 통합

- Share Extension
- App Group Queue
- App Intents/Shortcuts
- WidgetKit Today Widget
- APNs Deep Link Routing
- BGAppRefreshTask 기회형 동기화

## 3. 상세 검증에서 발견하고 수정한 결함

1. **원격 해제 네트워크 오류 후 Keychain 잔존**
   서버 호출 실패와 무관하게 로컬 세션을 반드시 삭제하도록 수정하고 회귀 테스트를 추가했다.

2. **외부 Custom URL 자동 Pairing**
   다른 앱이나 웹이 `jmactionhub://pair`를 열어도 자동 Claim하지 않고 Pairing 화면에 채운 뒤 사용자 확인을 요구한다.

3. **Delta Change 1페이지 제한**
   앱 동기화를 최대 10페이지까지 반복하고 Cursor를 불투명 값으로 취급한다.

4. **서버 Delta Cursor 무서명**
   HMAC-SHA256 서명 Cursor로 변경하고 변조 입력은 HTTP 400으로 거부한다.

5. **Production QR의 Host Header 신뢰**
   Production에서는 명시적 `public_base_url` 또는 구성값만 사용하고 Request Host fallback을 금지한다.

6. **Offline Capture 처리 중 서버 중단**
   `processing` Capture에 Lock 시각을 기록하고 Timeout 이후 안전하게 재선점한다.

7. **QR Camera Permission 누락**
   미결정/허용/거부 상태를 구분하고 설정 이동 또는 붙여넣기 대안을 제공한다.

8. **Speech AudioSession/Tap 정리 누락 가능성**
   시작·중지·오류·View 종료 모든 경로에서 Tap과 Audio Session을 정리한다.

9. **Widget 잠금화면 정보 노출**
   Top 제목과 상태 카운트를 `privacySensitive()`로 표시했다.

10. **구현하지 않은 Silent Push Background Mode**
    v0.1은 alert push 후 앱 열기/foreground sync 구조이므로 `remote-notification`을 제거했다.

## 4. 현재 판정

- **Server v0.8.0:** 개발·Migration·실제 HTTP·Swift 계약 검증 완료
- **Swift Core:** Debug/Release Build와 자동 테스트 완료
- **iOS Xcode Source:** 기능 구현과 정적검증 완료
- **Signed iOS Binary/TestFlight:** Xcode/Apple Developer 환경이 필요하므로 운영 인수 대기

## 5. 최종 적대적 검증 보강

11. **QR Scanner가 문서와 달리 즉시 Claim을 수행**
    QR 인식은 페어링 정보를 화면에 채우기만 하고, 서버 주소를 표시한 뒤 사용자가 `확인한 서버에 연결`을 눌러야 네트워크 Claim을 전송하도록 수정했다.

12. **범용 Custom URL Scheme 충돌 가능성**
    앱이 등록하고 서버가 발급하는 Scheme을 `jmactionhub://`로 변경했다. 구버전 링크는 수동 붙여넣기 호환에만 허용하며 앱 진입점으로 등록하지 않는다.

13. **중복 Query Item으로 인한 Swift Dictionary Precondition Failure**
    페어링 링크의 필수 항목을 하나씩 검증하고 중복·알 수 없는 항목을 명시적으로 거부하도록 수정했다.
