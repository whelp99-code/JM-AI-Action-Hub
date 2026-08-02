# Native iOS v0.2.1 릴리스 검증 보고서

## Linux Source 검증

- Xcode project deterministic check: PASS
- OpenAPI contract: PASS
- Expected server version: 0.9.0
- OpenAPI operations: 80
- Swift source/static project validation: PASS
- swift-format strict: PASS
- XCTest: 36 passed
- Swift Testing smoke: 1 passed
- 전체 Swift source parse: PASS
- Plist/Entitlement/Privacy Manifest lint: PASS
- Swift live client → FastAPI v0.9.0 Focus E2E: PASS

## 검증된 기능

- Focus Codable models
- API request/response paths
- Q1 classify
- Human Big3
- Micro Steps
- Focus start/pause/resume/complete
- Weekly report
- Widget Snapshot v0.1 cache 호환
- pending route handoff
- version gate

## Apple 환경 인수 필요

- Xcode Simulator generic iOS build
- App/Share/Widget target signing
- ActivityKit 실제 Lock Screen/Dynamic Island
- App Intents의 Siri/Shortcuts 등록
- Widget timeline/개인정보 처리
- Face ID
- Speech/Microphone
- APNs Live
- Archive/TestFlight
