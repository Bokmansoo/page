# Sprint 28 - AI 배경 비주얼 생성 실행계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 상품명·카테고리·확인된 사실 카드 기반으로 상세페이지에 어울리는 배경/히어로 비주얼 후보를 생성하고, 사용자가 선택한 배경을 상세페이지 편집·export에 반영한다.

**Architecture:** Sellform 본체는 상세페이지 구조와 검증된 문구를 유지하고, 배경 비주얼은 독립된 `visual asset` 후보로 생성·저장한다. 첫 버전은 이미지 생성 API가 없어도 동작하도록 카테고리별 안전한 그래디언트/패턴 fallback을 제공하고, 이미지 생성 API가 설정된 경우에만 AI 배경 후보를 만든다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Pillow, Next.js, OpenAI/Google LLM Router, 선택적 이미지 생성 Provider.

---

## 범위

- 사용자는 page-editor에서 “AI 배경 후보 만들기”를 누를 수 있다.
- AI는 상품명, 카테고리, 판매 전략, 확인된 사실 카드를 기반으로 2~3개의 배경 콘셉트를 제안한다.
- 배경 후보는 실제 상품 정보와 충돌하지 않는 추상적·라이프스타일형 배경을 기본으로 한다.
- 상표·로고·인증마크·브랜드 제품 실물 이미지는 사용자가 제공한 이미지가 없으면 생성하지 않는다.
- 선택된 배경은 상세페이지 미리보기와 export 이미지에 반영된다.
- 이미지 생성 API가 없거나 실패하면 카테고리별 fallback 배경을 사용한다.

## 제외 범위

- 쿠팡/스마트스토어 자동 업로드.
- 타사 브랜드 로고 자동 생성.
- 공급처 이미지의 권리 검증 자동화.
- 실제 제품 사진을 AI로 임의 생성해 사실처럼 보이게 하는 기능.

## 파일 구조

- Create: `backend/src/services/visual_background_service.py`
  - 배경 후보 프롬프트 생성, fallback 배경 생성, 후보 메타데이터 정리.
- Modify: `backend/src/db/models.py`
  - `GeneratedVisualAsset` 또는 기존 asset 모델 확장.
- Create: `backend/src/api/visual_assets.py`
  - `POST /api/v1/projects/{project_id}/visual-backgrounds/generate`
  - `POST /api/v1/projects/{project_id}/visual-backgrounds/{asset_id}/select`
- Modify: `backend/src/api/__init__.py` 또는 router 등록 파일
  - visual assets router 등록.
- Modify: `backend/src/services/export_service.py`
  - 선택된 배경 이미지를 export에 반영.
- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - 배경 후보 생성/선택 UI 추가.
- Create: `backend/tests/test_visual_background_service.py`
  - fallback 후보, 안전 프롬프트, 선택 상태 검증.
- Create: `backend/tests/test_visual_assets_api.py`
  - API 생성/선택 플로우 검증.
- Create: `docs/testing/2026-06-26-sellform-sprint-28-ai-background-test-log.md`
- Create: `docs/reviews/2026-06-26-sellform-sprint-28-code-review.md`
- Create: `docs/troubleshooting/2026-06-26-sellform-sprint-28-ai-background.md`

## Task 1: 배경 후보 도메인 모델과 fallback 생성기

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_visual_background_service.py`

```python
from src.services.visual_background_service import build_background_candidates


def test_build_background_candidates_returns_safe_living_fallbacks():
    candidates = build_background_candidates(
        product_name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
        strategy_key="problem_solution",
        facts=[
            "상품명은 루메나 휴대용 무선 냉각선풍기이다.",
            "모델명은 FAN JET ULTRA이다.",
        ],
        image_provider_enabled=False,
    )

    assert len(candidates) >= 2
    assert all(candidate["kind"] == "fallback" for candidate in candidates)
    assert all("logo" not in candidate["prompt"].lower() for candidate in candidates)
    assert any("시원" in candidate["description"] or "쿨링" in candidate["description"] for candidate in candidates)
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_background_service.py -q
```

Expected: `ModuleNotFoundError: No module named 'src.services.visual_background_service'`

- [ ] **Step 3: 최소 구현**

`backend/src/services/visual_background_service.py`

```python
from __future__ import annotations


def build_background_candidates(
    product_name: str,
    category: str,
    strategy_key: str,
    facts: list[str],
    image_provider_enabled: bool = False,
) -> list[dict]:
    base_prompt = (
        f"Create a clean ecommerce detail page background for {product_name}. "
        f"Category: {category}. Strategy: {strategy_key}. "
        "No logos, no certification marks, no fake product render, no text."
    )
    return [
        {
            "kind": "fallback",
            "title": "쿨링 라이프스타일 배경",
            "description": "시원한 공기감과 생활/리빙 제품 분위기를 강조하는 배경입니다.",
            "prompt": base_prompt + " Soft cool blue gradient, airy tabletop lifestyle mood.",
            "palette": ["#EAF4FF", "#DDEBFF", "#FFFFFF"],
        },
        {
            "kind": "fallback",
            "title": "미니멀 제품 강조 배경",
            "description": "제품 정보와 핵심 장점을 읽기 쉽게 받쳐주는 미니멀 배경입니다.",
            "prompt": base_prompt + " Minimal white and pale gray surface, clean ecommerce layout.",
            "palette": ["#FFFFFF", "#F1F5F9", "#E0EAFF"],
        },
    ]
