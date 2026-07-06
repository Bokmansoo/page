# Sprint 67 검수 화면과 고급 편집기 분리 기획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** `검수하며 다듬기`와 `고급 편집기로 열기`가 같은 화면처럼 보이지 않게 역할과 UI를 명확히 분리한다.

**아키텍처:** 현재 `page-editor?mode=review|advanced`가 같은 `ReviewEditorLayout`을 사용하는 구조를 분리한다. 공통 데이터 로딩은 shell로 유지하고, review mode와 advanced mode는 별도 컴포넌트로 렌더링한다.

**기술 스택:** Next.js App Router, React, TypeScript, Tailwind CSS, Playwright E2E

---

## 1. 현재 문제

현재 두 버튼은 다음 URL로 이동한다.

```text
/workspace/projects/{project_id}/page-editor?mode=advanced
/workspace/projects/{project_id}/page-editor?mode=review
```

하지만 실제 구현은 둘 다 같은 `ReviewEditorLayout`을 사용한다. 그래서 사용자는 두 기능이 같은 페이지라고 느낀다.

---

## 2. 화면 역할 정의

### 검수하며 다듬기

목적:

- 최종 출력 전 문제를 확인한다.
- readiness blocker를 해결한다.
- AI 문구 수정과 이미지 검수를 빠르게 한다.

주요 기능:

- 다운로드 가능 상태 체크
- 섹션별 문제 표시
- AI 문구 수정
- 생성 이미지 승인/교체
- 누락된 HTML visual 자동 보강

### 고급 편집기

목적:

- 상세페이지 구조와 디자인을 직접 조정한다.
- 검수보다 자유도가 높다.

주요 기능:

- 섹션 순서 변경
- 섹션 숨김/표시
- 제목/본문 직접 편집
- 이미지 교체
- visual type 변경
- overlay 위치/색상/정렬 조정

---

## 3. 파일 구조

생성:

- `frontend/src/components/page-editor/PageEditorShell.tsx`
- `frontend/src/components/page-editor/ReviewPageEditor.tsx`
- `frontend/src/components/page-editor/AdvancedPageEditor.tsx`
- `frontend/src/components/page-editor/ReadinessChecklist.tsx`
- `frontend/src/components/page-editor/SectionTreePanel.tsx`
- `frontend/src/components/page-editor/SectionPropertiesPanel.tsx`

수정:

- `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- `frontend/src/components/GeneratedDetailPageResult.tsx`

테스트:

- `frontend/e2e/review-editor-reframe.spec.ts`
- `frontend/e2e/advanced-editor.spec.ts`

---

## 4. 작업 계획

### Task 1 — 공통 데이터 로딩 shell 분리

- [ ] 현재 `page-editor/page.tsx`의 데이터 로딩 로직을 유지한다.
- [ ] 렌더링 부분을 `PageEditorShell`로 넘긴다.
- [ ] `mode`가 `review`면 `ReviewPageEditor`를 렌더링한다.
- [ ] `mode`가 `advanced`면 `AdvancedPageEditor`를 렌더링한다.

### Task 2 — ReviewPageEditor 구현

- [ ] 기존 검수 레이아웃을 review 전용으로 옮긴다.
- [ ] readiness checklist 영역을 추가한다.
- [ ] 오른쪽 패널은 AI 문구 수정과 blocker 해결 중심으로 둔다.
- [ ] 직접 수정 영역은 보조 기능으로 낮춘다.

### Task 3 — AdvancedPageEditor 구현

- [ ] 왼쪽에 `SectionTreePanel`을 둔다.
- [ ] 가운데에 canvas preview를 둔다.
- [ ] 오른쪽에 `SectionPropertiesPanel`을 둔다.
- [ ] 제목/본문/이미지/visual type을 직접 편집할 수 있게 한다.

### Task 4 — 버튼 라벨과 이동 정리

- [ ] 결과 화면의 `검수하며 다듬기`는 review mode로 이동한다.
- [ ] 결과 화면의 `고급 편집기로 열기`는 advanced mode로 이동한다.
- [ ] 두 화면 상단 제목과 설명이 명확히 다르게 보이게 한다.

### Task 5 — E2E 추가

- [ ] review mode에서 `AI 문구 수정`, `다운로드 전 확인`, `선택한 섹션 다듬기`가 보이는지 확인한다.
- [ ] advanced mode에서 `섹션 구조`, `속성 패널`, `visual type`이 보이는지 확인한다.
- [ ] 두 화면의 주요 텍스트가 서로 다름을 검증한다.

실행:

```bash
npx.cmd playwright test e2e/review-editor-reframe.spec.ts e2e/advanced-editor.spec.ts --project=chromium --reporter=line
```

---

## 5. 완료 기준

- 두 버튼이 서로 다른 목적의 화면으로 보인다.
- review mode는 검수/문제 해결 중심이다.
- advanced mode는 직접 편집 중심이다.
- E2E에서 두 모드 차이가 검증된다.
- 기존 AI 문구 수정 흐름이 깨지지 않는다.

