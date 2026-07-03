from typing import Any, Dict, Optional, Protocol
from pydantic import BaseModel
from src.agents.mock_outputs import (
    build_mock_product_understanding,
    build_mock_sales_strategy,
    build_mock_page_plan,
    build_mock_copy_set,
    build_mock_visual_plan,
    build_mock_qa_report,
)


class ProviderRequest(BaseModel):
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    schema_name: str


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
        pname = "유아 자전거"

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
            provider=req.provider,
            model=req.model,
            content=content,
            token_usage={"prompt_tokens": 100, "completion_tokens": 200},
            cost=0.001,
        )
        return result.model_dump()