```

- [ ] **Step 4: 통과 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_background_service.py -q
```

Expected: `1 passed`

## Task 2: API와 저장 구조 연결

- [ ] **Step 1: API 실패 테스트 작성**

`backend/tests/test_visual_assets_api.py`

```python
from fastapi.testclient import TestClient
from src.main import app


def test_generate_visual_background_candidates_returns_candidates():
    client = TestClient(app)
    response = client.post(
        "/api/v1/projects/project-1/visual-backgrounds/generate",
        json={
            "product_name": "루메나 휴대용 무선 냉각선풍기",
            "category": "Living",
            "strategy_key": "problem_solution",
            "facts": ["모델명은 FAN JET ULTRA이다."],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) >= 2
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_assets_api.py -q
```

Expected: `404 Not Found`

- [ ] **Step 3: API 최소 구현**

`backend/src/api/visual_assets.py`

```python
from pydantic import BaseModel
from fastapi import APIRouter
from src.services.visual_background_service import build_background_candidates

router = APIRouter(prefix="/api/v1/projects/{project_id}/visual-backgrounds", tags=["visual-backgrounds"])


class VisualBackgroundGenerateRequest(BaseModel):
    product_name: str
    category: str = "Living"
    strategy_key: str = "problem_solution"
    facts: list[str] = []


@router.post("/generate")
def generate_visual_background_candidates(project_id: str, request: VisualBackgroundGenerateRequest):
    return {
        "project_id": project_id,
        "candidates": build_background_candidates(
            product_name=request.product_name,
            category=request.category,
            strategy_key=request.strategy_key,
            facts=request.facts,
            image_provider_enabled=False,
        ),
    }
```

Router 등록 파일에 `visual_assets.router`를 추가한다.

- [ ] **Step 4: 통과 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_assets_api.py -q
```

Expected: `1 passed`

## Task 3: page-editor UI 후보 생성/선택

- [ ] **Step 1: 프론트 동작 테스트 또는 수동 QA 항목 작성**

`docs/testing/2026-06-26-sellform-sprint-28-ai-background-test-log.md`

```markdown
# Sprint 28 AI 배경 비주얼 테스트 로그

## 수동 QA

- [ ] page-editor에서 “AI 배경 후보 만들기” 버튼이 보인다.
- [ ] 버튼 클릭 시 2개 이상의 후보가 표시된다.
- [ ] 후보를 선택하면 미리보기 배경이 바뀐다.
- [ ] 이미지 API가 없어도 fallback 후보가 표시된다.
- [ ] export 시 선택한 배경이 반영된다.
```

- [ ] **Step 2: UI 구현**

`frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

- 우측 디자인 톤 패널 아래에 “AI 배경 후보 만들기” 버튼을 추가한다.
- 후보 카드에는 제목, 설명, 팔레트, “선택” 버튼을 표시한다.
- 선택된 후보는 preview 컨테이너의 배경 스타일에 반영한다.

- [ ] **Step 3: 프론트 빌드 확인**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected: build success.

## Task 4: export 반영

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_export_service.py`

```python
def test_run_export_uses_visual_background_palette_when_provided():
    snapshot = {
        "visual_background": {"palette": ["#EAF4FF", "#DDEBFF", "#FFFFFF"]},
        "sections": [{"key": "header", "title": "시원한 일상", "body": "루메나 선풍기 상세페이지"}],
    }

    result = run_export("project-bg", "version-bg", snapshot)

    from PIL import Image
    with Image.open(result["long_vertical_image"]) as image:
        assert image.width >= 720
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_service.py::test_run_export_uses_visual_background_palette_when_provided -q
```

Expected: fails until `visual_background` is handled.

- [ ] **Step 3: export_service 반영**

`backend/src/services/export_service.py`

- `sections_snapshot`이 dict일 때 `visual_background.palette`를 읽는다.
- export 배경색과 섹션 상단 장식에 palette를 반영한다.

- [ ] **Step 4: 통과 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_service.py -q
```

Expected: all pass.

## 완료 기준

- page-editor에서 상품에 맞는 배경 후보를 2개 이상 볼 수 있다.
- 이미지 생성 API가 없어도 fallback 배경 후보가 동작한다.
- 선택한 배경이 미리보기와 export에 반영된다.
- 타사 로고·인증마크·실물 제품을 AI가 임의 생성하지 않는다.
- backend 테스트와 frontend build가 통과한다.
- 테스트 로그, 코드리뷰 문서, 트러블슈팅 문서가 생성된다.

