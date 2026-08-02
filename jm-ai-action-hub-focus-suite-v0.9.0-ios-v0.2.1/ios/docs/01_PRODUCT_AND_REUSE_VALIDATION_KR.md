# 제품·기존 솔루션 재사용 상세 검증

## 1. 결론

네이티브 iOS 앱 개발은 정당하다. 그러나 개발 대상은 업무 원장이 아니라 **Action Hub 고유 제어 기능**으로 제한한다.

Todoist, Calendar, GitHub 앱은 각각 자신의 원장 관리에는 우수하지만 다음을 제공하지 않는다.

- Action Hub 자연어 분석 결과 일괄 검토
- 일정·Todo·GitHub 후보를 한 화면에서 승인
- 사람/AI/Hybrid/External 실행자 상태
- AI Worker → PR → CI → Merge 연결
- Waiting-for/Follow-up
- Action Hub Audit/Conflict/Retry
- 서버 Pairing/Connector 상태

따라서 새 앱은 “또 하나의 Todo 앱”이 아니라 **네이티브 Action Control Surface**다.

## 2. 기술 대안

| 대안 | 장점 | 단점 | 판정 |
|---|---|---|---|
| PWA만 유지 | 개발비 최소 | Share Extension, Keychain, Widget, App Intents, APNs, Face ID 통합 한계 | 백업 UI로 유지 |
| WKWebView Wrapper | 빠른 포장 | 네이티브 가치 부족, 이중 Navigation/인증 | 제외 |
| React Native | 다중 플랫폼 | iOS Extension/Widget/App Intents에 Swift 필요, 현재 Android 요구 없음 | 제외 |
| Flutter | UI 생산성 | Extension/Widget/App Intents 브리지 증가 | 제외 |
| SwiftUI | Apple 기능 직접 사용, 코드량 최소 | macOS/Xcode 필요 | 채택 |

## 3. Apple 기능 재사용

| 요구 | 재사용 프레임워크 | 직접 개발 범위 |
|---|---|---|
| QR | AVFoundation | Pairing Parser/UX |
| 음성 | Speech | Transcript → Capture |
| 생체 잠금 | LocalAuthentication | 잠금 정책 |
| 안전 저장 | Keychain Services | Session Codable Store |
| 공유 | Share Extension | 원자적 Queue |
| 앱/확장 공유 | App Groups | Queue/Snapshot/Cursor |
| 시스템 명령 | App Intents | Capture/Open Intent |
| 위젯 | WidgetKit | 최소 Dashboard Snapshot |
| 푸시 | UserNotifications/APNs | Token 등록/Route |
| 기회형 동기화 | BackgroundTasks | Capture Flush/Refresh |

## 4. OpenAPI Client 결정

Swift OpenAPI Generator를 검토했지만 v0.1.0에서는 다음 이유로 Runtime Dependency를 추가하지 않았다.

- iOS가 사용하는 모바일 Endpoint는 제한된 Subset이다.
- Linux에서 Swift Client–FastAPI 실제 E2E를 직접 실행해야 했다.
- Server OpenAPI의 56 Operation 전체를 앱 바이너리에 생성할 필요가 없다.
- 생성기/Transport Runtime 버전 추가가 초기 App Store 검증 표면을 늘린다.

대신 다음을 적용했다.

```text
서버 OpenAPI 저장
→ operationId 고정
→ SHA/필수 Operation 검사
→ Compact Typed Client
→ 실제 HTTP E2E
```

모바일 API가 확대되어 수동 Client 코드가 임계치를 넘으면 Swift OpenAPI Generator로 전환한다.

## 5. 개발하지 않은 기능

- 자체 Todo/Calendar/Kanban
- Provider Token 직접 연결
- 파일/PDF/OCR Intake v0.1
- Live Activity v0.1
- Apple Watch v0.1
- 자동 Merge/배포
- Push에 상세 업무 표시
- Share Extension에서 LLM 호출
- iOS 자체 Parser

## 6. 최종 경계

```text
Capture / Review / Approve / Observe  → iOS
Parse / Route / Execute / Sync / Audit → Server
Source of Truth                        → Existing Apps
```
