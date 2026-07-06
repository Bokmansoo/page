# Sellform Sprint 23 LLM Web Browsing Fact Extraction Code Review

## 1. Overview
본 코드 리뷰는 **Sprint 23: LLM Web Browsing Fact Extraction**의 기획 및 구현 결과를 검토합니다. 이번 스프린트에서는 쇼핑몰 등의 크롤링 차단 정책으로 인해 1차 HTTP 수집이 실패한 경우, OpenAI Responses API의 `web_search_preview` 도구를 활용하여 상품 정보를 우회/보조 수집하고, 수집된 근거를 기반으로 AI 사실 카드 후보를 생성하는 아키텍처를 도입했습니다.

## 2. Key Changes

### A. Web Browsing Config & Collector 추가
- **[config.py](file:///c:/page/backend/src/config.py)**: Web Browsing 기능의 온/오프 토글(`SELLFORM_WEB_BROWSING_ENABLED`), 모델 지정(`gpt-5.4-nano`), 타임아웃 및 최대 글자수 파라미터 설정을 Settings 모델에 추가했습니다.
- **[web_browsing_collector.py](file:///c:/page/backend/src/services/web_browsing_collector.py)**: OpenAI Responses API를 활용하여 주어진 상품명 및 링크에 대한 한국어 상품 정보 요약을 가져오는 보조 수집 계층을 구현했습니다. 응답 객체 내의 `output_text` 콘텐츠 블록을 정상 추출하며 타임아웃 및 예외 처리를 정밀화했습니다.

### B. HTTP 수집 실패 시 Fallback 연결
- **[source_collector.py](file:///c:/page/backend/src/services/source_collector.py)**:
  - 1차 URL 수집(httpx)이 차단되거나 실패한 경우, `WebBrowsingCollector`를 호출하여 실시간 검색/브라우징으로 요약 텍스트를 소싱하도록 아키텍처를 확장했습니다.
  - **하위 호환성 보장**: API 키가 아예 없거나 설정이 꺼져 있는 개발/테스트 환경에서는 Web Browsing fallback 실패 원인을 기록하는 대신, 기존 1차 HTTP 수집 에러(`blocked_or_forbidden`, `network_error`)를 그대로 `failed_sources`에 기록해 복귀하도록 예외 분기를 설계했습니다. 이를 통해 기존 팩트 추출 단위 테스트들과의 정합성을 100% 유지합니다.

### C. 프론트엔드 오류 메시지 확장
- **[page.tsx (facts)](file:///c:/page/frontend/src/app/workspace/projects/%5Bid%5D/facts/page.tsx)**:
  - `FAILED_SOURCE_MESSAGES` 매핑 테이블에 `web_browsing_api_key_missing`, `web_browsing_empty_result`, `web_browsing_failed` 에러 키들을 한글 메시지로 추가 정의했습니다.
  - 사용자가 "AI가 어떤 원인으로 소싱을 실패했는지"와 "그에 따라 상세페이지 텍스트를 수동으로 입력해야 하는 근거"를 시각적으로 인지할 수 있게 피드백을 강화했습니다.

## 3. Test & Verification Review
- **[test_web_browsing_collector.py](file:///c:/page/backend/tests/test_web_browsing_collector.py)**: API 키 미지정 실패 시나리오 및 OpenAI Responses API를 활용한 정상 수집 성공 Mock 테스트 케이스를 구축하여 동작을 입증했습니다.
- **[test_facts.py](file:///c:/page/backend/tests/test_facts.py)**: 1차 httpx 수집이 차단(403 Forbidden)되었을 때 `WebBrowsingCollector`가 정상적으로 호출되어, 획득한 검색 결과를 바탕으로 팩트 후보군을 자동 생성해내는 통합 연동 시나리오(`test_auto_extract_uses_web_browsing_when_url_fetch_is_blocked`)를 검증하여 패스시켰습니다.

## 4. Conclusion
구현된 폴백 아키텍처는 쿠팡, 스마트스토어 등 외부 쇼핑몰 크롤링 방지 환경에서도 AI가 웹 검색을 통해 상품 스펙과 특장점을 원활히 찾아내도록 지원합니다. 예외 분기를 매끄럽게 설계하여 기존 테스트와 환경 호환성을 깨트리지 않는 상태로 성공적으로 완성되었습니다.
