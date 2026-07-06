# Sellform Sprint 64 Integration Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 프로젝트를 새 visual contract로 안전하게 보정하고 생성·검수·편집·PNG/JPG 다운로드 전체 흐름의 회귀를 차단한다.

**Architecture:** idempotent backfill service가 기존 section/candidate/fact를 canonical visual contract로 변환한다. 하나의 readiness validator가 결과 화면과 export API에 같은 blocker를 제공하며, production-like E2E fixture가 전체 흐름을 검증한다.

**Tech Stack:** FastAPI, SQLAlchemy, Next.js, Playwright, pytest

---

## 파일 구조

- Create: `backend/src/services/visual_contract_backfill.py`
- Create: `backend/src/services/page_readiness_service.py`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/api/exports.py`
- Modify: `backend/src/services/visual_package_planner.py`
- Create: `backend/tests/test_visual_contract_backfill.py`
- Create: `backend/tests/test_page_readiness_service.py`
- Create: `frontend/e2e/upload-ready-golden-path.spec.ts`
- Modify: `docs/runbooks/2026-07-03-sellform-server-start-and-llm-mode-guide.md`

### Task 1: 기존 프로젝트 idempotent backfill

**Files:**
- Create: `backend/src/services/visual_contract_backfill.py`
- Test: `backend/tests/test_visual_contract_backfill.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from src.db.models import PageSection, ProductPage, ProductProject


def test_backfill_maps_two_images_and_three_html_graphics(db_session):
    project = ProductProject(
        id="legacy-project",
        workspace_id="workspace-1",
        brand_id="brand-1",
        name="Legacy page",
    )
    page = ProductPage(id="legacy-page", project_id=project.id)
    sections = [
        PageSection(page_id=page.id, section_type="hero", image_asset_id="hero-asset", sort_order=0),
        PageSection(page_id=page.id, section_type="comparison", image_asset_id=None, sort_order=1),
        PageSection(page_id=page.id, section_type="detail_1", image_asset_id=None, sort_order=2),
        PageSection(page_id=page.id, section_type="detail_2", image_asset_id="detail-asset", sort_order=3),
        PageSection(page_id=page.id, section_type="guarantee", image_asset_id=None, sort_order=4),
    ]
    db_session.add_all([project, page, *sections])
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)
    assert report.updated == 5
    assert [section.visual_kind for section in page.sections] == [
        "image", "html_graphic", "html_graphic", "image", "html_graphic"
    ]

    second = backfill_page_visuals(db_session, project.id)
    assert second.updated == 0
```

- [ ] **Step 2: RED 확인**

Run: `uv run --project backend pytest backend/tests/test_visual_contract_backfill.py -v`  
Expected: module not found.

- [ ] **Step 3: backfill 구현**

```python
LAYOUT_BY_SECTION = {
    "comparison": "comparison_cards",
    "detail_1": "benefit_cards",
    "guarantee": "spec_table",
}


def backfill_page_visuals(db: Session, project_id: str) -> BackfillReport:
    page = db.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    updated = 0
    for section in page.sections:
        if section.visual_kind:
            continue
        if section.image_asset_id:
            section.visual_kind = "image"
            section.visual_payload = {"layout_variant": "hero_overlay" if section.section_type == "hero" else "image_text"}
        else:
            section.visual_kind = "html_graphic"
            section.visual_payload = build_grounded_html_payload(section, page.project)
        updated += 1
    db.commit()
    return BackfillReport(project_id=project_id, updated=updated)
```

`build_grounded_html_payload()`는 confirmed facts만 사용한다. 근거가 없으면 값 대신
`verification_status=needs_review`를 저장하고 판매용 문장으로 만들지 않는다.

- [ ] **Step 4: GREEN 확인**

Run: `uv run --project backend pytest backend/tests/test_visual_contract_backfill.py -v`  
Expected: all passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/services/visual_contract_backfill.py backend/tests/test_visual_contract_backfill.py
git commit -m "feat: backfill legacy page visual contracts"
```

