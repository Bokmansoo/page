# Sprint 72 작업 목록 코드리뷰

## 결론

승인 가능. Sprint 72 기획의 핵심 요구사항인 “내가 생성한 상세페이지 작업 목록 확인”, “결과 보기/검수하며 다듬기/출력 이력 이동”, “상단 메뉴 작업 목록 진입”, “empty state”가 구현되었습니다.

## 구현 확인

### Backend

- `backend/src/schemas/project_worklist.py`
  - `ProjectWorklistItem`, `ProjectWorklistResponse` DTO 추가.
- `backend/src/api/projects.py`
  - `GET /api/v1/projects/worklist` 추가.
  - 현재 워크스페이스의 프로젝트만 최신 수정순으로 최대 100개 반환.
  - 동적 `/{project_id}` 라우트보다 먼저 선언되어 `/worklist`가 프로젝트 ID로 오인식되지 않음.
  - 각 항목에 `project_id`, `project_name`, `status`, `result_url`, `review_url`, `export_history_url`, `last_export_status`, `updated_at` 포함.
- `backend/tests/test_project_worklist_api.py`
  - seed 후 작업 목록 응답 검증.
  - 신규 워크스페이스 empty state 응답 검증.

### Frontend

- `frontend/src/lib/projectWorklist.ts`
  - `/api/v1/projects/worklist` fetch 클라이언트 추가.
  - 기존 mock auth header 패턴 유지.
- `frontend/src/components/ProjectWorklist.tsx`
  - 작업 카드 목록 UI 추가.
  - 상태 배지, 최근 출력 상태, 마지막 수정일 표시.
  - “결과 보기”, “검수하며 다듬기”, “출력 이력” CTA 제공.
  - 작업이 없을 때 “첫 상세페이지 만들기” empty state 제공.
- `frontend/src/app/workspace/projects/page.tsx`
  - `/workspace/projects` 작업 목록 페이지 추가.
  - loading/error/refresh 상태 처리.
- `frontend/src/app/workspace/layout.tsx`
  - 상단 메뉴와 기존 사이드 메뉴 영역에 “작업 목록” 링크 추가.
- `frontend/e2e/project-worklist.spec.ts`
  - 작업 목록 표시 검증.
  - 카드 CTA 링크 검증.
  - `/workspace` 상단 메뉴에서 작업 목록 진입 검증.

## 검증 결과

```text
uv run --project backend pytest backend/tests/test_project_worklist_api.py -q
2 passed
```

```text
npm.cmd run build
Compiled successfully
Route included: /workspace/projects
```

```text
npx.cmd playwright test e2e/project-worklist.spec.ts --project=chromium --reporter=line
2 passed
```

## 남은 참고사항

- 썸네일은 현재 최신 export job의 `output_images[0]`가 있을 때만 표시됩니다. 프로젝트 생성 직후나 export가 없는 경우에는 `NO IMG` placeholder가 표시됩니다.
- 출력 이력 링크는 `/workspace/exports?project_id=...` 형태로 넘기지만, 출력 이력 페이지가 이 query를 필터로 실제 적용하는지는 Sprint 71 범위 밖입니다. 필요하면 후속 Sprint에서 “프로젝트별 출력 이력 필터”를 추가하면 좋습니다.
