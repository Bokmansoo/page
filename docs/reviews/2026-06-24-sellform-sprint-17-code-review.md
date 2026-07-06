# Sellform Sprint 16 Code Review

**Sprint Goal:** URL 입력 시 백엔드에서 원문 텍스트 자동 수집 및 AI 사실 카드 후보 생성 연동, 실패 상태 매핑 및 Fallback UX 제공.

---

## 1. 주요 변경 파일 목록

- `backend/src/services/source_collector.py` (수집 엔진 및 프로젝트 통합 수집)
- `backend/tests/test_source_collector.py` (수집 엔진 단위 테스트)
- `backend/tests/test_facts.py` (사실 카드 생성 통합 테스트)
- `frontend/src/app/workspace/projects/[id]/facts/page.tsx` (URL 실패 원인 매핑 및 수동 복사 CTA)

---

## 2. 컴포넌트별 코드 분석 및 검토

### 2.1 Backend 수집 엔진 (`source_collector.py`)

#### HTMLTextExtractor
- 파이썬 표준 라이브러리 `html.parser.HTMLParser`를 확장하여 불필요한 script, style, nav, footer, header, noscript 태그 등을 필터링한 본문 순수 텍스트만 안전하게 정제 추출합니다.
- 외부 라이브러리(BeautifulSoup 등) 의존성을 최소화하여 가볍고 빠르게 빌드 및 무결성을 유지합니다.

#### fetch_url_source
- 일반적인 User-Agent 문자열 헤더를 지정하고, 10초 타임아웃을 지정하여 서버 블로킹 문제를 차단했습니다.
- 응답 상태 코드(403, 401, 429)에 대해 `blocked_or_forbidden` 실패 유형으로 명시 매핑하고, 일반 네트워크 에러나 예외 발생 시 `network_error`로 안전하게 리턴합니다.
- 20,000자 초과 텍스트는 Truncation하여 LLM 입력 제한을 방지합니다.

*개선 피드백:*
- 표준 `HTMLParser`는 비정상적인 HTML(Broken HTML tag)을 만났을 때 가끔 일부 파싱이 건너뛰어질 수 있으나, 본문 스펙 수집 목적에서는 외부 사이트 차단이 더 주된 병목이므로 경량 구현으로 적합합니다. 추후 더 고도화된 정제가 필요할 때만 `BeautifulSoup`이나 `lxml` 검토를 제안합니다.

### 2.2 API 및 AI facts 통합 (`test_facts.py`)

- `test_auto_extract_uses_url_source_text_for_fact_candidates`를 통해 모킹된 성공적인 URL 수집 텍스트가 AI 상세페이지 사실 카드 추출(Adapter) 입력으로 올바르게 병합되고, `extraction_source == "url"`로 매핑됨을 검증했습니다.
- `test_auto_extract_reports_url_failure_gracefully`를 통해 403 Forbidden 등으로 URL 수집이 실패한 프로젝트에서도 전체 프로세스가 에러 없이 완료되고, `failed_sources`에 사유가 기입되어 리턴되는 안정적인 예외 흐름을 확인했습니다.

### 2.3 Frontend UI (`page.tsx`)

- `FAILED_SOURCE_MESSAGES` 상에 URL 관련 상세 실패 원인(`blocked_or_forbidden`, `timeout`, `network_error`)에 대해 친절한 한글 안내와 안내 대응책을 맵핑했습니다.
- `autoExtractResult.failed_sources`가 존재하고 그 원본 소스가 `url`일 경우, 사용자가 "상세 정보 복사본 일괄 붙여넣기 📋"를 눌러 즉시 Bulk Modal을 띄울 수 있는 CTA 버튼 동선을 구현하여 편의성을 대폭 개선했습니다.

---

## 3. 코드 품질 및 설계적 만족도

- **안정성 (Reliability):** 외부 네트워크 요청에 따른 예외(Timeout, 403 등)를 정상 예외 범위 내로 포섭하여 API 크래시를 방지함.
- **사용자 경험 (UX):** 단순한 에러 메시지 노출을 넘어, 차단 유형별(쿠팡, 스마트스토어 등)로 구체적인 대체 방법(상세 복사 후 붙여넣기)을 제공하고 CTA 버튼으로 즉각 유도함.
- **테스트 커버리지 (Coverage):** URL 수집의 개별 예외(성공, 차단, 타임아웃, 네트워크 실패)에 대한 mock 단위 테스트와 auto-extract 통합 연동 테스트를 확보하여 회귀 결함을 통제함.
