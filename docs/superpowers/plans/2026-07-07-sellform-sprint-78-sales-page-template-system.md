# Sprint 78 상세페이지 템플릿 고도화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:brainstorming` if template options change product UX, then `superpowers:test-driven-development` for implementation.

**Goal:** 상품군과 판매 목적에 맞는 상세페이지 구성 템플릿을 제공하고, 문제 제기부터 구매 전 확인까지 이어지는 설득 흐름을 안정화한다.

**Scope:** 템플릿 정의, 섹션 구조, 상품군별 variation, Studio V2 기획 초안과 최종 상세페이지 연결.

---

## 1. 기본 상세페이지 흐름

첨부 이미지의 “상세페이지 구성 방법”을 Sellform에 맞게 구조화한다.

1. 문제 제기: 고객의 핵심 고민
2. 메인 소구점 강조: 이 제품으로 해결 가능한 핵심 메시지
3. 소구점 A: 가장 강한 장점
4. 소구점 B: 추가 장점
5. 소구점 A 재강조: 핵심 메시지 반복
6. 소구점 B~D 정리: 나머지 장점 정리
7. 전체 요약: 전체 흐름을 한 문장으로 정리
8. 상품 정보: 최종 구매 판단용 정보

---

## 2. 템플릿 종류

| 템플릿 | 목적 |
| --- | --- |
| 기본 판매형 | 대부분의 일반 상품에 사용 |
| 문제 해결형 | 불편/고민 해결이 강한 상품 |
| 라이프스타일형 | 사용 장면과 감성이 중요한 상품 |
| 스펙 비교형 | 기능, 수치, 구성품 비교가 중요한 상품 |
| 초보 셀러형 | 쉬운 문장과 안전한 표현 우선 |
| 프리미엄형 | 고급스러운 톤과 브랜드 감성 우선 |

---

## 3. 섹션 컴포넌트 계약

각 섹션은 아래 데이터를 가진다.

```json
{
  "section_type": "problem",
  "role": "문제 제기",
  "headline": "더운 날, 손이 가는 선풍기는 따로 있죠",
  "body": "책상, 차량, 야외처럼 전원 연결이 번거로운 순간에도 바로 꺼내 쓸 수 있어야 합니다.",
  "evidence_fact_ids": ["wireless", "portable"],
  "visual_strategy": "html_graphic",
  "editable": true
}
```

필수 원칙:

- `role`은 내부 관리용이며 고객에게 그대로 노출하지 않는다.
- `headline`, `body`만 고객 노출 문구다.
- `evidence_fact_ids`로 어떤 상품 정보에 근거했는지 추적한다.
- `visual_strategy`는 이미지 생성, 누끼 합성, HTML 그래픽 중 하나를 명확히 지정한다.

---

## 4. 작업 계획

### Task 1: 템플릿 schema 정의

**Files:**

- `backend/src/services/detail_page_template_service.py`
- `backend/tests/test_detail_page_template_service.py`

**Implementation:**

- 템플릿 ID, 섹션 순서, 필수/선택 섹션 정의
- 상품군/목적별 템플릿 선택 규칙

### Task 2: Studio V2 기획 초안과 연결

**Files:**

- `backend/src/services/planning_draft_service.py`
- `frontend/src/app/workspace/projects/[id]/planning/page.tsx`

**Implementation:**

- 기획 초안 카드가 템플릿 섹션 구조와 매핑된다.
- 사용자가 섹션을 삭제/정렬하면 최종 상세페이지에도 반영된다.

### Task 3: 최종 렌더링 연결

**Files:**

- `backend/src/services/page_composer_service.py`
- `frontend/src/components/DetailPageDocument.tsx`

**Implementation:**

- 템플릿 섹션의 `visual_strategy`에 따라 이미지/HTML 그래픽 렌더링을 분기한다.
- `Specs`, `Pre-purchase`, `Comparison`은 기본적으로 HTML/CSS로 렌더링한다.

### Task 4: 템플릿별 E2E 추가

**Files:**

- `frontend/e2e/planning-template-flow.spec.ts`

**Checks:**

- 기본 판매형 템플릿 생성
- 문제 해결형 템플릿 생성
- 섹션 삭제/정렬 후 최종 상세페이지 반영
- 고객 노출 문구에 내부 role 문구가 나오지 않음

---

## 5. 완료 기준

- 상세페이지 구조가 상품군/판매 목적에 맞게 선택된다.
- 기획 초안과 최종 상세페이지 섹션이 일관되게 연결된다.
- 고객 노출 문구와 내부 기획 role이 분리된다.
- 템플릿별 E2E가 통과한다.

