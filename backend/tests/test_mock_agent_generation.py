from backend.src.agents.mock_outputs import build_mock_product_understanding, build_mock_page_assembly


def test_mock_product_understanding_uses_input_name():
    result = build_mock_product_understanding(product_name="유아 자전거")
    assert result["product_type"] == "유아 자전거"
    assert "target_customer" in result
    assert result["verified_facts"]


def test_mock_page_assembly_has_copy_and_visual_slots():
    result = build_mock_page_assembly(product_name="유아 자전거")
    assert len(result["sections"]) >= 5
    assert all(section["title"] for section in result["sections"])
    assert all(section["visual_role"] for section in result["sections"])
