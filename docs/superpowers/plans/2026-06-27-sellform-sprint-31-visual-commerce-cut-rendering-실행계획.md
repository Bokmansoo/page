# Sprint 31 - 이미지 중심 커머스 컷 렌더링 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sprint 30의 “텍스트 카드 + 이미지 슬롯” 결과물을 쿠팡/스마트스토어 상세페이지처럼 이미지, 배경, 카피가 한 컷 안에서 함께 보이는 커머스형 상세페이지 이미지로 고도화한다.

**Architecture:** 기존 사실 카드, 페이지 섹션, 이미지 매핑 구조는 유지하되, 렌더링 계층에 “visual commerce cut” 모델을 추가한다. 각 섹션은 긴 본문 카드가 아니라 `headline`, `subcopy`, `supporting_text`, `visual_role`, `image_asset_id`, `background_style`을 가진 하나의 광고 컷으로 변환된다.

**Tech Stack:** FastAPI, Python, Pillow, PostgreSQL, Next.js, TypeScript, Tailwind CSS, 기존 export/rendering 서비스.

---

## 1. 배경

현재 Sprint 30 결과물은 상세페이지라기보다 텍스트 중심 카드에 이미지 자리가 붙은 형태다. 실제 판매용 상세페이지는 글보다 이미지가 중심이고, 카피는 이미지 안이나 이미지 주변에 짧게 배치되어야 한다.

사용자가 기대하는 결과물은 다음과 같다.

- 세로형 상세페이지 안에 여러 개의 “광고 컷”이 이어진다.
- 각 컷은 배경색, 상품 이미지, 상황 이미지, 짧은 헤드라인, 보조 카피를 함께 가진다.
- 긴 본문은 줄이고, 핵심 메시지와 근거만 남긴다.
- 이미지가 없을 때는 빈 사각형이 아니라 “이미지 필요” 상태나 AI 배경 fallback이 명확하게 보인다.

## 2. 범위

### 포함

- 섹션별 커머스 컷 데이터 모델 추가
- 섹션 카피를 컷용 짧은 문장으로 압축하는 서비스 추가
- 시각 역할(`visual_role`) 분류 추가
- hero/problem/benefit/spec/proof 등 컷 타입별 레이아웃 정의
- page-editor 미리보기에서 컷형 레이아웃 표시
- export PNG에서 이미지와 카피가 한 컷 안에 배치되도록 렌더링
- 이미지가 없는 섹션에 대한 명확한 fallback 처리
- 테스트 로그, 코드 리뷰, 트러블슈팅 문서 작성

### 제외

- Figma MCP 연동
  - Sprint 32에서 별도 진행한다.
- 실제 AI 이미지 생성 API 연동
  - Sprint 28 계열에서 다루며, Sprint 31은 기존/업로드/생성된 이미지 자산을 배치하는 데 집중한다.
- 쿠팡/스마트스토어 자동 업로드
- 영상 기반 상세페이지 생성

## 3. 목표 결과물

Sprint 31 완료 후 export 이미지는 다음 특징을 가져야 한다.

```text
[문제 제기 컷]
짙은/밝은 배경 + 큰 헤드라인 + 상품/상황 이미지 + 짧은 문제 카피

[메인 소구 컷]
상품 이미지 중심 + 핵심 장점 1개 + 근거 작은 글씨

[추가 장점 컷]
이미지 좌/우 배치 + 장점 1~2개

[스펙/구매 판단 컷]
표 형태 정보 + 인증/모델명/구성품 근거
```

긴 문단을 그대로 넣지 않고, 컷별로 읽히는 문장 수를 제한한다.

## 4. 설계 방향

### 4.1 커머스 컷 모델

새로운 내부 표현을 추가한다.

```python
@dataclass
class CommerceVisualCut:
    section_id: str
    section_type: str
    layout_type: str
    visual_role: str
    headline: str
    subcopy: str
    supporting_text: str | None
    image_asset_id: str | None
    background_style: str
    emphasis_level: int
```

권장 `layout_type`:

- `hero_visual`
- `problem_visual`
- `main_claim_visual`
- `benefit_visual`
- `proof_visual`
- `spec_visual`
- `summary_visual`

권장 `visual_role`:

- `product_main`
- `lifestyle_scene`
- `detail_closeup`
- `proof_or_certification`
- `spec_table`
- `background_only`

### 4.2 카피 길이 제한

커머스 컷은 본문을 길게 넣지 않는다.

기본 제한:

