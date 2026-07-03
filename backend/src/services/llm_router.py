import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

from src.config import settings
from src.services.ai_adapter import OpenAIAdapter, GeminiAdapter, AIResponse
from src.services.fact_extractor import ExtractedFactCandidate, extract_fact_candidates
from src.services.source_collector import CollectedSource

logger = logging.getLogger(__name__)


class RouterResult(BaseModel):
    provider: str
    model: str
    candidates: List[ExtractedFactCandidate]
    failed_sources: List[Dict[str, Any]]


class LLMRouter:
    def __init__(self):
        # SELLFORM_LLM_* is the public config namespace.
        # Older FACTORY_LLM_* values are still accepted by Settings aliases.
        self.enable_fallbacks = settings.SELLFORM_LLM_ENABLE_FALLBACKS

    def extract_facts(self, raw_text: str) -> RouterResult:
        failed_sources: List[Dict[str, Any]] = []

        # 순차적 폴백 체인 설정
        providers_chain = [
            (settings.SELLFORM_LLM_DEFAULT_PROVIDER, settings.SELLFORM_LLM_DEFAULT_MODEL),
            (settings.SELLFORM_LLM_FALLBACK1_PROVIDER, settings.SELLFORM_LLM_FALLBACK1_MODEL),
            (settings.SELLFORM_LLM_FALLBACK2_PROVIDER, settings.SELLFORM_LLM_FALLBACK2_MODEL),
        ]

        for provider, model in providers_chain:
            # 폴백 비활성화 상태에서 디폴트 이외의 시도는 건너뜀
            if not self.enable_fallbacks and provider != settings.SELLFORM_LLM_DEFAULT_PROVIDER:
                continue

            # mock 모드인 경우 외부 API 호출 배제
            if settings.SELLFORM_GENERATION_MODE == "mock" and provider not in ("deterministic", "mock"):
                continue


            try:
                if provider == "openai":
                    # OpenAI API Key 유효성 체크
                    if not settings.OPENAI_API_KEY:
                        continue
                    
                    # effective_openai_model 하위 호환성 체크 적용
                    effective_model = settings.effective_openai_model or model
                    adapter = OpenAIAdapter(model_name=effective_model)
                    response: AIResponse = adapter.extract_facts(raw_text)
                    candidates = self._convert_to_candidates(response, "ai")
                    return RouterResult(
                        provider="openai",
                        model=effective_model,
                        candidates=candidates,
                        failed_sources=failed_sources
                    )

                elif provider in ("google", "gemini"):
                    # Gemini API Key 유효성 체크
                    if not settings.GEMINI_API_KEY:
                        continue

                    adapter = GeminiAdapter(model_name=model)
                    response: AIResponse = adapter.extract_facts(raw_text)
                    candidates = self._convert_to_candidates(response, "ai")
                    return RouterResult(
                        provider="google",
                        model=model,
                        candidates=candidates,
                        failed_sources=failed_sources
                    )

                elif provider == "deterministic":
                    # Local rule-based fallback
                    source = CollectedSource(source="manual_text", text=raw_text)
                    candidates = extract_fact_candidates([source])
                    return RouterResult(
                        provider="deterministic",
                        model=model or "local-rule-based",
                        candidates=candidates,
                        failed_sources=failed_sources
                    )

            except Exception as exc:
                logger.warning(f"LLM Router: Provider '{provider}' (model: '{model}') 실패. 사유: {exc}")
                failed_sources.append({
                    "provider": provider,
                    "model": model,
                    "reason": str(exc)
                })

        # 모든 설정된 체인이 실패했을 때 최종 안전 장치 (deterministic fallback 강제 실행)
        logger.error("LLM Router: 설정된 모든 Provider 체인이 실패했습니다. 최종 로컬 deterministic fallback을 강제 수행합니다.")
        source = CollectedSource(source="manual_text", text=raw_text)
        candidates = extract_fact_candidates([source])
        return RouterResult(
            provider="deterministic",
            model="local-rule-based",
            candidates=candidates,
            failed_sources=failed_sources
        )

    def _convert_to_candidates(self, response: AIResponse, source_kind: str) -> List[ExtractedFactCandidate]:
        candidates: List[ExtractedFactCandidate] = []
        # AI Fact Extraction Configurations 내에 지정된 최대 개수를 초과하지 않음
        max_facts = settings.AI_FACT_EXTRACTION_MAX_FACTS

        for fact in response.data.facts[:max_facts]:
            fact_text = fact.fact_text.strip() if fact.fact_text else ""
            if not fact_text:
                continue
            source_text = fact.source_text.strip() if fact.source_text and fact.source_text.strip() else fact_text
            candidates.append(
                ExtractedFactCandidate(
                    fact_text=fact_text,
                    source_text=source_text,
                    source_asset_id=None,
                    confidence=0.86,
                    extraction_source=source_kind,
                    needs_review=True,
                    risk_flags=[]
                )
            )
        return candidates


def get_text_provider_by_settings() -> Any:
    from src.services.provider_adapters import MockTextProvider
    return MockTextProvider()

