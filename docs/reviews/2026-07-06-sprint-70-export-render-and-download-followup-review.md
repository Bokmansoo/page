# Sprint 70 보완 코드리뷰: Export Render & Browser Download

> 리뷰 일자: 2026-07-06  
> 원 리뷰 문서: `docs/reviews/2026-07-06-sprint-70-export-render-and-download-code-review.md`  
> 기획 문서: `docs/superpowers/plans/2026-07-06-sellform-sprint-70-browser-download-and-clean-export-render.md`

---

## 1. 보완이 필요했던 이유

초기 리뷰 문서에는 Sprint 70이 승인된 것으로 기록되어 있었지만, 실제 코드 확인 결과 프론트 빌드가 실패했다.

발견된 문제:

- `frontend/src/components/GeneratedDetailPageResult.tsx`에 File System Access API 제거 잔재가 남아 TypeScript 문법 오류 발생
- `/export-render/projects/[id]/page.tsx`에서 사용하지 않는 `id`, `versionId` 변수로 lint 실패
- 결과 화면 코드에 `showSaveFilePicker`, `SaveFilePicker`, `SaveFileHandle`, `createWritable`, `chooseSaveFile` 관련 문자열이 남아 Sprint 70 목표와 불일치

---

## 2. 보완 수정

### Frontend

- `GeneratedDetailPageResult.tsx`
  - 깨진 저장 위치 선택 함수 잔재 제거
  - PNG/JPG 저장 흐름은 `<a download>` 기반 브라우저 다운로드 흐름으로 유지
  - File System Access API 관련 문자열 제거 확인

- `frontend/src/app/export-render/projects/[id]/page.tsx`
  - 사용하지 않는 `params`, `searchParams`, `id`, `versionId` 제거
  - `DetailPageRenderClient`가 `useParams()`와 `useSearchParams()`로 필요한 값을 직접 읽는 현재 구조와 일치시킴

---

## 3. 검증 결과

### Frontend build

```bash
cd frontend
npm.cmd run build
```

결과: 통과

### Backend export tests

```bash
uv run --project backend pytest backend/tests/test_export_service.py backend/tests/test_export_api.py -q
```

결과:

```text
9 passed
```

### Sprint 70 E2E

```bash
cd frontend
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts e2e/export-render-clean-page.spec.ts --project=chromium --reporter=line
```

결과:

```text
2 passed
```

---

## 4. 최종 판정

**보완 후 승인.**

현재 기준으로 Sprint 70의 핵심 요구사항은 충족한다.

- PNG/JPG 저장은 브라우저 download event 기반으로 검증됨
- 결과 화면 코드에서 File System Access API 직접 사용 제거됨
- export render 라우트는 `/export-render/projects/[id]`로 분리됨
- 기존 `/workspace/projects/[id]/export-render`는 새 라우트로 redirect됨
- backend export 기본 경로는 `/export-render/projects/{project_id}`임

---

## 5. 남은 주의점

- 기존 리뷰 문서 본문은 인코딩이 깨져 있어 후속 관리 시 이 보완 리뷰 문서를 기준으로 삼는 것이 안전하다.
- `backend/tests/test_export_api.py`는 실제 DB fixture 기반 API 호출이 아니라 `FileResponse` header convention 위주 검증이다. Sprint 71 또는 export history 작업에서 실제 asset fixture 기반 다운로드 재검증을 추가하는 것이 좋다.
