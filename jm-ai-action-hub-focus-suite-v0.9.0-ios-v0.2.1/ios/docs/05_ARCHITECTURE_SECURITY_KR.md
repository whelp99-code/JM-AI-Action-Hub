# iOS 아키텍처·보안 설계

## 1. Process 경계

```text
Main App Process
Share Extension Process
Widget Process
App Intents Execution
```

여러 Process가 하나의 JSON Array를 읽고 다시 쓰면 Lost Update가 발생할 수 있다. 따라서 Capture 하나당 파일 하나를 Atomic Write하며 `client_capture_id`를 파일명으로 사용한다.

## 2. Keychain

저장:

- Device ID
- Access Token/Expires
- Refresh Token/Expires
- Server URL
- Device metadata

접근성:

```text
kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
```

이 선택은 재부팅 후 한 번 잠금 해제한 뒤 Background Upload가 가능하고, 다른 기기나 Backup으로 Token이 이동하지 않게 한다.

## 3. Network

- Remote `http://` 차단
- Loopback 개발만 HTTP 허용
- Bearer Token
- 401 한 번만 Refresh 후 Retry
- 동시 Refresh는 Actor 내 Single-flight
- Refresh 실패 시 Local Session 폐기
- Dynamic Path Segment percent encoding

## 4. Pairing Trust

앱은 QR Claim 전에 다음을 검증한다.

```text
service == JM-AI Action Hub
mobile_enabled == true
pairing_supported == true
mobile_api_version == 1
current_app_version >= minimum_ios_app_version
```

이 검증은 잘못된 서비스나 호환되지 않는 서버에 Pairing Code를 보내지 않게 한다.

## 5. Extension

Share Extension은 텍스트와 URL만 받는다. 파일/PDF/OCR은 v0.2 범위다.

```text
collect
→ trim/dedupe
→ App Group queue
→ 350ms status
→ completeRequest
```

네트워크, Parser, Provider 등록은 Extension에서 하지 않는다.

## 6. Speech

- 사용자 명시적 버튼
- Permission 확인
- 가능한 경우 On-device Recognition 우선
- 원본 오디오 저장 안 함
- 최종 Transcript만 Capture
- View 종료 시 Recognition 중지

## 7. Push

- 앱 Launch 때 이미 권한이 있으면 APNs에 다시 등록해 Device Token 변경을 갱신
- Push Payload는 Event/Internal ID만 사용
- App이 열린 뒤 인증 API로 상세 조회
- Review Event는 Plan Deep Link
- 나머지는 Activity

## 8. Biometric

앱 잠금은 `deviceOwnerAuthentication`을 사용해 Face ID뿐 아니라 기기 Passcode fallback을 허용한다. Capture Extension은 잠금 없이 저장 가능하지만 Main App 상세는 잠금 정책을 적용한다.

## 9. Widget

Widget Snapshot에는 다음만 저장한다.

- review count
- waiting count
- AI running count
- overload minutes
- Top title 최대 3개

Token, 원문, 설명, Provider payload는 저장하지 않는다.

## 10. 알려진 Trade-off

- Certificate Pinning 없음: Self-host TLS 인증서 교체 용이성을 우선. 신뢰된 HTTPS와 QR 물리 전달을 사용한다.
- App Attest 없음: 개인용 v0.1 범위. 다중 사용자·고보안 배포 시 도입 후보.
- SwiftData 없음: 원장 기능이 없고 소량 Queue/Snapshot만 필요해 파일 기반이 더 단순하다.
- OpenAPI Codegen 없음: 제한 API Subset과 Build Dependency 최소화를 우선. 계약 검증과 E2E로 보완한다.
