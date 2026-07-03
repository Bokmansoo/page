import pytest
from src.agents.schemas import ProductUnderstandingOutput, SalesStrategyOutput
from src.agents.graph import AgentGraph
from src.agents.state import AgentRunMode, AgentRunState, ProductInput
from src.services.provider_adapters import MockTextProvider


@pytest.fixture
def auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


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


def test_real_text_graph_uses_provider_without_image_generation():
    graph = AgentGraph.real_text(text_provider=MockTextProvider())
    state = AgentRunState(
        project_id="p1",
        mode=AgentRunMode.REAL,
        product_input=ProductInput(product_name="유아 자전거"),
    )
    completed = graph.run_text_generation(state)
    assert "product_understanding" in completed.outputs
    assert "sales_strategy" in completed.outputs
    assert "copy_set" in completed.outputs
    assert "generated_assets" not in completed.outputs

    assert "page_assembly" in completed.outputs
    sections = completed.outputs["page_assembly"]["sections"]
    assert len(sections) > 0
    assert sections[0]["title"]


def test_run_real_api_endpoint(client, auth_headers):
    created = client.post(
        "/api/agent-runs",
        headers=auth_headers,
        json={"product_name": "유아 자전거", "description": "안전 바퀴 장착"},
    ).json()

    response = client.post(f"/api/agent-runs/{created['id']}/run", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["current_stage"] == "review_editor"
    assert "product_understanding" in data["outputs"]
    assert "copy_set" in data["outputs"]
    assert "page_assembly" in data["outputs"]
