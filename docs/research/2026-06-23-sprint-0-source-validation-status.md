# 조사 기록: Sprint 0 출처 검증 상태와 출시 차단 조건

- **조사 질문:** Sprint 0에서 생성한 외부 규격·법규·AI 조사 문서가 구현 결정에 쓸 만큼 추적 가능한가?
- **확인 날짜:** 2026-06-23

## 확인 결과

| 영역 | 상태 | 구현에 사용할 수 있는 결론 |
|---|---|---|
| 쿠팡·스마트스토어 이미지 규격 | 미확정 | 세부 판매자 가이드 원문을 확인하기 전에는 숫자·형식·장수 제한을 하드코딩하지 않는다. |
| 공급처 크롤링·권리 위험 | 방향성 확인 | 자동 추출 실패를 기본값으로 보고 수동 입력 대체 흐름과 자산 출처 기록을 구현한다. 개별 플랫폼 약관은 실제 연동 직전 재검토한다. |
| 카테고리별 표시·광고 규칙 | 방향성 확인 | 차단성 규칙은 법률·고시 원문과 법무·규제 검토 전까지 “주의 경고”로 취급한다. |
| AI 공급자 문서 | 공식 문서 접근 확인 | 특정 모델을 고정하지 않고, Sprint 3 전 제품 테스트 팩의 실측 결과로 선택한다. |

## 확인한 공식 AI 문서

- OpenAI 최신 모델 가이드: <https://developers.openai.com/api/docs/guides/latest-model.md>
- OpenAI Structured Outputs 가이드: <https://platform.openai.com/docs/guides/structured-outputs>
- Anthropic 모델 개요: <https://docs.anthropic.com/en/docs/about-claude/models/overview>
- Google Gemini 모델 가이드: <https://ai.google.dev/gemini-api/docs/models>

## 출시 차단 조건

1. Sprint 5의 판매처 이미지 출력 프리셋은 각 판매처의 공식 원문, 직접 URL 또는 로그인 후 경로, 확인 날짜, 확인자, 캡처를 기록하기 전에는 활성화하지 않는다.
2. 뷰티·식품·건강기능식품의 최종 출력 차단 규칙은 관련 법령·고시 원문 또는 전문가 검토 근거가 없으면 경고로만 표시한다.
3. Sprint 3의 AI 공급자·모델 고정은 상품 테스트 팩 실측 평가 전에는 하지 않는다.

