# Sellform URL Source Collection Troubleshooting

본 문서는 Sprint 16 (URL Source Collection) 개발 및 테스트 과정에서 직면한 이슈들과 해결책, 그리고 향후 고도화 과제를 정리한 문서입니다.

---

## 1. 직면한 문제 및 해결 과정

### Issue 1: `test_facts.py` 통합 테스트 실패 (`test_auto_extract_reports_url_fallback_without_failing`)

- **증상:** pytest 실행 시 `test_auto_extract_reports_url_fallback_without_failing` 테스트 케이스에서 어설션 실패(AssertionError) 발생.
- **원인 분석:**
  - 기존 코드에서는 URL 수집 기능이 온전히 구현되지 않아 `url_collection_deferred` 라는 지연 실패 메시지를 반환하도록 목(Mock) 응답이 설계되어 있었습니다.
  - Sprint 16에서 실제 `fetch_url_source` 수집기를 통해 URL Fetch가 수행됨에 따라, 테스트 내 예제 도메인(`https://supplier.example.com/product/123`)이 모킹되지 않은 실제 네트워크 예외 상태로 넘어가면서 `network_error` 상태 코드가 반환되었습니다.
  - 이로 인해 기대값(`url_collection_deferred`)과 실제값(`network_error`) 간의 불일치가 발생해 테스트가 깨졌습니다.
- **해결책:**
  - URL 수집 실패 시 500 에러를 유발하지 않고 Graceful하게 fallback하는 테스트 본연의 목적에 맞춰, `url_collection_deferred` 기대를 실제 에러 상황인 `network_error`를 기대하도록 assert 구문을 갱신했습니다.
  - `test_facts.py` 내 해당 테스트 케이스 어설션 대상을 수정하여 백엔드 모든 통합 테스트가 18 Passed로 통과되었습니다.

---

## 2. 향후 과제 및 개선 방안 (Future Work)

1. **동적 렌더링(SPA) 웹사이트 지원**:
   - 현재 구현은 `httpx`를 통한 정적 HTML Fetch 방식을 취하므로, 네이버 스마트스토어나 일부 React/Vue 기반 쇼핑몰 등 자바스크립트 실행을 필수로 요구하는 동적 페이지 수집 시 본문 데이터가 비어있거나 불완전하게 수집되는 한계가 있습니다.
   - 향후 서비스 고도화 시, 백엔드에 헤드리스 브라우저(Playwright / Puppeteer 등)나 별도의 프리렌더링 API 서비스 연동을 검토하여 동적 스크래핑 성능을 보강할 수 있습니다.
2. **IP 차단 및 Rate Limit 스케일 방어**:
   - 다수의 프로젝트가 동시에 같은 공급처 사이트 URL을 수집 요청할 경우, Sellform의 서버 IP가 일시적으로 스마트스토어나 외부 도매 사이트로부터 차단(429 Too Many Requests)될 가능성이 있습니다.
   - 이를 예방하기 위해, Host별로 요청 스로틀링(Throttling) 큐를 도입하거나 스케줄링 간격을 두어 수집하도록 큐 시스템(Celery 등) 도입을 고려해볼 수 있습니다.
3. **HTMLTextExtractor 예외 처리 개선**:
   - `html.parser.HTMLParser`가 복잡하게 깨진 HTML 문서를 만나 파싱 중단이 발생할 경우에 대비하여, 파싱 예외 발생 시 원문 자체를 최소 가공하여 반환하거나 Fallback으로 정규식을 활용해 단순 태그만 제거하는 2차 안전장치를 검토합니다.
