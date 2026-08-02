# iPhone 단축어 연결 가이드

## 전제

- Action Hub가 iPhone에서 접근 가능한 HTTPS 또는 개인 VPN 주소로 실행 중
- 서버 `.env`의 `ACTION_HUB_API_KEY` 설정 완료
- iPhone PWA **설정** 화면에 같은 API 키 저장 완료
- Safari에서 Action Hub를 홈 화면에 추가

## 권장 입력 방식의 우선순위

1. **복사 → 홈 화면 Action Hub → 붙여넣기**: 가장 단순하고 앱별 공유 차이가 적다.
2. **공유 시트 단축어 → 계획 생성 → PWA 검토 화면 열기**: 자주 입력할 때 가장 빠르다.
3. **음성 받아쓰기 → 같은 단축어 실행**: 이동 중 입력에 사용한다.

Action Hub는 원문을 URL query에 넣지 않는다. URL에는 임의의 `plan_id`만 전달하고, 실제 원문은 인증된 API 요청 본문으로 전송한다.

## 단축어 A — 선택한 텍스트를 검토 화면으로 보내기

### 1. 공유 입력 설정

1. 단축어 앱에서 새 단축어 생성
2. 단축어 상세 설정에서 **공유 시트에서 보기** 활성화
3. 입력 유형은 `텍스트`와 `URL`만 선택
4. 입력이 없을 때는 `클립보드 가져오기`를 사용하도록 분기

### 2. Action Hub 계획 생성

`URL의 콘텐츠 가져오기` 동작을 추가한다.

- URL: `https://ACTION-HUB-HOST/api/v1/inbox/parse`
- 메서드: `POST`
- 요청 본문: `JSON`
- 헤더:

```text
Content-Type: application/json
X-Action-Hub-Key: YOUR_ACTION_HUB_API_KEY
```

JSON 본문:

```json
{
  "text": "[단축어 입력]",
  "source": "ios-shortcut",
  "timezone": "Asia/Seoul"
}
```

### 3. 검토 화면 열기

1. API 응답 사전에서 `id` 값을 가져온다.
2. 다음 URL을 만든다.

```text
https://ACTION-HUB-HOST/?plan_id=[응답의 id]
```

3. `URL 열기` 동작으로 Safari 또는 홈 화면 PWA를 연다.
4. Action Hub가 해당 계획을 불러오면 항목을 수정·승인·실행한다.

이 흐름에서는 카카오톡·메일 원문이 브라우저 주소, 방문 기록, 프록시 access log에 남지 않는다. `plan_id`만 URL에 남고 계획 조회는 API 키로 보호된다.

## 단축어 B — 클립보드 빠른 등록

1. `클립보드 가져오기`
2. 위 단축어 A의 API 호출 동작 재사용
3. 응답 `id` 추출
4. `?plan_id=` 검토 화면 열기
5. 이름을 `Action Hub에 보내기`로 지정
6. 홈 화면, 제어 센터 또는 뒷면 탭에 배치

## 단축어 C — 음성 등록

1. `텍스트 받아쓰기`
2. 언어를 `한국어`로 지정
3. 받아쓴 텍스트를 위 단축어 A의 JSON `text`에 전달
4. 응답 `id`로 검토 화면 열기

Siri 호출 문구 예:

```text
액션 허브 등록
```

## API 키 보안

- API 키가 포함된 단축어는 개인 기기에서만 사용한다.
- 단축어 파일이나 iCloud 링크를 다른 사람에게 공유하지 않는다.
- 기기를 분실했거나 단축어를 공유했다면 서버 `.env`의 키를 교체한다.
- 인터넷에 직접 노출할 때는 반드시 HTTPS, 방화벽 또는 Tailscale 같은 개인 VPN을 사용한다.
- 키는 외부 서비스의 Todoist·GitHub·Google 토큰과 다르다. Action Hub 키만 단축어에 넣는다.

## PWA Web Share Target

지원되는 Android·Chromium 환경에서는 설치형 PWA가 시스템 공유 대상으로 표시될 수 있다. 이 경로는 `POST /share-target`을 사용하고 원문을 sessionStorage로 넘기므로 URL에 원문을 노출하지 않는다.

iPhone에서는 브라우저·앱별 지원 차이가 있으므로 **복사+PWA** 또는 위 **단축어 방식**을 공식 경로로 사용한다.

## 오류 처리

| 증상 | 확인할 항목 |
|---|---|
| `401 Invalid API key` | 단축어 헤더와 서버 `.env` 키가 같은지 확인 |
| PWA가 계획을 불러오지 못함 | PWA 설정에 API 키가 저장되어 있는지 확인 |
| `422` | 텍스트가 비어 있지 않은지, JSON 본문 형식 확인 |
| 서버 접속 불가 | HTTPS 주소, VPN, 방화벽, 서버 상태 확인 |
| 같은 계획이 다시 열림 | 동일 원문은 중복 방지됨; 새 계획이 필요하면 API에 `force_new: true` 추가 |
