"""Sprint 37 - style token이 Figma visual layout과 PNG export에 동일하게 반영되는지 검증."""
from unittest.mock import MagicMock

from src.services.figma_visual_layout_builder import build_figma_visual_layout
from src.services.visual_page_renderer import build_visual_sections


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(selected_style: str | None = None, category: str = "Living"):
    project = MagicMock()
    project.selected_style = selected_style
    project.selected_background = None
    project.category = category
    project.name = "테스트 상품"
    return project


def _make_page(sections: list[dict]):
    """Minimal page-like object accepted by figma_visual_layout_builder."""
    page = MagicMock()
    page.project_id = "proj-1"
    page.theme_color = "#3B82F6"
    page.font_family = "sans-serif"
    # PageSection-like objects
    sec_objects = []
    for idx, s in enumerate(sections):
        sec = MagicMock()
        sec.section_type = s.get("section_type", s.get("key", f"section_{idx}"))
        sec.title = s.get("title", "제목")
        sec.body_copy = s.get("body_copy", s.get("body", "본문"))
        sec.associated_fact_ids = s.get("associated_fact_ids", [])
        sec.image_asset_id = s.get("image_asset_id", None)
        sec.sort_order = idx
        sec.is_visible = True
        sec_objects.append(sec)
    page.sections = sec_objects
    return page


SAMPLE_SECTIONS = [
    {"key": "problem_statement", "section_type": "problem_statement", "title": "고객의 고민", "body_copy": "무더운 여름 선풍기가 없어 불편합니다."},
    {"key": "main_claim", "section_type": "main_claim", "title": "핵심 해결 메시지", "body_copy": "루메나 무선 냉각 선풍기로 더위를 날리세요."},
    {"key": "secondary_benefit", "section_type": "secondary_benefit", "title": "추가 장점", "body_copy": "18시간 연속 사용이 가능합니다."},
    {"key": "main_claim_support", "section_type": "main_claim_support", "title": "근거", "body_copy": "4800mAh 대용량 배터리."},
    {"key": "benefit_list", "section_type": "benefit_list", "title": "장점 목록", "body_copy": "휴대성 우수, 소음 최소화."},
    {"key": "summary_claim", "section_type": "summary_claim", "title": "요약", "body_copy": "당신의 여름을 시원하게."},
    {"key": "product_information", "section_type": "product_information", "title": "상품 정보", "body_copy": "모델명: LM-FAN100"},
]


# ---------------------------------------------------------------------------
# Tests: build_figma_visual_layout style_key propagation
# ---------------------------------------------------------------------------

def test_figma_layout_reflects_selected_style_key_lifestyle():
    project = _make_project(selected_style="lifestyle")
    page = _make_page(SAMPLE_SECTIONS)
    result = build_figma_visual_layout(project=project, page=page, assets=[])

    assert result["style_key"] == "lifestyle"


def test_figma_layout_reflects_selected_style_key_spec_focused():
    project = _make_project(selected_style="spec_focused")
    page = _make_page(SAMPLE_SECTIONS)
    result = build_figma_visual_layout(project=project, page=page, assets=[])

    assert result["style_key"] == "spec_focused"


def test_figma_layout_reflects_selected_style_key_problem_solution():
    project = _make_project(selected_style="problem_solution")
    page = _make_page(SAMPLE_SECTIONS)
    result = build_figma_visual_layout(project=project, page=page, assets=[])

    assert result["style_key"] == "problem_solution"


def test_figma_layout_style_key_defaults_to_default_when_none():
    project = _make_project(selected_style=None)
    page = _make_page(SAMPLE_SECTIONS)
    result = build_figma_visual_layout(project=project, page=page, assets=[])

    assert result["style_key"] == "default"


# ---------------------------------------------------------------------------
# Tests: figma style token affects background_tone on cuts
# ---------------------------------------------------------------------------

