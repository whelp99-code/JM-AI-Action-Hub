# JM-AI Action Hub 릴리스 검증 안내

현재 릴리스는 **v0.7.0**이다.

- 최신 상세 검증: `docs/20_RELEASE_VERIFICATION_V070_KR.md`
- 테스트·인수 기준: `docs/09_TEST_ACCEPTANCE_KR.md`
- 단계별 완료 보고: `docs/06_PHASE_COMPLETION_REPORT_KR.md`
- v0.1→v0.7 업그레이드: `docs/19_UPGRADE_V010_TO_V070_KR.md`

v0.1.0의 과거 27개 테스트·단방향 등록 기준은 현재 릴리스 판정에 사용하지 않는다. v0.7.0은 Outbox, Webhook, Reconciliation, AI Worker, Follow-up, Planning, Fireflies, Personal Rule, Weekly ROI를 포함한 폐쇄형 상태 모델을 기준으로 검증한다.

현재 자동 기준:

```text
54 passed
warnings treated as errors
statement coverage >= 80%
Python compile PASS
JavaScript syntax PASS
```

Wheel·HTTP·압축본 재검증과 최종 SHA-256은 릴리스 생성 시 `docs/20_RELEASE_VERIFICATION_V070_KR.md` 및 `SHA256SUMS-jm-ai-action-hub-v0.7.0.txt`에 기록한다.
