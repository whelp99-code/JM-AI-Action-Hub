# 알려진 제한과 후속 범위

## v0.1.0 제한

- iOS 18+만 지원
- Android 없음
- Share는 Text/URL만 지원
- 사진/OCR/PDF 없음
- Live Activity 없음
- Apple Watch 없음
- iPad 전용 UX 없음
- Certificate Pinning/App Attest 없음
- 앱 자체 Offline Plan Editing 없음
- 서버 미연결 중에는 Capture만 가능
- APNs가 없어도 동작하지만 즉시 상태 알림은 제한

## v0.2 후보

- VisionKit Text Scanner
- Screenshot/Photo OCR
- PDF Text Extraction
- Attachment Upload
- Capture Preview/Redaction

## v0.3 후보

- Live Activity for long AI execution
- Apple Watch quick capture/status
- iPad split view
- Spotlight entity indexing

## 도입 조건

기능은 실제 사용 로그에서 반복 불편이 확인될 때만 추가한다.

| 기능 | 도입 조건 |
|---|---|
| OCR | 이미지에서 Action 등록이 주 5회 이상 |
| Live Activity | 10분+ AI 실행 상태 확인이 반복 |
| Watch | iPhone을 꺼내지 못해 Capture 누락 발생 |
| Offline Plan Edit | 네트워크 단절 중 Review 필요가 반복 |
| App Attest | 외부 사용자/다중 Tenant 또는 보안 요구 상승 |

## 운영·검증 경계

1. 현재 실행환경에는 Xcode/Apple SDK가 없어 App Target·Extension의 실제 Type-check/Build를 수행하지 못했다.
2. 실제 iPhone Provisioning, App Group, Face ID, Share Sheet, Siri, Widget, APNs는 물리 기기 인수가 필요하다.
3. BackgroundTasks 실행시각은 iOS가 결정하므로 즉시 업로드를 보장하지 않는다. Foreground/APNs가 주 경로다.
4. Share Extension v0.1은 Text/URL 중심이며 이미지·PDF 본문 OCR은 0.2 범위다.
5. 음성 인식 품질·On-device 지원은 언어·기기·OS 상태에 따라 달라진다.
6. Widget은 개인정보 노출을 줄이기 위해 상세 Action 조작을 제공하지 않는다.
7. Swift API 모델은 OpenAPI Snapshot, Contract Script, Live Smoke로 검증하지만 자동 생성 Client로 아직 전환하지 않았다.
8. Jailbroken Device나 OS 전체 장악을 앱 수준에서 완전히 방어할 수 없다.
9. TestFlight/App Store Privacy Label은 실제 배포 설정과 함께 최종 확정해야 한다.
10. 다중 사용자 Tenant/RBAC는 Server의 후속 범위다. 현재는 개인용 기기 Scope 모델이다.


## v0.1 운영 주의

- Delta Cursor는 서버 서명 불투명 토큰이므로 앱에서 해석하거나 생성하지 않는다.
- Production Pairing QR은 서버 구성의 공개 HTTPS URL이 없으면 발급하지 않는다.
- v0.1 Push는 사용자 표시용 Alert 중심이다. Silent `content-available` 처리를 구현하기 전에는 `remote-notification` Background Mode를 켜지 않는다.
- Widget 정보는 `privacySensitive()`이지만 실제 잠금화면 표시 정책은 실기기에서 확인한다.
