# PRD 및 기능명세 — JM-AI Action Hub iOS v0.1.0

## 1. 제품 정의

> iPhone에서 자연어·음성·공유 입력을 잃지 않고 수집하고, Action Hub의 분석 결과를 검토·승인하며 사람·AI·외부 원장의 실제 실행 상태까지 확인하는 네이티브 Companion.

## 2. 핵심 사용자

- 여러 AI 개발 프로젝트를 동시에 운영하는 개인 사용자
- 카카오톡·메일·회의·웹에서 Action이 자주 발생하는 컨설턴트/대표
- Todoist·Calendar·GitHub는 유지하되 통합 승인 흐름이 필요한 사용자

## 3. Jobs To Be Done

1. 다른 앱을 보던 중 3초 안에 업무를 수집한다.
2. 여러 문장을 일정·Todo·개발 작업으로 분해한 결과만 검토한다.
3. 불확실한 날짜·Repository·실행자를 iPhone에서 수정한다.
4. 승인한 업무만 실제 원장에 보낸다.
5. AI가 맡은 업무가 PR·CI·Merge까지 갔는지 확인한다.
6. 상대방 회신 대기와 Follow-up을 놓치지 않는다.

## 4. 기능 요구사항

| ID | 요구사항 | 우선순위 | 구현 |
|---|---|---:|---:|
| FR-IOS-001 | QR 기반 Server Pairing | Must | 완료 |
| FR-IOS-002 | Keychain Session | Must | 완료 |
| FR-IOS-003 | Text/Clipboard Capture | Must | 완료 |
| FR-IOS-004 | Share Extension | Must | 완료 |
| FR-IOS-005 | Offline Queue | Must | 완료 |
| FR-IOS-006 | Batch Upload/Idempotency | Must | 완료 |
| FR-IOS-007 | Review Plan List/Detail | Must | 완료 |
| FR-IOS-008 | Item Edit/Reject | Must | 완료 |
| FR-IOS-009 | Approve와 Execute 분리 | Must | 완료 |
| FR-IOS-010 | Revision Conflict | Must | 완료 |
| FR-IOS-011 | Today Decision | Must | 완료 |
| FR-IOS-012 | AI/Waiting/Failure Activity | Must | 완료 |
| FR-IOS-013 | Device Revoke | Must | 완료 |
| FR-IOS-014 | APNs Registration/Navigation | Should | 완료 |
| FR-IOS-015 | Biometric Lock | Should | 완료 |
| FR-IOS-016 | Korean Speech Capture | Should | 완료 |
| FR-IOS-017 | App Intent/Shortcuts | Should | 완료 |
| FR-IOS-018 | Widget | Should | 완료 |
| FR-IOS-019 | OCR/PDF | Could | 0.2 예정 |
| FR-IOS-020 | Live Activity/Watch | Could | 0.3 예정 |

## 5. 비기능 요구사항

### 보안

- Remote HTTP 금지
- 관리자 API Key 저장 금지
- Provider Credential 저장 금지
- Pairing Code 자동 Claim 금지(Custom URL)
- Push 민감정보 금지
- Keychain ThisDeviceOnly

### 신뢰성

- Capture 원자적 파일 저장
- 서버 Client ID Idempotency
- 성공/중복 Receipt 후에만 로컬 삭제
- Token Refresh 직렬화
- Delta Cursor 영속화
- Revision 409 노출

### UX

- Dynamic Type
- VoiceOver Label
- Dark Mode
- Offline Count
- Error Message 사용자 언어화
- 외부 원장으로 Deep Link

## 6. 상태 모델

### 연결

```text
loading → disconnected → connected
                    └→ failed → retry/disconnect
```

### Capture

```text
local_pending → uploading → processed/duplicate
                        └→ failed → retry
```

### Plan

```text
draft → approved → queued/executing → registered
     └→ rejected
```

### 실제 Action

```text
registered → waiting/running/human_review → completed
                                   └→ failed
```

## 7. 제외 범위

- iOS 자체 Todo/Calendar 편집 전체 기능
- GitHub PR Review 전체 기능
- Provider OAuth를 iOS에서 직접 수행
- Share Extension 장시간 Network/LLM 작업
- 자동 Approval/Execute
- Push Notification에서 민감한 상세내용 표시
