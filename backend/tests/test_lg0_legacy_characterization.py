"""LG-0 regression contract for the existing sequential generation path.

This is intentionally a characterization test: until LG-8, the legacy path
must keep its stage order and structured outputs while LangGraph is introduced
alongside it.
"""

from __future__ import annotations

from src.agents.graph import AgentGraph
from src.agents.schemas import (
    CopySetOutput,
    DetailPagePlanOutput,
    ProductUnderstandingOutput,
    QAReportOutput,
    SalesStrategyOutput,
    VisualPlanOutput,
)
from src.agents.state import AgentRunState, AgentStage, ProductInput
from src.config import settings
from src.services.openai_image_provider import OpenAIImageProvider
from src.services.provider_adapters import OpenAITextProvider


STAGE_ORDER = [stage.value for stage in AgentStage]


def _legacy_golden_input() -> AgentRunState:
    return AgentRunState(
        project_id="lg0-characterization-project",
        product_input=ProductInput(
            product_name="경추 마사지 베개",
            category="Living",
            description="판매자 확인 제품 정보",
            feature_details="온열과 압박 기능",
            components="본체, 충전 케이블",
            cautions="치료·효능 표현을 사용하지 않습니다.",
            product_url="https://supplier.example/products/neck-pillow",
            freeform_input="대표 기준 사진을 바탕으로 판매 페이지를 만듭니다.",
            reference_urls=["https://supplier.example/reference"],
            selling_points=["제품 크기 40 x 17 x 15cm"],
            desired_mood=["차분한 정보형"],
        ),
        input_snapshot={
            "product_url": "https://supplier.example/products/neck-pillow",
            "reference_urls": ["https://supplier.example/reference"],
            "freeform_input": "대표 기준 사진을 바탕으로 판매 페이지를 만듭니다.",
            "ux_auto_generate": True,
            "approved_facts": [
                {
                    "id": "fact-size",
                    "field_key": "product_size",
                    "value": "40 x 17 x 15cm",
                    "status": "seller_confirmed",
                }
            ],
        },
    )


def _raise_if_external_provider_is_called(*_args, **_kwargs):
    raise AssertionError("LG-0 legacy characterization must not call an external provider")


def test_lg0_legacy_golden_path_preserves_11_agent_transitions_and_output_contracts(monkeypatch):
    """Fix the current legacy behavior before later Sprints replace it."""

    monkeypatch.setattr(settings, "SELLFORM_GRAPH_RUNTIME", "legacy")
    monkeypatch.setattr(OpenAITextProvider, "generate_json", _raise_if_external_provider_is_called)
    monkeypatch.setattr(OpenAIImageProvider, "generate", _raise_if_external_provider_is_called)

    graph = AgentGraph.mock()
    observed_stages: list[str] = []
    for agent in graph.agents:
        original_run = agent.run
        agent_name = agent.name

        def traced_run(state, *, _original_run=original_run, _agent_name=agent_name):
            observed_stages.append(state.current_stage.value)
            assert state.current_stage.value == _agent_name
            return _original_run(state)

        agent.run = traced_run

    result = graph.run(_legacy_golden_input())

    assert observed_stages == STAGE_ORDER
    assert result.current_stage == AgentStage.QA_REVIEW
    assert [key for key in result.outputs if key in STAGE_ORDER] == STAGE_ORDER

    assert result.outputs["input_router"] == {
        "input_type": "mixed",
        "missing_inputs": [],
    }
    assert {
        "product_url",
        "freeform_input",
        "reference_urls",
        "uploaded_images",
        "url_images",
        "reference_images",
        "reference_text_blocks",
        "source_summary",
    } <= result.outputs["source_collection"].keys()
    assert result.outputs["reference_analysis"]["skipped"] is False
    assert result.outputs["reference_analysis"]["reference_available"] is True

    ProductUnderstandingOutput.model_validate(result.outputs["product_understanding"])
    SalesStrategyOutput.model_validate(result.outputs["sales_strategy"])
    DetailPagePlanOutput.model_validate(result.outputs["page_planning"])
    CopySetOutput.model_validate(result.outputs["copywriting"])
    VisualPlanOutput.model_validate(result.outputs["visual_planning"])
    QAReportOutput.model_validate(result.outputs["qa_review"])

    assert {"scene_plan", "visual_slots", "image_jobs"} <= result.outputs["visual_planning"].keys()
    assert {"jobs", "candidates", "images"} <= result.outputs["image_generation"].keys()
    assert result.outputs["page_assembly"]["sections"]
    assert {"status", "warnings", "can_export"} <= result.outputs["qa_review"].keys()
    assert result.outputs["legacy"]["page_plan"] == result.outputs["page_planning"]
    assert result.outputs["legacy"]["copy_set"] == result.outputs["copywriting"]
