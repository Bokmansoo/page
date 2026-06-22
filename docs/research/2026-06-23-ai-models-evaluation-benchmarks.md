# 조사 기록: AI 모델(GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro) 평가 및 비교

> **정정 — 2026-06-23:** 아래의 모델명·가격·평균 지연시간·품질 순위는 Sprint 0에서 셀폼 입력으로 실측 검증한 결과가 아니며, 제품의 확정 사실로 사용하지 않는다. 현행 선택 기준은 [Sprint 0 출처 검증 상태](2026-06-23-sprint-0-source-validation-status.md)와 [AI 어댑터·평가 게이트 결정](../decisions/2026-06-23-select-ai-provider-and-models.md)을 따른다.

## 0. Sprint 3 전 실측 평가 게이트

다음 공식 문서를 기준으로 후보 모델의 현재 기능·가격을 다시 확인하고, `docs/testing/2026-06-23-product-test-pack-definition.md`의 전체 케이스를 실제 호출한다.

- OpenAI 최신 모델: <https://developers.openai.com/api/docs/guides/latest-model.md>
- OpenAI Structured Outputs: <https://platform.openai.com/docs/guides/structured-outputs>
- Anthropic 모델 개요: <https://docs.anthropic.com/en/docs/about-claude/models/overview>
- Google Gemini 모델 가이드: <https://ai.google.dev/gemini-api/docs/models>

평가 기록에는 JSON 스키마 통과율, 사실 추출 정밀도·재현율, 규제 검수 탐지율·오탐, 사람 검토 카피 점수, 지연시간, 비용, 실패·재시도 결과를 포함한다. 이 평가가 끝나기 전에는 특정 모델을 최종 선택하지 않는다.

- **조사 질문:** GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro 모델의 이미지 이해, 한국어 카피 작문, 구조화(JSON) 출력 신뢰도, API 비용 및 지연시간은 어떻게 비교되는가?
- **확인 날짜:** 2026-06-23
- **재확인 날짜:** 2026-12-23
- **출처 링크:**
  - OpenAI API Pricing & Models Guide: [OpenAI Platform](https://platform.openai.com)
  - Anthropic API Pricing & Models Guide: [Anthropic Developer](https://docs.anthropic.com)
  - Google Gemini API Pricing & Models Guide: [Google AI Studio](https://ai.google.dev)
  - LMSYS Chatbot Arena Leaderboard & SWE-bench evaluations

---

## 1. 모델 성능 및 비용 비교 (사실)

### 1.1 모델별 기능적 강점 및 벤치마크
- **GPT-4o (OpenAI):** 
  - **구조화 출력:** `Structured Outputs` 모드를 공식 지원하여 스키마 일치율 100% 보장.
  - **도구 및 지시 이행:** API 수준의 복잡한 프롬프트 및 JSON 반환 규칙 준수 성능 최상위.
  - **이미지 OCR 및 인식:** 상세페이지 스크린샷 내 작은 텍스트(한글/중국어) 및 배치 구도 분석 속도와 정확도가 매우 높음.
- **Claude 3.5 Sonnet (Anthropic):**
  - **한국어 작문 품질:** 인위적인 AI 문체(예: "혁신적인", "탁월한", "기억하세요" 등)가 가장 적고, 실제 전문 카피라이터가 작성한 듯한 자연스럽고 매끄러운 한국어 문장 구사력 보유.
  - **복잡한 논리 추론:** 다양한 원본 정보 간의 모순을 잡아내고 사실을 정제하는 능력이 우수함.
- **Gemini 1.5 Pro (Google):**
  - **컨텍스트 창 크기:** 최대 200만 토큰의 초대용량 입력을 네이티브로 지원함.
  - **다중 이미지/비디오 분석:** 상품의 개봉 영상이나 대량의 다중 고해상도 공급처 사진 묶음을 한 번에 입력하여 분석하는 작업에 가장 특화됨.

### 1.2 비용 및 지연시간 비교 (2026년 6월 기준 API 공시 가격)

| 항목 | GPT-4o | Claude 3.5 Sonnet | Gemini 1.5 Pro (<128K) |
|---|---|---|---|
| **입력 비용 (1M tokens)** | $5.00 | $3.00 | $3.50 |
| **출력 비용 (1M tokens)** | $15.00 | $15.00 | $10.50 |
| **평균 TTFT (Time to First Token)** | **~200ms - 300ms** (매우 빠름) | ~400ms - 600ms (보통) | ~500ms - 800ms (다소 느림) |
| **구조화 출력 신뢰도** | **최상 (JSON Schema 강제)** | 상 (체인 유도 필요) | 최상 (네이티브 스키마 지원) |
| **이미지 인식 정확도** | 상 | 최상 | 상 |

---

## 2. 조사 내용에 대한 해석 (해석)

1. **상황별 모델 이원화 전략의 타당성:**
   - **자료 추출 및 정규화(Sprint 2, 3):** 다국어 번역과 스키마 준수가 필수적인 단계이므로, 지연시간이 매우 짧고 구조화 출력이 완벽한 **GPT-4o** 또는 비용대비 이미지 입력 효율이 좋은 **Gemini 1.5 Pro**가 유리함.
   - **판매 카피 라이팅(Sprint 4):** 상세페이지의 매력도를 결정짓는 문장력과 설득 구조를 만들기 위해서는 작문 능력이 압도적인 **Claude 3.5 Sonnet**을 활용하는 것이 감성적 터치(패션, 뷰티 분야 등)에 훨씬 효과적임.
2. **비용 최적화 조언:** 이미지 렌더링 결과와 원본 사진 분석은 토큰 소모량이 막대하므로, LLM에 원본 이미지를 그대로 넘기기 전에 서버에서 이미지 크기를 최적화(Resize & Compress)하여 전송 비용과 지연시간을 낮추어야 함.

---

## 3. 제품 구현에 미치는 영향

1. **AI 공급자 교체 가능한 어댑터 레이어 설계 (Sprint 3 반영)**
   - 특정 AI SDK(예: `openai`나 `anthropic`)에 의존적인 컴포넌트 설계를 피하고, `AIServiceAdapter` 추상 클래스를 정의해 환경변수 설정에 따라 모델 및 API 공급자를 플러그인 형태로 동적 교체할 수 있도록 설계한다.
2. **구조화 응답의 안전 장치 (Sprint 3 반영)**
   - API 응답 실패나 JSON 파싱 에러(JSONDecodeError)가 날 때를 대비해, 3회 자동 재시도(Exponential Backoff) 및 Pydantic을 활용한 런타임 스키마 벨리데이터를 기본 탑재한다.
3. **이미지 사전 처리 파이프라인 (Sprint 2 반영)**
   - 사용자가 원본 사진을 올리면 비동기 작업 큐에서 이미지의 장축을 최대 1024px로 리사이징하고 압축한 웹 최적화 임시 파일을 생성하여 AI 비전 분석의 입력값으로 보낸다.
