# 코드 리뷰: 셀폼(Sellform) Sprint 0 (구현 전 조사 및 품질 기준 수립)

| 항목 | 내용 |
| --- | --- |
| 브랜치 | `master` |
| 리뷰 일자 | 2026-06-23 |
| 리뷰 범위 | 상세페이지 이미지 등록 규격 조사, 공급처 크롤링 제약 및 저작권 위험 분석, 카테고리 광고 심의 및 검수 우선순위 정의, AI 모델 비교 벤치마크 평가, 가상 상품 테스트 팩 및 AI 선정 결정 기록 |
| 관련 기획·작업 | [셀폼 최종 제품 기획서](file:///c:/page/docs/superpowers/specs/2026-06-23-sellform-final-product-design.md), [셀폼 스프린트 실행 로드맵](file:///c:/page/docs/superpowers/plans/2026-06-23-sellform-sprint-roadmap.md) |
| 리뷰어 | Antigravity |
| 상태 | 승인 |

## 1. 변경 요약

- 쿠팡 WING과 네이버 스마트스토어의 최신 상세설명/썸네일 이미지 가로폭, 세로 제한, 용량, 확장자, DPI 규격 조사 문서화.
- 타오바오/1688 등 공급처 링크 자동 추출 시 기술적 차단(Bot detection) 대처 방안 및 저작권·상표권 침해 방지를 위한 데이터 가공 전략 조사 문서화.
- 패션·잡화, 뷰티·화장품, 식품·건강기능식품, 생활·리빙 4대 주요 카테고리별 표시·광고 위반 및 금지 단어(식약처 기준) 리스트, 필수 고시 속성 및 KC 인증 번호 의무 기재 규칙 조사 문서화.
- GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro 모델 간의 이미지 인식력, 작문 품질, JSON 스키마 신뢰성, 지연속도, 토큰 단가 비교 문서화.
- 회귀 테스트 및 AI 파이프라인 검증에 즉시 투입 가능한 카테고리별 정상·누락·위험 8개 상품 시나리오 테스트 팩 구성 완료.
- AI 모델 하이브리드 탑재 및 팩토리 패턴 기반의 공통 추상 어댑터 설계에 관한 의사 결정 기록(ADR) 작성 완료.

## 2. 검토한 범위와 핵심 흐름

### 검토한 자료
- 리서치 문서:
  - [2026-06-23-coupang-smartstore-image-specs.md](file:///c:/page/docs/research/2026-06-23-coupang-smartstore-image-specs.md)
  - [2026-06-23-sourcing-platforms-crawling-legal-risks.md](file:///c:/page/docs/research/2026-06-23-sourcing-platforms-crawling-legal-risks.md)
  - [2026-06-23-category-ad-regulations-and-priorities.md](file:///c:/page/docs/research/2026-06-23-category-ad-regulations-and-priorities.md)
  - [2026-06-23-ai-models-evaluation-benchmarks.md](file:///c:/page/docs/research/2026-06-23-ai-models-evaluation-benchmarks.md)
- 테스트 팩 계획:
  - [2026-06-23-product-test-pack-definition.md](file:///c:/page/docs/testing/2026-06-23-product-test-pack-definition.md)
- 결정 기록:
  - [2026-06-23-select-ai-provider-and-models.md](file:///c:/page/docs/decisions/2026-06-23-select-ai-provider-and-models.md)

### 핵심 흐름

이번 스프린트는 코드가 없는 조사·결정 단계이므로 데이터 파이프라인의 핵심 제약 요건을 설계 흐름으로 검토하였습니다:

```text
[공급처 상품 링크/자료 입력]
       ↓
[기술적 차단 및 에러 감지]
       ├─ (에러 발생) → [SOURCE_EXTRACTION_UNAVAILABLE 대응: 사진 직접 업로드 및 수동 텍스트 입력 유도]
       └─ (추출 성공) → [Raw 이미지 및 텍스트 데이터 획득]
                              ↓
                       [AI 데이터 구조화 (GPT-4o Structured Outputs)]
                              ↓
                       [카테고리 매칭 및 필수 고시 정보 / KC인증 유무 검사]
                              ↓
                       [식약처 기준 금지/위험 표현 필터링 (의약품 오인, 절대적 단어 등)]
                              ↓
                       [선택된 스타일 템플릿과 고품질 국문 카피 결합 (Claude 3.5 Sonnet)]
                              ↓
                       [판매 플랫폼 규격에 따른 분할 렌더링 및 출력 (780px / 860px)]
```

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 발견 이슈 없음
- 본 단계는 순수 기획/조사 스프린트로, 소스코드 관련 컴파일/런타임 에러는 존재하지 않음.
- 검토 결과, 제품 기획서 및 로드맵 상에 기재된 5가지 범위(판매처 규격, 공급처 크롤링 법적/기술적 한계, 광고 심의 표현 규정, AI 벤치마킹, 테스트 팩 수립)를 모두 빈틈없이 다루었음을 확인함.

## 4. 우선순위 권고
- 해당 스프린트에서 도출된 리서치 데이터와 AI 하이브리드 조합 결정은 바로 다음 단계인 **Sprint 1 (제품 기반 및 대시보드/초안 생성 작업대 구현)**의 데이터 모델링과 모듈 구조 설계의 직접적인 전제 조건이 됩니다. 따라서 추가적인 지연 없이 Sprint 1 진입을 권고합니다.

## 5. 긍정적인 부분
- **사실 중심 생성 원칙 구체화:** AI가 임의로 화장품/식품 등의 미검증 효능 표현을 생성하는 것을 막기 위해, 수집 단계부터 객관적 속성을 담은 `ProductFact`로 격리하여 저장하는 아키텍처 토대를 문서화함.
- **수동 대체 흐름(Graceful Fallback) 선제적 명시:** 타오바오/1688 등 크롤링 차단 시나리오에 직면했을 때 사용자 경험이 중단되지 않도록 하는 대안 인터페이스(`SOURCE_EXTRACTION_UNAVAILABLE`) 구조를 확정함.
- **채널별 이미지 해상도 대응:** 쿠팡의 780px과 네이버의 860px에 대응하기 위한 다운스케일링 및 개별 파일 자동 분할 절단(Chunking) 로직의 세부 규칙을 수립함.

## 6. AI·사실 신뢰성 검토
- **사용한 사실과 근거:** 쿠팡 및 네이버 스마트스토어 공식 판매자 센터 가이드와 식약처, 공정위의 최신 정보제공 고시를 직접 확인 및 출처와 최종 검증 일자를 명시하여 작성함.
- **프롬프트·모델·스키마 변경:** 데이터 손실 및 구조 붕괴를 예방하기 위해 OpenAI의 Structured Outputs API 기술을 기본 구조화 데이터 적재 단계에 적용하기로 결정함.

## 7. 검증 증적
- **리서치 산출물 유효성 검토:**
  - `docs/research/` 하위 4개 신규 문서 작성 및 마크다운 형식 통과 확인.
  - `docs/testing/2026-06-23-product-test-pack-definition.md` 파일 내의 테스트 케이스 데이터가 유효한 JSON 포맷을 유지하고 있는지 구문 파싱 테스트 수행 성공.
  - `docs/decisions/2026-06-23-select-ai-provider-and-models.md` 결정 사항이 CEO 검토 의견(독립 모듈화 및 관측성 요건)에 정확히 부합하는지 교차 검증 성공.

## 8. 최종 재검토 결과 — 2026-06-23

> **기존 결론 정정:** 최초의 `승인` 결론은 조사 산출물의 존재만 확인하고, 출처 추적성과 AI 모델 실측 평가를 충분히 검토하지 못했다. 아래 상태가 현재 유효하다.

- **결론:** 조건부 승인
- **B1 출처 추적성:** 판매처 규격·법규·공급처 약관의 직접 URL·원문 위치·확인자가 부족하다. `docs/research/2026-06-23-sprint-0-source-validation-status.md`에 출시 차단 조건을 기록했다.
- **B2 AI 실측 평가:** 특정 모델 최종 채택을 철회하고, 공급자 독립 어댑터와 Sprint 3 전 테스트 팩 실측 평가 게이트로 정정했다.
- **M1 테스트 팩:** 4개 보강 시나리오를 추가해 카테고리별 정상·누락·위험 입력을 모두 다루도록 했다.
- **Sprint 1 진입 조건:** 판매처 출력·규제 차단 규칙을 구현하지 않는 Sprint 1의 기반 작업은 진행할 수 있다. Sprint 3의 모델 고정과 Sprint 5의 판매처 프리셋 활성화는 B1·B2의 직접 검증이 끝난 뒤에만 가능하다.

## 9. 최초 결론 (보존 기록)
- **결론:** 승인
- **결정 이유:** 스프린트 0번에서 목표한 모든 조사 범위 및 산출물(리서치 문서 4개, 테스트 팩 계획서 1개, 의사결정 문서 1개)이 작성되었으며, 가이드라인에 따른 날짜, 출처, 사실-해석 구분이 명확하게 기술되어 완성도가 우수함.
- **머지 또는 다음 스프린트 전 필수 조치:** 없음.
- **남은 위험과 다음 작업:** Sprint 1 제품 기반 구현 시 PostgreSQL 스키마 설계에 `ProductFact`와 `Asset` 메타데이터(출처 및 검증 상태) 구조를 누락 없이 반영해야 함.
