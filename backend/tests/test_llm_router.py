import pytest
from unittest.mock import patch, MagicMock
from src.services.llm_router import LLMRouter, RouterResult
from src.services.ai_adapter import AIResponse, ExtractionResultSchema, ExtractedFactSchema
from src.config import settings

@pytest.fixture(autouse=True)
def mock_settings_keys():
    orig_openai = settings.OPENAI_API_KEY
    orig_gemini = settings.GEMINI_API_KEY
    settings.OPENAI_API_KEY = "mock-openai-key"
    settings.GEMINI_API_KEY = "mock-gemini-key"
    yield
    settings.OPENAI_API_KEY = orig_openai
    settings.GEMINI_API_KEY = orig_gemini

def test_router_openai_success():
    # OpenAI 성공 시나리오: Google이나 Deterministic 폴백을 타지 않음.
    mock_data = ExtractionResultSchema(
        product_name="OpenAI Fan",
        recommended_category="Living",
        facts=[
            ExtractedFactSchema(fact_text="OpenAI를 통해 추출된 사실 1", source_text="근거 1"),
            ExtractedFactSchema(fact_text="OpenAI를 통해 추출된 사실 2", source_text="근거 2")
        ]
    )
    mock_response = AIResponse(
        data=mock_data,
        provider="openai",
        model_name="gpt-5.4-nano",
        input_tokens=100,
        output_tokens=50,
        duration_ms=450
    )

    with patch("src.services.llm_router.OpenAIAdapter") as mock_openai_adapter_class:
        mock_adapter = MagicMock()
        mock_adapter.extract_facts.return_value = mock_response
        mock_openai_adapter_class.return_value = mock_adapter

        with patch("src.services.llm_router.GeminiAdapter") as mock_gemini_adapter_class:
            router = LLMRouter()
            result = router.extract_facts("상품 정보 원문")

            # OpenAI가 성공했으므로 GeminiAdapter는 호출되지 않음
            mock_gemini_adapter_class.assert_not_called()
            mock_adapter.extract_facts.assert_called_once_with("상품 정보 원문")

            assert result.provider == "openai"
            assert result.model == "gpt-5.4-nano"
            assert len(result.candidates) == 2
            assert result.candidates[0].fact_text == "OpenAI를 통해 추출된 사실 1"
            assert result.failed_sources == []

def test_router_openai_fail_google_success():
    # OpenAI 실패하고 Google(Gemini) 성공 시나리오
    mock_data = ExtractionResultSchema(
        product_name="Google Fan",
        recommended_category="Living",
        facts=[
            ExtractedFactSchema(fact_text="Google을 통해 추출된 사실 1", source_text="근거 1")
        ]
    )
    mock_response = AIResponse(
        data=mock_data,
        provider="google",
        model_name="gemini-2.5-flash",
        input_tokens=120,
        output_tokens=60,
        duration_ms=500
    )

    with patch("src.services.llm_router.OpenAIAdapter") as mock_openai_adapter_class:
        # OpenAI는 ValueError(예: API Key 누락) 발생
        mock_openai_adapter = MagicMock()
        mock_openai_adapter.extract_facts.side_effect = ValueError("OpenAI API Key 누락")
        mock_openai_adapter_class.return_value = mock_openai_adapter

        with patch("src.services.llm_router.GeminiAdapter") as mock_gemini_adapter_class:
            mock_gemini_adapter = MagicMock()
            mock_gemini_adapter.extract_facts.return_value = mock_response
            mock_gemini_adapter_class.return_value = mock_gemini_adapter

            router = LLMRouter()
            result = router.extract_facts("상품 정보 원문")

            mock_openai_adapter.extract_facts.assert_called_once()
            mock_gemini_adapter.extract_facts.assert_called_once_with("상품 정보 원문")

            assert result.provider == "google"
            assert result.model == "gemini-2.5-flash"
            assert len(result.candidates) == 1
            assert result.candidates[0].fact_text == "Google을 통해 추출된 사실 1"
            assert len(result.failed_sources) == 1
            assert result.failed_sources[0]["provider"] == "openai"
            assert "OpenAI API Key 누락" in result.failed_sources[0]["reason"]

def test_router_all_api_fail_deterministic_fallback():
    # OpenAI, Google 모두 실패하여 deterministic fallback으로 떨어지는 시나리오
    with patch("src.services.llm_router.OpenAIAdapter") as mock_openai_adapter_class:
        mock_openai_adapter = MagicMock()
        mock_openai_adapter.extract_facts.side_effect = Exception("OpenAI Timeout")
        mock_openai_adapter_class.return_value = mock_openai_adapter

        with patch("src.services.llm_router.GeminiAdapter") as mock_gemini_adapter_class:
            mock_gemini_adapter = MagicMock()
            mock_gemini_adapter.extract_facts.side_effect = Exception("Gemini Connection Error")
            mock_gemini_adapter_class.return_value = mock_gemini_adapter

            with patch("src.services.llm_router.extract_fact_candidates") as mock_extract_candidates:
                from src.services.fact_extractor import ExtractedFactCandidate
                mock_extract_candidates.return_value = [
                    ExtractedFactCandidate(
                        fact_text="로컬 룰 기반 추출 사실 1",
                        source_text="로컬 근거 1",
                        source_asset_id=None,
                        confidence=0.5,
                        extraction_source="deterministic"
                    )
                ]

                router = LLMRouter()
                result = router.extract_facts("상품 정보 원문")

                mock_openai_adapter.extract_facts.assert_called_once()
                mock_gemini_adapter.extract_facts.assert_called_once()
                mock_extract_candidates.assert_called_once()

                assert result.provider == "deterministic"
                assert result.model == "local-rule-based"
                assert len(result.candidates) == 1
                assert result.candidates[0].fact_text == "로컬 룰 기반 추출 사실 1"
                assert len(result.failed_sources) == 2
                assert result.failed_sources[0]["provider"] == "openai"
                assert result.failed_sources[1]["provider"] == "google"
