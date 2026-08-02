# iOS v0.2.0 Focus Matrix 제품·기능 명세

## 제품 정의

Action Hub iOS Focus Matrix는 Todo 목록을 새로 저장하는 기능이 아니다. 서버의 실제 Action을 중요도·긴급도 관점으로 빠르게 분류하고, 사람과 AI의 오늘 책임을 확정한 뒤 Focus Session으로 연결하는 Native Decision Surface다.

## 정보 구조

```text
Focus Tab
├── Triage
├── Matrix
├── Dual Big3
├── Active Session
└── Day Close
```

## Triage 카드

표시:

- 제목·프로젝트·원장
- Deadline/Due
- 예상시간
- Executor/Worker
- 중요도·긴급도·Q 추천
- 신뢰도
- 추천 근거

동작:

- Q1 실행
- Q2 계획
- Q3 위임
- Q4 보류

제스처와 동일한 명시적 버튼, VoiceOver Action을 함께 제공한다. Q4는 삭제가 아니며 Q3는 자동 Dispatch가 아니다.

## Matrix

- 2×2 사분면
- 각 사분면 Count와 Action 목록
- Untriaged Count
- Q1 Action에서 Focus 시작
- Q2는 Big3/Calendar 계획 후보
- Q3는 Executor 변경 후보
- Q4는 Day Close 또는 보류

## Dual Big3

- Human 최대 3개
- AI 최대 3개
- 오늘 available_minutes
- Human/AI committed minutes
- overload warning
- 동일 Action 중복 선택 금지

## Micro Steps

- 3~5개 권장
- 완료 Toggle
- Human/AI/Hybrid/External 표시
- preferred worker와 예상시간

## Focus Session

- 10·25·50·90분 preset
- 단일 활성 세션
- Green/Yellow/Red
- Pause/Resume/Extend
- Complete/Abandon
- 종료 메모
- Action 완료는 별도 선택

## Day Close

미완료 업무마다 다음 중 하나를 명시적으로 고른다.

- 내일 또는 특정일 재계획
- 작업 분할
- AI/사람에게 위임
- Deadline 변경
- 취소
- 외부 응답 대기

## 접근성

- 제스처 단독 기능 금지
- Dynamic Type
- VoiceOver Label/Hint/Custom Action
- 색상 외 텍스트로 Traffic State 표시
- Reduce Motion 환경에서 핵심 동작 유지
