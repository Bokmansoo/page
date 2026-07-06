# Sprint 36 - 이미지 자산 자동 매핑 고도화 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 업로드/수집/생성된 상품 이미지를 상세페이지 7단 구조의 각 섹션에 자동 배치하여, Figma와 PNG 결과물에 실제 이미지가 자연스럽게 들어가도록 만든다.

**Architecture:** 기존 `Asset`, `PageSection.image_asset_id`, Figma visual layout 구조를 유지한다. 새 이미지 매핑 서비스가 이미지 메타데이터, OCR/AI caption, 파일명, source_type을 기반으로 section별 image role을 점수화하고, 사용자가 page-editor에서 수동 보정할 수 있게 한다.

**Tech Stack:** FastAPI, Python, PostgreSQL, Pillow/OCR metadata, TypeScript, Next.js, Figma Plugin API, Pytest, Jest.

---

## 1. 배경

Sprint 35에서 Figma 결과물의 시각 레이아웃을 개선하더라도, 실제 상품 이미지가 섹션에 들어가지 않으면 결과물은 여전히 placeholder 중심으로 보인다.

상세페이지 품질은 “어떤 이미지가 어디에 들어가는지”에 크게 좌우된다.

예시:

- 대표 제품 이미지 → HERO, PURCHASE
- 사용 장면 이미지 → PROBLEM, LIFESTYLE
- 제품 클로즈업 → SOLUTION, FEATURES
- 인증/라벨 이미지 → PROOF, PRODUCT_INFORMATION
- 구성품 이미지 → PURCHASE

Sprint 36은 이미지 자체 생성이 아니라 “이미 존재하는 이미지를 올바른 섹션에 넣는 작업”에 집중한다.

## 2. 범위

### 포함

- 이미지 자산 role 분류 모델 추가
- section별 image role 요구사항 정의
- 자동 매핑 점수화
- 중복 이미지 사용 제한/허용 정책
- page-editor에서 섹션별 이미지 매핑 상태 표시
- 사용자가 이미지 매핑을 수동 변경할 수 있는 UX
- Figma Plugin payload와 PNG export에 매핑된 이미지 반영
- 이미지 부족 상태 경고

### 제외

- AI 이미지 생성
- 외부 URL 이미지 대량 크롤링
- Figma 스타일 후보 선택
- 소셜 영상 프레임 추출

## 3. 목표 결과

사용자가 상품 이미지 여러 장을 업로드하거나 URL 수집으로 이미지를 가져온 뒤, 버튼 한 번으로 아래 매핑이 자동 생성되어야 한다.

```text
HERO              -> 대표 제품 이미지
PROBLEM           -> 사용 환경/고객 불편 이미지
SOLUTION          -> 제품 작동/클로즈업 이미지
BENEFITS          -> 장점 설명용 이미지 3개 또는 대표 이미지 재사용
FEATURES          -> 기능/스펙 이미지
LIFESTYLE         -> 라이프스타일/사용 장면 이미지
PURCHASE          -> 구성품/제품 정면 이미지
```

이미지가 부족하면 “부족한 이미지 유형”을 명확히 안내한다.

## 4. 파일 구조

### Backend

- Modify: `backend/src/services/image_asset_mapper.py`
  - 이미지 asset을 `product_main`, `lifestyle_scene`, `detail_closeup`, `package_or_components`, `certification`, `background` 등으로 분류한다.
- Modify: `backend/src/services/image_asset_mapper.py`
  - section별 요구 image role과 asset 후보를 점수화해 매핑한다.
- Modify: `backend/src/services/figma_visual_layout_builder.py`
  - Sprint 35 visual layout에 mapping result를 반영한다.
- Modify: `backend/src/api/pages.py`
  - 이미지 자동 매핑 실행 API를 추가한다.
- Test: `backend/tests/test_image_asset_mapper.py`
- Test: `backend/tests/test_page_image_mapping_api.py`
- Test: `backend/tests/test_page_draft_image_mapping.py`

### Frontend

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - 섹션별 이미지 매핑 상태와 수동 변경 UI를 추가한다.
- Create: `frontend/src/components/ImageMappingPanel.tsx`
  - 이미지 매핑 전용 패널.

### Figma Plugin

- Modify: `integrations/figma-plugin/src/visual-renderer.ts`
  - mapped asset이 있는 경우 이미지 fill을 우선 사용한다.
- Test: `integrations/figma-plugin/tests/visual-renderer.test.ts`

### Docs

- Create: `docs/testing/2026-06-28-sellform-sprint-36-image-mapping-test-log.md`
- Create: `docs/reviews/2026-06-28-sellform-sprint-36-code-review.md`
- Create: `docs/troubleshooting/2026-06-28-sellform-sprint-36-image-mapping.md`

## 5. 이미지 role 정의

