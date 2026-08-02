# iOS v0.2.1 Live Focus·Widget·App Intents 구현 명세

## ActivityKit

`FocusActivityAttributes`:

```text
sessionId
actionItemId
title
plannedMinutes
```

Content State:

```text
state
startedAt
plannedEndAt
pausedAt
pausedSeconds
extensionMinutes
trafficState
progress
```

지원 화면:

- Lock Screen
- Dynamic Island compact/minimal/expanded

Lifecycle:

```text
Focus start → request Activity
pause/resume/extend → update Activity
complete/abandon → end Activity
앱 재실행 → 서버 active session과 정합화
```

## Widget

Snapshot 최소 데이터:

- Review/Waiting/AI count
- Untriaged count
- Human/AI Big3 제목
- 활성 Focus 제목·종료시각·Traffic

v0.1 Snapshot과 backward-compatible decoding을 유지한다.

## App Group route handoff

Widget/App Intent가 `pending_navigation_route`를 App Group에 저장하고 앱이 active가 되면 한 번 소비한다. 직접 서버 상태를 변경하지 않는다.

## 제한

ActivityKit 컴파일·권한·Dynamic Island 배치는 Xcode/iOS SDK와 실기기에서 최종 인수가 필요하다. Linux 검증은 Swift parse, Core tests, plist/static project, contract, live Swift API client까지다.
