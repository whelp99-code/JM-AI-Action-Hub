# iOS Mobile API 보안 설계 및 검증

## 1. 인증 경계

기존 관리자 API는 `X-Action-Hub-Key`를 사용한다. 이 키는 모든 관리 권한을 가지므로 iOS 앱에 저장하거나 전송하지 않는다.

```text
Administrator / CLI
  └─ X-Action-Hub-Key

Native iOS Device
  └─ Authorization: Bearer <device access token>
       ├─ device_id
       ├─ scopes
       ├─ token_version
       ├─ iat / exp / jti
       └─ fixed issuer / audience
```

Access Token은 HS256 서명을 사용하고, 발급자·수신자·만료·발급시각·Scope·Token Version을 모두 검증한다. Production에서는 API Key와 분리된 32자 이상의 `ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET`이 필수다.

## 2. Pairing

### 발급

1. 관리자 인증 후 Pairing Session 생성
2. 안전한 난수 Code 생성
3. `HMAC(secret, pairing_id:code)`만 저장
4. QR에는 서버 URL, Pairing ID, 1회 Code 포함
5. 기본 5분 후 만료

### Claim

1. 앱은 먼저 `/capabilities`로 서비스·API 버전·최소 앱 버전을 검증
2. QR의 Remote URL은 HTTPS여야 함
3. Code Hash 상수시간 비교
4. 시도 횟수 증가
5. 한 Claim만 성공하도록 조건부 DB Update
6. Device와 Refresh Token Family 생성

## 3. Refresh Rotation

### 정상 흐름

```text
R1 제출
→ R1 consumed_at 기록
→ R2 생성
→ R1.replaced_by_id = R2
→ R2 + 새 Access Token 반환
```

### 응답 유실 대응

서버가 R2를 생성했지만 네트워크 응답이 사라질 수 있다. 앱이 즉시 R1을 다시 보내면 이를 침해로 오판해 기기를 해제해서는 안 된다.

따라서 기본 30초 유예 안에는 R2를 HMAC으로 재구성해 **동일 R2**를 재반환한다. 평문 Refresh Token은 DB에 저장하지 않는다.

### 재사용 탐지

유예기간 이후 R1이 다시 사용되면 다음을 수행한다.

```text
Token Family 전체 revoke
Device status = revoked
Device token_version 증가
기존 Access Token 즉시 무효화
```

보안상 이 유예는 짧게 유지한다. 높은 보안이 필요한 환경에서는 5~10초로 축소하거나 향후 App Attest/DPoP 계층을 추가할 수 있다.

## 4. Scope

기본 Scope:

```text
capture:write
plans:read
plans:edit
plans:approve
plans:execute
brief:read
activity:read
devices:write
devices:push
```

서버는 Access Token Scope와 현재 Device Scope의 교집합만 인정한다. 관리자가 DB에서 Scope를 축소하면 기존 Token의 넓은 Scope가 그대로 유지되지 않는다.

## 5. Capture Idempotency

- 기기 UUID 기반 `client_capture_id`
- DB Unique `(device_id, client_capture_id)`
- 동일 ID·동일 내용: 기존 Receipt 반환
- 동일 ID·다른 내용: 충돌 거부
- 처리 실패: 동일 ID 재시도 허용
- 동시 전송: Savepoint/Unique 충돌을 HTTP 500으로 노출하지 않음

## 6. Optimistic Concurrency

Plan과 Action Item에 `revision`을 추가한다.

```text
Client reads revision=7
Client PATCH expected_revision=7
Server is revision=8
→ HTTP 409 revision_conflict
```

클라이언트가 최신 Plan을 다시 불러와 사용자에게 재검토하게 한다. 모바일이 데스크톱의 최신 수정사항을 덮어쓰지 않는다.

## 7. Cursor

Delta Sync Cursor에는 마지막 timestamp와 entity ID가 들어가며 HMAC으로 서명된다. 클라이언트가 임의 Cursor를 구성하거나 순서를 조작하면 서버가 400으로 거부한다.

## 8. APNs 개인정보

전송 허용:

```json
{
  "event": "review_required",
  "entity_type": "plan",
  "entity_id": "internal-id"
}
```

전송 금지:

```text
원문
고객명
작업 제목
GitHub Private Repository 이름
회의 내용
외부 토큰
```

기기 잠금화면에서 민감 업무가 노출되지 않도록 Alert 문구는 일반화한다.

## 9. 운영 Secret

```dotenv
ACTION_HUB_API_KEY=<admin secret>
ACTION_HUB_MOBILE_ACCESS_TOKEN_SECRET=<separate mobile signing secret>
ACTION_HUB_APNS_TEAM_ID=<Apple Team ID>
ACTION_HUB_APNS_KEY_ID=<APNs Key ID>
ACTION_HUB_APNS_BUNDLE_ID=<app bundle id>
ACTION_HUB_APNS_PRIVATE_KEY_PATH=/run/secrets/AuthKey_XXXX.p8
```

`.p8` 파일은 ZIP, Git, Docker Image, iOS 앱에 포함하지 않는다. 런타임 Secret Mount를 사용한다.

## 10. 검증 결과

- 잘못된 Pairing Code와 만료 Session 거부
- Pairing Code 평문 미저장
- 동시 Claim 단일 성공
- Access Token 변조·과대크기·잘못된 Claim 거부
- Refresh 정상 재시도와 침해 재사용 구분
- Scope별 403
- 원격 기기 해제 후 기존 Access Token 401
- Production HTTP Pairing 거부
- Push Token 형식 검증
- Push Idempotency가 호출자의 다른 DB 변경을 Rollback하지 않음