| role | 설명 | 우선 섹션 |
| --- | --- | --- |
| `product_main` | 제품이 가장 잘 보이는 대표 이미지 | HERO, PURCHASE |
| `lifestyle_scene` | 사람이 사용하는 장면, 공간 배치 | PROBLEM, LIFESTYLE |
| `detail_closeup` | 팬, 버튼, 소재, 표면 등 클로즈업 | SOLUTION, FEATURES |
| `package_or_components` | 구성품, 박스, 충전 케이블 등 | PURCHASE |
| `certification` | KC, 인증, 라벨, 스펙표 | PRODUCT_INFORMATION |
| `background` | 배경용 이미지 | HERO, SUMMARY |
| `unknown` | 분류 불가 | fallback 후보 |

## 6. 구현 작업

### Task 1: 이미지 asset classifier 추가

**Files:**

- Modify: `backend/src/services/image_asset_mapper.py`
- Test: `backend/tests/test_image_asset_mapper.py`

- [ ] Step 1: 실패 테스트 작성

검증 내용:

```python
def test_classifies_asset_by_filename_and_metadata():
    asset = Asset(filename="fan_product_front.png", source_type="uploaded_image")
    result = classify_image_asset(asset, metadata={"caption": "portable fan product front view"})
    assert result.primary_role == "product_main"
    assert result.confidence >= 0.6
```

- [ ] Step 2: 테스트 실패 확인

```cmd
uv run pytest backend/tests/test_image_asset_mapper.py -q
```

- [ ] Step 3: rule-based classifier 구현

초기 버전은 LLM 없이 다음 신호를 사용한다.

- filename
- mime_type
- source_type
- OCR/caption metadata
- image width/height

- [ ] Step 4: 테스트 통과 확인

```cmd
uv run pytest backend/tests/test_image_asset_mapper.py -q
```

### Task 2: section image mapper 추가

**Files:**

- Modify: `backend/src/services/image_asset_mapper.py`
- Test: `backend/tests/test_image_asset_mapper.py`

- [ ] Step 1: 실패 테스트 작성

검증 내용:

```python
def test_maps_product_main_to_hero_and_components_to_purchase():
    mapping = map_images_to_sections(sections, classified_assets)
    assert mapping["problem_statement"].asset_role in {"lifestyle_scene", "product_main"}
    assert mapping["product_information"].asset_role in {"package_or_components", "certification", "product_main"}
```

- [ ] Step 2: 테스트 실패 확인

```cmd
uv run pytest backend/tests/test_image_asset_mapper.py -q
```

- [ ] Step 3: score 기반 매핑 구현

점수 기준:

- role match: +60
- caption keyword match: +20
- unused asset bonus: +10
- exact section hint: +20
- repeated asset penalty: -15

- [ ] Step 4: 테스트 통과 확인

```cmd
uv run pytest backend/tests/test_image_asset_mapper.py -q
```

### Task 3: 자동 매핑 API 추가

**Files:**

- Modify: `backend/src/api/pages.py`
- Test: `backend/tests/test_page_image_mapping_api.py`

- [ ] Step 1: 실패 테스트 작성

API 예시:

```http
POST /api/v1/projects/{project_id}/images/auto-map
```

응답 예시:

```json
{
  "mapped_count": 5,
  "missing_roles": ["lifestyle_scene"],
  "section_mappings": [
    {
      "section_type": "problem_statement",
      "asset_id": "...",
      "role": "lifestyle_scene",
      "confidence": 0.82
    }
  ]
}
```

- [ ] Step 2: 테스트 실패 확인

```cmd
uv run pytest backend/tests/test_page_image_mapping_api.py -q
```

- [ ] Step 3: API 구현

매핑 결과는 `PageSection.image_asset_id`에 저장하고, confidence/role은 metadata 필드 또는 별도 mapping structure에 저장한다.

- [ ] Step 4: API 테스트 통과 확인

```cmd
uv run pytest backend/tests/test_page_image_mapping_api.py -q
```

### Task 4: page-editor 이미지 매핑 UX

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Create: `frontend/src/components/ImageMappingPanel.tsx`

- [ ] Step 1: 사용자가 볼 상태 정의

표시 항목:

- 섹션명
- 현재 이미지 thumbnail
- AI 추천 role
- confidence
- 변경 버튼
- 이미지 부족 경고

- [ ] Step 2: 프론트 테스트 또는 Playwright 테스트 작성

검증:

- 이미지 매핑 버튼이 보인다.
- 매핑 API 성공 후 섹션별 thumbnail이 표시된다.
- 이미지가 부족하면 missing role 안내가 보인다.

- [ ] Step 3: UI 구현
- [ ] Step 4: 프론트 빌드 확인

```cmd
cd C:\page\frontend
npm.cmd run build
```

### Task 5: Figma/PNG 결과물 반영 검증

**Files:**

- Modify: `backend/src/services/figma_visual_layout_builder.py`
- Modify: `integrations/figma-plugin/src/visual-renderer.ts`

- [ ] Step 1: visual layout에 section별 `image_asset_ref`가 들어가는지 테스트
- [ ] Step 2: Figma renderer가 `image_asset_ref`의 image bytes를 사용하도록 검증
- [ ] Step 3: PNG export에서도 같은 매핑을 사용하도록 연결 확인

