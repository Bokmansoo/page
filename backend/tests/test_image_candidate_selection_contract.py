from src.agents.nodes.image_generation.agent import ImageGenerationAgent
from src.agents.nodes.image_generation.schema import AgentOutputSchema as ImageGenerationSchema
from src.agents.nodes.page_assembly.agent import PageAssemblyAgent
from src.agents.state import AgentRunState


def test_image_generation_returns_candidates_per_visual_slot():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "source_collection": {
                "uploaded_images": [
                    {"asset_id": "asset-1", "filename": "삼탠바이미.png", "source_type": "uploaded"}
                ],
                "url_images": [
                    {"asset_id": "url-asset-1", "filename": "URL 참고 이미지.png", "source_type": "url-extracted"}
                ],
            },
            "visual_planning": {
                "visual_slots": [
                    {"slot_id": "hero", "role": "대표 상품 컷"},
                    {"slot_id": "usage", "role": "사용 장면 컷"},
                ]
            },
        },
    )

    result = ImageGenerationAgent().run(state)
    parsed = ImageGenerationSchema.model_validate(result.outputs["image_generation"])
    candidates = parsed.candidates

    assert candidates["hero"][0].source_type == "uploaded"
    assert candidates["hero"][0].asset_id == "asset-1"
    assert candidates["hero"][0].is_recommended is True
    assert any(candidate.source_type == "url-extracted" for candidate in candidates["usage"])
    assert any(candidate.source_type == "mock-generated" for candidate in candidates["usage"])


def test_page_assembly_uses_selected_image_candidate():
    state = AgentRunState(
        project_id="project-1",
        selected_image_candidates={"hero": "candidate-hero-selected"},
        outputs={
            "page_planning": {"sections": [{"section_id": "hero", "role": "hero"}]},
            "copywriting": {"sections": {"hero": {"title": "공간을 바꾸는 스마트 모니터"}}},
            "image_generation": {
                "candidates": {
                    "hero": [
                        {"candidate_id": "candidate-hero-default", "asset_id": "asset-default", "source_type": "mock-generated"},
                        {"candidate_id": "candidate-hero-selected", "asset_id": "asset-selected", "source_type": "uploaded"},
                    ]
                }
            },
        },
    )

    result = PageAssemblyAgent().run(state)
    hero = result.outputs["page_assembly"]["sections"][0]
    assert hero["visual_slot"]["asset_id"] == "asset-selected"


def test_page_assembly_marks_missing_image_when_no_candidate_exists():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "page_planning": {"sections": [{"section_id": "hero", "role": "hero"}]},
            "copywriting": {"sections": {"hero": {"title": "이미지 없는 섹션"}}},
            "image_generation": {"candidates": {}},
        },
    )

    result = PageAssemblyAgent().run(state)
    hero = result.outputs["page_assembly"]["sections"][0]
    assert hero["visual_slot"]["status"] == "missing_image"
    assert hero["image_asset_id"] is None


def test_page_assembly_does_not_repeat_uploaded_source_when_generation_failed():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "page_planning": {"sections": [{"section_id": "hero", "role": "hero"}]},
            "copywriting": {"sections": {"hero": {"title": "거실 속 삼탠바이미"}}},
            "image_generation": {
                "jobs": [
                    {
                        "job_id": "hero-1",
                        "slot_id": "hero",
                        "status": "provider_error",
                    }
                ],
                "candidates": {
                    "hero": [
                        {
                            "candidate_id": "candidate-hero-uploaded",
                            "asset_id": "asset-uploaded",
                            "source_type": "uploaded",
                            "is_recommended": False,
                        }
                    ]
                },
            },
        },
    )

    result = PageAssemblyAgent().run(state)
    hero = result.outputs["page_assembly"]["sections"][0]

    assert hero["visual_slot"]["status"] == "generation_failed"
    assert hero["visual_slot"]["asset_id"] is None
    assert hero["image_asset_id"] is None
