from backend.src.services.prompt_registry import PromptRegistry


def test_prompt_registry_loads_named_prompt():
    registry = PromptRegistry(base_path="backend/prompts")
    prompt = registry.load("agents/product_understanding")
    assert "상품" in prompt
    assert "검증된 사실" in prompt


def test_prompt_registry_rejects_path_traversal():
    registry = PromptRegistry(base_path="backend/prompts")
    try:
        registry.load("../.env")
    except ValueError as exc:
        assert "Invalid prompt name" in str(exc)
    else:
        raise AssertionError("path traversal should be rejected")
