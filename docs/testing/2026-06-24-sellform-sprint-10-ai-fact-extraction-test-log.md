# 테스트 실행 로그: Sellform Sprint 10 AI 사실 카드 자동 추출

- 날짜: 2026-06-24
- 목적: 상품 텍스트/이미지/URL fallback 기반 AI 사실 카드 자동 추출 기능의 동작과 회귀 안정성을 검증한다.

## 1. TDD RED 확인

먼저 `backend/tests/test_facts.py`에 자동 추출 API 테스트를 추가했다.

추가 테스트:

- `test_auto_extract_creates_reviewable_fact_candidates_from_manual_text`
- `test_auto_extract_skips_duplicate_candidates`
- `test_auto_extract_reports_url_fallback_without_failing`
- `test_auto_extract_creates_image_asset_candidate`

구현 전 실행 결과:

```text
uv run --project backend pytest backend/tests/test_facts.py -q

결과:
3 failed, 6 passed

주요 실패:
POST /api/v1/projects/{project_id}/facts/auto-extract
-> 405 Method Not Allowed
```

이 실패로 자동 추출 API가 아직 구현되지 않았음을 확인했다.

## 2. Sprint 10 단위 테스트

```text
uv run --project backend pytest backend/tests/test_facts.py -q

결과:
10 passed, 109 warnings in 1.16s
```

검증 내용:

- 수동 텍스트에서 5개 이상 사실 후보 생성
- 자동 생성 후보는 `unknown` 또는 `needs_revision` 상태로 저장
- 자동 생성 후보는 `needs_review=true`
- 중복 후보 재생성 방지
- URL 직접 수집 실패/보류가 전체 API 실패로 번지지 않음
- 이미지 자산 기반 후보가 `source_asset_id`와 연결됨

## 3. 백엔드 전체 회귀 테스트

```text
uv run --project backend pytest -q

결과:
54 passed, 415 warnings in 8.34s
```

## 4. 프론트 빌드 검증

```text
cd frontend
npm.cmd run build

결과:
Compiled successfully
Linting and checking validity of types ...
Generating static pages (9/9)
```

## 5. 판단

Sprint 10의 1차 범위인 “수동 텍스트 + 업로드 이미지 기반 사실 후보 자동 생성”은 테스트와 빌드를 통과했다.

URL 직접 수집은 이번 구현에서 의도적으로 deferred 처리했다. 캡차, 로그인, 약관, SSRF, timeout 위험이 있으므로 현재는 사용자가 입력한 텍스트와 업로드 자산을 분석 대상으로 사용하고, URL은 fallback 안내로 기록한다.

