# Sprint 76 실제 상품 누끼 기반 장면 합성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` and `superpowers:systematic-debugging` for image fidelity regressions.

**Goal:** AI가 상품 본체를 새로 그려 실제 상품과 달라지는 문제를 줄이고, 업로드 상품 이미지의 누끼를 중심으로 배경·조명·그림자·장면을 자연스럽게 합성한다.

**Scope:** 상품 이미지 누끼 생성/저장, 섹션별 이미지 전략, AI 보정 후보 라벨, 이미지 후보 패널 표시.

---

## 1. 해결할 문제

AI가 상품을 새로 생성하면 실제 상품과 달라질 수 있다.

- 팬 모양이 달라짐
- 버튼 위치가 달라짐
- 색상/재질이 달라짐
- 로고나 디스플레이가 바뀜
- 손에 든 장면에서 제품 비율이 바뀜

정확한 상세페이지를 위해 상품 본체는 실제 업로드 이미지에서 가져온 누끼를 기준으로 유지해야 한다.

---

## 2. 이미지 모드

| 모드 | 설명 | 사용 위치 |
| --- | --- | --- |
| 정확도 우선 | 실제 상품 누끼를 거의 그대로 사용 | Hero, 스펙, 구매 전 체크 |
| 자연스러운 합성 | 누끼 상품에 배경, 그림자, 조명을 맞춤 | 라이프스타일, 책상, 침대, 차량, 야외 |
| AI 보정 후보 | 손에 든 장면, 측면 느낌 등 AI가 일부 변형 | 사용 장면 후보, 검수 필요 |

정면 사진 1장만으로 측면이나 손에 쥔 장면을 만들면 AI 추정이 들어간다. 이 후보는 반드시 `AI 보정 후보 - 검수 필요`로 표시한다.

---

## 3. 섹션별 이미지 전략

| 섹션 | 처리 방식 |
| --- | --- |
| Hero | 실제 상품 누끼 + 고급 배경 + HTML 문구 |
| Problem | 문제 상황 이미지 또는 HTML 카드 |
| Lifestyle | 누끼 상품을 장면에 합성 |
| Comparison | HTML/CSS 비교 카드 + 상품 누끼 |
| Features | 아이콘/카드형 HTML 그래픽 |
| Specs | 이미지 생성하지 않고 HTML/CSS 표 |
| Pre-purchase | 체크리스트 카드 |
| CTA | 상품 누끼 + 마지막 확인 문구 |

---

## 4. 작업 계획

### Task 1: 상품 누끼 asset 모델 정의

**Files:**

- `backend/src/models.py`
- `backend/src/api/assets.py`
- migration 파일

**Implementation:**

- 원본 상품 이미지와 누끼 이미지를 연결한다.
- asset metadata에 `source_asset_id`, `cutout_status`, `background_removed`, `product_identity_preserved`를 저장한다.

### Task 2: 누끼 생성 서비스 추가

**Files:**

- `backend/src/services/product_cutout_service.py`
- `backend/tests/test_product_cutout_service.py`

**Implementation:**

- 업로드 이미지에서 배경 제거를 수행한다.
- 외부 API가 없거나 실패하면 원본 이미지를 안전 fallback으로 사용한다.
- 투명 PNG 또는 마스크 asset을 저장한다.

### Task 3: 이미지 생성 프롬프트를 합성 중심으로 변경

**Files:**

- `backend/src/services/image_generation_service.py`
- `backend/src/api/pages.py`

**Implementation:**

- “상품을 새로 그려라”가 아니라 “제공된 상품 누끼를 유지하라”는 계약으로 변경한다.
- Hero/Lifestyle은 누끼와 배경 합성 중심으로 요청한다.
- Specs/Comparison/Pre-purchase는 이미지 생성 대신 HTML/CSS 그래픽으로 보낸다.

### Task 4: 이미지 후보 패널 라벨 추가

**Files:**

- `frontend/src/components/DetailPageImageCandidatePanel.tsx`

**Labels:**

- `실제 상품 누끼 사용`
- `AI 배경 합성`
- `AI 보정 후보 - 검수 필요`
- `HTML 그래픽`
- `상품 형태 변경 가능성 있음`

---

## 5. 완료 기준

- Hero 섹션은 실제 상품 누끼 기반 이미지를 우선 사용한다.
- 스펙/비교/체크리스트는 불필요한 AI 사진을 만들지 않는다.
- AI 보정 후보에는 검수 필요 라벨이 보인다.
- 상품 정체성 보존 여부를 테스트와 UI에서 확인할 수 있다.