## 7. 검증 명령

```cmd
uv run pytest backend/tests/test_image_asset_mapper.py backend/tests/test_page_image_mapping_api.py backend/tests/test_page_draft_image_mapping.py -q
cd C:\page\integrations\figma-plugin
npm.cmd test
npm.cmd run build
cd C:\page\frontend
npm.cmd run build
```

## 8. 완료 기준

- 이미지가 3장 이상 있는 프로젝트에서 최소 4개 섹션에 이미지가 자동 매핑된다.
- 사용자는 섹션별 이미지를 수동으로 바꿀 수 있다.
- Figma Plugin 결과물에 실제 이미지가 들어간다.
- 이미지가 부족할 경우 어떤 이미지 유형이 필요한지 안내한다.
- 자동 테스트, 수동 QA, 코드리뷰, 테스트로그, 트러블슈팅 문서가 남는다.

## 9. 2026-06-29 코드 정합성 보강

이 절은 위 계획에서 현재 코드와 다른 파일명·경로를 교정하며, 충돌할 경우 이 절을 우선한다.

### 확정 파일

- Modify: `backend/src/services/image_asset_mapper.py`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/db/models.py`
- Modify: `backend/src/services/figma_visual_layout_builder.py`
- Modify: `backend/src/services/visual_page_renderer.py`
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Create: `frontend/src/components/ImageMappingPanel.tsx`
- Modify: `integrations/figma-plugin/src/visual-renderer.ts`
- Test: `backend/tests/test_image_asset_mapper.py`
- Test: `backend/tests/test_page_image_mapping_api.py`
- Test: `backend/tests/test_page_draft_image_mapping.py`
- Test: `backend/tests/test_figma_visual_layout_builder.py`
- Create: `frontend/e2e/sprint36-image-mapping.spec.ts`

`image_asset_classifier.py`와 `section_image_mapper.py`를 새로 만들지 않는다. 기존 `image_asset_mapper.py`를 역할 분류와 점수 계산이 분리된 작은 함수들로 확장한다.

### 입력 경계

- 직접 업로드 이미지와 기존 URL 수집 흐름이 만든 `Asset`을 동일하게 처리한다.
- Sprint 36에서 외부 사이트를 새로 크롤링하지 않는다.
- URL 이미지 추출 실패는 자산 매핑 실패가 아니라 수집 단계 오류로 표시한다.
- 한 장만 있을 때는 HERO 우선, 두 장 이상일 때는 역할별 분산을 적용한다.

### 추가 TDD 작업

- [ ] **Step 1: 역할 및 신뢰도 계약 테스트 추가**

```python
def test_mapper_returns_role_confidence_and_missing_roles():
    result = map_image_assets_to_sections(sections, assets)
    assert result.assignments[0].role == "product_main"
    assert 0.0 <= result.assignments[0].confidence <= 1.0
    assert "lifestyle_scene" in result.missing_roles
```

- [ ] **Step 2: 테스트 실패 확인**

```cmd
cd C:\page\backend
uv run pytest tests/test_image_asset_mapper.py -q
```

Expected: 기존 반환형이 list이므로 `assignments` 속성 접근에서 FAIL.

- [ ] **Step 3: 기존 API 응답을 하위 호환 형태로 확장**

`POST /api/v1/projects/{project_id}/page/auto-map-images` 응답에 `missing_roles`와 각 assignment의 `role`, `confidence`를 추가한다. 기존 `assigned_count`, `skipped_count`, `assignments`는 유지한다.

- [ ] **Step 4: 수동 매핑 API 테스트 추가**

```python
def test_user_can_replace_section_image_mapping(client, project_with_page):
    response = client.patch(
        f"/api/v1/projects/{project_with_page.id}/page/sections/section-1/image",
        json={"asset_id": "asset-2"},
        headers=MOCK_HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["image_asset_id"] == "asset-2"
```

- [ ] **Step 5: 수동 매핑 API와 감사 로그 구현**

다른 프로젝트의 asset은 `400`, 권한 없는 프로젝트는 `404`, 이미지가 아닌 asset은 `422`를 반환한다. 성공 시 새 `DetailPageVersion`과 `AuditLog(action="page_section_image_changed")`를 만든다.

- [ ] **Step 6: UI 및 E2E 검증**

```cmd
cd C:\page\frontend
npx.cmd playwright test e2e/sprint36-image-mapping.spec.ts
npm.cmd run build
```

E2E는 자동 매핑 실행, 누락 역할 경고, 섹션 이미지 교체, 새로고침 후 매핑 유지까지 검증한다.

### 보강 완료 기준

- 매핑 결과가 역할, 신뢰도, 누락 역할을 제공한다.
- 업로드 이미지와 URL 수집 이미지가 동일한 매핑 파이프라인을 탄다.
- 수동 교체가 버전과 감사 로그에 남는다.
- Figma와 PNG가 같은 `PageSection.image_asset_id`를 사용한다.
