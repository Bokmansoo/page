# Sprint 45 - 상세페이지 패키지 및 AI 에디터 셸 코드 리뷰

> 이 문서는 최초 구현 시점의 리뷰입니다. 보완 완료 결과는
> `2026-07-02-sellform-sprint-45-remediation-code-review.md`를 기준으로 합니다.

본 문서는 Sprint 45 구현 작업(상세페이지 패키지 계약, AI 에셋 필터링 로직, 3패널 에디터 셸 및 AI Edit 명령 통합)에 대한 핵심 소스 코드 리뷰입니다.

---

## 1. 코드 리뷰 개요

- **목적**: 상세페이지 패키지 계약 스키마 유효성, AI 승인 자산과 미승인 자산 간의 매핑 보안 필터링 규칙, AI Edit 퀵 액션 연동 API, 그리고 3패널 에디터 프론트엔드 연동 상태의 품질 검증.
- **대상**:
  - `detail_page_package_service.py` (상세페이지 패키지 구성 및 AI Edit 비즈니스 로직)
  - `page_generator.py` (판매 전략 파라미터 결합 및 Mock 카피 반영)
  - `visual_page_renderer.py` (자산 부재 시 fallback_label 'image needed' 규격화)
  - `pages.py (API)` (상세페이지 패키지 획득 및 AI Edit 명령 API endpoints)
  - `DetailPagePackageEditor.tsx` (프론트엔드 3패널 모바일 프리뷰 에디터)
  - `AiEditCommandPanel.tsx` (프론트엔드 AI Edit 퀵 액션 연동 패널)
  - `test_detail_page_package_service.py` (패키지 정렬, 자산 필터링, AI Edit mock 동작 검증 테스트)

---

## 2. 세부 코드 리뷰 의견

### 1) 상세페이지 패키지 서비스 및 스키마 (`detail_page_package_service.py`)
- **강점**:
  - `DetailPagePackage` Pydantic 스키마를 신설하여 `sales_strategy`, `copy_sections`, `visual_plan`, `page_sections`, `marketplace_copy`, `export_targets`의 6개 핵심 필드 계약을 명확히 명세화했습니다.
  - **내러티브 정렬 순서 보장**: 상세페이지 로드 시 `default_order`를 기준으로 `problem_statement` -> `main_claim` -> `secondary_benefit` -> `main_claim_support` -> `benefit_list` -> `summary_claim` -> `product_information` 순으로 정렬하도록 강제하여 정렬 제어를 확실히 달성했습니다.
  - **AI 승인 자산 필터링**: `Asset` 중 오리지널 에셋(`sourced`, `self_shot`)과 `ImageGenerationJobRecord` 내에서 `status == "approved"`인 에셋만 유효 자산으로 한정하도록 전처리 필터를 구현했습니다.
  - **자산 부재 폴백**: 매핑된 에셋이 없거나 승인받지 못한 에셋인 경우, visual_slot의 종류를 placeholder로 전환하고 `fallback_label`에 `"image needed"`를 명확히 바인딩해 주었습니다.
  - **Deterministic Mock Edits**: `stronger_headline`, `natural_tone`, `remove_section` 등 기획상의 AI 조작 요구사항에 대해 텍스트 마커 추가, sort_order 스왑, 가시성 토글의 확정적인 Mock 행위를 DB 단에 즉시 반영하고 커밋해 줍니다.

### 2) 상품 페이지 생성기 서비스 (`page_generator.py`)
- **강점**:
  - `generate_page` 함수 인자에 `sales_strategy`를 수용할 수 있게 시그니처를 수정하고, Mock 생성 과정인 `_get_problem_solution_mock_page` 내부에서 판매 전략에 실재하는 `buyer_problem` 및 `main_selling_point`를 섹션 0(문제 상황)과 섹션 1(메인 해결안)에 유기적으로 매핑해 가독성이 향상되었습니다.

### 3) 비주얼 렌더러 (`visual_page_renderer.py`)
- **강점**:
  - `build_visual_sections` 메서드 내에서 매핑 실패 혹은 placeholder 구성 시, 기본 다국어 가이드를 `"image needed"`로 완전히 단일 통일화하여 기획안과의 오차를 차단했습니다.

### 4) 상세페이지 패키지 API 엔드포인트 (`pages.py`)
- **강점**:
  - `GET /projects/{project_id}/detail-page-package`: 프로젝트 기반의 디테일 페이지 패키지 전체 사양을 검증된 스키마 형식으로 일괄 노출합니다.
  - `POST /projects/{project_id}/page/sections/{section_id}/ai-edit`: section_id와 `AiEditCommandPayload`를 받아 deterministic한 수정을 커밋하고 최신 패키지 정보를 즉각 재반환합니다.

### 5) 3패널 에디터 프론트엔드 연동 (`DetailPagePackageEditor.tsx`, `AiEditCommandPanel.tsx`)
- **강점**:
  - Left(판매 전략 요약 및 섹션 목록 아웃라인), Center(모바일 뷰포트 스크롤 프리뷰), Right(직접 편집 폼 및 AI Command 연동)의 3패널 레이아웃이 유려하게 연동되도록 마운트했습니다.
  - **UX 미감 향상**: 다크 톤(slate-950/900)에 둥근 카드, 반투명 블러 백드롭, 로더 스피너를 갖춘 프리미엄 디자인이 적용되었습니다.
  - **"image needed" 플레이스홀더**: 승인되지 않았거나 누락된 이미지 슬롯을 노란색/주황색의 점선 테두리와 함께 경고 느낌의 애니메이션으로 구현하여 유저의 의사 결정을 능동적으로 돕습니다.
  - **TypeScript 타입 안전성 및 Null 안전 검증**: strict 린트 규칙(ESLint) 준수를 위해 모든 `any` 타입을 `DetailPagePackageData`, `CopySection`, `VisualSlot` 등의 정밀 인터페이스로 전면 개편하고 사용하지 않는 변수(`idx`, `projectId` 등)를 완전히 제거했습니다. 또한 컴파일러의 strict null check를 통과시키기 위해 `handleDirectSave` 진입 시 `pkg` null 가드(`if (!selectedSectionId || !pkg) return;`)를 추가하여 프로덕션 빌드 결함을 근원적으로 차단했습니다.

### 6) 단위 및 통합 테스트 (`test_detail_page_package_service.py`, `test_figma_plugin_visual_payload.py`)
- **강점**:
  - 상세페이지 패키지의 생성 계약 확인 및 정렬 테스트(`test_detail_page_package_generation_and_order`), 오리지널/승인 에셋 필터링 및 미승인 에셋의 image needed 폴백 검증(`test_asset_approval_filtering_and_fallback`), AI Edit mock 명령 실행 및 DB 영속화 확인(`test_ai_edit_command_execution`)의 3개 케이스를 정교히 구축하여 품질 회귀 테스트 자산을 확충했습니다.
  - **Figma 페이로드 Mock 테스트 보완**: Sprint 44/45의 자산 필터링 정책 엄격화에 맞추어 `test_figma_plugin_visual_payload.py`의 Mock 에셋 객체에 누락되었던 `mime_type` 및 `source_type` 속성을 추가로 지정해 주어, 전체 패키지 빌드 테스트 스위트가 깨짐 없이 통과(100% Green)되도록 보완하였습니다.

