# Sellform Sprint 24 Remediation Test Log

## 1. 테스트 목적

Sprint 24 브라우저 보조 수집 보완 작업이 다음 조건을 만족하는지 확인했다.

- 백엔드 파서가 숫자 불릿과 일반 커머스 노이즈를 정리한다.
- `/facts/bulk/parse` API가 후보와 제외 수를 반환한다.
- 후보별 근거에 전체 붙여넣기 원문과 추출 후보가 포함된다.
- 프론트 빌드가 깨지지 않는다.

## 2. 백엔드 테스트

### 명령

```cmd
cd /d C:\page
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_bulk_fact_parser.py backend\tests\test_facts.py -q
```

### 결과

```text
24 passed
```

### 주요 검증

- `test_parse_bulk_fact_text_filters_common_commerce_noise_and_duplicates`
  - `무료배송`, `구매후기`, `쿠팡 추천 상품` 제외 확인.
  - 중복 스펙 제거 확인.
- `test_parse_bulk_facts_returns_backend_candidates_with_full_source_context`
  - `/facts/bulk/parse` API 응답 확인.
  - `candidate_count`, `excluded_count` 확인.
  - 후보별 `source_text`에 전체 원문과 추출 후보가 포함되는지 확인.

## 3. 프론트 빌드

### 명령

```cmd
cd /d C:\page\frontend
npm.cmd run build
```

### 결과

```text
Compiled successfully
```

## 4. 결론

Sprint 24 보완 작업은 테스트와 빌드 기준을 통과했다.
