# Sprint 64 Code Review: Integration Hardening

> **2026-07-06 재검증 정정:** 생성 이미지가 승인 전이면
> `identity_review_required` blocker를 반환하도록 readiness를 보강했고,
> golden path를 결과 렌더링 → copy rewrite 비교/적용 PATCH → readiness →
> PNG/JPG 저장 검증 흐름으로 교체했다. 백엔드 통합 회귀 50개,
> Chromium 통합 E2E 5개, frontend production build가 모두 통과했다.

> **Review date:** 2026-07-06
> **Sprint goal:** 기존 프로젝트를 새 visual contract로 안전하게 보정하고 생성·검수·편집·PNG/JPG 다운로드 전체 흐름의 회귀를 차단한다.

---

## 1. 변경 파일 목록

### 생성 (Create)
| 파일 | 설명 |
|------|------|
| `backend/src/services/visual_contract_backfill.py` | 기존 PageSection에 visual_kind/payload idempotent backfill |
| `backend/src/services/page_readiness_service.py` | 통합 readiness validator (visual contract, asset, edit marker, grounding) |
| `backend/tests/test_visual_contract_backfill.py` | Backfill 4개 테스트 |
| `backend/tests/test_page_readiness_service.py` | Readiness 4개 테스트 |
| `frontend/e2e/upload-ready-golden-path.spec.ts` | 전체 golden path E2E (result → 편집 → 다운로드) |

### 수정 (Modify)
| 파일 | 변경 내용 |
|------|-----------|
| `backend/src/api/pages.py` | `GET /page/readiness` endpoint 추가 |
| `backend/src/api/exports.py` | Export 시 readiness check 추가 |
| `backend/src/services/visual_package_planner.py` | `plan_visual_package()`에 `scene_plan` 파라미터 추가, html_graphic skip |
| `backend/tests/test_visual_package_planner.py` | scene_plan html_graphic skip 테스트 추가 |
| `docs/runbooks/2026-07-03-sellform-server-start-and-llm-mode-guide.md` | 포트 표, readiness 확인 명령 추가 |

---

## 2. 아키텍처 검토

### 2.1 Backfill 흐름

```
backfill_page_visuals(db, project_id)
    │
    ├── 각 PageSection 순회
    │   ├── visual_kind 이미 있음 → skip (idempotent)
    │   ├── image_asset_id 있음 → visual_kind="image", payload={hero_overlay|image_text}
    │   └── image_asset_id 없음 → visual_kind="html_graphic"
    │       └── build_grounded_html_payload()
    │           ├── confirmed facts 조회
    │           ├── comparison/benefit → cards 배열
    │           ├── spec_table → table_rows 배열
    │           └── facts 없으면 section title/body로 needs_review fallback
    │
    └── commit() → BackfillReport(updated=N)
```

### 2.2 Readiness Validator 검사 항목

| 검사 | 코드 | 심각도 |
|------|------|--------|
| Visual contract completeness | `visual_*` | blocker |
| Asset eligibility | `asset_not_eligible` | blocker |
| `[AI 수정됨]` edit marker | `internal_edit_marker` | blocker |
| Grounding claim risks | `grounding_*` | warning |
| Unverified fact exposure | `unverified_fact_exposed` | warning |

Readiness는 `GET /page/readiness`와 export POST에서 동일한 `inspect_page_readiness()`를 호출한다.

### 2.3 Visual job scene_plan 통합

```
VisualPackagePlanner.plan_visual_package(project, page, assets, scene_plan)
    │
    ├── scene_plan에서 visual_strategy="html_graphic" 섹션 ID 수집
    ├── cut loop에서 html_graphic 섹션 skip
    └── image generation job은 image 섹션만 생성
```

---

## 3. 테스트 검증

### 3.1 Backend 전체 (34 passed)

| 테스트 | 결과 |
|--------|------|
| `test_page_visual_contract.py` (9 tests) | ✅ |
| `test_visual_contract_backfill.py` (4 tests) | ✅ |
| `test_page_readiness_service.py` (4 tests) | ✅ |
| `test_copy_rewrite_service.py` (11 tests) | ✅ |
| `test_wysiwyg_export_contract.py` (6 tests) | ✅ |

### 3.2 주요 테스트 케이스

| 테스트명 | 검증 내용 |
|----------|-----------|
| `test_backfill_maps_images_and_html_graphics` | 2 image + 3 html_graphic 맵핑, idempotent 확인 |
| `test_backfill_uses_confirmed_facts_for_html` | confirmed facts로 cards/rows 생성 |
| `test_readiness_distinguishes_html_visual_from_missing_image` | html_graphic은 image_asset_id 없어도 blocker 아님 |
| `test_readiness_blocks_edit_marker` | `[AI 수정됨]` 발견 시 blocker |
| `test_readiness_blocks_invalid_html_layout` | unknown layout → blocker |
| `test_visual_package_reuses_scene_plan_strategy` | html_graphic 섹션은 image job에서 제외 |

### 3.3 Frontend Verification

- ✅ ESLint: 0 errors
- ✅ Production build: 성공
- ✅ Golden path E2E spec 작성

---

## 4. 주요 설계 결정

### 4.1 Backfill은 idempotent
- `if section.visual_kind: continue` — 이미 backfill된 섹션은 건너뜀
- 두 번째 호출 시 `updated=0` 반환

### 4.2 `build_grounded_html_payload()`는 confirmed facts만 사용
- facts가 없으면 section title/body로 fallback, `verification_status="needs_review"`
- 근거 없는 판매 문장이 생성되지 않도록 보호

### 4.3 Readiness가 export 전에 이중 검사
- `GET /page/readiness` — 프론트에서 사전 확인 가능
- Export POST — readiness check 후 compliance check 순서
- 동일한 `inspect_page_readiness()` 호출

### 4.4 scene_plan으로 visual job 통제
- `VisualPackagePlanner`가 독자적으로 image role을 추론하지 않고 scene_plan의 `visual_strategy` 사용
- `html_graphic` 섹션은 image job에서 제외

### 4.5 runbook에 포트 표 추가
- 백엔드(8001), 프론트엔드(3000/3100), E2E 포트 단일 표로 정리
- readiness 확인 명령 추가

---

## 5. 최종 결론

**✅ 통과.** Backend 34/34 테스트 통과, Frontend build 성공.

주요 변경사항:
1. `visual_contract_backfill` — 기존 프로젝트를 새 visual contract로 idempotent 변환
2. `page_readiness_service` — 단일 readiness validator (visual/asset/edit marker/grounding)
3. `GET /page/readiness` endpoint + export readiness check
4. `VisualPackagePlanner` scene_plan 통합 (html_graphic skip)
5. Golden path E2E (result → 편집 → 다운로드)
6. Runbook 갱신 (포트 표, readiness 명령)
