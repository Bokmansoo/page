from src.services.detail_page_scene_planner import build_scene_plan


def test_scene_plan_uses_composite_for_hero_when_product_asset_exists():
    plan = build_scene_plan(
        product_name="아이 LED 자전거",
        asset_ids=["asset-1"],
        confirmed_facts=["LED 조명", "보조바퀴 탈착 가능"],
        desired_mood=["안전한", "감성적인"],
    )

    hero = next(section for section in plan["sections"] if section["section_id"] == "hero")
    assert hero["visual_strategy"] == "cutout_composite"
    assert hero["source_asset_ids"] == ["asset-1"]
    assert hero["text_free_required"] is True
    assert "No text" in hero["image_prompt"]
    assert "no Korean letters" in hero["image_prompt"]


def test_scene_plan_keeps_spec_table_as_html_graphic():
    plan = build_scene_plan(
        product_name="아이 LED 자전거",
        asset_ids=["asset-1"],
        confirmed_facts=["LED 조명"],
        desired_mood=[],
    )

    spec = next(section for section in plan["sections"] if section["section_id"] == "spec_table")
    assert spec["visual_strategy"] == "html_graphic"
    assert spec["image_prompt"] == ""
    assert spec["identity_risk"] == "low"


def test_visual_planning_turns_scene_plan_into_generation_jobs():
    from src.agents.nodes.visual_planning.agent import VisualPlanningAgent
    from src.agents.state import AgentRunState, ProductInput

    state = AgentRunState(
        project_id="scene-project",
        product_input=ProductInput(
            product_name="LED 어린이 자전거",
            asset_ids=["asset-1"],
            selling_points=["LED 조명", "보조 바퀴 탈착"],
            desired_mood=["안전한", "따뜻한"],
        ),
    )

    output = VisualPlanningAgent().run(state).outputs["visual_planning"]

    assert output["scene_plan"]["product_name"] == "LED 어린이 자전거"
    assert output["scene_plan"]["confirmed_fact_count"] == 2
    assert {job["scene_section_id"] for job in output["image_jobs"]} == {
        "hero",
        "lifestyle",
    }
    assert all(job["source_asset_ids"] == ["asset-1"] for job in output["image_jobs"])
