TEXT_FREE_POLICY = "No text, no Korean letters, no English letters, no logo, no watermark, no label."


def _prompt(base: str) -> str:
    return f"상세페이지용 이미지. {base} {TEXT_FREE_POLICY} Leave clean space for typography."


def build_scene_plan(
    *,
    product_name: str,
    asset_ids: list[str],
    confirmed_facts: list[str],
    desired_mood: list[str],
) -> dict:
    mood_text = ", ".join(desired_mood) if desired_mood else "clean commerce"
    primary_assets = asset_ids[:1]
    generated_strategy = "cutout_composite" if primary_assets else "generated_scene"
    identity_risk = "medium" if primary_assets else "high"

    sections = [
        {
            "section_id": "hero",
            "target_slot_id": "hero",
            "section_type": "hero",
            "visual_strategy": generated_strategy,
            "source_asset_ids": primary_assets,
            "image_prompt": _prompt(
                f"Premium commerce hero background for {product_name}, {mood_text}, studio lighting, realistic shadows."
            ),
            "text_free_required": True,
            "identity_risk": identity_risk,
        },
        {
            "section_id": "pain_points",
            "target_slot_id": "comparison",
            "section_type": "pain_points",
            "visual_strategy": "html_graphic",
            "source_asset_ids": [],
            "image_prompt": "",
            "text_free_required": True,
            "identity_risk": "low",
        },
        {
            "section_id": "benefits",
            "target_slot_id": "detail_1",
            "section_type": "benefit_cards",
            "visual_strategy": "html_graphic",
            "source_asset_ids": [],
            "image_prompt": "",
            "text_free_required": True,
            "identity_risk": "low",
        },
        {
            "section_id": "lifestyle",
            "target_slot_id": "detail_2",
            "section_type": "lifestyle_scene",
            "visual_strategy": generated_strategy,
            "source_asset_ids": primary_assets,
            "image_prompt": _prompt(
                f"Natural lifestyle scene for {product_name}, {mood_text}, commercial product photography."
            ),
            "text_free_required": True,
            "identity_risk": identity_risk,
        },
        {
            "section_id": "spec_table",
            "target_slot_id": "guarantee",
            "section_type": "spec_table",
            "visual_strategy": "html_graphic",
            "source_asset_ids": [],
            "image_prompt": "",
            "text_free_required": True,
            "identity_risk": "low",
        },
    ]

    return {
        "product_name": product_name,
        "confirmed_fact_count": len(confirmed_facts),
        "sections": sections,
    }
