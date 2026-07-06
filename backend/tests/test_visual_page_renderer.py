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
