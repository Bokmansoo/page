# Grounded Page Generation Validation Test Log

## 1. 개요
* **테스트 날짜:** 2026-06-26
* **목적:** 상세페이지 생성 시 확인된 사실 카드를 중심으로 문구를 검수하고, 수치, 성능, 안전, 건강, 인증, 비교 우위 관련 근거 없는 위험 표현을 정상적으로 경고하는지 검증한다.

## 2. 테스트 환경
* **OS:** Windows
* **Backend:** FastAPI, SQLAlchemy, pytest
* **Frontend:** Next.js, TypeScript

## 3. 테스트 수행 결과

### 3.1. 백엔드 단위 및 통합 테스트 (`backend/tests/test_grounding_validator.py`)
pytest를 활용하여 총 4개의 핵심 기능을 검증하였으며, 전체 테스트 케이스가 성공하였습니다.
```powershell
uv run --project backend pytest backend/tests/test_grounding_validator.py -q
```
* **결과:** 4 passed, 17 warnings
* **테스트 케이스 명세:**
  1. `test_detects_numeric_and_performance_claim_without_evidence`: 근거(확인된 사실 카드) 없이 수치 및 성능 비교 우위 표현을 썼을 때 위험 경고를 올바르게 생성하는지 테스트.
  2. `test_maps_section_to_relevant_confirmed_facts`: 섹션 문장과 사실 카드 사이의 토큰 정합성을 계산하여, 50% 이상의 키워드가 매칭되는 팩트 카드를 올바르게 매핑하는지 테스트.
  3. `test_builds_grounding_review_summary`: 섹션 리스트 전체에 대한 요약 통계(주의 필요 건수, 근거 연결된 섹션 수, 사용된 사실 카드 수)가 정확하게 집계되는지 테스트.
  4. `test_get_page_grounding_review_endpoint`: `/projects/{project_id}/page/grounding-review` API 엔드포인트가 정상적으로 200 OK와 grounding review JSON 데이터를 반환하는지 테스트.

### 3.2. 프론트엔드 빌드 검증 (`frontend/`)
Next.js 프로덕션 빌드를 수행하여 타입 체크 및 린트 검증을 통과했습니다.
```powershell
cd frontend
npm.cmd run build
```
* **결과:** ✓ Compiled successfully (Generating static pages 9/9, Finalizing page optimization)
* **특이사항:** `GroundingReviewPanel.tsx` 컴포넌트와 `page-editor/page.tsx` 내 실시간 검수 요약 바 및 상세 탭 렌더링에 필요한 TypeScript 컴파일 오류 없음.
# 후속 보완 검증 - 섹션 부분 재생성 저장 누락 수정

## 4. 실패 재현

전체 백엔드 테스트 실행 중 다음 회귀 테스트가 실패했다.

```powershell
uv run pytest -q
```

```text
FAILED tests/test_pages_sprint4_remediation.py::test_regenerate_page_section_applies_user_instruction
```

원인은 `regenerate_page_section`에서 새로 생성한 `new_copy`를 `section.body_copy`에 저장하지 않은 채 응답을 반환한 것이었다.

## 5. 단일 회귀 테스트 재검증

```powershell
uv run pytest tests/test_pages_sprint4_remediation.py::test_regenerate_page_section_applies_user_instruction -q
```

- 결과: `1 passed`

## 6. 전체 회귀 검증

```powershell
uv run pytest -q
```

- 결과: `90 passed, 520 warnings`

```powershell
cd frontend
npm.cmd run build
```

- 결과: `Compiled successfully`

## 7. 결론

Sprint 20 보완 후 상세페이지 근거 검수 기능과 기존 page editor 섹션 부분 수정 기능이 함께 정상 동작한다.
