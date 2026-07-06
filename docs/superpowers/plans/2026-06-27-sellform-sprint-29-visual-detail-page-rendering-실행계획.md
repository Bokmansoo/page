# Sprint 29 - 이미지 중심 상세페이지 렌더링 고도화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 글 중심으로 생성되는 Sellform 상세페이지 export를 쿠팡·네이버 스마트스토어에서 실제로 쓰기 좋은 “이미지 중심 세로형 상세페이지”로 고도화한다.

**Architecture:** 페이지 생성 단계에서는 검증된 사실 카드를 그대로 길게 노출하지 않고, 섹션별 판매 카피·이미지 슬롯·근거 요약으로 변환한 `visual section` 구조를 만든다. Export 단계는 이 구조를 받아 히어로 이미지, 제품/사용 장면 영역, 짧은 카피, 아이콘형 장점, 후면 스펙표로 렌더링한다. 실제 상품 이미지가 없으면 Sprint 28의 배경 후보와 안전한 플레이스홀더 비주얼을 사용한다.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, Pillow, Next.js, React, existing Sellform page generation/export services.

---

## 1. 배경과 문제 정의

현재 export 결과물은 기능적으로는 동작하지만, 실제 상세페이지라기보다 “검증된 사실 카드 내용을 세로 문서로 나열한 이미지”에 가깝다.

문제:

- 글이 너무 길어 첫 화면에서 구매 이유가 보이지 않는다.
- 상품 이미지·사용 장면·배경 비주얼이 거의 없어 상세페이지다운 설득력이 약하다.
- KC 인증, 모델명, 상품번호 같은 근거 정보가 본문에 길게 섞여 가독성을 떨어뜨린다.
- 섹션마다 시각적 역할 차이가 적어 “문제 제기 → 해결 → 장점 → 구매 정보” 흐름이 약하다.

Sprint 29의 목표는 “AI가 만든 문장”을 더 늘리는 것이 아니라, 검증된 정보를 바탕으로 실제 판매용 상세페이지처럼 보이게 만드는 것이다.

---

## 2. 범위

### 포함

- 상세페이지 export 전용 `visual section` 변환기 추가.
- 검증된 사실 카드를 짧은 판매 카피와 근거 요약으로 분리.
- 섹션별 이미지 슬롯 정의.
- 상품 이미지가 없을 때 사용할 안전한 플레이스홀더/배경 비주얼 렌더링.
- 긴 본문 자동 압축 규칙.
- 후면 상품 정보 표 렌더링.
- page-editor 미리보기와 export 결과의 시각 구조 개선.
- 테스트 로그, 리뷰 문서, 트러블슈팅 문서 산출.

### 제외

- 쿠팡/스마트스토어 자동 업로드.
- 실제 상품 사진을 AI가 임의로 생성해 실물처럼 보이게 하는 기능.
- 브랜드 로고, KC 마크, 인증마크 이미지의 자동 생성.
- 외부 상세페이지 디자인 복제.
- 인스타/숏폼 영상 분석. 이 부분은 Sprint 25~27 범위다.

---

## 3. 완성 기준

- export 결과 첫 화면에 히어로 영역이 보인다.
- 섹션 본문은 기본적으로 1~3문장으로 압축된다.
- 상품 정보·인증·모델명 같은 긴 근거 데이터는 마지막 `product_information` 표로 이동한다.
- 이미지가 없더라도 배경 비주얼/아이콘/플레이스홀더가 있어 흰 문서처럼 보이지 않는다.
- 생활/리빙 상품 기준으로 “문제 해결형 7단 구조”가 시각적으로 표현된다.
- backend 전체 테스트와 frontend build가 통과한다.
- 실제 루메나 손선풍기 프로젝트로 export한 결과가 기존보다 이미지 중심에 가까워진다.

---

## 4. 파일 구조

- Create: `backend/src/services/visual_page_renderer.py`
  - 기존 page sections를 export 친화적인 visual sections로 변환한다.
  - 카피 압축, 근거 요약, 이미지 슬롯, 섹션 레이아웃 타입을 결정한다.

