# Sprint 35 - Figma 비주얼 커머스 렌더러 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Figma Plugin으로 생성되는 상세페이지를 현재의 텍스트 중심 프레임에서 이미지, 배경, 짧은 카피, 카드형 정보가 섞인 커머스형 상세페이지 프레임으로 고도화한다.

**Architecture:** 기존 Sellform page draft와 Figma plugin ticket/package 구조는 유지한다. 백엔드 payload에 `visual_layout`과 섹션별 visual metadata를 추가하고, Figma plugin renderer가 이 metadata를 사용해 860px 상세페이지 안에 hero/problem/solution/benefit/spec/lifestyle/purchase 컷을 시각적으로 배치한다.

**Tech Stack:** FastAPI, Python, PostgreSQL, TypeScript, Figma Plugin API, Jest, Pytest.

---

## 1. 배경

Sprint 34까지 Figma Plugin 연동 자체는 성공했다. 하지만 실제 Figma 결과물은 텍스트 섹션을 세로로 배치한 기본 문서형 프레임에 가깝다.

사용자가 기대하는 결과물은 다음과 같다.

- 860px 폭의 쇼핑몰 상세페이지형 긴 세로 프레임
- 이미지 안에 카피가 자연스럽게 들어간 히어로 컷
- 문제 제기, 해결, 장점, 기능, 구매 정보가 각각 시각적으로 구분된 컷
- Figma에서 텍스트와 이미지가 편집 가능한 native node
- 이미지가 없더라도 단순 빈 박스가 아니라 의도적인 placeholder/visual block

즉, 이번 Sprint 35의 핵심은 “Figma 연결”이 아니라 “Figma로 만들어지는 결과물의 시각 품질”이다.

## 2. 범위

### 포함

- Figma payload에 `visual_layout` 필드 추가
- canonical 7단 섹션을 커머스 컷 구조로 변환
- Figma plugin renderer에 visual commerce rendering mode 추가
- 히어로, 문제제기, 솔루션, 장점, 기능, 라이프스타일, 구매 섹션별 레이아웃 구현
- 이미지가 없을 때의 고급 placeholder 구현
- Figma에서 편집 가능한 텍스트/이미지/카드 노드 생성
- backend/plugin/frontend 테스트와 코드리뷰 문서 갱신

### 제외

- 이미지 자체를 새로 생성하는 AI image generation
- 이미지 자동 매핑 고도화
- 여러 스타일 후보 선택 UX
- Figma MCP Remote OAuth 경로 재시도

이 제외 범위는 Sprint 36, Sprint 37에서 다룬다.

## 3. 목표 결과

Figma Plugin으로 코드를 가져오면 다음 구조의 프레임이 생성되어야 한다.

```text
Sellform / {상품명} 상세페이지
└─ 860px Root Frame
   ├─ 01_HERO
   │  ├─ 배경/제품 이미지 영역
   │  ├─ 강한 메인 카피
   │  └─ 핵심 아이콘 3~4개
   ├─ 02_PROBLEM
   │  ├─ 고객 불편 이미지/placeholder
   │  └─ 문제 제기 카피
   ├─ 03_SOLUTION
   │  ├─ 제품 클로즈업 이미지/placeholder
   │  └─ 해결 메시지
   ├─ 04_BENEFITS
   │  └─ 3개 카드형 장점
   ├─ 05_FEATURES
   │  └─ 스펙/기능 아이콘 그리드
   ├─ 06_LIFESTYLE
   │  └─ 사용 상황 이미지 카드
   └─ 07_PURCHASE
      └─ 구성품/구매 판단 정보
```

## 4. 파일 구조

### Backend

- Modify: `backend/src/services/figma_design_payload_builder.py`
  - Figma Plugin payload에 visual metadata를 포함한다.
- Create: `backend/src/services/figma_visual_layout_builder.py`
  - 7단 page section을 visual commerce layout model로 변환한다.
- Test: `backend/tests/test_figma_visual_layout_builder.py`
  - 섹션 타입별 visual layout 매핑을 검증한다.
- Test: `backend/tests/test_figma_plugin_visual_payload.py`
  - ticket/package payload에 `visual_layout`이 포함되는지 검증한다.

### Figma Plugin

- Modify: `integrations/figma-plugin/src/contracts.ts`
  - `visual_layout`, `VisualCommerceCut`, `VisualSlot`, `CommerceMetric` 타입 추가.