- headline: 26자 이내 권장, 최대 36자
- subcopy: 60자 이내 권장, 최대 90자
- supporting_text: 80자 이내 권장

초과 시:

- 프론트 미리보기에서는 경고 표시
- export에서는 자동 줄바꿈과 축약 처리
- 장기적으로는 AI 재작성 기능과 연결

### 4.3 이미지 없는 경우

이미지가 없을 때는 다음 순서로 fallback한다.

1. 해당 섹션의 `image_asset_id`
2. 프로젝트 대표 이미지
3. 선택된 AI 배경 후보
4. 카테고리별 fallback visual block
5. “이미지 필요” 안내 영역

단, 최종 export에서는 빈 연한 파란 박스만 반복되지 않도록 한다. 이미지가 없으면 이미지가 없는 이유와 필요한 이미지 유형을 작게 표시한다.

## 5. 구현 작업

### Task 1. 커머스 컷 변환 서비스 추가

**Files:**

- Create: `backend/src/services/commerce_visual_cut_builder.py`
- Test: `backend/tests/test_commerce_visual_cut_builder.py`

작업:

- [ ] `CommerceVisualCut` dataclass를 만든다.
- [ ] `build_commerce_visual_cuts(page, assets, project)` 함수를 만든다.
- [ ] 기존 `PageSection`을 컷 모델로 변환한다.
- [ ] section_type별 layout_type을 매핑한다.
- [ ] section_type별 visual_role을 매핑한다.
- [ ] 긴 body_copy를 subcopy/supporting_text로 나눈다.

테스트:

- [ ] `problem_statement`는 `problem_visual`로 변환된다.
- [ ] `main_claim`은 `main_claim_visual`로 변환된다.
- [ ] `product_information`은 `spec_visual`로 변환된다.
- [ ] 긴 문장은 headline/subcopy/supporting_text로 분리된다.
- [ ] image_asset_id가 있는 섹션은 그대로 컷에 반영된다.

### Task 2. Visual renderer를 컷 기반으로 확장

**Files:**

- Modify: `backend/src/services/visual_page_renderer.py`
- Test: `backend/tests/test_visual_page_renderer_commerce_cuts.py`

작업:

- [ ] 기존 텍스트 카드형 렌더링 경로를 보존한다.
- [ ] 새 컷 모델을 받아 `visual_slot`, `copy_block`, `background_block`을 만든다.
- [ ] hero/problem/main_claim 섹션은 이미지가 크게 보이도록 한다.
- [ ] benefit/spec 섹션은 이미지와 텍스트가 분할 배치되도록 한다.
- [ ] 이미지가 없을 때 fallback block을 명확히 표시한다.

완료 기준:

- [ ] 같은 페이지 데이터로 기존 카드형보다 이미지 영역 비율이 커진다.
- [ ] 각 컷의 headline이 본문보다 더 큰 위계로 렌더링된다.
- [ ] 이미지 없는 섹션이 빈 박스만 반복되지 않는다.

### Task 3. Export service에서 컷형 PNG 렌더링 반영

**Files:**

- Modify: `backend/src/services/export_service.py`
- Test: `backend/tests/test_export_commerce_visual_cuts.py`

작업:

- [ ] export 전에 page section을 `CommerceVisualCut`으로 변환한다.
- [ ] 컷별 배경색/이미지/카피 레이어를 순서대로 합성한다.
- [ ] 이미지가 있는 컷은 이미지 영역이 전체 컷의 최소 35% 이상 차지하도록 한다.
- [ ] 텍스트는 이미지 위에 직접 덮을 때 반투명 패널 또는 대비 배경을 사용한다.
- [ ] 긴 텍스트는 자동 줄바꿈하고, 지나치게 길면 supporting_text로 내려보낸다.

완료 기준:

- [ ] export 결과물에서 섹션마다 이미지 또는 시각 블록이 보인다.
- [ ] 본문 문단이 길게 뭉쳐 보이지 않는다.
- [ ] 상품 이미지와 카피가 한 컷 안에서 같이 보인다.

### Task 4. Page editor 미리보기 UX 개선

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
- Optional Create: `frontend/src/components/CommerceCutPreview.tsx`

작업:

- [ ] 미리보기를 카드형이 아니라 컷형 레이아웃으로 표시한다.
- [ ] 섹션 리스트에 `visual_role` 또는 이미지 필요 상태를 표시한다.
- [ ] 이미지가 없는 섹션에는 “이 컷에는 제품/상황 이미지가 필요합니다” 안내를 표시한다.
- [ ] 선택된 섹션 편집 패널에서 headline/subcopy/supporting_text를 구분해 보여준다.
- [ ] 기존 section title/body_copy 편집은 유지한다.

