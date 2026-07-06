# Sellform Sprint 24 보완 트러블슈팅

## 1. 문제: 프론트와 백엔드 파싱 기준이 달라질 수 있음

- **증상**: `BrowserAssistedSourcePanel`은 프론트에서 줄 단위로 후보를 만들고, 백엔드에는 별도 `parse_bulk_fact_text`가 존재했다.
- **영향**: 나중에 파싱 기준이 달라지면 사용자 화면의 후보와 서버 검증 결과가 어긋날 수 있다.
- **조치**: `/api/v1/projects/{project_id}/facts/bulk/parse` API를 추가하고, 프론트가 이 API를 사용하도록 변경했다.

## 2. 문제: 배송/리뷰/광고성 줄까지 후보가 될 수 있음

- **증상**: 붙여넣은 원문에 `무료배송`, `구매후기`, `쿠팡 추천 상품` 같은 문장이 있으면 후보로 들어갈 수 있었다.
- **영향**: 상세페이지 근거 카드 품질이 낮아진다.
- **조치**: `bulk_fact_parser.py`에 커머스 노이즈 키워드 필터를 추가했다.

## 3. 문제: 후보별 근거 추적이 약함

- **증상**: 후보별 `source_text`가 단일 라인만 저장되면 전체 맥락을 나중에 확인하기 어렵다.
- **영향**: 상세페이지 생성/검수 단계에서 “이 말이 어디서 나왔는지” 확인하기 어렵다.
- **조치**: 파싱 API가 후보별 `source_text`에 전체 붙여넣기 원문과 추출 후보를 함께 넣도록 했다.

## 4. 검증

```text
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_bulk_fact_parser.py backend\tests\test_facts.py -q
24 passed
```

```text
npm.cmd run build
Compiled successfully
```
