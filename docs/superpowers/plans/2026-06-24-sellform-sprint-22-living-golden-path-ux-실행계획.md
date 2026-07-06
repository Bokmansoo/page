# Sellform Sprint 22 Living Golden Path UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 생활/리빙 상품 하나를 링크 입력부터 상세페이지 저장까지 진행할 때 사용자가 다음 행동을 헷갈리지 않도록 골든 패스 UX를 정리한다.

**Architecture:** 기존 기능을 크게 갈아엎지 않고, 프로젝트 생성 → 사실 확인 → 카테고리/스타일 선택 → 상세페이지 편집 → 저장/export 흐름 위에 단계 표시, 현재 할 일 안내, 버튼 활성화 조건, 실패/성공 상태 메시지를 추가한다. 디자인 디테일보다 작업 흐름의 명확성을 우선한다.

**Tech Stack:** Next.js, TypeScript, React, Tailwind CSS, FastAPI, pytest, frontend build, manual QA checklist.

---

## 1. 제품 결정

Sprint 22는 UI의 겉모습을 완전히 바꾸는 스프린트가 아니다.

이번 스프린트의 핵심은 “사용자가 지금 무엇을 해야 하는지 알 수 있게 만드는 것”이다.

### 지금 잡아야 하는 것

- 단계 표시
- 현재 해야 할 일 안내
- 다음 버튼 활성화 조건
- 실패/대기/성공 상태 문구
- page-editor 다음 행동 안내
- 저장/최종본/export 상태 안내
- Living 골든 패스 QA 체크리스트 기준 수동 테스트

### 나중에 바꿔도 되는 것

- 컬러 팔레트
- 로고
- 폰트 조합
- 카드 그림자
- 애니메이션
- Figma 디자인 시스템
- 대시보드 고급 레이아웃

---

## 2. 기준 시나리오

기준 상품:

```text
루메나 휴대용 무선 냉각선풍기
```

기준 카테고리:

```text
Living / 생활·리빙
```

기준 목표:

```text
상품 링크를 넣고, 사실 카드 확인 후, Living 상세페이지 초안을 저장할 수 있다.
```

참조 QA 문서:

```text
docs/testing/2026-06-24-sellform-living-golden-path-qa-checklist.md
```

---

## 3. 파일 구조

### Frontend

- Modify: `frontend/src/.../workspace` 관련 route/page
  - 프로젝트 목록과 프로젝트 생성 후 다음 행동 안내를 정리한다.
- Modify: `frontend/src/.../facts` 관련 route/page
  - 사실 카드 검수 단계 표시와 다음 버튼 조건을 정리한다.
- Modify: `frontend/src/.../page-editor` 관련 route/page
  - 상세페이지 편집 후 저장/최종본/export 안내를 정리한다.
- Create or Modify: `frontend/src/.../WorkflowStepHeader.tsx`
  - 단계 표시 공통 컴포넌트.
- Create or Modify: `frontend/src/.../NextActionPanel.tsx`
  - 현재 화면에서 사용자가 해야 할 일을 알려주는 공통 컴포넌트.

### Backend

- Backend API 변경은 최소화한다.
- 필요한 경우 프로젝트 상태 응답에 다음 값을 명확히 포함한다.

```text
current_step
confirmed_fact_count
category_status
page_version_count
final_version_id
export_status
```

### Docs

- Create: `docs/testing/2026-06-24-sellform-sprint-22-living-golden-path-ux-test-log.md`
- Create: `docs/reviews/2026-06-24-sellform-sprint-22-code-review.md`
- Create: `docs/troubleshooting/2026-06-24-sellform-sprint-22-living-golden-path-ux.md`

---

## 4. UX 문구 기준

### 프로젝트 생성 후

```text
상품 프로젝트가 생성되었습니다.
다음 단계: 상품 정보와 사실 카드를 확인해 주세요.
```

### 링크 수집 실패

```text
상품 링크에서 정보를 자동 수집하지 못했습니다.
수동 입력 또는 이미지 업로드로 계속 진행할 수 있습니다.
```

### 사실 카드 부족

```text
확인된 사실 카드가 3개 이상 필요합니다.
상품 스펙, 사용 시간, 구성품처럼 상세페이지에 사용할 근거를 추가해 주세요.
```

### 카테고리 미확정

```text
카테고리를 확정해야 상세페이지 구조를 안정적으로 만들 수 있습니다.
생활/리빙 상품이면 Living을 선택해 주세요.
```

### 상세페이지 생성 완료

```text
상세페이지 초안이 생성되었습니다.
문구를 확인한 뒤 최종본으로 저장하거나 다른 스타일로 재생성할 수 있습니다.
```

### 저장 완료

```text
현재 상세페이지가 버전으로 저장되었습니다.
최종본으로 지정하면 export 준비를 진행할 수 있습니다.
```

---

## 5. Task 1: 단계 표시 공통 컴포넌트

**Files:**

- Create or Modify: `frontend/src/.../WorkflowStepHeader.tsx`
- Modify: facts/page-editor/workspace pages

- [ ] **Step 1: 단계 정의**

다음 5단계를 화면에 표시한다.

```typescript
const SELLFORM_WORKFLOW_STEPS = [
  { key: "raw_input", label: "1 자료 입력" },
  { key: "facts_verification", label: "2 사실 확인" },
  { key: "style_selection", label: "3 스타일 선택" },
  { key: "page_editor", label: "4 상세페이지 편집" },
  { key: "export", label: "5 저장/내보내기" },
];
```

- [ ] **Step 2: 현재 단계 강조**

