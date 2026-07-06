# Sprint 68 Studio V2 기획 초안 흐름 기획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**목표:** 상품 입력 후 곧바로 최종 상세페이지를 만들지 않고, 먼저 Hookable식 `기획 초안`을 생성해 사용자가 구조를 검수한 뒤 상세페이지를 만들 수 있게 한다.

**아키텍처:** 상품 입력 데이터에서 `PlanningDraft`를 생성하고, 사용자가 섹션을 수정/삭제/정렬/승인하면 그 기획안을 `ProductPage`와 visual strategy로 변환한다. quick mode는 기존 직접 생성 흐름을 유지하고, quality mode는 planning draft를 거친다.

**기술 스택:** FastAPI, SQLAlchemy, Pydantic, Next.js App Router, React, LLM router, pytest, Playwright E2E

---

## 1. 왜 필요한가

현재 Sellform은 상품 입력 후 결과 상세페이지로 바로 이동하는 느낌이 강하다. 결과물이 이상하면 사용자는 이미 만들어진 상세페이지를 사후 수정해야 한다.

Hookable식 레퍼런스에서 좋았던 점은 중간에 `기획 초안` 단계가 있다는 것이다.

장점:

- 마케팅을 몰라도 팔리는 구조를 먼저 볼 수 있다.
- 상세페이지를 만들기 전에 섹션 구성을 수정할 수 있다.
- 이미지 생성 prompt 품질이 좋아진다.
- 최종 결과물이 뜬금없이 나오지 않는다.

---

## 2. 사용자 흐름

```text
상품 정보 입력
  ↓
AI 기획 초안 생성
  ↓
기획 초안 검수/수정
  ↓
상세페이지 만들기
  ↓
이미지/HTML visual 생성
  ↓
검수하며 다듬기
  ↓
PNG/JPG 다운로드
```

---

## 3. 기획 초안 카드

필수 카드:

- 히어로 메시지
- 타깃 고객
- 문제 상황
- 핵심 장점
- 사용 장면
- 비교 포인트
- 구매 전 확인사항
- 구성품/스펙
- 주의사항
- 최종 CTA

각 카드 필드:

```json
{
  "id": "draft-section-id",
  "type": "hero",
  "label": "히어로",
  "title": "무선 냉각으로 어디서나 쾌적함",
  "bullets": ["무선 충전 기반", "책상·차량·캠핑 사용"],
  "source_fact_ids": ["fact-id"],
  "visual_strategy": "image_overlay",
  "is_enabled": true,
  "sort_order": 0
}
```

---

## 4. 파일 구조

백엔드 생성:

- `backend/src/services/planning_draft_service.py`
- `backend/tests/test_planning_draft_service.py`

백엔드 수정:

- `backend/src/api/pages.py`
- `backend/src/services/detail_page_orchestrator.py`
- `backend/src/services/visual_package_planner.py`

프론트엔드 생성:

- `frontend/src/app/workspace/projects/[id]/planning/page.tsx`
- `frontend/src/components/planning/PlanningDraftEditor.tsx`
- `frontend/src/components/planning/PlanningDraftCard.tsx`
- `frontend/src/components/planning/PlanningModeSelector.tsx`

테스트:

- `frontend/e2e/planning-draft-flow.spec.ts`
- `backend/tests/test_planning_draft_service.py`

---

## 5. 작업 계획

### Task 1 — PlanningDraft schema 정의

- [ ] Pydantic schema를 만든다.
- [ ] DB 저장 방식은 초기에는 `ProductProject.intake_snapshot` 또는 별도 JSON 필드를 사용한다.
- [ ] 카드 id, type, title, bullets, source fact ids, visual strategy를 포함한다.

### Task 2 — PlanningDraft 생성 서비스 구현

- [ ] 확인된 product facts를 기반으로 기본 10개 섹션을 만든다.
- [ ] facts가 부족하면 사용자 입력 raw text를 기반으로 안전한 초안을 만든다.
- [ ] 검증되지 않은 수치나 최상급은 만들지 않는다.

### Task 3 — 기획 초안 API 추가

- [ ] `POST /projects/{project_id}/planning-draft` 생성 API를 추가한다.
- [ ] `GET /projects/{project_id}/planning-draft` 조회 API를 추가한다.
- [ ] `PATCH /projects/{project_id}/planning-draft` 수정 API를 추가한다.
- [ ] `POST /projects/{project_id}/planning-draft/approve` 승인 API를 추가한다.

### Task 4 — 기획 초안 편집 UI 구현

- [ ] 카드 목록을 보여준다.
- [ ] 카드 title/bullets를 수정할 수 있게 한다.
- [ ] 카드 숨김/표시를 지원한다.
- [ ] 순서 변경은 Sprint 68에서는 간단한 up/down 버튼으로 시작한다.
- [ ] 하단에 `상세페이지 만들기` CTA를 둔다.

### Task 5 — 승인된 기획안을 상세페이지로 변환

- [ ] 승인된 draft card를 `PageSection`으로 변환한다.
- [ ] card의 `visual_strategy`를 `visual_kind`, `visual_payload`, 이미지 생성 job 계획으로 변환한다.
- [ ] 이후 기존 상세페이지 생성/검수 흐름으로 연결한다.

### Task 6 — E2E 추가

- [ ] 상품 입력 후 planning 화면으로 이동하는지 확인한다.
- [ ] 기획 카드가 10개 이상 생성되는지 확인한다.
- [ ] 카드 하나를 수정하고 저장되는지 확인한다.
- [ ] `상세페이지 만들기`를 누르면 result/review 흐름으로 이어지는지 확인한다.

실행:

```bash
npx.cmd playwright test e2e/planning-draft-flow.spec.ts --project=chromium --reporter=line
```

---

## 6. 완료 기준

- 사용자가 최종 상세페이지 전에 기획 초안을 볼 수 있다.
- 기획 초안 카드를 수정할 수 있다.
- 승인된 기획안으로 상세페이지가 생성된다.
- quick mode와 quality mode가 구분된다.
- E2E에서 planning draft 흐름이 검증된다.

