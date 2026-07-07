# Sprint 77 AI 대본 버전 수정 및 비교 적용 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` before implementation.

**Goal:** 사용자가 직접 수정한 대본을 기준으로 목적별 AI 수정안을 만들고, 수정 전/후 비교 후 적용할 수 있게 한다.

**Scope:** AI copy rewrite presets, preview API, compare modal, manual edit preservation, E2E 검증.

---

## 1. 해결할 문제

현재 AI 문구 수정은 사용자의 의도와 다르게 원문에 `[AI 수정됨]` 같은 내부 마커를 붙이거나, 변화가 거의 없는 결과를 만들 수 있다. 사용자는 대본을 직접 고칠 수 있어야 하고, AI는 그 편집본을 기준으로 더 나은 버전을 제안해야 한다.

---

## 2. AI 수정 프리셋

| 버튼 | 목적 |
| --- | --- |
| 강한 구매 설득 버전 | 문제와 해결을 더 선명하게 연결 |
| 짧고 임팩트 있는 버전 | 제목과 본문을 압축 |
| 초보 셀러 자연스러운 버전 | 쉬운 단어와 짧은 문장 |
| 프리미엄 브랜드 톤 | 차분하고 고급스러운 문장 |
| 쿠팡/스마트스토어 최적화 버전 | 빠르게 장점이 보이는 구조 |
| 과장 줄인 신뢰형 버전 | 확인된 정보와 체크사항 중심 |
| 감성 라이프스타일 버전 | 사용 장면과 분위기 중심 |
| 구매 불안 감소 버전 | 구매 전 확인사항과 신뢰 정보 보강 |

---

## 3. UX 계약

AI 버튼을 누르면 즉시 덮어쓰지 않는다.

```text
수정 전:
냉각선풍기, 필요한 순간 바로 쓰는 선택

수정 후:
책상·차량·야외까지, 더운 순간 바로 꺼내 쓰는 무선 냉각 선풍기

[이 수정안 적용] [다시 생성] [취소]
```

수기 수정한 내용은 보호한다.

- 현재 입력창의 제목/본문을 source로 보낸다.
- 저장된 원본이 아니라 사용자가 지금 편집한 값을 기준으로 수정안을 만든다.
- 적용 전에는 PATCH하지 않는다.
- `이 수정안 적용`을 눌렀을 때만 PATCH한다.

---

## 4. 작업 계획

### Task 1: preview API 테스트 작성

**Files:**

- `backend/tests/test_copy_rewrite_preview.py`

**Checks:**

- preset별로 다른 rewrite intent가 적용된다.
- `[AI 수정됨]`이 절대 나오지 않는다.
- 수동 수정된 입력이 rewrite source가 된다.

### Task 2: preview API 구현/보강

**Files:**

- `backend/src/api/pages.py`
- `backend/src/services/copy_rewrite_service.py`

**Implementation:**

- `POST /page/sections/{section_id}/copy-rewrite/preview`
- request: current title/body, preset, optional user instruction
- response: before, after, rationale, safety_notes

### Task 3: 비교 모달 UI 구현

**Files:**

- `frontend/src/components/ReviewEditorLayout.tsx`
- `frontend/src/components/AiCopyRewriteCompareModal.tsx`

**Implementation:**

- 수정 전/후 카드 표시
- 적용, 다시 생성, 취소 버튼
- 적용 전 PATCH 금지

### Task 4: E2E 검증

**Files:**

- `frontend/e2e/review-editor-reframe.spec.ts`

**Checks:**

- 버튼 클릭 시 비교 모달 표시
- `이 수정안 적용` 후 PATCH 발생
- `[AI 수정됨]` count 0
- 수동 수정 값 기준으로 rewrite 요청

---

## 5. 완료 기준

- AI 수정 버튼은 목적별로 실제 다른 문구를 제안한다.
- 비교 모달 없이 즉시 덮어쓰지 않는다.
- 수기 수정 내용이 보존된다.
- `[AI 수정됨]` 또는 내부 지시문이 노출되지 않는다.