현재 단계는 강조하고, 완료된 단계는 `완료` 상태로 표시한다.

- [ ] **Step 3: 프론트 빌드 확인**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected:

```text
✓ built
```

---

## 6. Task 2: 현재 해야 할 일 안내 패널

**Files:**

- Create or Modify: `frontend/src/.../NextActionPanel.tsx`
- Modify: facts/page-editor/workspace pages

- [ ] **Step 1: 패널 표시 조건 정의**

각 단계별로 다음 안내를 표시한다.

```typescript
const NEXT_ACTION_MESSAGES = {
  raw_input: "상품명, 상품 링크, 이미지 또는 텍스트 정보를 입력해 주세요.",
  facts_verification: "상세페이지에 사용할 사실 카드를 확인해 주세요.",
  style_selection: "AI가 추천한 스타일 후보 중 하나를 선택해 주세요.",
  page_editor: "상세페이지 문구와 섹션 순서를 확인해 주세요.",
  export: "최종본을 지정하고 긴 이미지 또는 섹션별 ZIP으로 저장해 주세요.",
};
```

- [ ] **Step 2: 조건형 안내 추가**

사실 카드가 부족하면 다음 메시지를 우선 표시한다.

```text
확인된 사실 카드가 3개 이상 필요합니다.
```

카테고리가 미확정이면 다음 메시지를 우선 표시한다.

```text
카테고리를 확정해야 상세페이지 구조를 안정적으로 만들 수 있습니다.
```

- [ ] **Step 3: 실패/성공 상태 문구 정리**

`Failed to fetch` 같은 원문 오류만 보여주지 말고 사용자가 이해할 수 있는 문구를 함께 표시한다.

```text
백엔드 서버와 연결하지 못했습니다. 서버가 실행 중인지 확인해 주세요.
```

---

## 7. Task 3: 다음 단계 버튼 활성화 조건 정리

**Files:**

- Modify: facts page
- Modify: style selection/page editor page

- [ ] **Step 1: 사실 확인 단계 조건**

`검증 완료 및 다음 단계` 버튼은 아래 조건에서 활성화한다.

```text
확인된 사실 카드 3개 이상
카테고리 선택 또는 확정 가능 상태
```

- [ ] **Step 2: 스타일 선택 단계 조건**

상세페이지 생성 버튼은 아래 조건에서 활성화한다.

```text
스타일 후보 1개 선택됨
확인된 사실 카드 3개 이상
카테고리 확정됨
```

- [ ] **Step 3: export 단계 조건**

export 버튼은 아래 조건에서 활성화한다.

```text
상세페이지 버전 1개 이상
최종본 지정됨
```

조건이 부족하면 비활성화 이유를 버튼 근처에 표시한다.

---

## 8. Task 4: page-editor 다음 행동 안내

**Files:**

- Modify: page-editor UI

- [ ] **Step 1: 초안 생성 완료 배너 개선**

현재 초안 생성 완료 배너에 다음 행동을 함께 표시한다.

```text
AI 상세페이지 초안이 생성되었습니다.
다음으로 문구를 확인하고, 필요한 섹션을 수정한 뒤 최종본으로 저장해 주세요.
```

- [ ] **Step 2: 문구 품질 안내**

본문이 너무 짧은 섹션에는 다음 안내를 표시한다.

```text
이 섹션은 문구가 짧습니다. 핵심 사실과 사용 장면을 한 문장 더 추가해 보세요.
```

- [ ] **Step 3: 저장 상태 표시**

화면 상단 또는 사이드에 다음 상태를 표시한다.

```text
자동 저장됨
최종본 미지정
export 준비 전
```

---

## 9. Task 5: Living 골든 패스 수동 QA

**Files:**

- Use: `docs/testing/2026-06-24-sellform-living-golden-path-qa-checklist.md`
- Create: `docs/testing/2026-06-24-sellform-sprint-22-living-golden-path-ux-test-log.md`

- [ ] **Step 1: QA 체크리스트 실행**

루메나 휴대용 무선 냉각선풍기 기준으로 골든 패스를 끝까지 실행한다.

- [ ] **Step 2: 발견 이슈 기록**

아래 형식으로 테스트 로그에 기록한다.

```markdown
| 번호 | 단계 | 증상 | 기대 동작 | 실제 동작 | 심각도 | 조치 방향 |
| --- | --- | --- | --- | --- | --- | --- |
```

- [ ] **Step 3: Top 3 이슈 선정**

Blocker/Major 우선으로 다음 Sprint 후보를 정리한다.

---

## 10. 완료 기준

- 사용자는 현재 몇 단계에 있는지 알 수 있다.
- 사용자는 각 화면에서 다음에 무엇을 해야 하는지 알 수 있다.
- 다음 버튼이 왜 비활성화됐는지 알 수 있다.
- 링크 수집 실패, 백엔드 연결 실패, AI fallback 상태가 이해 가능한 문구로 표시된다.
- page-editor에서 초안 생성 후 다음 행동이 명확하다.
- 저장/최종본/export 상태가 명확하다.
- Living 골든 패스 QA 체크리스트를 1회 이상 실행했다.
- 테스트로그, 코드리뷰, 트러블슈팅 문서가 작성된다.
- 프론트 빌드가 통과한다.

---

## 11. 검증 명령

```powershell
cd frontend
npm.cmd run build
```

백엔드 변경이 포함된 경우:

```powershell
uv run --project backend pytest -q
```

수동 QA:

```text
docs/testing/2026-06-24-sellform-living-golden-path-qa-checklist.md 기준으로 루메나 상품 1개를 끝까지 진행한다.
```
