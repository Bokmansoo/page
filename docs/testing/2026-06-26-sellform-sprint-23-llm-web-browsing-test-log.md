# Sellform Sprint 23 LLM Web Browsing Fact Extraction Test Log

## 1. Test Overview
- **테스트 일시**: 2026-06-26
- **테스트 환경**: Local Development 환경 (FastAPI backend + Next.js frontend)
- **테스트 대상**: `WebBrowsingCollector` 및 `collect_project_sources` URL fallback 통합 연동
- **목표**: 1차 URL 수집 실패 시 OpenAI Responses API를 이용한 보조 수집 흐름이 정상 작동하고 기존 테스트 규격을 훼손하지 않는지 검증.

## 2. Automated Tests Results

### A. Web Browsing Collector 단위 테스트
- **실행 명령**:
  ```powershell
  backend\.venv\Scripts\python.exe -m pytest backend\tests\test_web_browsing_collector.py -v
  ```
- **결과**: `2 passed`
- **테스트 케이스 요약**:
  1. `test_web_browsing_collector_returns_disabled_when_api_key_missing`: API Key 누락 시 수집 실패 및 `web_browsing_api_key_missing` 사유 반환 검증 (PASS).
  2. `test_web_browsing_collector_uses_openai_responses_web_search`: OpenAI Responses API의 `web_search_preview` 도구를 사용하여 정상적으로 요약 결과가 Mocking을 통해 반환되는지 검증 (PASS).

### B. 사실 자동 추출 통합 테스트
- **실행 명령**:
  ```powershell
  backend\.venv\Scripts\python.exe -m pytest backend\tests\test_facts.py -v
  ```
- **결과**: `21 passed` (기존 20개 테스트 + 신규 통합 테스트 1개)
- **테스트 케이스 요약**:
  1. `test_auto_extract_uses_web_browsing_when_url_fetch_is_blocked` (NEW): 1차 URL httpx 수집이 403 Forbidden 등으로 실패할 때, `WebBrowsingCollector`를 fallback으로 연동하여 OpenAI Responses API 기반으로 상품 텍스트(예: "4,800mAh")를 추출하고 이를 이용해 사실 후보 카드가 정상 생성되는지 검증 (PASS).
  2. `test_auto_extract_reports_url_fallback_without_failing` & `test_auto_extract_reports_url_failure_gracefully`: 로컬 및 API 키 미등록 환경에서도 기존의 원천 HTTP 실패 사유가 `failed_sources`에 잘 보존되는지 검증 (PASS).

## 3. Manual Verification & QA (Frontend)
- **사실 확인 페이지 UI 피드백 검증**:
  - `FAILED_SOURCE_MESSAGES` 내의 신규 에러 키(`web_browsing_failed`, `web_browsing_api_key_missing`, `web_browsing_empty_result`)가 정상 바인딩됨을 확인했습니다.
  - API 키 누락 등 실질적인 수집 실패 발생 시, 우측 "AI 사실 카드 자동 생성 결과" 패널에 한글 경고 문구("AI 웹 검색을 사용하려면 OpenAI API 키가 필요합니다...")와 수동 상세 복사 붙여넣기 📋 버튼이 정상적으로 렌더링됨을 확인했습니다.

## 4. Conclusion
본 스프린트에서 제공하는 보조 수집 레이어와 하위 호환성 에러 분기 로직은 자동 테스트 및 빌드를 통해 완벽하게 검증되었습니다.
