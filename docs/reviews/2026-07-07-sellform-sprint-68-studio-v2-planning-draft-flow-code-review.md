# Sellform Sprint 68: Studio V2 기획 초안 흐름 코드 리뷰

## 판정

보완 후 승인입니다.

초기 구현은 Sprint 68의 큰 방향(품질 모드, 기획 초안 카드, 수정 UI, 승인 API)은 들어가 있었지만, 실제 실행 기준으로는 몇 가지 치명적인 불일치가 있었습니다. 이번 보완으로 기획 문서의 핵심 흐름인 `상품 입력 → 기획 초안 검수 → 카드 수정/정렬/숨김 → 상세페이지 조립 → 결과 화면 이동`이 동작 가능한 상태로 정리되었습니다.

## 발견한 문제와 수정 내용

1. 프론트 API 경로 불일치

- 문제: 프론트가 `/api/projects/{project_id}/planning-draft`를 호출하고 있었지만, 백엔드는 `/api/v1/projects/{project_id}/planning-draft`로 라우터가 붙어 있습니다.
- 영향: 실제 서버에서는 기획 초안 조회/생성/저장/승인 요청이 404 또는 실패로 이어질 수 있었습니다.
- 수정: `PlanningDraftEditor`, planning page, E2E mock을 모두 `/api/v1/projects/{project_id}/planning-draft` 기준으로 맞췄습니다.

2. Sprint 68 프론트 파일 깨짐

- 문제: `PlanningDraftCard.tsx`, `PlanningDraftEditor.tsx`, `PlanningModeSelector.tsx`, planning page에 깨진 한글 문자열, 잘못된 JSX 닫힘 태그, `id: str` 같은 TypeScript 오류가 섞여 있었습니다.
- 영향: 빌드 또는 IDE 타입 검사에서 빨간 오류가 날 수 있었습니다.
- 수정: 관련 컴포넌트를 정상 TypeScript/JSX와 자연스러운 한글 UI 문구로 복구했습니다.

3. PlanningDraft 백엔드 스키마/서비스 문구 깨짐

- 문제: `planning_draft.py`, `planning_draft_service.py`에 깨진 description/string이 많아 유지보수와 검수가 어렵고, 일부 문자열은 IDE에서 오류처럼 보일 수 있었습니다.
- 수정: Pydantic schema와 deterministic fallback draft generator를 정상 한글/명확한 구조로 정리했습니다.

4. 승인 API 런타임 오류 가능성

- 문제: `pages.py`의 planning approve 로직에서 `run = ...` 코드가 깨진 주석 뒤에 붙어 사실상 주석 처리되어 있었습니다. 아래에서 `if run:`을 호출하므로 승인 시 `NameError`가 발생할 수 있었습니다.
- 수정: `AgentRun` 조회 코드를 정상 코드로 복구했습니다.

5. 승인 후 결과 페이지 연결 안정성

- 문제: 승인 API가 `DetailPageVersion(is_final=False)`로 저장하고 있었습니다. 결과/렌더/다운로드 흐름은 최종본 기준으로 동작하므로 승인 직후 결과 화면 연결이 불안정할 수 있었습니다.
- 수정: 기획 승인으로 생성되는 `DetailPageVersion`을 `is_final=True`로 저장하도록 변경했습니다.

6. `pages.py` 상단 SyntaxError

- 문제: `CreatePageRequest.primary_color` description 문자열이 깨져 실제 `SyntaxError`가 발생했습니다.
- 영향: 백엔드 import가 실패하고, IDE에서 `pages.py`뿐 아니라 연관 import인 `exports.py`까지 빨갛게 보일 수 있었습니다.
- 수정: 해당 Pydantic Field 설명 문자열을 정상화했습니다.

## 검증 결과

- `backend/src/api/exports.py` 문법 검사: 통과
- `backend/src/api/pages.py` 문법 검사: 통과
- `backend/src/schemas/planning_draft.py` 문법 검사: 통과
- `backend/src/services/planning_draft_service.py` 문법 검사: 통과
- `from src.api import exports, pages`: 통과
- `uv run pytest tests/test_planning_draft_service.py tests/test_exports.py tests/test_export_history_api.py -q`: 8 passed
- `npm.cmd run build`: 통과
- `npx.cmd playwright test e2e/planning-draft-flow.spec.ts --project=chromium --reporter=line`: 1 passed

## 남은 주의사항

- `pages.py`에는 과거 인코딩 깨짐으로 생긴 주석/로그 문구가 아직 일부 남아 있습니다. 이번 작업에서는 실행 오류와 Sprint 68 직접 흐름을 우선 복구했습니다.
- 다음 정리 작업에서 `pages.py` 전체 한글 주석/로그 메시지를 별도 리팩터링하면 IDE 가독성이 더 좋아집니다.
- 프론트 빌드 경고는 기존 `<img>` 사용 및 hook dependency 경고이며, 이번 Sprint 68 보완을 막는 오류는 아닙니다.
