# Sellform Sprint 58 Detail Page Library and History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development while implementing each task and superpowers:verification-before-completion before declaring the sprint complete.

**Goal:** 사용자가 생성한 상세페이지를 `내 상세페이지`에서 찾고, 다시 열고, 편집하고, 다운로드하거나 삭제할 수 있게 한다.

**Architecture:** 기존 `Project`, `ProductPage`, `DetailPageVersion`, `ExportArtifact`를 사용자용 library summary로 집계한다. 운영용 dashboard와 분리된 white-first 보관함을 만들고 모든 조회와 변경은 workspace 범위로 제한한다.

**Tech Stack:** FastAPI, SQLAlchemy, Next.js 14, React, pytest, Playwright.

---

## File Structure

- Create: `backend/src/services/detail_page_library_service.py`
- Modify: `backend/src/api/projects.py`
- Create: `backend/tests/test_detail_page_library_api.py`
- Create: `frontend/src/app/workspace/library/page.tsx`
- Create: `frontend/src/components/DetailPageLibrary.tsx`
- Create: `frontend/src/components/DetailPageLibraryItem.tsx`
- Modify: `frontend/src/app/workspace/layout.tsx`
- Modify: `frontend/src/lib/api.ts`
- Create: `frontend/e2e/detail-page-library.spec.ts`

## Tasks

### Task 1: 사용자용 보관함 조회 API

- [ ] 다른 workspace의 프로젝트가 노출되지 않는 실패 테스트를 먼저 작성한다.
- [ ] `GET /api/v1/projects/library`에 pagination, status, search, sort를 추가한다.
- [ ] 각 항목에 대표 이미지, 상품명, 상태, 수정 시각, 최종본 ID, 최근 export를 포함한다.
- [ ] 대표 이미지는 최종본의 hero 선택 이미지에서 결정하고 없으면 명시적 fallback을 사용한다.
- [ ] N+1 query 없이 목록을 조회한다.

### Task 2: 삭제와 이력 보존 계약

- [ ] `DELETE /api/v1/projects/{project_id}`를 workspace 권한과 함께 구현한다.
- [ ] 삭제 전 확인용 요약을 반환하거나 UI에서 상품명을 재확인한다.
- [ ] 관련 페이지, 버전, export metadata의 정리 정책을 테스트한다.
- [ ] 실제 파일 삭제 실패가 DB를 반쪽 상태로 만들지 않게 한다.

### Task 3: White-first 내 상세페이지 화면

- [ ] `/workspace/library`에 반복 카드 목록이 아닌 스캔 가능한 작업 목록을 구현한다.
- [ ] 각 항목에 `결과 보기`, `편집 계속`, `다운로드`, `삭제` 명령을 제공한다.
- [ ] 빈 상태에는 AI 상세페이지 생성 화면으로 가는 명확한 버튼을 제공한다.
- [ ] loading, error, no-result, deleting 상태를 구현한다.
- [ ] `DESIGN.md`의 white-first, calm green, soft commerce 원칙을 따른다.

### Task 4: 전역 내비게이션 연결

- [ ] 기존 `상품 프로젝트` 또는 미구현 `출력 이력` alert를 실제 보관함 링크로 교체한다.
- [ ] 결과 화면의 `내 상세페이지` 동작을 보관함으로 연결한다.
- [ ] 브라우저 뒤로가기가 직전 결과/편집 화면으로 정상 복귀하는지 검증한다.

### Task 5: 사용자 흐름 E2E

- [ ] 생성 완료 프로젝트가 보관함에 나타난다.
- [ ] 결과 화면을 다시 열면 동일한 최종본이 보인다.
- [ ] 편집 후 새 최종본을 확정하면 목록의 수정 시각과 버전이 갱신된다.
- [ ] 최근 PNG/JPG를 다시 다운로드할 수 있다.
- [ ] 삭제 후 목록과 직접 URL 모두에서 접근할 수 없다.

Run:

```cmd
cd /d C:\page\backend
uv run pytest tests\test_detail_page_library_api.py -v

cd /d C:\page\frontend
npm.cmd run build
npm.cmd run test:e2e -- detail-page-library.spec.ts
```

## Acceptance Criteria

- 사용자는 URL을 기억하지 않아도 모든 생성 상세페이지를 찾을 수 있다.
- 보관함에서 결과 보기, 편집, 재다운로드, 삭제가 동작한다.
- workspace 간 데이터가 섞이지 않는다.
- 상태와 최종본 버전이 실제 백엔드 데이터와 일치한다.
- 화면은 운영 dashboard가 아니라 1인 셀러용 white-first 보관함으로 보인다.