def test_figma_lifestyle_style_applies_warm_tone_to_first_cut():
    """lifestyle 스타일 선택 시 첫 컷(problem_statement) background_tone이 warm_neutral이어야 한다."""
    project = _make_project(selected_style="lifestyle")
    page = _make_page(SAMPLE_SECTIONS)
    result = build_figma_visual_layout(project=project, page=page, assets=[])

    first_cut = result["cuts"][0]
    # STYLE_BACKGROUND_OVERRIDE["lifestyle"]["problem_statement"] → "warm_neutral"
    assert first_cut["background_tone"] == "warm_neutral"


def test_figma_spec_focused_style_applies_cool_tone_to_first_cut():
    """spec_focused 스타일 선택 시 첫 컷(problem_statement)이 default cool_blue 배경이어야 한다."""
    project = _make_project(selected_style="spec_focused")
    page = _make_page(SAMPLE_SECTIONS)
    result = build_figma_visual_layout(project=project, page=page, assets=[])

    first_cut = result["cuts"][0]
    # STYLE_BACKGROUND_OVERRIDE["spec_focused"] has no problem_statement override → default "cool_blue"
    assert first_cut["background_tone"] == "cool_blue"


# ---------------------------------------------------------------------------
# Tests: build_visual_sections style token propagation
# ---------------------------------------------------------------------------

def test_png_visual_sections_include_style_token_for_lifestyle():
    sections_raw = [s.copy() for s in SAMPLE_SECTIONS]
    result = build_visual_sections(
        product_name="루메나 선풍기",
        category="Living",
        sections=sections_raw,
        selected_style="lifestyle",
    )
    assert len(result) > 0
    # Each section should carry style information
    for sec in result:
        assert "style" in sec or "background_style" in sec or "visual_slot" in sec


def test_png_visual_sections_include_style_token_for_spec_focused():
    sections_raw = [s.copy() for s in SAMPLE_SECTIONS]
    result = build_visual_sections(
        product_name="루메나 선풍기",
        category="Living",
        sections=sections_raw,
        selected_style="spec_focused",
    )
    assert len(result) > 0
    # Each section must carry style info (matching lifestyle test level)
    for sec in result:
        assert "style" in sec, f"section {sec.get('key')} missing 'style' key"
        assert sec["style"]["style_key"] == "spec_focused"


def test_png_visual_sections_fallback_when_style_is_none():
    sections_raw = [s.copy() for s in SAMPLE_SECTIONS]
    result = build_visual_sections(
        product_name="루메나 선풍기",
        category="Living",
        sections=sections_raw,
        selected_style=None,
    )
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: style token consistency between figma and png
# ---------------------------------------------------------------------------

def test_figma_and_png_share_same_background_tone_for_lifestyle():
    """기획 9절 Step 4: figma와 PNG 양쪽이 동일한 배경 tone을 사용해야 한다."""
    project = _make_project(selected_style="lifestyle")
    page = _make_page(SAMPLE_SECTIONS)

    figma = build_figma_visual_layout(project=project, page=page, assets=[])
    sections_raw = [s.copy() for s in SAMPLE_SECTIONS]
    png = build_visual_sections(
        product_name="루메나 선풍기",
        category="Living",
        sections=sections_raw,
        selected_style="lifestyle",
    )

    # Both must reflect lifestyle style
    assert figma["style_key"] == "lifestyle"
    assert len(png) > 0

    # Compare background_tone consistency: figma cuts[0] vs png sections[0]
    # Figma first cut → problem_statement → warm_neutral (from STYLE_BACKGROUND_OVERRIDE)
    figma_first_tone = figma["cuts"][0]["background_tone"]
    png_first_style = png[0].get("style", {})
    assert png_first_style.get("background_tone") == figma_first_tone, (
        f"PNG first section background_tone ({png_first_style.get('background_tone')}) "
        f"does not match Figma first cut ({figma_first_tone})"
    )
    # Also check that section_type alignment is correct across Figma and PNG
    for i, cut in enumerate(figma["cuts"]):
        if i < len(png):
            png_style = png[i].get("style", {})
            assert png_style.get("style_key") == figma["style_key"], (
                f"Section {i} style_key mismatch: PNG={png_style.get('style_key')} vs Figma={figma['style_key']}"
            )