- Modify: `backend/src/services/export_service.py`
  - 기존 텍스트 카드형 렌더링을 visual section 기반 렌더링으로 교체 또는 분기한다.
  - 히어로, 이미지+카피, 아이콘 장점, 스펙표 레이아웃을 Pillow로 그린다.

- Modify: `backend/src/services/page_generator.py`
  - mock/fallback 페이지의 본문 길이를 줄이고, 긴 근거 정보가 중간 섹션에 과도하게 들어가지 않도록 한다.

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`
  - 미리보기에서 이미지 슬롯과 시각 섹션 타입을 이해할 수 있게 표시한다.
  - “글 중심 미리보기”에서 “상세페이지 섹션 미리보기”로 UX를 개선한다.

- Create: `backend/tests/test_visual_page_renderer.py`
  - 긴 본문이 압축되는지, 근거 정보가 product_information으로 이동하는지 검증한다.

- Modify: `backend/tests/test_export_service.py`
  - export 결과가 히어로/이미지 슬롯/짧은 카피 구조를 갖는지 검증한다.

- Create: `docs/testing/2026-06-27-sellform-sprint-29-visual-detail-page-rendering-test-log.md`

- Create: `docs/reviews/2026-06-27-sellform-sprint-29-code-review.md`

- Create: `docs/troubleshooting/2026-06-27-sellform-sprint-29-visual-rendering.md`

---

## 5. 데이터 구조

새 변환기는 기존 section을 다음 형태로 바꾼다.

```python
{
    "key": "problem_statement",
    "layout": "hero",
    "eyebrow": "PROBLEM",
    "headline": "작은 불편이 쌓이면 일상이 번거로워집니다",
    "subcopy": "더운 출근길과 야외 대기 시간, 손 안의 시원함이 필요한 순간을 짚어줍니다.",
    "visual_slot": {
        "kind": "generated_background",
        "role": "cooling_lifestyle",
        "fallback_label": "시원한 바람을 표현한 블루 그라데이션"
    },
    "proofs": [
        "상품명: 루메나 휴대용 무선 냉각선풍기"
    ]
}
```

레이아웃 타입:

- `hero`: 첫 화면. 큰 배경/제품 이미지 + 핵심 카피.
- `image_text`: 이미지 영역과 짧은 설명.
- `benefit_cards`: 장점을 2~3개 카드로 요약.
- `proof_block`: 근거 요약.
- `spec_table`: 상품 정보, 모델명, 인증, 주의사항 표.

---

## 6. Task 1: Visual section 변환기 추가

**Files:**

- Create: `backend/src/services/visual_page_renderer.py`
- Create: `backend/tests/test_visual_page_renderer.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_visual_page_renderer.py`

```python
from src.services.visual_page_renderer import build_visual_sections


def test_build_visual_sections_compresses_long_fact_dump_into_short_copy():
    sections = [
        {
            "key": "main_claim",
            "title": "일상의 불편을 덜어주는 실용적인 선택",
            "body": (
                "사용 환경에서 확인할 정보를 확인된 상품 사실로 정리합니다. "
                "KC 인증정보(전지)는 XU100557-25045이고 KC 인증정보(본품)는 R-R-ONH-FANJETULTRA입니다. "
                "품명/모델명 표기는 루메나 휴대용 무선 냉각선풍기 / FAN JET ULTRA이고 "
                "쿠팡 상품번호는 8717208468입니다. "
                "제조자는 Dongguan Aohai Technology Co.,Ltd. 입니다."
            ),
            "associated_fact_ids": ["fact-1", "fact-2"],
        }
    ]

    result = build_visual_sections(
        product_name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
        sections=sections,
        selected_background="cooling-blue",
        image_assets=[],
    )

    assert result[0]["layout"] in {"hero", "image_text", "benefit_cards", "proof_block", "spec_table"}
    assert len(result[0]["subcopy"]) <= 120
    assert "쿠팡 상품번호" not in result[0]["subcopy"]
    assert result[0]["visual_slot"]["kind"] in {"generated_background", "product_image", "placeholder"}
