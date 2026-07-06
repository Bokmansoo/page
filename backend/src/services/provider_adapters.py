import json
import logging
from typing import Any, Dict, List, Optional, Protocol
from pydantic import BaseModel
import openai
import anthropic
import google.generativeai as genai

from src.config import settings
from src.agents.schemas import (
    ProductUnderstandingOutput,
    SalesStrategyOutput,
    DetailPagePlanOutput,
    CopySetOutput,
    VisualPlanOutput,
    QAReportOutput,
)
from src.agents.mock_outputs import (
    build_mock_product_understanding,
    build_mock_sales_strategy,
    build_mock_page_plan,
    build_mock_copy_set,
    build_mock_visual_plan,
    build_mock_qa_report,
)

logger = logging.getLogger(__name__)

SCHEMA_MAP = {
    "product_understanding": ProductUnderstandingOutput,
    "sales_strategy": SalesStrategyOutput,
    "page_plan": DetailPagePlanOutput,
    "copy_set": CopySetOutput,
    "visual_plan": VisualPlanOutput,
    "qa_report": QAReportOutput,
}


class ProviderRequest(BaseModel):
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    schema_name: str
    product_name: Optional[str] = None


class ProviderResult(BaseModel):
    provider: str
    model: str
    content: Dict[str, Any]
    token_usage: Optional[Dict[str, int]] = None
    cost: Optional[float] = None


class TextProviderProtocol(Protocol):
    def generate_json(self, req: ProviderRequest) -> Dict[str, Any]:
        ...


class MockTextProvider:
    def generate_json(self, req: ProviderRequest) -> Dict[str, Any]:
        schema = req.schema_name
        pname = req.product_name or "상품"

        if schema == "product_understanding":
            content = build_mock_product_understanding(pname)
        elif schema == "sales_strategy":
            content = build_mock_sales_strategy(pname)
        elif schema == "page_plan":
            content = build_mock_page_plan(pname)
        elif schema == "copy_set":
            content = build_mock_copy_set(pname)
        elif schema == "visual_plan":
            content = build_mock_visual_plan(pname)
        elif schema == "qa_report":
            content = build_mock_qa_report(pname)
        else:
            content = {}

        result = ProviderResult(
            provider="mock",
            model="mock-text",
            content=content,
            token_usage={"prompt_tokens": 100, "completion_tokens": 200},
            cost=0,
        )
        return result.model_dump()


class OpenAITextProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_FACT_MODEL or "gpt-4o-mini"
        self.client = openai.OpenAI(api_key=self.api_key) if self.api_key else None

    def generate_json(self, req: ProviderRequest) -> Dict[str, Any]:
        if not self.client:
            raise ValueError("OpenAI API key missing or client not initialized.")

        schema_cls = SCHEMA_MAP.get(req.schema_name)
        if not schema_cls:
            raise ValueError(f"Unknown schema name: {req.schema_name}")

        response = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": req.system_prompt},
                {"role": "user", "content": req.user_prompt},
            ],
            response_format=schema_cls,
            temperature=0.2,
            timeout=settings.AI_FACT_EXTRACTION_TIMEOUT_SECONDS,
        )
        parsed = response.choices[0].message.parsed
        if not parsed:
            raise ValueError("OpenAI failed to parse response into expected Pydantic model.")

        result = ProviderResult(
            provider="openai",
            model=self.model,
            content=parsed.model_dump(),
            token_usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            cost=None,
        )
        return result.model_dump()


class GeminiTextProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model or "gemini-1.5-flash"
        if self.api_key:
            genai.configure(api_key=self.api_key)

    def generate_json(self, req: ProviderRequest) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("Gemini API key missing.")

        schema_cls = SCHEMA_MAP.get(req.schema_name)
        if not schema_cls:
            raise ValueError(f"Unknown schema name: {req.schema_name}")

        generation_config = {
            "response_mime_type": "application/json",
            "response_schema": schema_cls,
            "temperature": 0.2,
        }

        model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=req.system_prompt,
            generation_config=generation_config,
        )

        response = model.generate_content([req.user_prompt])
        raw_json = json.loads(response.text)
        validated = schema_cls.model_validate(raw_json)

        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count
            output_tokens = response.usage_metadata.candidates_token_count

        result = ProviderResult(
            provider="google",
            model=self.model_name,
            content=validated.model_dump(),
            token_usage={
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
            },
            cost=None,
        )
        return result.model_dump()


class ClaudeTextProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = model or "claude-3-5-sonnet-20241022"
        self.client = anthropic.Anthropic(api_key=self.api_key) if self.api_key else None

    def generate_json(self, req: ProviderRequest) -> Dict[str, Any]:
        if not self.client:
            raise ValueError("Anthropic API key missing or client not initialized.")

        schema_cls = SCHEMA_MAP.get(req.schema_name)
        if not schema_cls:
            raise ValueError(f"Unknown schema name: {req.schema_name}")

        json_schema = schema_cls.model_json_schema()

        tool_definition = {
            "name": f"format_{req.schema_name}",
            "description": f"Outputs data conforming to schema: {req.schema_name}",
            "input_schema": json_schema,
        }

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4000,
            system=req.system_prompt,
            messages=[{"role": "user", "content": req.user_prompt}],
            tools=[tool_definition],
            tool_choice={"type": "tool", "name": f"format_{req.schema_name}"},
            temperature=0.2,
        )

        tool_call = next(
            (content for content in response.content if content.type == "tool_use"), None
        )
        if not tool_call:
            raise ValueError("Claude did not use the formatting tool.")

        raw_result = tool_call.input
        validated = schema_cls.model_validate(raw_result)

        result = ProviderResult(
            provider="anthropic",
            model=self.model,
            content=validated.model_dump(),
            token_usage={
                "prompt_tokens": response.usage.input_tokens if response.usage else 0,
                "completion_tokens": response.usage.output_tokens if response.usage else 0,
            },
            cost=None,
        )
        return result.model_dump()


class FallbackTextProvider:
    def __init__(self, providers: List[TextProviderProtocol]):
        self.providers = providers

    def generate_json(self, req: ProviderRequest) -> Dict[str, Any]:
        last_exception = None
        for provider in self.providers:
            try:
                logger.info(f"Trying provider {provider.__class__.__name__} for {req.schema_name}...")
                return provider.generate_json(req)
            except Exception as e:
                logger.warning(
                    f"LLM Provider {provider.__class__.__name__} failed on {req.schema_name}. "
                    f"Error: {e}. Trying next provider in fallback chain..."
                )
                last_exception = e
        raise last_exception or Exception("All text providers in fallback chain failed")