완료 기준:

- [ ] 사용자가 결과물이 실제 상세페이지 컷처럼 나올지 편집 화면에서 예측할 수 있다.
- [ ] 이미지 없는 이유를 사용자가 이해할 수 있다.

### Task 5. 컷 품질 검사 추가

**Files:**

- Create: `backend/src/services/commerce_cut_quality.py`
- Test: `backend/tests/test_commerce_cut_quality.py`

작업:

- [ ] 컷별 이미지 존재 여부를 검사한다.
- [ ] headline/subcopy 길이 초과를 검사한다.
- [ ] 이미지 없는 중요 섹션(hero/problem/main_claim)을 warning으로 표시한다.
- [ ] product_information 섹션이 너무 긴 경우 warning으로 표시한다.

완료 기준:

- [ ] export 전 “이미지 중심 상세페이지 품질”을 검사할 수 있다.
- [ ] 사용자는 어떤 컷에 이미지나 카피 보완이 필요한지 알 수 있다.

## 6. 테스트 계획

### 백엔드

```cmd
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q
```

검증:

- [ ] 커머스 컷 변환 테스트 통과
- [ ] visual renderer 컷 테스트 통과
- [ ] export 컷 렌더링 테스트 통과
- [ ] 기존 Sprint 29~30 export 테스트 회귀 없음

### 프론트엔드

```cmd
cd frontend
npm.cmd run build
```

검증:

- [ ] page-editor 빌드 성공
- [ ] 컷 미리보기 컴포넌트 타입 오류 없음

### 수동 QA

1. PostgreSQL-only 모드로 서버를 실행한다.
2. 생활/리빙 상품 프로젝트를 만든다.
3. 상품 URL 또는 수동 텍스트로 사실 카드를 만든다.
4. 최소 3개 이상의 사실 카드를 확인됨으로 바꾼다.
5. 상세페이지 초안을 생성한다.
6. 이미지 자산이 있는 경우 자동 매핑을 실행한다.
7. page-editor에서 컷형 미리보기를 확인한다.
8. export 이미지를 생성한다.
9. 결과물이 “텍스트 카드”가 아니라 “이미지+카피 컷”으로 보이는지 확인한다.

## 7. 산출 문서

구현 완료 후 다음 문서를 작성한다.

- `docs/testing/2026-06-27-sellform-sprint-31-commerce-cut-rendering-test-log.md`
- `docs/reviews/2026-06-27-sellform-sprint-31-code-review.md`
- `docs/troubleshooting/2026-06-27-sellform-sprint-31-commerce-cut-rendering.md`
- 필요 시 `docs/decisions/2026-06-27-sellform-commerce-cut-rendering-strategy.md`

## 8. 리스크와 대응

### R1. 이미지가 없어도 상세페이지처럼 보이기 어려움

대응:

- 이미지 없는 섹션을 무리하게 꾸미지 않는다.
- 이미지 필요 상태를 명확히 표시한다.
- AI 배경은 상품 이미지를 대체하는 것이 아니라 보조 배경으로만 사용한다.

### R2. 텍스트가 너무 길어질 수 있음

대응:

- 컷 모델에서 headline/subcopy/supporting_text를 분리한다.
- 길이 초과 warning을 표시한다.
- export에서는 자동 줄바꿈과 축약을 적용한다.

### R3. 기존 export와 충돌할 수 있음

대응:

- 기존 카드형 렌더링 코드를 완전히 삭제하지 않는다.
- 컷형 렌더링은 별도 builder/service로 분리한다.
- 기존 테스트를 유지한다.

## 9. 완료 정의

- [ ] export 결과물이 섹션별 이미지 중심 컷으로 보인다.
- [ ] 최소 hero/problem/main_claim 중 1개 이상에 이미지 또는 시각 블록이 크게 들어간다.
- [ ] 긴 본문이 카드에 그대로 뭉쳐 들어가지 않는다.
- [ ] page-editor 미리보기에서 컷 구조를 확인할 수 있다.
- [ ] 이미지 없는 섹션의 fallback이 명확하다.
- [ ] 백엔드 테스트가 통과한다.
- [ ] 프론트 빌드가 통과한다.
- [ ] 테스트 로그, 코드 리뷰, 트러블슈팅 문서가 작성된다.
