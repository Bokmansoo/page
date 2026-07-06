import pytest
from src.agents.nodes.page_assembly.agent import PageAssemblyAgent
from src.agents.state import AgentRunState

def test_page_assembly_uses_real_generated_asset_when_selected():
    state = AgentRunState(
        project_id="project-1",
        selected_image_candidates={"hero": "candidate-real-hero"},
        outputs={
            "page_planning": {"sections": [{"section_id": "hero", "role": "hero"}]},
            "copywriting": {"sections": {"hero": {"title": "공간을 바꾸는 스마트 모니터", "body": "작은 공간에서도 화면을 자유롭게 배치하세요."}}},
            "image_generation": {
                "candidates": {
                    "hero": [
                        {
                            "candidate_id": "candidate-real-hero",
                            "asset_id": "asset-real-hero",
                            "source_type": "real-generated",
                            "identity_check": {"status": "needs_review"},
                        }
                    ]
                }
            },
        },
    )

    result = PageAssemblyAgent().run(state)
    section = result.outputs["page_assembly"]["sections"][0]

    assert section["title"] == "공간을 바꾸는 스마트 모니터"
    assert section["visual_slot"]["asset_id"] == "asset-real-hero"
    assert section["visual_slot"]["source_type"] == "real-generated"
    assert section["visual_slot"]["candidate_id"] == "candidate-real-hero"
    assert section["visual_slot"]["identity_check"]["status"] == "needs_review"


def test_page_assembly_preserves_scene_plan_metadata():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "visual_planning": {
                "scene_plan": {
                    "sections": [
                        {
                            "section_id": "hero",
                            "target_slot_id": "hero",
                            "visual_strategy": "cutout_composite",
                            "identity_risk": "medium",
                            "text_free_required": True,
                        },
                        {
                            "section_id": "pain_points",
                            "target_slot_id": "comparison",
                            "visual_strategy": "html_graphic",
                            "identity_risk": "low",
                            "text_free_required": True,
                        },
                    ]
                }
            },
            "image_generation": {
                "candidates": {
                    "hero": [
                        {
                            "candidate_id": "hero-generated",
                            "asset_id": "hero-asset",
                            "source_type": "real-generated",
                            "is_recommended": True,
                        }
                    ]
                }
            },
        },
    )

    output = PageAssemblyAgent().run(state).outputs["page_assembly"]
    hero = next(section for section in output["sections"] if section["id"] == "sec-1")
    comparison = next(section for section in output["sections"] if section["id"] == "sec-2")

    assert hero["scene_section_id"] == "hero"
    assert hero["visual_strategy"] == "cutout_composite"
    assert comparison["visual_strategy"] == "html_graphic"
    assert comparison["visual_slot"]["status"] == "html_rendered"
