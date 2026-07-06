import pytest
from src.services.copy_rewrite_service import CopyRewriteCommand, CopyRewriteService


@pytest.mark.parametrize(
    ("command", "changes_title", "changes_body"),
    [
        ("stronger_headline", True, False),
        ("shorter_natural", True, True),
        ("reduce_exaggeration", False, True),
        ("usage_context", False, True),
        ("beginner_seller_tone", True, True),
        ("reduce_purchase_anxiety", False, True),
        ("custom_edit", False, True),
    ],
)
def test_mock_rewrite_changes_expected_fields(command, changes_title, changes_body):
    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=CopyRewriteCommand(command),
        title="최고의 무선 선풍기",
        body_copy="무조건 가장 시원합니다.",
        instruction="차량 사용을 자연스럽게 넣어줘",
        confirmed_facts=["무선 사용", "USB-C 충전"],
        forbidden_claims=["가장 시원합니다"],
        section_type="hero",
    )
    assert (result.title != "최고의 무선 선풍기") is changes_title
    assert (result.body_copy != "무조건 가장 시원합니다.") is changes_body
    assert "[AI 수정됨]" not in result.title + result.body_copy
    assert "차량 사용을 자연스럽게 넣어줘 :" not in result.body_copy


def test_mock_rewrite_respects_forbidden_claims():
    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=CopyRewriteCommand.REDUCE_EXAGGERATION,
        title="최고의 무선 선풍기",
        body_copy="무조건 가장 시원합니다.",
        forbidden_claims=["가장 시원합니다"],
        section_type="hero",
    )
    assert "가장 시원합니다" not in result.body_copy


def test_mock_custom_edit_does_not_leak_instruction():
    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=CopyRewriteCommand.CUSTOM_EDIT,
        title="무선 선풍기",
        body_copy="편리하게 사용하세요.",
        instruction="차량 사용을 자연스럽게 넣어줘",
        section_type="hero",
    )
    assert "차량 사용을 자연스럽게 넣어줘" not in result.body_copy
    assert "[AI 수정됨]" not in result.body_copy


def test_real_rewrite_rejects_unconfirmed_claim():
    class FakeRouter:
        def generate_text(self, system_prompt, user_prompt):
            return (
                '{"title": "공식 1위 무선 선풍기",'
                '"body_copy": "24시간 연속 사용할 수 있습니다.",'
                '"change_summary": "강한 제목"}'
            )

    service = CopyRewriteService(mode="real", router=FakeRouter())
    result = service.preview(
        command=CopyRewriteCommand.STRONGER_HEADLINE,
        title="무선 선풍기",
        body_copy="필요한 곳에서 사용하세요.",
        instruction="",
        confirmed_facts=["무선 사용"],
        forbidden_claims=["공식 1위", "24시간"],
        section_type="hero",
    )
    # Should reject unconfirmed claims and restore original
    assert result.title == "무선 선풍기"
    assert result.grounding_warnings


def test_real_rewrite_fallback_on_parse_error():
    class BrokenRouter:
        def generate_text(self, system_prompt, user_prompt):
            return "not valid json"

    service = CopyRewriteService(mode="real", router=BrokenRouter())
    result = service.preview(
        command=CopyRewriteCommand.STRONGER_HEADLINE,
        title="무선 선풍기",
        body_copy="편리하게 사용하세요.",
        instruction="",
        section_type="hero",
    )
    assert result.title == "무선 선풍기"
    assert result.body_copy == "편리하게 사용하세요."


def test_sanitizer_removes_internal_markers():
    from src.services.copy_rewrite_service import sanitize_rewrite_output

    result = sanitize_rewrite_output("[AI 수정됨] 바람과 냉각감을 더해")
    assert "[AI 수정됨]" not in result


def test_sanitizer_removes_plus_and_em_dash():
    from src.services.copy_rewrite_service import sanitize_rewrite_output

    result = sanitize_rewrite_output("바람+냉각—콘센트 없이")
    assert "+" not in result
    assert "—" not in result


def test_sanitizer_removes_instruction_leak():
    from src.services.copy_rewrite_service import sanitize_rewrite_output

    result = sanitize_rewrite_output("차량 사용을 자연스럽게 넣어줘 : 어디서나 사용하세요.")
    assert "차량 사용을 자연스럽게 넣어줘" not in result


def test_mock_rewrite_has_no_forbidden_symbols():
    service = CopyRewriteService(mode="mock")
    for cmd in CopyRewriteCommand:
        result = service.preview(
            command=cmd,
            title="무선 선풍기",
            body_copy="편리하게 사용하세요.",
            section_type="hero",
        )
        assert "[AI 수정됨]" not in result.title + result.body_copy + result.change_summary
        assert "+" not in result.title and "+" not in result.body_copy
        assert "—" not in result.title and "—" not in result.body_copy


def test_stronger_headline_always_changes_title():
    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=CopyRewriteCommand.STRONGER_HEADLINE,
        title="무선 선풍기",
        body_copy="편리하게 사용하세요.",
        section_type="hero",
    )
    assert result.title != "무선 선풍기"


def test_shorter_natural_changes_both():
    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=CopyRewriteCommand.SHORTER_NATURAL,
        title="무선 선풍기",
        body_copy="편리하게 사용하세요.",
        section_type="hero",
    )
    assert result.title != "무선 선풍기"
    assert result.body_copy != "편리하게 사용하세요."


def test_usage_context_adds_usage_scene():
    service = CopyRewriteService(mode="mock")
    result = service.preview(
        command=CopyRewriteCommand.USAGE_CONTEXT,
        title="무선 선풍기",
        body_copy="편리하게 사용하세요.",
        section_type="hero",
    )
    assert "방" in result.body_copy or "차량" in result.body_copy or "캠핑" in result.body_copy or "침대" in result.body_copy
