# Sprint 73 결과 화면/편집 진입 UX 정리 코드리뷰

## 결론

승인 가능. Sprint 73 기획의 핵심 요구사항인 결과 화면 CTA 역할 분리, `review`/`advanced` 편집 모드 헤더 분리, 다운로드 blocker 안내 개선, 작업 목록/출력 이력 이동 경로 추가가 구현되었습니다.

## 구현 확인

### 결과 화면 CTA 분리

- `frontend/src/components/GeneratedDetailPageResult.tsx`
  - 상단 CTA를 `검수하며 다듬기`와 `고급 편집기로 열기` 링크로 분리했습니다.
  - 본문 상단에 `다음 작업` 섹션을 추가했습니다.
  - 각 CTA에 목적 설명을 추가했습니다.
    - `검수하며 다듬기`: 문구와 이미지를 빠르게 확인하고 누락·오류를 줄이는 흐름.
    - `고급 편집기로 열기`: 레이아웃과 섹션을 더 세밀하게 수정하는 흐름.
  - `작업 목록`, `출력 이력` 링크를 추가했습니다.

### review/advanced 모드 헤더 분리

- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - `mode=review`일 때 제목/설명을 `검수하며 다듬기` 흐름으로 표시합니다.
  - `mode=advanced`일 때 제목/설명을 `고급 편집기` 흐름으로 표시합니다.

- `frontend/src/components/ReviewEditorLayout.tsx`
  - `modeTitle`, `modeDescription` props를 추가했습니다.
  - editor 헤더가 프로젝트명만 보여주는 구조에서 “현재 편집 목적”을 먼저 보여주는 구조로 바뀌었습니다.

### 다운로드 blocker UX 개선

- `frontend/src/components/GeneratedDetailPageResult.tsx`
  - 이미지/HTML visual contract 문제가 있을 때 다운로드 버튼을 단순 disabled 처리하지 않고, 클릭 시 blocker 안내가 표시되도록 변경했습니다.
  - 사용자는 막힌 이유와 다음 행동을 바로 확인할 수 있습니다.

- `frontend/src/components/ExportReadinessWarningV2.tsx`
  - 깨진 기존 안내 문구 대신 한글 UX 문구를 가진 새 경고 컴포넌트를 추가했습니다.
  - `role="alert"`를 사용해 E2E와 접근성 기준으로도 식별 가능하게 했습니다.
  - `검수하며 이미지 보완` 버튼으로 review mode 진입을 유도합니다.

### E2E

- `frontend/e2e/result-editor-entrypoints.spec.ts`
  - 결과 화면에서 서로 다른 CTA가 보이는지 검증.
  - `mode=review`, `mode=advanced` 헤더/설명 분리 검증.
  - 이미지 누락 시 다운로드 blocker 안내와 보완 CTA 검증.

## 검증 결과

```text
npm.cmd run build
Compiled successfully
```

```text
npx.cmd playwright test e2e/result-editor-entrypoints.spec.ts --project=chromium --reporter=line
3 passed
```

```text
npx.cmd playwright test e2e/completed-detail-page-export.spec.ts --project=chromium --reporter=line
1 passed
```

## 남은 참고사항

- 기존 `frontend/src/components/ExportReadinessWarning.tsx`는 문자열이 깨진 상태라 직접 수정 대신 `ExportReadinessWarningV2.tsx`를 추가하고 결과 화면 import를 교체했습니다. 추후 정리 Sprint에서 기존 컴포넌트를 제거하거나 V2로 대체 통합하면 좋습니다.
- 고급 편집기의 실제 레이아웃 편집 기능 확장은 Sprint 73 범위 밖입니다. 이번 Sprint는 진입 목적과 설명을 분리하는 UX 정리에 집중했습니다.
