# Focus UX·접근성·안전 기준

## 스와이프 방향

| 방향 | 의미 | 대체 버튼 |
|---|---|---|
| 위 | Q1 지금 실행 | 실행 |
| 오른쪽 | Q2 계획 | 계획 |
| 왼쪽 | Q3 위임 | 위임 |
| 아래 | Q4 보류 | 보류 |

오작동 방지를 위해 분류 결과는 서버에 Audit로 기록하며, 삭제·Worker Dispatch·외부 변경은 발생하지 않는다.

## Traffic State

- Green: 계획시간 80% 미만
- Yellow: 80~100%
- Red: 계획시간 이상

색상과 함께 텍스트·아이콘·남은/초과 시간을 표시한다.

## Live Activity 개인정보

- `privacySensitive` 적용
- 업무 원문·고객 연락처·금액·회의 내용 미표시
- 제목은 사용자가 잠금화면 민감정보 노출 설정에 따라 시스템 보호
- 제어는 앱 열기 중심
- 승인·외부 실행·Merge 버튼은 제공하지 않음

## App Intents 안전선

허용:

- Capture Text
- Today 열기
- Focus 열기
- Triage 열기
- Matrix 열기

금지:

- 전체 승인
- Action 실행
- Worker Dispatch
- PR Merge
- Day Close 자동 이월