```

```python
def test_product_information_keeps_purchase_facts_as_spec_table():
    sections = [
        {
            "key": "product_information",
            "title": "상품 정보",
            "body": "모델명은 FAN JET ULTRA입니다. KC 인증정보는 R-R-ONH-FANJETULTRA입니다.",
            "associated_fact_ids": ["fact-1"],
        }
    ]

    result = build_visual_sections(
        product_name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
        sections=sections,
        selected_background="cooling-blue",
        image_assets=[],
    )

    assert result[0]["layout"] == "spec_table"
    assert result[0]["headline"] == "구매 전 확인 정보"
    assert any("FAN JET ULTRA" in row["value"] for row in result[0]["spec_rows"])
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_page_renderer.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.services.visual_page_renderer'
```

- [ ] **Step 3: 최소 구현**

`backend/src/services/visual_page_renderer.py`

```python
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


LONG_PROOF_PATTERNS = [
    "KC 인증",
    "상품번호",
    "모델명",
    "제조",
    "수입",
    "품명",
    "인증정보",
]


@dataclass(frozen=True)
class VisualSlot:
    kind: str
    role: str
    fallback_label: str


def _sentence_split(text: str) -> list[str]:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다\.)\s+", normalized)
    return [part.strip() for part in parts if part.strip()]


def _compress_copy(text: str, max_chars: int = 110) -> str:
    sentences = [
        sentence
        for sentence in _sentence_split(text)
        if not any(pattern in sentence for pattern in LONG_PROOF_PATTERNS)
    ]
    if not sentences:
        sentences = _sentence_split(text)
    copy = " ".join(sentences[:2]).strip()
    if len(copy) <= max_chars:
        return copy
    return copy[: max_chars - 1].rstrip() + "…"


def _extract_spec_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    patterns = [
        ("모델명", r"(?:모델명|품명/모델명)[^A-Za-z0-9가-힣]*(?P<value>[A-Za-z0-9가-힣 /\\-]+)"),
        ("KC 인증", r"(?:KC 인증정보|KC 인증)[^A-Za-z0-9가-힣]*(?P<value>[A-Z0-9\\-]+)"),
        ("상품번호", r"(?:상품번호)[^0-9]*(?P<value>[0-9]+)"),
    ]
    for label, pattern in patterns:
        match = re.search(pattern, text)
        if match:
            rows.append({"label": label, "value": match.group("value").strip()})
    if not rows and text:
        rows.append({"label": "확인 정보", "value": _compress_copy(text, 160)})
    return rows


def _layout_for_key(key: str, index: int) -> str:
    normalized = (key or "").lower()
    if index == 0 or normalized in {"header", "problem_statement"}:
        return "hero"
    if normalized == "benefit_list":
        return "benefit_cards"
    if normalized == "product_information":
        return "spec_table"
    if normalized in {"main_claim_support", "summary_claim"}:
        return "proof_block"
    return "image_text"


def _visual_slot_for(layout: str, selected_background: str | None, image_assets: list[dict[str, Any]]) -> dict[str, str]:
    if image_assets:
        return {
            "kind": "product_image",
            "role": layout,
            "fallback_label": "업로드된 상품 이미지",
        }
    if selected_background:
        return {
            "kind": "generated_background",
            "role": selected_background,
            "fallback_label": "선택한 배경 비주얼",
        }
    return {
        "kind": "placeholder",
        "role": layout,
        "fallback_label": "상품 이미지가 없을 때 사용하는 안전한 비주얼 영역",
    }


