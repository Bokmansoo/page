# Sellform Sprint 23 LLM Web Browsing Fact Extraction Troubleshooting

## 1. Issue: Regression in Existing HTTP Failure Tests after Fallback Integration
- **발생 증상**: `test_auto_extract_reports_url_fallback_without_failing` 및 `test_auto_extract_reports_url_failure_gracefully` 기존 2개 테스트가 `failed_sources` 비교 부분에서 AssertionError로 실패함.
  ```text
  E AssertionError: assert [{'source': '...key_missing'}] == [{'source': '...twork_error'}]
  E At index 0 diff: {'source': 'url', 'reason': 'web_browsing_api_key_missing'...} != {'source': 'url', 'reason': 'network_error'...}
  ```
- **원인 분석**: 1차 httpx URL 수집 실패 시 무조건 web browsing fallback 로직이 실행되도록 구성했기 때문입니다. API 키가 주어지지 않은 일반 로컬 테스트 환경에서는 `WebBrowsingCollector`가 `web_browsing_api_key_missing`을 반환하며, 기존 HTTP 에러(예: 403 Forbidden, 404 Not Found) 정보가 덮어씌워지는 부작용(Side-effect)이 발생했습니다.
- **해결 조치**: 
  - `source_collector.py` 내의 에러 보존 로직을 고도화했습니다.
  - web browsing fallback 수집의 실패 원인이 `web_browsing_disabled` 또는 `web_browsing_api_key_missing`인 경우는 **물리적 환경 요인에 의한 Fallback 미실행** 상태이므로, 1차 HTTP 수집에서 겪은 원래의 실패 원인(`blocked_or_forbidden` 또는 `network_error`)을 그대로 `failed_sources`에 기록해 반환하게 분기 처리했습니다.
  - 이를 통해 API 키가 설정되지 않은 기존 테스트 환경과의 하위 호환성을 완벽하게 보장했습니다.

## 2. Issue: Mocking Attribute Error during WebBrowsingCollector Patching
- **발생 증상**: 통합 테스트에서 `monkeypatch.setattr` 호출 시 다음과 같은 모듈 속성 누락 에러 발생.
  ```text
  AttributeError: module 'src.services.source_collector' has no attribute 'WebBrowsingCollector'
  ```
- **원인 분석**: `source_collector.py` 내부에서 `WebBrowsingCollector`를 호출 시 함수 내부에서 로컬 import(`from src.services.web_browsing_collector import WebBrowsingCollector`)를 수행했기 때문에, 테스트 런타임에서 `src.services.source_collector` 모듈 객체의 속성으로 조회되지 않아 패칭(Patching)에 실패한 것입니다.
- **해결 조치**:
  - `source_collector.py` 파일의 최상단(Module scope)으로 `from src.services.web_browsing_collector import WebBrowsingCollector`를 이동시켜, 모듈 속성으로 정상 노출되도록 개선했습니다.
  - 이로써 `monkeypatch.setattr`을 통한 테스트 환경 격리 및 Mocking이 정상 작동하게 되었습니다.