- Modify: `integrations/figma-plugin/src/payload-validator.ts`
  - visual layout schema validation 추가.
- Modify: `integrations/figma-plugin/src/renderer.ts`
  - 기존 단순 renderer와 visual commerce renderer 분기.
- Create: `integrations/figma-plugin/src/visual-renderer.ts`
  - 커머스 컷 전용 Figma node renderer.
- Create: `integrations/figma-plugin/tests/visual-renderer.test.ts`
  - 7단 컷, 이미지 placeholder, 텍스트 노드 생성 검증.

### Docs

- Create: `docs/testing/2026-06-28-sellform-sprint-35-figma-visual-renderer-test-log.md`
- Create: `docs/reviews/2026-06-28-sellform-sprint-35-code-review.md`
- Create: `docs/troubleshooting/2026-06-28-sellform-sprint-35-figma-visual-renderer.md`

## 5. 데이터 계약

### 추가 payload 예시

```json
{
  "schema_version": "1.1",
  "payload": {
    "title": "루메나 휴대용 무선 냉각선풍기",
    "visual_layout": {
      "layout_version": "commerce_visual_v1",
      "width": 860,
      "cuts": [
        {
          "section_type": "hero",
          "layout_type": "hero_split_visual",
          "headline": "한 손에 담는 시원함",
          "subcopy": "강력한 냉각 바람을 언제 어디서나",
          "image_role": "product_main",
          "image_asset_ref": "asset_hero_01",
          "badges": ["강력 냉각", "초경량", "저소음"],
          "background_tone": "cool_blue"
        }
      ]
    }
  }
}
```

### canonical cut mapping

| 기존 section_type | visual layout_type | 목적 |
| --- | --- | --- |
| `problem_statement` | `problem_visual` | 고객 불편을 시각화 |
| `main_claim` | `solution_visual` | 제품이 해결하는 핵심 가치 |
| `secondary_benefit` | `benefit_cards` | 추가 장점 카드화 |
| `main_claim_support` | `proof_visual` | 근거/인증/스펙 보강 |
| `benefit_list` | `feature_grid` | 기능/장점 그리드 |
| `summary_claim` | `lifestyle_visual` | 사용 상황 요약 |
| `product_information` | `purchase_info` | 구매 판단 정보 |

## 6. 구현 작업

### Task 1: visual layout builder 추가

**Files:**

- Create: `backend/src/services/figma_visual_layout_builder.py`
- Test: `backend/tests/test_figma_visual_layout_builder.py`

- [ ] Step 1: 실패 테스트 작성

검증 내용:

```python
def test_build_visual_layout_has_seven_commerce_cuts():
    layout = build_figma_visual_layout(project=project, page=page, assets=assets)
    assert layout["layout_version"] == "commerce_visual_v1"
    assert layout["width"] == 860
    assert len(layout["cuts"]) == 7
    assert layout["cuts"][0]["layout_type"] == "problem_visual"
```

- [ ] Step 2: 테스트 실패 확인

```cmd
uv run pytest backend/tests/test_figma_visual_layout_builder.py -q
```

Expected: `build_figma_visual_layout` import failure.

- [ ] Step 3: 최소 구현

`build_figma_visual_layout()`은 기존 `PageSection`을 정렬 순서대로 읽고, section_type 기반으로 layout_type, image_role, background_tone을 매핑한다.

- [ ] Step 4: 테스트 통과 확인

```cmd
uv run pytest backend/tests/test_figma_visual_layout_builder.py -q
```

Expected: PASS.

### Task 2: Figma payload에 visual layout 포함

**Files:**

- Modify: `backend/src/services/figma_design_payload_builder.py`
- Test: `backend/tests/test_figma_plugin_visual_payload.py`

- [ ] Step 1: 실패 테스트 작성

검증 내용:

```python
def test_figma_payload_contains_visual_layout():
    payload = build_figma_design_payload(project, page, assets)
    assert payload["schema_version"] in {"1.1", "1.0"}
    assert payload["visual_layout"]["layout_version"] == "commerce_visual_v1"
```

- [ ] Step 2: 테스트 실패 확인

```cmd
uv run pytest backend/tests/test_figma_plugin_visual_payload.py -q
```

- [ ] Step 3: payload builder에 visual layout 병합

기존 `cuts`는 하위 호환을 위해 유지하고, 새 `visual_layout`을 추가한다.

