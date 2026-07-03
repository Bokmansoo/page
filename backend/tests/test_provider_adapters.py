from src.services.provider_adapters import ProviderRequest, MockTextProvider


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
