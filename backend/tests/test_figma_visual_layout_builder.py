from types import SimpleNamespace

from src.services.figma_visual_layout_builder import build_figma_visual_layout


def _section(section_type: str, title: str, order: int, image_asset_id: str | None = None):
    return SimpleNamespace(
        id=f"sec-{order}",
        section_type=section_type,
        title=title,
        body_copy=f"{title}을 설명하는 본문입니다.",
        sort_order=order,
        is_visible=True,
        image_asset_id=image_asset_id,
    )


def test_build_figma_visual_layout_has_seven_commerce_cuts():
    page = SimpleNamespace(
        sections=[
            _section("problem_statement", "작은 불편이 쌓이면 일상이 번거로워집니다", 0),
            _section("main_claim", "일상의 불편을 덜어주는 실용적인 선택", 1, "asset-main"),
            _section("secondary_benefit", "공간과 사용 경험에 더하는 장점", 2),
            _section("main_claim_support", "왜 이 상품이어야 할까요?", 3),
            _section("benefit_list", "구매 전 확인할 장점들", 4),
            _section("summary_claim", "한 문장으로 정리하면", 5),
            _section("product_information", "상품 정보", 6),
        ]
    )
    project = SimpleNamespace(
        name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
        selected_background="cooling-blue",
    )

    layout = build_figma_visual_layout(project=project, page=page, assets=[])

    assert layout["layout_version"] == "commerce_visual_v1"
    assert layout["width"] == 860
    assert len(layout["cuts"]) == 7
    assert layout["cuts"][0]["section_type"] == "problem_statement"
    assert layout["cuts"][0]["layout_type"] == "problem_visual"
    assert layout["cuts"][0]["image_role"] == "lifestyle_scene"
    assert layout["cuts"][1]["image_asset_ref"] == "asset-main"
    assert layout["cuts"][1]["badges"]


def test_build_figma_visual_layout_uses_intentional_placeholders_without_images():
    page = SimpleNamespace(
        sections=[
            _section("problem_statement", "작은 불편이 쌓이면 일상이 번거로워집니다", 0),
            _section("main_claim", "일상의 불편을 덜어주는 실용적인 선택", 1),
            _section("secondary_benefit", "공간과 사용 경험에 더하는 장점", 2),
            _section("main_claim_support", "왜 이 상품이어야 할까요?", 3),
            _section("benefit_list", "구매 전 확인할 장점들", 4),
            _section("summary_claim", "한 문장으로 정리하면", 5),
            _section("product_information", "상품 정보", 6),
        ]
    )
    project = SimpleNamespace(name="상품", category="Living", selected_background=None)

    layout = build_figma_visual_layout(project=project, page=page, assets=[])

    assert all(cut["visual_slot"]["kind"] == "placeholder" for cut in layout["cuts"])
    assert layout["cuts"][0]["visual_slot"]["fallback_label"] == "고객 불편 장면 이미지"
