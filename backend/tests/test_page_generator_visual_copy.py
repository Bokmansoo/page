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


def test_real_provider_prompt_contains_confirmed_sales_strategy():
    strategy = {
        "target_customer": "혼자 상세페이지를 만드는 1인 셀러",
        "buyer_problem": "어떤 장점을 먼저 강조할지 어렵다",
        "main_selling_point": "확인된 근거로 구매 이유를 정리한다",
    }

    content = PageGenerationService._build_user_content(
        category="Living",
        facts_payload=[],
        sales_strategy=strategy,
    )

    assert strategy["target_customer"] in content
    assert strategy["buyer_problem"] in content
    assert strategy["main_selling_point"] in content
