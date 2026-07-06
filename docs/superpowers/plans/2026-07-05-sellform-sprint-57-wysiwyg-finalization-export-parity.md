# Sellform Sprint 57 WYSIWYG Finalization and Export Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development while implementing each task and superpowers:verification-before-completion before declaring the sprint complete.

**Goal:** 사용자가 결과 화면에서 확인한 상세페이지를 현재 상태 그대로 최종본으로 확정하고, 동일한 내용과 디자인의 PNG/JPG로 저장한다.

**Architecture:** 현재 `ProductPage`를 불변 `DetailPageVersion` 최종본으로 확정한 뒤, 결과 화면과 export가 같은 최종본 DTO와 canonical React renderer를 사용한다. 백엔드는 기존 Pillow 기반 재조립 대신 export 전용 HTML을 Playwright로 캡처한다.

**Tech Stack:** FastAPI, SQLAlchemy, Next.js 14, React, Playwright, pytest.

---

## Scope

- 현재 편집본에서 명시적인 최종본 생성
- 한 프로젝트의 활성 최종본을 정확히 한 개로 유지
- 결과 화면과 PNG/JPG의 데이터 및 렌더링 통일
- 브라우저 저장 위치 선택이 가능한 실제 다운로드
- Figma와 기존 패키지 출력이 같은 최종본을 참조하도록 계약 정리

## File Structure

- Create: `backend/src/services/page_finalization_service.py`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/api/exports.py`
- Modify: `backend/src/services/export_service.py`
- Create: `backend/tests/test_page_finalization_service.py`
- Create: `backend/tests/test_wysiwyg_export_contract.py`
- Create: `frontend/src/components/DetailPageDocument.tsx`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Create: `frontend/src/app/workspace/projects/[id]/render/page.tsx`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/e2e/wysiwyg-finalization-export.spec.ts`

## Tasks

### Task 1: 최종본 스냅샷 계약

**Files:**
- Create: `backend/src/services/page_finalization_service.py`
- Modify: `backend/src/api/pages.py`
- Test: `backend/tests/test_page_finalization_service.py`

- [ ] 현재 섹션 순서, 카피, 스타일, `image_asset_id`를 포함한 최종본 생성 실패 테스트를 작성한다.
- [ ] `POST /api/v1/projects/{project_id}/page/finalize`를 추가한다.
- [ ] 같은 프로젝트의 기존 `is_final`을 해제하고 새 버전 하나만 활성 최종본으로 만든다.
- [ ] `GET /api/v1/projects/{project_id}/page/final`이 최종본 ID와 스냅샷을 반환하게 한다.
- [ ] 최종본이 없는 경우 최신 draft로 몰래 대체하지 않고 명시적인 상태를 반환한다.

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_page_finalization_service.py -v
```

### Task 2: Canonical 상세페이지 렌더러

**Files:**
- Create: `frontend/src/components/DetailPageDocument.tsx`
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Create: `frontend/src/app/workspace/projects/[id]/render/page.tsx`

- [ ] 결과 화면의 상세페이지 본문을 `DetailPageDocument`로 분리한다.
- [ ] 렌더러 입력은 최종본 DTO 하나로 제한한다.
- [ ] 결과 화면과 export 전용 route가 같은 컴포넌트를 사용한다.
- [ ] export route에서는 헤더, 후보 패널, 버튼, 브라우저 장식을 렌더하지 않는다.
- [ ] 이미지와 웹폰트가 모두 로딩된 뒤 `data-export-ready=true`를 표시한다.

### Task 3: Playwright 기반 PNG/JPG 출력

**Files:**
- Modify: `backend/src/api/exports.py`
- Modify: `backend/src/services/export_service.py`
- Test: `backend/tests/test_wysiwyg_export_contract.py`

- [ ] export가 요청된 `final_version_id`만 사용한다는 실패 테스트를 작성한다.
- [ ] 백엔드 Playwright가 export route를 고정 폭으로 열고 `data-export-ready`를 기다리게 한다.
- [ ] 문서 전체 높이를 측정해 PNG/JPG를 캡처한다.
- [ ] 형식별 MIME type, 확장자, 품질 옵션을 정확히 설정한다.
- [ ] 이미지 누락이나 route 오류에서는 성공 artifact를 만들지 않는다.
- [ ] 기존 Pillow 렌더러는 legacy fallback으로 격리하고 기본 경로에서 사용하지 않는다.

### Task 4: 실제 다운로드 UX

**Files:**
- Modify: `frontend/src/components/GeneratedDetailPageResult.tsx`
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/e2e/wysiwyg-finalization-export.spec.ts`

- [ ] `최종본 확정` 전에는 다운로드 버튼이 이유와 함께 비활성화된다.
- [ ] PNG/JPG 선택 후 export 생성, 상태 polling, binary fetch를 수행한다.
- [ ] File System Access API 지원 브라우저에서는 저장 위치 선택 창을 연다.
- [ ] 미지원 브라우저에서는 `<a download>`로 정상 fallback 한다.
- [ ] `Failed to fetch` 대신 단계별 한국어 오류와 재시도 버튼을 표시한다.

### Task 5: 화면·파일 동일성 회귀 테스트

- [ ] 결과 화면과 export route의 섹션 ID, 카피, 이미지 URL이 동일한지 검증한다.
- [ ] PNG/JPG magic bytes, MIME type, 폭, 최소 높이를 검증한다.
- [ ] placeholder 문구가 출력 픽셀을 만드는 DOM에 남지 않는지 검증한다.
- [ ] 새 최종본을 확정하면 이전 export가 최신 파일로 오인되지 않는지 검증한다.

## Acceptance Criteria

- 결과 화면과 저장 파일의 섹션, 문구, 이미지, 색상, 순서가 같다.
- PNG와 JPG 모두 열 수 있고 브라우저에서 저장 위치를 선택하거나 정상 다운로드된다.
- 최종본 ID가 export artifact에 기록된다.
- export 실패 시 프로젝트와 최종본은 유지되며 재시도할 수 있다.
- 실제 OpenAI 이미지 API를 호출하지 않고 전체 테스트를 실행할 수 있다.