### Task 2: 단일 readiness validator

**Files:**
- Create: `backend/src/services/page_readiness_service.py`
- Modify: `backend/src/api/pages.py`
- Modify: `backend/src/api/exports.py`
- Test: `backend/tests/test_page_readiness_service.py`

- [ ] **Step 1: blocker 테스트 작성**

```python
from types import SimpleNamespace
from src.services.visual_package_planner import VisualPackagePlanner


def _section(**overrides):
    values = {
        "id": "section-1",
        "visual_kind": "image",
        "visual_payload": {"layout_variant": "image_text"},
        "image_asset_id": "asset-1",
        "identity_status": "approved",
        "title": "제목",
        "body_copy": "본문",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_readiness_distinguishes_html_visual_from_missing_image():
    page = SimpleNamespace(
        sections=[
            _section(id="hero", image_asset_id="hero"),
            _section(
                id="comparison",
                visual_kind="html_graphic",
                visual_payload={
                    "layout_variant": "comparison_cards",
                    "cards": [{"title": "무선", "body": "이동"}],
                },
                image_asset_id=None,
            ),
        ],
    )
    assert inspect_page_readiness(page).blockers == []


def test_readiness_blocks_unreviewed_identity():
    page = SimpleNamespace(
        sections=[_section(image_asset_id="generated", identity_status="needs_review")]
    )
    assert inspect_page_readiness(page).blockers[0].code == "identity_review_required"
```

- [ ] **Step 2: RED 확인**

Run: `uv run --project backend pytest backend/tests/test_page_readiness_service.py -v`  
Expected: module not found.

- [ ] **Step 3: readiness response 구현**

```python
class ReadinessIssue(BaseModel):
    section_id: str
    code: str
    message: str


class PageReadiness(BaseModel):
    ready: bool
    blockers: list[ReadinessIssue]
    warnings: list[ReadinessIssue]
```

검사 항목:

- visual contract completeness
- asset 존재와 eligibility
- AI 상품 identity review
- grounding/compliance blockers
- 내부 edit marker
- 미확인 spec의 판매 문구 노출

`GET /projects/{id}/page/readiness`와 export POST가 같은 service를 호출한다.

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_page_readiness_service.py backend/tests/test_exports.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/services/page_readiness_service.py backend/src/api/pages.py backend/src/api/exports.py backend/tests/test_page_readiness_service.py
git commit -m "feat: unify page and export readiness"
```

### Task 3: Visual job 이중 상태 제거

**Files:**
- Modify: `backend/src/services/visual_package_planner.py`
- Modify: `backend/src/agents/nodes/visual_planning/agent.py`
- Test: `backend/tests/test_visual_package_planner.py`
- Test: `backend/tests/test_detail_page_scene_planner.py`

- [ ] **Step 1: 동일 섹션 전략 테스트 작성**

```python
from types import SimpleNamespace


def test_visual_package_reuses_scene_plan_strategy():
    project = SimpleNamespace(
        id="project-1",
        name="무선 선풍기",
        selected_background="cooling-blue",
        selected_style="problem_solution",
    )
    scene_plan = {
        "sections": [
            {
                "section_id": "pain_points",
                "target_slot_id": "comparison",
                "visual_strategy": "html_graphic",
                "visual_payload": {
                    "layout_variant": "comparison_cards",
                    "cards": [{"title": "무선", "body": "간편한 이동"}],
                },
            }
        ]
    }
    page = SimpleNamespace(
        sections=[
            SimpleNamespace(
                id="comparison",
                section_type="comparison",
                title="전원 제약 없이",
                body_copy="필요한 곳에서 사용",
                image_asset_id=None,
            )
        ]
    )
    jobs = VisualPackagePlanner().plan_visual_package(
        project=project,
        page=page,
        assets=[],
        scene_plan=scene_plan,
    )
    assert all(job.section_id != "comparison" for job in jobs)
