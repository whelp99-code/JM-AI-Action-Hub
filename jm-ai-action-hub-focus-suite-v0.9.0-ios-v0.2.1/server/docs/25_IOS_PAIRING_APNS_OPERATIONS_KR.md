# iOS Pairing·APNs 운영 가이드

## 1. Production 준비

```dotenv
ACTION_HUB_APP_ENV=production
ACTION_HUB_API_KEY=<admin secret 32+>
ACTION_HUB_MOBILE_ENABLED=true
ACTION_HUB_MOBILE_PUBLIC_BASE_URL=https://action-hub.example.com
ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET=<separate secret 32+>
ACTION_HUB_WORKER_INLINE=false
```

확인:

```bash
action-hub check --json
curl https://action-hub.example.com/readiness
curl https://action-hub.example.com/api/v1/mobile/capabilities
```

## 2. Pairing

```bash
action-hub mobile-pairing \
  --base-url https://action-hub.example.com \
  --qr-output /tmp/action-hub-pairing.svg \
  --print-qr
```

운영 규칙:

- 화면 공유나 메신저에 QR을 남기지 않는다.
- 5분 내 사용자 본인이 스캔한다.
- 사용 후 SVG를 삭제한다.
- 실패가 반복되면 새 Pairing을 생성한다.

기기 확인:

```bash
action-hub mobile-devices
```

해제:

```bash
action-hub mobile-revoke <device-id>
```

## 3. APNs Key

Apple Developer 계정에서 APNs Token Signing Key (`.p8`)를 발급한다.

```dotenv
ACTION_HUB_APNS_TEAM_ID=TEAMID
ACTION_HUB_APNS_KEY_ID=KEYID
ACTION_HUB_APNS_BUNDLE_ID=com.example.actionhub.ios
ACTION_HUB_APNS_PRIVATE_KEY_PATH=/run/secrets/AuthKey_KEYID.p8
```

주의:

- `.p8`는 재다운로드가 제한되므로 비밀 저장소에 보관한다.
- Git/ZIP/Docker Image에 넣지 않는다.
- 서버 프로세스만 읽을 수 있도록 파일 권한을 제한한다.

```bash
chmod 600 /run/secrets/AuthKey_KEYID.p8
```

## 4. Bundle과 Environment

- Debug/TestFlight 개발 검증에서 등록된 Token의 `push_environment`를 확인한다.
- Release는 `production`, Debug는 `sandbox`로 빌드 설정한다.
- 서버는 기기별 Environment에 따라 APNs Host를 선택한다.

## 5. Test Push

앱에서 알림 권한을 허용하고 Token 등록 후:

```http
POST /api/v1/mobile/devices/me/push-test
Authorization: Bearer <device-token>
```

Worker가 Push Queue를 처리해야 한다.

```bash
action-hub-worker --once
```

확인 대상:

- `push_notifications.state=sent`
- iPhone 수신
- 잠금화면에 민감 원문 없음
- 알림 탭 시 Review 또는 Activity 이동

## 6. 장애

### APNs 미설정

- 핵심 앱 기능 영향 없음
- Push Queue는 실패/재시도 상태
- 앱 Foreground Sync, Background Refresh, 수동 Sync 유지

### 410 / Unregistered

- 해당 Push Token을 더 이상 사용하지 않도록 운영자가 기기 상태를 확인한다.
- 앱 재실행 시 APNs 등록을 다시 수행하고 새 Token을 서버에 갱신한다.

### Provider Token 오류

- Team ID, Key ID, `.p8`, Bundle ID 확인
- 서버 시간 동기화 확인
- Key 폐기 여부 확인

## 7. 개인정보

APNs Payload는 Event와 내부 ID만 포함한다. Alert 제목/본문도 일반 문구를 사용한다. 상세 원문은 앱이 열린 뒤 인증된 HTTPS API로 조회한다.