- [ ] Step 4: 관련 API 테스트 실행

```cmd
uv run pytest backend/tests/test_figma_plugin_api.py backend/tests/test_figma_plugin_visual_payload.py -q
```

### Task 3: Figma Plugin 계약과 validator 확장

**Files:**

- Modify: `integrations/figma-plugin/src/contracts.ts`
- Modify: `integrations/figma-plugin/src/payload-validator.ts`
- Test: `integrations/figma-plugin/tests/payload-validator.test.ts`

- [ ] Step 1: `visual_layout`이 있는 payload를 통과시키는 테스트 추가
- [ ] Step 2: `visual_layout.cuts.length !== 7`이면 `INVALID_VISUAL_CUT_COUNT`를 던지는 테스트 추가
- [ ] Step 3: 타입과 validator 구현
- [ ] Step 4: 테스트 실행

```cmd
cd C:\page\integrations\figma-plugin
npm.cmd test -- payload-validator.test.ts
```

### Task 4: visual commerce renderer 구현

**Files:**

- Create: `integrations/figma-plugin/src/visual-renderer.ts`
- Modify: `integrations/figma-plugin/src/renderer.ts`
- Test: `integrations/figma-plugin/tests/visual-renderer.test.ts`

- [ ] Step 1: 실패 테스트 작성

검증 내용:

- root frame width is 860
- root frame name contains product title
- 7 section frames exist
- hero section has background rectangle, headline text, badge nodes
- image missing section has intentional placeholder, not empty white space

- [ ] Step 2: 테스트 실패 확인

```cmd
cd C:\page\integrations\figma-plugin
npm.cmd test -- visual-renderer.test.ts
```

- [ ] Step 3: renderer 구현

권장 layout:

| section | height | image ratio | style |
| --- | ---: | ---: | --- |
| HERO | 560 | 55% | full bleed image + headline overlay |
| PROBLEM | 520 | 45% | image left / copy right |
| SOLUTION | 520 | 50% | product visual centered |
| BENEFITS | 620 | 60% | 3 cards |
| FEATURES | 460 | 20% | icon grid |
| LIFESTYLE | 620 | 70% | 3 lifestyle tiles |
| PURCHASE | 520 | 40% | 구성품 + 구매 판단 card |

- [ ] Step 4: 기존 renderer와 분기

`payload.visual_layout`이 있으면 visual renderer를 사용하고, 없으면 기존 renderer를 사용한다.

- [ ] Step 5: plugin build

```cmd
cd C:\page\integrations\figma-plugin
npm.cmd run build
```

### Task 5: 실제 Figma 수동 QA

**Files:**

- Update: `docs/testing/2026-06-28-sellform-sprint-35-figma-visual-renderer-test-log.md`
- Update: `docs/reviews/2026-06-28-sellform-sprint-35-code-review.md`

- [ ] Step 1: backend/frontend 실행
- [ ] Step 2: Sellform에서 Figma Plugin 코드 발급
- [ ] Step 3: Figma Plugin에서 코드 입력
- [ ] Step 4: 다음을 확인

체크리스트:

- [ ] root frame width 860
- [ ] 7개 section frame
- [ ] 최소 4개 섹션에 이미지 영역 또는 고급 placeholder
- [ ] headline이 이미지/배경과 같은 컷 안에 배치
- [ ] 텍스트 노드 직접 편집 가능
- [ ] 이미지 fill 교체 가능
- [ ] 이전 텍스트형 단순 프레임보다 시각적으로 명확히 개선

## 7. 검증 명령

```cmd
uv run pytest backend/tests/test_figma_visual_layout_builder.py backend/tests/test_figma_plugin_visual_payload.py backend/tests/test_figma_plugin_api.py -q
cd C:\page\integrations\figma-plugin
npm.cmd test
npm.cmd run build
cd C:\page\frontend
npm.cmd run build
```

## 8. 완료 기준

- Figma Plugin으로 생성한 결과물이 텍스트 문서형이 아니라 커머스 상세페이지 컷처럼 보인다.
- Figma root frame은 860px이며 canonical 7단 구조를 유지한다.
- 이미지가 없을 때도 의도적인 visual placeholder가 표시된다.
- 기존 JSON fallback과 ticket code import가 모두 유지된다.
- 자동 테스트, build, 수동 Figma QA, 코드리뷰 문서가 남는다.

