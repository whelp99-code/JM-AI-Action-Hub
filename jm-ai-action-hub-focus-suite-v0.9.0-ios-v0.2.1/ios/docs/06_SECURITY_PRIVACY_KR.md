# JM-AI Action Hub iOS 보안·개인정보

## 1. 기기 저장

| 데이터 | 저장 위치 | 보호 |
|---|---|---|
| Access/Refresh Token | Keychain | AfterFirstUnlockThisDeviceOnly |
| Offline Capture | App Group File | Atomic + File Protection |
| Widget Snapshot | App Group File | 최소 Count/Title, File Protection |
| Delta Cursor | App Group File | File Protection |
| Biometric Preference | UserDefaults | 민감정보 없음 |

저장하지 않는 데이터:

- 관리자 API Key
- Todoist/GitHub/Google/Fireflies Token
- APNs `.p8`
- 음성 원본
- Provider Password

## 2. 개인정보 원칙

- Share/Clipboard/Speech는 사용자가 명시적으로 실행할 때만 수집
- Clipboard 자동 감시 금지
- Speech 원본 녹음 저장 금지
- Push에는 원문·고객명·작업 제목 금지
- Widget은 잠금화면 노출을 고려해 최소 요약만 저장
- 로그에 Bearer/Refresh/Pairing Code 금지

## 3. 인증

- QR의 Server URL은 HTTPS 필수
- Access Token은 짧은 수명
- Refresh는 회전하며 Server Reuse Detection 지원
- 기기 Remote Revoke 지원
- 앱 연결 해제는 Remote 실패와 무관하게 Local Credential 삭제

## 4. Face ID/Passcode

`deviceOwnerAuthentication`을 사용해 Face ID가 불가능할 경우 Device Passcode Fallback을 허용한다.

잠금 범위:

- Today 상세
- Review 원문
- AI Worker 상태
- Activity
- Settings

Share Extension의 빠른 수집은 App Lock과 별개로 허용해 Capture 마찰을 줄인다.

## 5. Threat Notes

| 위협 | 처리 |
|---|---|
| 악성 웹의 jmactionhub://pair | 자동 Claim하지 않고 Pairing UI 확인 |
| 탈옥/기기 전체 장악 | 완전 방어 불가, Remote Revoke와 짧은 Access Token |
| App Group 내 파일 변조 | Server Client ID/Content Hash 검증, malformed quarantine |
| APNs Payload 노출 | Generic 내용만 사용 |
| Screenshot 노출 | 현재 Screen Capture 차단 미구현; 운영 정책으로 보완 |
| Backup 복원 | Keychain ThisDeviceOnly Token은 타 기기로 이동하지 않음 |

## 6. Privacy Manifest

현재 Manifest 선언:

- Tracking: false
- Other User Content: App Functionality
- Device ID: App Functionality
- UserDefaults Required Reason

실제 App Store 제출 전 Xcode Privacy Report와 Apple 요구 Reason Code를 다시 검토한다.
