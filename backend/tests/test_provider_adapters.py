import json
from types import SimpleNamespace

from src.config import settings
from src.agents.schemas import ProductUnderstandingOutput
from src.services import provider_adapters
from src.services.llm_router import get_text_provider_by_settings
from src.services.provider_adapters import (
    ClaudeTextProvider,
    FallbackTextProvider,
    GeminiTextProvider,
    MockTextProvider,
    OpenAITextProvider,
    ProviderRequest,
)


def test_mock_text_provider_returns_schema_compatible_json():
    provider = MockTextProvider()
    result = provider.generate_json(
        ProviderRequest(
            provider="mock",
            model="mock-text",
            system_prompt="system",
            user_prompt="user",
            schema_name="product_understanding",
        )
    )
    assert result["provider"] == "mock"
    assert isinstance(result["content"], dict)


def test_mock_text_provider_uses_requested_product_name():
    provider = MockTextProvider()
    result = provider.generate_json(
        ProviderRequest(
            provider="mock",
            model="mock-text",
            system_prompt="system",
            user_prompt="상품명: 스테인리스 프라이팬",
            schema_name="product_understanding",
            product_name="스테인리스 프라이팬",
        )
    )

    assert result["content"]["product_type"] == "스테인리스 프라이팬"


def test_fallback_text_provider_tries_next_provider_after_failure():
    calls = []

    class FailingProvider:
        def generate_json(self, req):
            calls.append("primary")
            raise RuntimeError("primary unavailable")

    class SuccessfulProvider:
        def generate_json(self, req):
            calls.append("fallback")
            return {"provider": "fallback", "model": "fallback-model", "content": {}}

    provider = FallbackTextProvider([FailingProvider(), SuccessfulProvider()])

    result = provider.generate_json(
        ProviderRequest(
            provider="router",
            model="router",
            system_prompt="system",
            user_prompt="user",
            schema_name="product_understanding",
        )
    )

    assert calls == ["primary", "fallback"]
    assert result["provider"] == "fallback"


def test_text_provider_factory_uses_text_pipeline_settings(monkeypatch):
    monkeypatch.setattr(settings, "SELLFORM_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "SELLFORM_TEXT_LLM_ENABLE_FALLBACKS", True)
    monkeypatch.setattr(settings, "SELLFORM_TEXT_LLM_PRIMARY_PROVIDER", "claude")

    monkeypatch.setattr(settings, "SELLFORM_TEXT_LLM_PRIMARY_MODEL", "claude-primary")
    monkeypatch.setattr(settings, "SELLFORM_TEXT_LLM_FALLBACK1_PROVIDER", "openai")
    monkeypatch.setattr(settings, "SELLFORM_TEXT_LLM_FALLBACK1_MODEL", "openai-fallback")
    monkeypatch.setattr(settings, "SELLFORM_TEXT_LLM_FALLBACK2_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "SELLFORM_TEXT_LLM_FALLBACK2_MODEL", "gemini-fallback")

    provider = get_text_provider_by_settings()

    assert isinstance(provider, FallbackTextProvider)
    assert [type(item) for item in provider.providers] == [
        ClaudeTextProvider,
        OpenAITextProvider,
        GeminiTextProvider,
    ]
    assert [
        getattr(item, "model", getattr(item, "model_name", None))
        for item in provider.providers
    ] == ["claude-primary", "openai-fallback", "gemini-fallback"]


def _product_understanding_payload(product_name):
    return {
        "product_type": product_name,
        "target_customer": "상품을 찾는 고객",
        "verified_facts": ["등록된 상품 정보"],
        "assumptions": [],
    }


def _provider_request(product_name="스테인리스 프라이팬"):
    return ProviderRequest(
        provider="router",
        model="configured",
        system_prompt="system",
        user_prompt="user",
        schema_name="product_understanding",
        product_name=product_name,
    )


def test_openai_text_provider_parses_structured_response_without_network():
    parsed = ProductUnderstandingOutput.model_validate(
        _product_understanding_payload("스테인리스 프라이팬")
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
    )
    parse_calls = []

    class FakeCompletions:
        def parse(self, **kwargs):
            parse_calls.append(kwargs)
            return response

    provider = OpenAITextProvider.__new__(OpenAITextProvider)
    provider.model = "openai-test"
    provider.client = SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    )

    result = provider.generate_json(_provider_request())

    assert result["provider"] == "openai"
    assert result["content"]["product_type"] == "스테인리스 프라이팬"
    assert parse_calls[0]["response_format"] is ProductUnderstandingOutput


def test_gemini_text_provider_validates_json_response_without_network(monkeypatch):
    payload = _product_understanding_payload("스테인리스 프라이팬")
    response = SimpleNamespace(
        text=json.dumps(payload, ensure_ascii=False),
        usage_metadata=SimpleNamespace(
            prompt_token_count=13,
            candidates_token_count=9,
        ),
    )

    class FakeModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def generate_content(self, prompts):
            assert prompts == ["user"]
            return response

    monkeypatch.setattr(provider_adapters.genai, "GenerativeModel", FakeModel)

    provider = GeminiTextProvider.__new__(GeminiTextProvider)
    provider.api_key = "test-key"
    provider.model_name = "gemini-test"

    result = provider.generate_json(_provider_request())

    assert result["provider"] == "google"
    assert result["content"]["product_type"] == "스테인리스 프라이팬"


def test_claude_text_provider_validates_tool_response_without_network():
    payload = _product_understanding_payload("스테인리스 프라이팬")
    response = SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", input=payload)],
        usage=SimpleNamespace(input_tokens=17, output_tokens=8),
    )
    create_calls = []

    class FakeMessages:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            return response

    provider = ClaudeTextProvider.__new__(ClaudeTextProvider)
    provider.model = "claude-test"
    provider.client = SimpleNamespace(messages=FakeMessages())

    result = provider.generate_json(_provider_request())

    assert result["provider"] == "anthropic"
    assert result["content"]["product_type"] == "스테인리스 프라이팬"
    assert create_calls[0]["tool_choice"]["name"] == "format_product_understanding"
