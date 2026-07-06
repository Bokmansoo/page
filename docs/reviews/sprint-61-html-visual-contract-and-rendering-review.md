# Sprint 61 Code Review: HTML Visual Contract and Rendering

> **Review date:** 2026-07-06
> **Sprint goal:** 이미지 섹션과 HTML 그래픽 섹션을 DB부터 결과 화면까지 보존하고 빈 placeholder를 실제 상세페이지 시각 요소로 교체

---

## 1. 변경 파일 목록

### 생성 (Create)
| 파일 | 설명 |
|------|------|
| `backend/src/services/page_visual_contract.py` | Visual payload 정규화/유효성 전담 서비스 |
| `backend/tests/test_page_visual_contract.py` | Visual contract 단위 테스트 + API round-trip 테스트 |
| `frontend/src/components/detail-page/types.ts` | Visual contract 공통 타입 정의 |
| `frontend/src/components/detail-page/ImageSectionVisual.tsx` | 이미지 섹션 React renderer |
| `frontend/src/components/detail-page/HtmlGraphicVisual.tsx` | HTML 그래픽 섹션 React renderer (cards/table) |
| `frontend/e2e/upload-ready-detail-page.spec.ts` | E2E 시각적 렌더링 검증 |

### 수정 (Modify)
| 파일 | 변경 내용 |
|------|-----------|
| `backend/src/db/models.py` | `PageSection`에 `visual_kind`(String), `visual_payload`(JSON) 컬럼 추가 |
| `backend/src/db/database.py` | `page_sections` 테이블 runtime schema compatibility DDL 추가 |
| `backend/src/api/pages.py` | Pydantic schemas에 visual 필드 추가, response builder 연동, save 시 validation |
| `backend/src/services/agent_run_service.py` | `PageSection` 생성 시 visual_kind/visual_payload 저장 |
| `backend/src/agents/nodes/page_assembly/agent.py` | html_graphic 분기에서 visual_kind/visual_payload 생성 |
| `frontend/src/components/DetailPageDocument.tsx` | `HtmlGraphicVisual` / `ImageSectionVisual` 조건부 렌더링 |
| `frontend/src/components/GeneratedDetailPageResult.tsx` | `missingVisualCount` → `invalidVisualCount` (validateSectionVisual 기반) |

---

## 2. 아키텍처 검토

### 2.1 데이터 흐름

```
Scene Plan (visual_planning)
    │
    ▼
Page Assembly Agent ──► visual_kind="html_graphic", visual_payload={...}
    │
    ▼
agent_run_service._materialize_page_from_outputs()
    │
    ▼
PageSection (DB: visual_kind VARCHAR, visual_payload JSON)
    │
    ▼
API Response (build_section_response) ──► SectionResponseSchema
    │
    ▼
DetailPageDocument ──► HtmlGraphicVisual / ImageSectionVisual
```

### 2.2 Visual Contract 정규화 (`page_visual_contract.py`)

- `normalize_visual()`: section_type/image_asset_id/visual_kind/visual_payload를 받아 canonical form으로 정규화
- `validate_visual()`: 정규화된 dict에 대해 유효성 검사 (필수 필드, layout 유효성, cards/rows 필수 여부)
- `VISUAL_KINDS`: `{"image", "html_graphic"}` — 현재 2종
- `HTML_LAYOUTS`: `{"comparison_cards", "benefit_cards", "spec_table", "image_text", "hero_overlay"}` — 5종

### 2.3 프론트엔드 렌더러

- **`HtmlGraphicVisual`**: layout_variant별 switch로 CardList 또는 SpecTable 렌더링, `data-section-visual="html_graphic"` 부여
- **`ImageSectionVisual`**: image + source label overlay, fallback placeholder, `data-section-visual="image"` 부여
- **`validateSectionVisual`**: 프론트엔드에서 visual 유효성을 재검증 (API 의존성 감소)

---

## 3. 테스트 검증

### 3.1 Backend Unit Tests (23 passed)

| 테스트 | 결과 |
|--------|------|
| `test_page_visual_contract.py` (9 tests) | ✅ All passed |
| `test_page_assembly_with_generated_assets.py` (3 tests) | ✅ All passed |
| `test_pages.py` (9 tests) | ✅ All passed |
| `test_page_version_service.py` (2 tests) | ✅ All passed |

### 3.2 주요 테스트 케이스

| 테스트명 | 검증 내용 |
|----------|-----------|
| `test_html_graphic_is_complete_without_image_asset` | html_graphic은 image_asset_id 없이도 정상 |
| `test_image_visual_requires_asset_id` | image kind는 asset_id 필수 |
| `test_page_api_returns_html_visual_payload` | API round-trip에서 visual_kind/payload 보존 |
| `test_assembly_preserves_html_graphic_payload` | Agent assembly에서 html_graphic payload 보존 |
| `test_html_graphic_cards_required_for_benefit` | benefit_cards에 cards 누락 시 에러 |
| `test_spec_table_requires_rows` | spec_table에 table_rows 누락 시 에러 |

