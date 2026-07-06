from src.agents.nodes.reference_analysis.agent import ReferenceAnalysisAgent
from src.agents.nodes.reference_analysis.schema import AgentOutputSchema
from src.agents.state import AgentRunState


def test_reference_analysis_extracts_takeaways_without_copying():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "source_collection": {
                "product_url": "https://example.com/product",
                "reference_text_blocks": [
                    "우리 아이 첫 자전거, 아직도 망설이고 계세요?",
                    "아이 먼저 찾는 자전거",
                ],
            }
        },
    )

    result = ReferenceAnalysisAgent().run(state)
    analysis = result.outputs["reference_analysis"]
    parsed = AgentOutputSchema.model_validate(analysis)

    assert parsed.reference_available is True
    assert parsed.structure_takeaways
    assert parsed.copy_risk_notes
    assert "우리 아이 첫 자전거" not in parsed.recommended_rewrite_direction
    assert "새로 작성" in parsed.recommended_rewrite_direction