def build_visual_sections(
    product_name: str,
    category: str,
    sections: list[dict[str, Any]],
    selected_background: str | None = None,
    image_assets: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    image_assets = image_assets or []
    visual_sections: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        key = section.get("key") or section.get("section_type") or f"section_{index + 1}"
        body = section.get("body") or section.get("body_copy") or ""
        layout = _layout_for_key(key, index)

        visual_section = {
            "key": key,
            "layout": layout,
            "eyebrow": str(key).upper(),
            "headline": section.get("title") or product_name,
            "subcopy": _compress_copy(body),
            "visual_slot": _visual_slot_for(layout, selected_background, image_assets),
            "proofs": section.get("associated_fact_ids", []),
        }

        if layout == "spec_table":
            visual_section["headline"] = "구매 전 확인 정보"
            visual_section["subcopy"] = "구매 전 확인해야 할 핵심 정보를 정리했습니다."
            visual_section["spec_rows"] = _extract_spec_rows(body)

        visual_sections.append(visual_section)

    return visual_sections
```

- [ ] **Step 4: 통과 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_page_renderer.py -q
```

Expected:

```text
2 passed
```

---

## 7. Task 2: 페이지 생성 fallback 카피 길이 제한

**Files:**

- Modify: `backend/src/services/page_generator.py`
- Modify: `backend/tests/test_pages.py` 또는 Create: `backend/tests/test_page_generator_visual_copy.py`

- [ ] **Step 1: 긴 fact dump 방지 테스트 작성**

`backend/tests/test_page_generator_visual_copy.py`

```python
from src.services.page_generator import PageGenerationService


def test_problem_solution_mock_page_keeps_sales_copy_short():
    service = PageGenerationService(api_key=None)
    facts = [
        {
            "id": "fact-1",
            "fact_text": (
                "상품명은 루메나 휴대용 무선 냉각선풍기입니다. "
                "모델명은 FAN JET ULTRA입니다. "
                "KC 인증정보는 R-R-ONH-FANJETULTRA입니다. "
                "쿠팡 상품번호는 8717208468입니다."
            ),
            "source_text": "상품 상세 스니펫",
        }
    ]

    page = service.generate_page(
        category="Living",
        confirmed_facts=facts,
        style_preset="problem_solution",
        narrative_template="problem_solution",
    )

    non_product_info_sections = [
        section for section in page.sections if section.section_type != "product_information"
    ]
    assert all(len(section.body_copy) <= 180 for section in non_product_info_sections)
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_page_generator_visual_copy.py -q
```

Expected:

```text
AssertionError
```

- [ ] **Step 3: fallback 카피 압축 적용**

`backend/src/services/page_generator.py`

`_get_problem_solution_mock_page` 내부에서 `fact_summary`를 그대로 모든 섹션에 붙이지 않고 아래 helper를 사용한다.

```python
def _short_fact_summary(facts: list[dict], max_chars: int = 120) -> str:
    text = " ".join([fact.get("fact_text", "") for fact in facts])
    blocked_keywords = ["KC 인증", "상품번호", "제조", "수입", "인증정보"]
    sentences = [sentence.strip() for sentence in text.split(".") if sentence.strip()]
    sales_sentences = [
        sentence for sentence in sentences if not any(keyword in sentence for keyword in blocked_keywords)
    ]
    summary = ". ".join(sales_sentences[:2] or sentences[:1]).strip()
    if summary and not summary.endswith("."):
        summary += "."
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1].rstrip() + "…"
    return summary
```

그리고 중간 섹션에는 `short_fact_summary`만 사용한다. `product_information` 섹션에만 전체 구매 확인 정보를 넣는다.

- [ ] **Step 4: 통과 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_page_generator_visual_copy.py -q
```

Expected:

```text
1 passed
```

---

## 8. Task 3: Export 렌더러를 이미지 중심 구조로 변경

**Files:**

- Modify: `backend/src/services/export_service.py`
- Modify: `backend/tests/test_export_service.py`
- Create: `backend/tests/test_export_visual_layout.py`

- [ ] **Step 1: export visual layout 테스트 작성**

`backend/tests/test_export_visual_layout.py`

```python
from PIL import Image
from src.services.export_service import run_export


def test_run_export_creates_visual_detail_page_not_text_document():
    snapshot = {
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "visual_background": {"selected_background": "cooling-blue"},
        "sections": [
            {
                "key": "problem_statement",
                "title": "작은 불편이 쌓이면 일상이 번거로워집니다",
                "body": "더운 출근길과 야외 대기 시간, 손 안의 시원함이 필요한 순간을 짚어줍니다.",
            },
            {
                "key": "main_claim",
                "title": "일상의 불편을 덜어주는 실용적인 선택",
                "body": "휴대용 무선 팬으로 필요한 순간 간편하게 사용할 수 있습니다.",
            },
            {
                "key": "product_information",
                "title": "상품 정보",
                "body": "모델명은 FAN JET ULTRA입니다. KC 인증정보는 R-R-ONH-FANJETULTRA입니다.",
            },
        ],
    }

    result = run_export("project-visual-layout", "version-visual-layout", snapshot)

    with Image.open(result["long_vertical_image"]) as image:
        assert image.width >= 860
        assert image.height >= 1200
        top_pixel = image.getpixel((20, 20))
        assert top_pixel != (255, 255, 255)
```

- [ ] **Step 2: 실패 또는 현재 품질 부족 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_visual_layout.py -q
```

Expected:

```text
FAIL
```

현재 export가 텍스트 카드 중심이므로 top 영역이 히어로 비주얼로 충분히 보장되지 않는다.

- [ ] **Step 3: export_service에 visual section 변환 연결**

`backend/src/services/export_service.py`

`run_export`에서 `sections = normalize_sections_snapshot(sections)` 직후 원본 snapshot 정보를 보존한다.

```python
original_snapshot = sections
if isinstance(sections, dict):
    original_snapshot = sections
    sections = normalize_sections_snapshot(sections)
```

그리고 프로젝트/스냅샷에서 selected background를 읽은 뒤 다음을 호출한다.

```python
from src.services.visual_page_renderer import build_visual_sections

visual_sections = build_visual_sections(
    product_name=getattr(project, "title", "상품") if db is not None and project else "상품",
    category=getattr(project, "category", "Living") if db is not None and project else "Living",
    sections=sections,
    selected_background=selected_bg,
    image_assets=[],
)
```

이후 기존 section 반복 렌더링 대신 `visual_sections`를 렌더링한다.

- [ ] **Step 4: 히어로 레이아웃 그리기 함수 추가**

`backend/src/services/export_service.py`

```python
def _draw_hero_section(draw, section, width, height, palette, title_font, body_font, label_font):
    accent = (37, 99, 235)
    text = (15, 23, 42)
    muted = (71, 85, 105)
    draw.rounded_rectangle([(48, 48), (width - 48, height - 48)], radius=36, fill=(255, 255, 255))
    draw.text((76, 82), section["eyebrow"], fill=muted, font=label_font)
    draw.text((76, 132), section["headline"], fill=accent, font=title_font)
    y = 196
    for line in _wrap_text(section["subcopy"], body_font, width - 152):
        draw.text((76, y), line, fill=text, font=body_font)
        y += 38
    draw.ellipse([(width - 260, height - 260), (width - 80, height - 80)], fill=palette[1])
    draw.arc([(width - 230, height - 230), (width - 110, height - 110)], start=20, end=320, fill=accent, width=10)
```

- [ ] **Step 5: 이미지+카피 레이아웃 그리기 함수 추가**

`backend/src/services/export_service.py`

```python
def _draw_image_text_section(draw, section, width, height, palette, title_font, body_font, label_font):
    accent = (37, 99, 235)
    text = (15, 23, 42)
    muted = (71, 85, 105)
    draw.rounded_rectangle([(44, 30), (width - 44, height - 30)], radius=24, fill=(255, 255, 255))
    draw.rounded_rectangle([(72, 64), (width - 72, 250)], radius=20, fill=palette[1])
    draw.text((92, 92), section["visual_slot"]["fallback_label"], fill=muted, font=body_font)
    draw.text((72, 292), section["headline"], fill=accent, font=title_font)
    y = 350
    for line in _wrap_text(section["subcopy"], body_font, width - 144):
        draw.text((72, y), line, fill=text, font=body_font)
        y += 38
```

- [ ] **Step 6: 스펙표 레이아웃 그리기 함수 추가**

`backend/src/services/export_service.py`

```python
def _draw_spec_table_section(draw, section, width, height, title_font, body_font, label_font):
    text = (15, 23, 42)
    muted = (71, 85, 105)
    border = (226, 232, 240)
    draw.rounded_rectangle([(44, 30), (width - 44, height - 30)], radius=24, fill=(255, 255, 255))
    draw.text((72, 72), "구매 전 확인 정보", fill=text, font=title_font)
    y = 140
    for row in section.get("spec_rows", []):
        draw.line([(72, y), (width - 72, y)], fill=border, width=1)
        draw.text((72, y + 24), row["label"], fill=muted, font=label_font)
        draw.text((240, y + 24), row["value"], fill=text, font=body_font)
        y += 76
```

- [ ] **Step 7: 통과 확인**

Run:

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_export_visual_layout.py backend\tests\test_export_visual_background.py backend\tests\test_export_service.py -q
```

Expected:

```text
all passed
```

---

## 9. Task 4: Page editor 미리보기의 시각 구조 개선

**Files:**

- Modify: `frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

- [ ] **Step 1: 현재 미리보기 구조 확인**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

- [ ] **Step 2: 미리보기 섹션에 이미지 슬롯 표시 추가**

`frontend/src/app/workspace/projects/[id]/page-editor/page.tsx`

선택된 섹션 미리보기 카드에 다음 정보가 보이게 한다.

```tsx
<div className="rounded-2xl bg-gradient-to-br from-blue-50 to-white p-5">
  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-400">
    Visual Slot
  </p>
  <p className="mt-2 text-sm text-slate-600">
    상품 이미지가 없으면 선택한 배경 비주얼과 안전한 플레이스홀더를 사용합니다.
  </p>
</div>
```

- [ ] **Step 3: 섹션 본문 길이 경고 추가**

본문 카피가 180자를 넘으면 아래 안내를 표시한다.

```tsx
{selectedSection.body.length > 180 ? (
  <p className="mt-2 text-xs text-amber-300">
    상세페이지 본문이 길어 가독성이 떨어질 수 있습니다. AI 부분 수정으로 1~3문장으로 줄여주세요.
  </p>
) : null}
```

- [ ] **Step 4: 프론트 빌드 확인**

Run:

```powershell
cd frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

---

## 10. Task 5: 문서와 리뷰 산출물 작성

**Files:**

- Create: `docs/testing/2026-06-27-sellform-sprint-29-visual-detail-page-rendering-test-log.md`
- Create: `docs/reviews/2026-06-27-sellform-sprint-29-code-review.md`
- Create: `docs/troubleshooting/2026-06-27-sellform-sprint-29-visual-rendering.md`

- [ ] **Step 1: 테스트 로그 작성**

`docs/testing/2026-06-27-sellform-sprint-29-visual-detail-page-rendering-test-log.md`

````markdown
# Sprint 29 이미지 중심 상세페이지 렌더링 테스트 로그

## 검증 범위

- visual section 변환
- 긴 카피 압축
- 상품 정보 표 분리
- export 히어로/이미지 슬롯 렌더링
- page-editor 미리보기 빌드

## 실행 명령

```powershell
backend\.venv\Scripts\python.exe -B -m pytest backend\tests\test_visual_page_renderer.py backend\tests\test_export_visual_layout.py -q
cd frontend
npm.cmd run build
```

## 결과

- Backend:
- Frontend:

## 수동 QA

- [ ] 루메나 손선풍기 프로젝트로 export 결과 확인
- [ ] 첫 화면이 히어로 이미지/배경 중심으로 보이는지 확인
- [ ] 긴 KC/모델명 정보가 중간 카피에 과도하게 노출되지 않는지 확인
- [ ] 마지막 상품 정보 섹션에서 구매 전 확인 정보가 보이는지 확인
````

- [ ] **Step 2: 코드리뷰 문서 작성**

`docs/reviews/2026-06-27-sellform-sprint-29-code-review.md`

```markdown
# 코드 리뷰: Sellform Sprint 29 이미지 중심 상세페이지 렌더링 고도화

| 항목 | 내용 |
| --- | --- |
| 리뷰 일자 | 2026-06-27 |
| 리뷰 범위 | visual section 변환기, export 렌더링, page-editor 미리보기, 테스트 |
| 리뷰어 | Codex |

## 1. 변경 요약

- 글 중심 export를 이미지 중심 상세페이지 구조로 개선.
- 긴 fact dump를 짧은 판매 카피와 상품 정보 표로 분리.
- 히어로/이미지+카피/스펙표 레이아웃 추가.
- 이미지가 없을 때 배경 비주얼/플레이스홀더를 사용하는 구조 추가.

## 2. 확인 결과

- Backend 테스트:
- Frontend build:

## 3. 발견 이슈

### 이슈 없음

또는 발견된 이슈를 이곳에 기록한다.

## 4. 남은 위험

- 실제 상품 이미지가 없으면 여전히 플레이스홀더 품질에 한계가 있다.
- AI 이미지 생성 API 연동은 Sprint 28 후속 또는 별도 스프린트에서 다룬다.
```

- [ ] **Step 3: 트러블슈팅 문서 작성**

`docs/troubleshooting/2026-06-27-sellform-sprint-29-visual-rendering.md`

```markdown
# Sprint 29 이미지 중심 렌더링 트러블슈팅

## 문제: export가 다시 글 중심으로 보인다

### 확인

- `visual_page_renderer.build_visual_sections`가 호출되는지 확인한다.
- snapshot이 dict일 때 sections 추출 후 visual 변환이 유지되는지 확인한다.

### 해결

- `run_export`에서 `visual_sections`를 기준으로 렌더링한다.

## 문제: 상품 정보가 중간 카피에 길게 섞인다

### 확인

- `LONG_PROOF_PATTERNS`에 `KC 인증`, `상품번호`, `모델명`, `제조`가 포함되어 있는지 확인한다.

### 해결

- 중간 섹션은 `_compress_copy`를 사용하고 `product_information`은 `spec_table`로 렌더링한다.
```

---

## 11. 전체 검증 명령

Sprint 29 구현 후 다음을 실행한다.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
backend\.venv\Scripts\python.exe -B -m pytest backend\tests -q
```

Expected:

```text
all backend tests passed
```

```powershell
cd frontend
npm.cmd run build
```

Expected:

```text
Compiled successfully
```

---

## 12. 수동 QA 시나리오

1. `http://localhost:3000/workspace` 접속.
2. `+ 새 상품 프로젝트` 클릭.
3. 상품명: `루메나 휴대용 무선 냉각선풍기`.
4. 상품 링크 입력.
5. `AI로 사실 카드 자동 생성` 클릭.
6. 3개 이상 사실 카드 `확인됨` 처리.
7. `검증 완료 및 다음 단계` 클릭.
8. 스타일 후보 선택.
9. page-editor에서 상세페이지 미리보기 확인.
10. 배경 후보 선택.
11. 저장/내보내기.
12. export PNG 확인.

확인 포인트:

- 첫 화면이 큰 이미지/배경 중심인지.
- 글이 섹션마다 1~3문장 수준인지.
- KC 인증/모델명/상품번호가 마지막 상품 정보 쪽으로 정리되는지.
- 흰 종이 위에 텍스트만 나열된 결과로 보이지 않는지.

---

## 13. Self Review

- Spec coverage:
  - 이미지 중심 상세페이지 렌더링: Task 3.
  - 긴 글 압축: Task 1, Task 2.
  - 근거와 판매 카피 분리: Task 1, Task 2.
  - 상품 정보 후면 배치: Task 1, Task 3.
  - page-editor 미리보기 개선: Task 4.
  - 문서/리뷰/테스트 산출물: Task 5.

- Placeholder scan:
  - 구현자가 바로 따라갈 수 있도록 파일 경로, 테스트 코드, 실행 명령, 기대 결과를 포함했다.

- Type consistency:
  - `visual_sections`는 `layout`, `headline`, `subcopy`, `visual_slot`, `spec_rows`를 사용한다.
  - export renderer는 동일 필드를 기준으로 렌더링한다.
