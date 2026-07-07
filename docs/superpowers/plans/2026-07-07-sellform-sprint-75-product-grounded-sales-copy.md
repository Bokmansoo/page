# Sprint 75 제품 기반 판매 카피 품질 개선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` before implementation. This sprint changes generation behavior, so write failing tests before changing prompts/services.

**Goal:** 상품 링크·상품 정보·입력 특징을 근거로 구매자가 읽는 판매 카피를 생성하고, 내부 기획 지시문이 최종 상세페이지에 노출되지 않게 한다.

**Scope:** 기획 초안 생성 서비스, 상세페이지 섹션 카피 생성, 금지 문구 필터, mock/real 모드 품질 테스트.

---

## 1. 해결할 문제

현재 결과물에는 다음처럼 고객용 문구가 아닌 내부 지시문이 노출된다.

- `가장 먼저 보여줄 핵심 사용 가치를 한 문장으로 정리합니다.`
- `상품 입력 정보를 바탕으로 안전한 표현을 사용합니다.`
- `구매자가 불편을 느끼는 순간부터 보여주세요.`
- `확인된 장점만 또렷하게 정리해요.`

이 문구는 상세페이지 대본이 아니라 AI에게 주어야 할 작성 가이드다.

---

## 2. 목표 대본 구조

AI는 상품 정보에서 확인 가능한 사실을 바탕으로 아래 흐름을 만든다.

1. 문제 제기: 고객의 핵심 불편
2. 메인 소구점: 이 제품이 해결하는 핵심 메시지
3. 소구점 A: 가장 강한 장점
4. 소구점 B: 추가 장점과 사용 장면
5. 소구점 A 재강조: 핵심 메시지 반복
6. 소구점 B~D 정리: 장점 카드/리스트
7. 전체 요약: 구매 이유 한 문장
8. 상품 정보: 스펙, 구성품, 충전, 사용 조건, 구매 전 체크

---

## 3. 카피 생성 규칙

### 반드시 해야 할 것

- 상품명, 상품 링크, 입력 특징, 업로드 이미지에서 확인 가능한 정보만 사용한다.
- `무엇을`, `어디서`, `왜 쓰는지`가 제목에 드러나게 한다.
- 문제 상황과 제품 장점을 연결한다.
- 구매 전 확인사항은 신뢰형 문구로 정리한다.

### 금지할 것

- 없는 기능, 수치, 인증, 효과 만들기
- `최고`, `완벽`, `무조건` 같은 근거 없는 확정 표현
- `+`, `—`, `[AI 수정됨]` 같은 어색한 마커
- `정리합니다`, `보여주세요`, `입력 정보를 바탕으로`, `안전한 표현` 같은 내부 문구

---

## 4. 작업 계획

### Task 1: 금지 문구 테스트 작성

**Files:**

- `backend/tests/test_planning_draft_service.py`
- `backend/tests/test_page_composer_copy_quality.py`

**Checks:**

- mock 모드 결과에도 내부 지시문이 없어야 한다.
- real LLM fallback 결과에도 내부 지시문이 없어야 한다.
- 제목에 `+`, `—`, `[AI 수정됨]`이 없어야 한다.

### Task 2: 상품 사실 추출 컨텍스트 정리

**Files:**

- `backend/src/services/planning_draft_service.py`
- `backend/src/services/page_composer_service.py`

**Implementation:**

- 상품 입력값을 `product_facts`로 정규화한다.
- 상품 링크 수집 정보가 있으면 우선 사용한다.
- 사용자가 입력한 특징, 옵션, 이미지 설명을 함께 반영한다.
- 불확실한 정보는 `needs_verification`으로 분리하고 최종 카피에는 단정하지 않는다.

### Task 3: 프롬프트와 mock fallback 교체

**Files:**

- `backend/src/services/planning_draft_service.py`

**Implementation:**

- 시스템 프롬프트를 UTF-8 한글로 복구한다.
- JSON schema를 고객 노출 문구 중심으로 재정의한다.
- mock fallback도 실제 판매 카피 예시로 교체한다.

### Task 4: 품질 가드 추가

**Files:**

- `backend/src/services/copy_quality_guard.py` 또는 기존 서비스 내부

**Implementation:**

- 금지 문구 검사
- 과장 표현 검사
- 빈약한 제목 검사
- 내부 메타 문구 검사
- 실패 시 fallback 재작성 또는 안전한 기본 카피 적용

---

## 5. 완료 기준

- 상세페이지 결과에 내부 기획 문구가 나오지 않는다.
- 상품 정보 기반으로 구매자가 이해 가능한 판매 카피가 생성된다.
- 금지 문구 테스트가 통과한다.
- mock 모드와 real 모드 모두 같은 품질 가드를 통과한다.

