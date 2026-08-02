# iOS 수동 시험 시나리오

## TC-01 정상 Pairing

1. Server CLI QR 생성
2. 앱 QR 스캔
3. Device Name 확인
4. Dashboard 로드

기대: 관리자 API Key 없이 기기 Session 생성.

## TC-02 Pairing 만료

QR 생성 후 TTL 경과 뒤 Claim.

기대: 만료 메시지, Device 미생성.

## TC-03 외부 Pair Link

Safari에서 `jmactionhub://pair?...` 열기.

기대: 값이 Pairing 화면에 채워지지만 자동 Claim하지 않음.

## TC-04 오프라인 Share

1. Airplane Mode
2. 카카오톡 Text Share
3. Extension 성공 메시지
4. 앱 Offline Queue Count 확인
5. 네트워크 복구

기대: 정확히 한 Plan, Queue 0.

## TC-05 동시 Share

앱 직접 입력과 Share Extension을 연속 실행.

기대: 모든 Capture 보존, 파일 덮어쓰기 없음.

## TC-06 Revision Conflict

1. iPhone에서 Plan 열기
2. PWA에서 같은 Item 수정
3. iPhone에서 저장

기대: 409 Conflict 안내, 조용한 덮어쓰기 없음.

## TC-07 Approval Gate

Draft를 Approve만 수행.

기대: 외부 등록 전 Execute 별도 필요.

## TC-08 Remote Revoke

관리자 CLI로 Device Revoke 후 앱 Refresh.

기대: 401→Disconnected, 재페어링 요구.

## TC-09 Disconnect Offline

Server 중단 상태에서 앱 연결 해제.

기대: 오류 안내하더라도 Local Keychain 삭제, 앱 Disconnected.

## TC-10 APNs Privacy

실제 Review 알림 수신.

기대: Generic Alert, 고객명/원문/작업제목 없음.

## TC-11 Speech

한국어 여러 Action 발화.

기대: Text 전사, 원본 녹음 미저장, 종료 후 Microphone Indicator 해제.

## TC-12 Widget Lock Screen Exposure

Widget 확인.

기대: Count/최소 Title만 표시, 원문/Description 없음.
