import pytest
from unittest.mock import MagicMock, patch
from src.services.ai_adapter import (
    retry_with_backoff, 
    OpenAIAdapter, 
    GeminiAdapter, 
    AnthropicAdapter, 
    ExtractionResultSchema,
    ExtractedFactSchema
)

# Exponential Backoff 재시도 테스트
def test_retry_decorator_success_after_failure():
    call_count = 0

    @retry_with_backoff(retries=3, delay=0.01, backoff=1.0)
    def dummy_func():
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise ValueError("Temporary failure")
        return "success"

    result = dummy_func()
    assert result == "success"
    assert call_count == 2


def test_retry_decorator_fail_eventually():
    call_count = 0

    @retry_with_backoff(retries=3, delay=0.01, backoff=1.0)
    def dummy_func():
        nonlocal call_count
        call_count += 1
        raise ValueError("Persistent failure")

    with pytest.raises(ValueError) as exc:
        dummy_func()
    assert "Persistent failure" in str(exc.value)
    assert call_count == 3


# OpenAI Adapter Mocking Test
@patch("openai.OpenAI")
def test_openai_adapter_extract(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    
    # Mocking completion response
    mock_response = MagicMock()
    mock_parsed_data = ExtractionResultSchema(
        product_name="테스트 상품",
        recommended_category="Fashion",
        facts=[
            ExtractedFactSchema(fact_text="소재는 면 100%입니다.", source_text="면 100%")
        ]
    )
    mock_response.choices = [
        MagicMock(message=MagicMock(parsed=mock_parsed_data))
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    
    mock_client.beta.chat.completions.parse.return_value = mock_response

    adapter = OpenAIAdapter(api_key="mock_key", model_name="gpt-4o-mini")
    res = adapter.extract_facts("샘플 텍스트")

    assert res.data.product_name == "테스트 상품"
    assert res.provider == "openai"
    assert res.input_tokens == 100
    assert res.output_tokens == 50
    mock_client.beta.chat.completions.parse.assert_called_once()


# Gemini Adapter Mocking Test
@patch("google.generativeai.GenerativeModel")
@patch("google.generativeai.configure")
def test_gemini_adapter_extract(mock_configure, mock_model_class):
    mock_model = MagicMock()
    mock_model_class.return_value = mock_model
    
    # Mock response
    mock_response = MagicMock()
    mock_response.text = '{"product_name": "테스트 화장품", "recommended_category": "Beauty", "facts": [{"fact_text": "히알루론산 수분 크림입니다.", "source_text": "히알루론산"}]}'
    mock_response.usage_metadata = MagicMock(prompt_token_count=120, candidates_token_count=60)
    mock_model.generate_content.return_value = mock_response

    adapter = GeminiAdapter(api_key="mock_key", model_name="gemini-1.5-flash")
    res = adapter.extract_facts("샘플 텍스트")

    assert res.data.product_name == "테스트 화장품"
    assert res.provider == "google"
    assert res.input_tokens == 120
    assert res.output_tokens == 60
    mock_model.generate_content.assert_called_once()


# Anthropic Adapter Mocking Test
@patch("anthropic.Anthropic")
def test_anthropic_adapter_extract(mock_anthropic_class):
    mock_client = MagicMock()
    mock_anthropic_class.return_value = mock_client
    
    # Mock message response with tool use
    mock_response = MagicMock()
    mock_tool_use = MagicMock()
    mock_tool_use.type = "tool_use"
    mock_tool_use.input = {
        "product_name": "테스트 거치대",
        "recommended_category": "Living",
        "facts": [
            {"fact_text": "대나무 재질입니다.", "source_text": "대나무"}
        ]
    }
    mock_response.content = [mock_tool_use]
    mock_response.usage = MagicMock(input_tokens=150, output_tokens=70)
    
    mock_client.messages.create.return_value = mock_response

    adapter = AnthropicAdapter(api_key="mock_key", model_name="claude-3-5-sonnet-20241022")
    res = adapter.extract_facts("샘플 텍스트")

    assert res.data.product_name == "테스트 거치대"
    assert res.provider == "anthropic"
    assert res.input_tokens == 150
    assert res.output_tokens == 70
    mock_client.messages.create.assert_called_once()
