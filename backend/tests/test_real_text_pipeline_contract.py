from src.agents.schemas import ProductUnderstandingOutput, SalesStrategyOutput


def test_product_understanding_schema_requires_facts():
    output = ProductUnderstandingOutput(
        product_type="유아 자전거",
        target_customer="첫 자전거를 찾는 부모",
        buyer_problem="안전한 첫 자전거 선택이 어렵다",
        verified_facts=["보조 바퀴 포함"],
        assumptions=["실내외 사용 가능"],
        risk_notes=[],
    )
    assert output.verified_facts == ["보조 바퀴 포함"]


def test_sales_strategy_schema_has_recommended_direction():
    output = SalesStrategyOutput(
        recommended_direction="문제 해결형",
        alternatives=["감성형", "스펙 강조형"],
        main_claim="처음 타는 순간부터 안정적인 자전거",
        support_claims=["보조 바퀴", "낮은 안장"],
        reason="초보 사용자의 구매 불안을 직접 해결한다",
    )
    assert output.recommended_direction == "문제 해결형"