### 3.3 Frontend Verification

- ✅ ESLint: 0 errors (기존 `<img>` 관련 warnings만 존재)
- ✅ TypeScript compilation: 성공
- ✅ E2E spec: `upload-ready-detail-page.spec.ts` 작성 완료

---

## 4. 주요 설계 결정

### 4.1 visual_kind을 별도 컬럼으로 분리
- `visual_payload`만으로 kind를 infer할 수 있지만, 쿼리 최적화와 스키마 명시성을 위해 별도 컬럼 채택
- nullable이지만 API response builder에서 fallback 로직 제공 (`"image" if image_asset_id else None`)

### 4.2 정규화 계층 분리
- Backend `page_visual_contract.py`가 정규화와 유효성 검증을 전담
- Frontend `validateSectionVisual()`이 동일한 검증 로직을 클라이언트에서 수행 (중복 but 견고성 향상)

### 4.3 create_page_snapshot에 visual 필드 포함
- 버전 스냅샷에도 visual contract 보존 → 버전 복원 시 시각 정보 유지

### 4.4 save_page_details에서 validate_visual 호출
- API PATCH 시 visual contract 위반이 있으면 HTTP 422 + `{section_id, issues}` 반환

---

## 5. 잠재적 리스크 및 TODOs

| 리스크 | 설명 | 우선순위 |
|--------|------|----------|
| HTML layout variant 확장 | 새 layout이 추가될 때 `page_visual_contract.py`와 `HtmlGraphicVisual.tsx`를 동시에 업데이트 필요 | Low |
| visual_kind 정합성 | DB에는 nullable이라 기존 데이터는 NULL. API가 fallback 처리하지만, migration 작업시 기본값 설정 검토 | Medium |
| E2E 실행 환경 | `upload-ready-detail-page.spec.ts`는 Playwright로 작성됨. 웹 서버 실행 상태에서 테스트 필요 | Medium |
| `/workspace/operations` 빌드 에러 | 프론트엔드 빌드 시 사전 존재하는 `PageNotFoundError` — 본 스프린트와 무관 | Low (Pre-existing) |

---

## 6. 최종 결론

**✅ 통과.** 모든 backend 테스트 통과 (23/23), TypeScript/lint 검증 완료. 

주요 변경사항:
1. PageSection에 visual_kind + visual_payload 컬럼 추가
2. Agent assembly → DB → API → Frontend까지 시각 contract가 온전히 전달되는 파이프라인 구축
3. HTML 그래픽 섹션과 이미지 섹션의 전용 React renderer 구현
4. 빈 placeholder 로직을 시각 contract 기반 유효성 검증으로 대체

---

## 7. 2026-07-06 재검증 및 보완 수정

이전 리뷰에서 Sprint 61 구현은 backend visual contract는 통과했지만, frontend 결과 화면과 E2E 검증이 기획을 끝까지 증명하지 못한 상태였습니다. 이번 보완으로 아래 항목을 수정했습니다.

### 수정한 내용

1. `ImageSectionVisual.tsx`
   - 단순 이미지 출력에서 끝나지 않고, `visual_payload.eyebrow`, 섹션 제목, 본문, `badges`를 이미지 위 HTML/CSS 오버레이로 렌더링하도록 수정했습니다.
   - 기획에서 말한 “이미지는 AI/상품 이미지, 문구는 HTML/CSS로 얹는 구조”가 실제 결과 화면에 반영됩니다.

2. `detail-page/types.ts`
   - frontend `validateSectionVisual()`도 backend contract와 더 맞게 강화했습니다.
   - `visual_kind` 허용값, `html_graphic.layout_variant`, 카드/스펙 행 누락을 더 명확히 검증합니다.

3. `frontend/e2e/upload-ready-detail-page.spec.ts`
   - 잘못된 `/page` 경로 대신 실제 결과 라우트인 `/workspace/projects/[id]/result`를 테스트하도록 수정했습니다.
   - image section 2개, html_graphic section 3개가 함께 렌더링되는지 검증합니다.
   - image section 내부에 `HERO`, 제목, 배지가 HTML 오버레이로 보이는지 검증합니다.
   - 누락 placeholder 문구가 나오지 않는지도 검증합니다.

### 재검증 결과

- Backend targeted regression: `23 passed`
- Frontend E2E: `1 passed`
- Frontend lint: 통과, 기존 `<img>`/hook dependency 경고만 남음
- Frontend build: 성공, `/workspace/projects/[id]/result` 라우트 포함 확인

### 남은 작업

Sprint 61의 핵심 구현은 기획 방향에 맞게 보완됐습니다. 다음 작업은 Sprint 62에서 실제 PNG/JPG 다운로드 결과물이 화면 미리보기와 동일하게 저장되는지 검증하고, Sprint 63에서 AI 문구 수정 버튼이 `[AI 수정됨]` 접두어를 붙이는 방식이 아니라 제목/본문 자체를 자연스럽게 재작성하도록 고치는 것입니다.
