# 코드 리뷰: Sellform Sprint 35 - Figma Visual Commerce Renderer

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-29 |
| 리뷰 범위 | Figma plugin visual layout payload, visual commerce renderer, payload validation, plugin tests/build |
| 기준 문서 | `docs/superpowers/plans/2026-06-28-sellform-sprint-35-figma-visual-commerce-renderer-실행계획.md` |
| 리뷰어 | Codex |

## 1. 변경 요약

- Backend Figma package payload에 `visual_layout` 확장 필드를 추가했다.
- `commerce_visual_v1` 레이아웃을 생성하는 backend builder를 추가했다.
- Figma plugin 계약 타입에 `VisualLayout`, `VisualCommerceCut`, `VisualSlot`을 추가했다.
- Figma plugin payload validator가 visual layout의 버전과 7개 컷 구성을 검증하도록 보강했다.
- 기존 텍스트 중심 renderer와 별도로 `visual-renderer.ts`를 추가했다.
- `renderDetailPage`는 visual layout이 있을 때 비주얼 커머스 renderer로 자동 분기한다.
- Figma plugin은 각 섹션을 860px 기준 commerce frame으로 만들고, 이미지가 있으면 `visual_image`, 없으면 `visual_placeholder`를 생성한다.
- headline/body/badge는 Figma에서 편집 가능한 text node로 생성된다.
- Figma plugin 전체 테스트와 build, frontend build까지 확인했다.

## 2. 기획 대비 구현 확인

| 기획 항목 | 구현 상태 | 확인 내용 |
| --- | --- | --- |
| Backend visual layout payload | 완료 | `visual_layout.layout_version = commerce_visual_v1`, 7개 cut 생성 |
| Figma plugin visual renderer | 완료 | `visual-renderer.ts` 추가, 860px root frame 및 7개 section 렌더링 |
| 이미지 중심 섹션 구조 | 부분 완료 | 이미지 bytes가 있으면 image fill, 없으면 visual placeholder와 warning 생성 |
| 기존 ticket/package flow 유지 | 완료 | 기존 import API 테스트 통과 |
| 기존 legacy renderer 유지 | 완료 | `renderer.test.ts` 기존 테스트 통과 |
| 테스트/리뷰/트러블슈팅 문서 | 완료 | testing, troubleshooting, review 문서 추가 |

## 3. 이슈 목록

심각도: 🔴 Blocker · 🟠 Major · 🟡 Minor · ⚪ Nit

### 🟡 M1. 실제 상품 이미지가 없으면 아직 placeholder가 많을 수 있음

- 위치: `integrations/figma-plugin/src/visual-renderer.ts`
- 내용: Sprint 35는 Figma에서 비주얼 커머스 구조를 만드는 데 집중했기 때문에, 이미지 매핑 품질 자체는 Sprint 36의 범위로 남아 있다.
- 영향: 사용자가 기대하는 “이미지 안에 글씨가 섞인 상세페이지”에 가까워졌지만, 이미지 자산이 부족하면 여전히 placeholder가 보일 수 있다.
- 권고: Sprint 36에서 상품 이미지 자동 매핑과 image role matching을 강화한다.

### 🟡 M2. Figma visual composition은 아직 기본형 중심

- 위치: `integrations/figma-plugin/src/visual-renderer.ts`
- 내용: hero/problem/solution/benefit/purchase별 높이와 색상 톤은 분리했지만, 실제 커머스 레퍼런스처럼 완전한 magazine형/카드뉴스형 compositing까지는 아니다.
- 영향: “예상 이미지” 수준의 고퀄리티 레이아웃은 Sprint 36~37의 이미지 매핑과 스타일 후보 선택이 결합되어야 안정화된다.
- 권고: Sprint 37에서 스타일 후보별 section layout preset을 분리한다.

## 4. 테스트 증적

### Backend

```powershell
uv run --project backend --group dev pytest backend/tests/test_figma_visual_layout_builder.py backend/tests/test_figma_plugin_visual_payload.py backend/tests/test_figma_plugin_api.py -q
```

결과:

```text
10 passed, 47 warnings in 1.22s
```

### Figma plugin

```powershell
npm.cmd test
```

작업 디렉터리:

```text
C:\page\integrations\figma-plugin
```

결과:

```text
Test Suites: 5 passed, 5 total
Tests:       16 passed, 16 total
```

### Figma plugin build

```powershell
npm.cmd run build
```

결과:

```text
Figma Plugin build succeeded.
```

### Frontend build

```powershell
npm.cmd run build
```

작업 디렉터리:

```text
C:\page\frontend
```

결과:

```text
✓ Compiled successfully
✓ Generating static pages (9/9)
```

## 5. 긍정적인 부분

- 기존 Figma plugin ticket flow를 깨지 않고 visual layout 확장만 추가한 점이 좋다.
- fallback renderer를 유지해서 구버전 payload도 계속 처리할 수 있다.
- 이미지가 없을 때 실패하지 않고 visual placeholder와 warning을 남기는 구조라 실제 운영에서 안전하다.
- 이제 Sprint 36/37에서 이미지 매핑과 스타일 후보를 붙이면 사용자가 원하는 “이미지 중심 상세페이지”로 발전시킬 수 있는 발판이 생겼다.

## 6. 최종 판단

Sprint 35는 기획서 기준으로 구현 완료로 판단한다.

다만 사용자가 기대하는 완성형 상세페이지 품질은 Sprint 35 단독으로 끝나는 것이 아니라, Sprint 36의 이미지 자동 매핑과 Sprint 37의 스타일 후보 선택까지 이어져야 한다.
