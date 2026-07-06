from src.services.prompt_registry import PromptRegistry


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


def test_prompt_registry_loads_agent_node_prompt_by_agent_name():
    registry = PromptRegistry(base_path="backend/src/agents/nodes")
    prompt = registry.load_agent_prompt("copywriting")

    assert "카피라이팅" in prompt
    assert "상세페이지" in prompt
