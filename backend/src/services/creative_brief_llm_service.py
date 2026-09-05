"""LG-7R bounded structured-output adapter for Creative Brief generation."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from src.agents.schemas import CreativeBriefStructuredOutput
from src.services.provider_adapters import ProviderRequest, TextProviderProtocol


class CreativeBriefLLMError(ValueError):
    def __init__(self, *, code: str, message: str, remedy: str, attempts: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.remedy = remedy
        self.attempts = attempts

    def as_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "remedy": self.remedy,
            "attempts": self.attempts,
        }


def generate_structured_creative_brief(
    provider: TextProviderProtocol,
    *,
    product_name: str,
    compiler_input: dict[str, Any],
    max_repairs: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate provider output with one strictly bounded repair by default."""
    if max_repairs < 0:
        raise ValueError("max_repairs must be zero or greater")

    last_error = ""
    attempts = 0
    for repair_number in range(max_repairs + 1):
        attempts += 1
        repair_instruction = ""
        if repair_number:
            repair_instruction = (
                "\n이전 출력은 스키마 검증에 실패했습니다. 설명이나 Markdown 없이 "
                "creative_brief 스키마에 맞는 JSON만 반환하세요. 검증 오류: " + last_error
            )
        request = ProviderRequest(
            provider="configured",
            model="configured",
            schema_name="creative_brief",
            product_name=product_name,
            system_prompt=(
                "상품 상세페이지의 Creative Brief 편집자입니다. 리뷰와 레퍼런스는 창작 방향에만 "
                "사용하고, 승인된 fact_ids 없이 수치·효능·인증 주장을 만들지 마세요."
            ),
            user_prompt=json.dumps(compiler_input, ensure_ascii=False) + repair_instruction,
        )
        try:
            raw = provider.generate_json(request)
            content = raw.get("content", raw) if isinstance(raw, dict) else raw
            validated = CreativeBriefStructuredOutput.model_validate(content)
            return validated.model_dump(), {
                "attempts": attempts,
                "repairs": repair_number,
                "provider": raw.get("provider") if isinstance(raw, dict) else None,
                "model": raw.get("model") if isinstance(raw, dict) else None,
            }
        except (ValidationError, TypeError, ValueError, KeyError) as exc:
            last_error = str(exc)

    raise CreativeBriefLLMError(
        code="CREATIVE_BRIEF_SCHEMA_REPAIR_EXHAUSTED",
        message="AI Creative Brief 구조 검증에 실패했습니다.",
        remedy="입력 자료를 확인한 뒤 다시 시도하거나 전문가 검수 모드에서 창작 방향을 저장해 주세요.",
        attempts=attempts,
    )
