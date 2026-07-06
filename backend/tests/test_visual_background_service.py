from src.services.visual_background_service import VisualBackgroundService


def test_visual_background_candidates_are_safe_korean_living_options():
    candidates = VisualBackgroundService().get_candidates(
        project_name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
    )

    assert len(candidates) >= 3
    candidate_ids = {candidate["id"] for candidate in candidates}
    assert {"cooling-blue", "minimal-white", "lifestyle-summer"}.issubset(candidate_ids)

    for candidate in candidates:
        assert candidate["title"]
        assert candidate["description"]
        assert candidate["style_key"]
        assert len(candidate["palette"]) >= 3
        assert all(color.startswith("#") for color in candidate["palette"])
        assert "로고" in candidate["safety_note"]
        assert "인증마크" in candidate["safety_note"]
        assert "荑" not in candidate["title"]
        assert "諛" not in candidate["description"]