```

- [ ] **Step 2: RED 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_visual_package_planner.py backend/tests/test_detail_page_scene_planner.py -v
```

Expected: comparison이 `needs_generation`으로 만들어져 FAIL.

- [ ] **Step 3: canonical scene plan 사용**

`VisualPackagePlanner.plan_visual_package()` signature에 다음 optional 인자를 추가한다.

```python
scene_plan: Optional[dict[str, Any]] = None
```

planner가 독자적으로 image role을 다시 추론하지 않고 `scene_plan`의
`visual_strategy`를 사용한다. `html_graphic`은 image job 목록에서 제외하고 page visual
contract의 readiness로 관리한다. 이미지 섹션만 `needs_generation|planned|completed`
상태를 갖는다.

- [ ] **Step 4: GREEN 확인**

Run:

```powershell
uv run --project backend pytest backend/tests/test_visual_package_planner.py backend/tests/test_detail_page_scene_planner.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```powershell
git add backend/src/services/visual_package_planner.py backend/src/agents/nodes/visual_planning/agent.py backend/tests/test_visual_package_planner.py backend/tests/test_detail_page_scene_planner.py
git commit -m "fix: unify visual planning status"
```

### Task 4: Production-like golden path

**Files:**
- Create: `frontend/e2e/upload-ready-golden-path.spec.ts`
- Modify: `docs/runbooks/2026-07-03-sellform-server-start-and-llm-mode-guide.md`

- [ ] **Step 1: Golden path E2E 작성**

시나리오:

1. 2개 image + 3개 HTML visual 결과 진입
2. 빈 placeholder가 없는지 확인
3. hero 선택
4. “제목을 더 강하게” preview
5. `[AI 수정됨]`이 없는 proposal 적용
6. result로 이동
7. readiness 완료 확인
8. PNG 다운로드
9. JPG 다운로드

핵심 assertions:

```ts
await expect(page.locator("[data-section-visual]")).toHaveCount(5);
await expect(page.getByText("이미지 누락")).toHaveCount(0);
await expect(page.getByText("[AI 수정됨]")).toHaveCount(0);
await expect(page.getByRole("button", { name: /PNG/ })).toBeEnabled();
await expect(page.getByRole("button", { name: /JPG/ })).toBeEnabled();
```

- [ ] **Step 2: E2E 실행**

Run:

```powershell
cd frontend
npx.cmd playwright test e2e/upload-ready-golden-path.spec.ts --project=chromium
```

Expected: passed.

- [ ] **Step 3: runbook 갱신**

runbook에 다음 검증 명령을 추가한다.

```powershell
curl.exe http://127.0.0.1:8001/api/v1/projects/<project-id>/page/readiness
```

frontend/backend port와 `NEXT_PUBLIC_API_BASE_URL`을 문서의 단일 표로 명시한다.

- [ ] **Step 4: Commit**

```powershell
git add frontend/e2e/upload-ready-golden-path.spec.ts docs/runbooks/2026-07-03-sellform-server-start-and-llm-mode-guide.md
git commit -m "test: cover upload ready detail page golden path"
```

### Task 5: 전체 릴리스 검증

```powershell
uv run --project backend pytest backend/tests/test_page_visual_contract.py backend/tests/test_visual_contract_backfill.py backend/tests/test_page_readiness_service.py backend/tests/test_copy_rewrite_service.py backend/tests/test_wysiwyg_export_contract.py -v
```

Expected: all passed.

```powershell
cd frontend
npm.cmd run lint
npm.cmd run build
npx.cmd playwright test e2e/upload-ready-detail-page.spec.ts e2e/completed-detail-page-export.spec.ts e2e/review-editor-reframe.spec.ts e2e/upload-ready-golden-path.spec.ts --project=chromium
```

Expected: lint error 0, build success, all selected E2E passed.
