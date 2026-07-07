# Sprint 74 다운로드/출력 이력 정합성 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:test-driven-development` before implementation. Implement task-by-task and verify each checkpoint.

**Goal:** PNG/JPG 다운로드를 “상세페이지 본문만 저장되는 브라우저 다운로드”로 안정화하고, 같은 결과물이 Sellform 출력 이력에도 기록되게 만든다.

**Scope:** 결과 페이지 다운로드 버튼, 백엔드 export 다운로드 응답, 출력 이력 기록/조회, E2E 검증.

---

## 1. 해결할 문제

- 저장 위치 선택 창이 뜨지만 Chrome 다운로드 기록과 사용자가 기대하는 다운로드 경험이 다르게 동작한다.
- 파일명이 UUID 중심으로 노출된다.
- 출력 이력 페이지가 실제 다운로드 artifact와 연결되지 않는다.
- 저장 이미지에 상단 네비게이션, 버튼, 사이드 패널이 섞일 위험이 있다.

---

## 2. 구현 방향

### 기본 다운로드 정책

- 기본 버튼은 `showSaveFilePicker`가 아니라 브라우저 일반 다운로드 방식으로 동작한다.
- Chrome 다운로드 기록에 남는 `Blob URL + a[download]` 또는 백엔드 attachment URL 다운로드로 통일한다.
- “다른 이름으로 저장”은 별도 선택 기능으로 분리한다. 단, 이번 Sprint의 필수 범위는 일반 다운로드 안정화다.

### 파일명 정책

파일명은 상품명 기반으로 생성한다.

```text
{상품명-slug}-상세페이지.{png|jpg}
```

예:

```text
루메나-휴대용-무선-냉각선풍기-상세페이지.jpg
```

### 캡처 대상

- export render route는 상세페이지 문서 루트만 캡처한다.
- header, sticky CTA, 이미지 후보 패널, 검수/편집 버튼은 export 대상에서 제외한다.

---

## 3. 작업 계획

### Task 1: 다운로드 E2E를 사용자 기대 기준으로 고정

**Files:**

- `frontend/e2e/completed-detail-page-export.spec.ts`
- `frontend/e2e/export-history.spec.ts`

**Checks:**

- PNG 다운로드 파일명이 상품명 기반인지 검증한다.
- JPG 다운로드 파일명이 상품명 기반인지 검증한다.
- 다운로드된 이미지에 `Sellform`, `AI 상세페이지 생성`, `검수하며 다듬기`, `고급 편집기로 열기` 텍스트가 포함되지 않도록 검증한다.
- export 성공 후 출력 이력에 같은 항목이 노출되는지 검증한다.

### Task 2: 프론트엔드 다운로드 흐름 정리

**Files:**

- `frontend/src/components/GeneratedDetailPageResult.tsx`

**Implementation:**

- 기본 다운로드에서 `showSaveFilePicker` 우선 호출을 제거하거나 옵션으로 분리한다.
- 백엔드 export job 완료 후 `downloadBlob(blob, filename)` 흐름을 일관되게 사용한다.
- `Content-Disposition` 파일명이 있으면 사용하고, 없으면 상품명 기반 fallback 파일명을 만든다.
- 다운로드 실패 메시지는 사람이 이해하는 한국어로 표시한다.

### Task 3: 백엔드 export 응답 계약 정리

**Files:**

- `backend/src/api/exports.py`
- `backend/src/services/export_service.py`

**Implementation:**

- `FileResponse` 또는 streaming response에 정확한 `media_type`을 넣는다.
- `Content-Disposition`에 UTF-8 파일명을 넣는다.
- export asset에 `project_id`, `format`, `filename`, `content_type`, `created_at`을 저장한다.
- 출력 이력 조회 API가 해당 artifact를 반환하도록 정리한다.

### Task 4: 출력 이력 연결 검증

**Files:**

- `backend/src/api/exports.py`
- `frontend/src/app/workspace/exports/page.tsx`
- `frontend/e2e/export-history.spec.ts`

**Checks:**

- 방금 다운로드한 PNG/JPG가 출력 이력에 표시된다.
- 출력 이력에서 다시 다운로드할 수 있다.
- 비어 있는 상태와 API 오류 상태 메시지가 구분된다.

---

## 4. 완료 기준

- PNG/JPG 다운로드가 Chrome 다운로드 기록에 남는다.
- 파일명이 상품명 기반이다.
- 저장 이미지는 상세페이지 본문만 포함한다.
- 출력 이력에서 같은 export artifact를 확인하고 다시 다운로드할 수 있다.
- 관련 E2E가 Chromium에서 통과한다.

