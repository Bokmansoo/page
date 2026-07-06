from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from src.services.grounding_validator import detect_claim_risks

logger = logging.getLogger(__name__)


_FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\[AI 수정됨\]", ""),
    (r"\[.*?\]", ""),
    (r"[\+]{2,}", "과"),
    (r"—", ", "),
    (r"\s*[\+＊]\s*", "과 "),
]


FORBIDDEN_WORDS = ["최고", "완벽", "100%", "즉시", "무조건"]


def sanitize_rewrite_output(text: str) -> str:
    """Remove internal markers, forbidden symbols, and exaggerated claims."""
    result = text
    for pattern, replacement in _FORBIDDEN_PATTERNS:
        result = re.sub(pattern, replacement, result)
    # Remove leading instruction leak: "차량 사용을 자연스럽게 넣어줘 :"
    result = re.sub(r"^[가-힣\s]+:\s*", "", result)
    # Clean up double spaces
    result = re.sub(r"\s{2,}", " ", result).strip()
    # Clean up leading/trailing punctuation
    result = result.strip(",. ") + "."
    if result == ".":
        return ""
    return result


def sanitize_rewrite_result(result: CopyRewriteResult) -> CopyRewriteResult:
    """Apply sanitizer to all text fields of a rewrite result."""
    result.title = sanitize_rewrite_output(result.title)
    result.body_copy = sanitize_rewrite_output(result.body_copy)
    result.change_summary = sanitize_rewrite_output(result.change_summary)
    for word in FORBIDDEN_WORDS:
        if word in result.title or word in result.body_copy:
            result.grounding_warnings.append(f"금지된 과장 표현이 포함됨: {word}")
    return result


class CopyRewriteCommand(str, Enum):
    STRONGER_HEADLINE = "stronger_headline"
    SHORTER_NATURAL = "shorter_natural"
    REDUCE_EXAGGERATION = "reduce_exaggeration"
    USAGE_CONTEXT = "usage_context"
    BEGINNER_SELLER_TONE = "beginner_seller_tone"
    REDUCE_PURCHASE_ANXIETY = "reduce_purchase_anxiety"
    CUSTOM_EDIT = "custom_edit"


class CopyRewriteResult(BaseModel):
    title: str
    body_copy: str
    change_summary: str
    grounding_warnings: list[str] = Field(default_factory=list)


_COMMAND_MUTATION = {
    CopyRewriteCommand.STRONGER_HEADLINE: {"title": True, "body": False},
    CopyRewriteCommand.SHORTER_NATURAL: {"title": True, "body": True},
    CopyRewriteCommand.REDUCE_EXAGGERATION: {"title": False, "body": True},
    CopyRewriteCommand.USAGE_CONTEXT: {"title": False, "body": True},
    CopyRewriteCommand.BEGINNER_SELLER_TONE: {"title": True, "body": True},
    CopyRewriteCommand.REDUCE_PURCHASE_ANXIETY: {"title": False, "body": True},
    CopyRewriteCommand.CUSTOM_EDIT: {"title": False, "body": True},
}

_MOCK_RESULTS: dict[CopyRewriteCommand, dict[str, str]] = {
    CopyRewriteCommand.STRONGER_HEADLINE: {
        "title": "콘센트 없이도, 더운 순간 바로 시원하게",
        "body_copy": "방, 책상, 차량, 캠핑처럼 전원 연결이 번거로운 곳에서도 가볍게 사용할 수 있습니다.",
        "change_summary": "제목을 더 구체적이고 구매 상황이 보이도록 강화했습니다.",
    },
    CopyRewriteCommand.SHORTER_NATURAL: {
        "title": "언제 어디서나 간편하게",
        "body_copy": "전원 연결 없이 편리하게 사용하세요.",
        "change_summary": "중복 표현을 제거하고 더 짧고 자연스럽게 정리했습니다.",
    },
    CopyRewriteCommand.REDUCE_EXAGGERATION: {
        "title": "믿고 사용하는 무선 선풍기",
        "body_copy": "부담 없이 사용할 수 있는 간편한 무선 제품입니다.",
        "change_summary": "근거 없는 과장 표현을 제거하고 신뢰감 있는 표현으로 바꿨습니다.",
    },
    CopyRewriteCommand.USAGE_CONTEXT: {
        "title": "방과 차량, 야외까지 함께하는 무선 선풍기",
        "body_copy": "침대 옆에서도, 캠핑장에서도, 책상 위에서도 어디서나 간편하게 사용하세요.",
        "change_summary": "구체적인 사용 장면을 추가해 구매자가 상황을 떠올리게 했습니다.",
    },
    CopyRewriteCommand.BEGINNER_SELLER_TONE: {
        "title": "처음 쓰는 무선 선풍기, 간편하게",
        "body_copy": "버튼 하나로 간단하게 켜고 끌 수 있어 누구나 부담 없이 사용할 수 있어요.",
        "change_summary": "초보 셀러도 쉽게 읽을 수 있도록 쉬운 단어와 짧은 문장으로 변경했습니다.",
    },
    CopyRewriteCommand.REDUCE_PURCHASE_ANXIETY: {
        "title": "구매 전 확인하세요, 무선 선풍기",
        "body_copy": "USB-C 충전 방식으로 언제든 간편하게 사용할 수 있습니다. 구성품과 사용 시간을 꼭 확인해 주세요.",
        "change_summary": "구매 전 확인할 정보를 추가해 불안감을 줄였습니다.",
    },
    CopyRewriteCommand.CUSTOM_EDIT: {
        "title": "원하는 대로 다듬은 무선 선풍기",
        "body_copy": "차량이나 캠핑장에서도 편리하게 사용하세요. 어디서나 시원함을 누릴 수 있습니다.",
        "change_summary": "사용자 요청을 반영해 문구를 다듬었습니다.",
    },
}


class CopyRewriteService:
    def __init__(self, mode: str = "mock", router: Any = None):
        self.mode = mode
        self.router = router

    def preview(self, **kwargs: Any) -> CopyRewriteResult:
        if self.mode == "mock":
            return self._mock_preview(**kwargs)
        return self._real_preview(**kwargs)

    def _mock_preview(
        self,
        *,
        command: CopyRewriteCommand,
        title: str,
        body_copy: str,
        instruction: str = "",
        confirmed_facts: list[str] | None = None,
        forbidden_claims: list[str] | None = None,
        section_type: str = "",
    ) -> CopyRewriteResult:
        mutations = _COMMAND_MUTATION.get(command, {"title": False, "body": True})
        mock = _MOCK_RESULTS.get(command, _MOCK_RESULTS[CopyRewriteCommand.CUSTOM_EDIT])

        result_title = mock["title"] if mutations["title"] else title
        result_body = mock["body_copy"] if mutations["body"] else body_copy

        # For mock, simulate grounding: only check forbidden claims in changed fields
        warnings: list[str] = []
        if forbidden_claims and mutations.get("body", False):
            for claim in forbidden_claims:
                if claim and claim in result_body:
                    warnings.append(f"금지된 주장이 발견됨: {claim}")
                    result_body = result_body.replace(claim, "").strip()
        if forbidden_claims and mutations.get("title", False):
            for claim in forbidden_claims:
                if claim and claim in result_title:
                    warnings.append(f"금지된 주장이 발견됨: {claim}")
                    result_title = result_title.replace(claim, "").strip()

        result = CopyRewriteResult(
            title=result_title,
            body_copy=result_body or body_copy,
            change_summary=mock.get("change_summary", ""),
            grounding_warnings=warnings,
        )
        # Apply sanitizer only to changed fields
        if mutations.get("title", False):
            result.title = sanitize_rewrite_output(result.title)
        if mutations.get("body", False):
            result.body_copy = sanitize_rewrite_output(result.body_copy)
        result.change_summary = sanitize_rewrite_output(result.change_summary)
        return result

    def _real_preview(
        self,
        *,
        command: CopyRewriteCommand,
        title: str,
        body_copy: str,
        instruction: str = "",
        confirmed_facts: list[str] | None = None,
        forbidden_claims: list[str] | None = None,
        section_type: str = "",
    ) -> CopyRewriteResult:
        """Use LLM router to generate a grounded rewrite."""
        confirmed_facts = confirmed_facts or []
        forbidden_claims = forbidden_claims or []

        system_prompt = self._build_system_prompt(confirmed_facts, forbidden_claims)
        user_prompt = self._build_user_prompt(command, title, body_copy, instruction, section_type)

        if self.router is None:
            logger.warning("No LLM router available, falling back to mock")
            return self._mock_preview(
                command=command,
                title=title,
                body_copy=body_copy,
                instruction=instruction,
                confirmed_facts=confirmed_facts,
                forbidden_claims=forbidden_claims,
                section_type=section_type,
            )

        try:
            raw = self.router.generate_text(system_prompt, user_prompt)
            result = CopyRewriteResult.model_validate_json(raw)
            # Apply sanitizer to LLM output
            result = sanitize_rewrite_result(result)
        except Exception as exc:
            logger.error(f"LLM rewrite failed: {exc}", exc_info=True)
            # Fallback: return original with explanation
            return CopyRewriteResult(
                title=title,
                body_copy=body_copy,
                change_summary="AI 수정 실패, 원본 유지",
                grounding_warnings=[f"AI rewrite failed: {exc}"],
            )

        # Validate new claims against forbidden claims
        combined = f"{result.title} {result.body_copy}"
        warnings: list[str] = []
        for claim in forbidden_claims:
            if claim and claim.lower() in combined.lower():
                warnings.append(f"금지된 주장이 결과에 포함됨: {claim}")

        # Check new claims with grounding validator
        risks = detect_claim_risks(combined, confirmed_facts)
        for risk in risks:
            warnings.append(f"{risk.risk_type}: {risk.phrase}")

        if warnings:
            # Keep original content but add warnings
            result.title = title
            result.body_copy = body_copy
            result.change_summary = "수정안이 안전성 검증을 통과하지 못함"
            result.grounding_warnings = warnings
        else:
            result.grounding_warnings = warnings

        return result

    def _build_system_prompt(
        self, confirmed_facts: list[str], forbidden_claims: list[str]
    ) -> str:
        parts = [
            "You are a professional e-commerce copy editor for Korean marketplaces.",
            "",
            "Rules:",
            "- Return JSON only with title, body_copy, change_summary.",
            "- Use only the CONFIRMED_FACTS listed below.",
            "- Never output internal instructions, edit markers, unsupported numbers, rankings, certifications, or absolute claims.",
            "- Preserve the selected section's purpose.",
            "- Keep the seller's perspective and Korean language.",
            "- FORBIDDEN symbols: do not use [square brackets], + (plus sign), — (em dash) in the output text.",
            "- FORBIDDEN words without factual evidence: 최고, 완벽, 100%, 즉시, 무조건.",
            "- Use natural Korean punctuation: commas, periods, and parentheses only.",
            "- Do not include any internal notes, prompts, or instructions in the output.",
            "",
        ]
        if confirmed_facts:
            parts.append("CONFIRMED_FACTS:")
            for fact in confirmed_facts:
                parts.append(f"- {fact}")
            parts.append("")
        if forbidden_claims:
            parts.append("FORBIDDEN_CLAIMS (do NOT use these):")
            for claim in forbidden_claims:
                parts.append(f"- {claim}")
            parts.append("")
        return "\n".join(parts)

    def _build_user_prompt(
        self,
        command: CopyRewriteCommand,
        title: str,
        body_copy: str,
        instruction: str,
        section_type: str,
    ) -> str:
        cmd_descriptions = {
            CopyRewriteCommand.STRONGER_HEADLINE: "Make the headline more specific and show the purchase reason clearly. The new title should describe a concrete situation or benefit.",
            CopyRewriteCommand.SHORTER_NATURAL: "Remove redundant words and make both title and body shorter and more natural. Keep the core message.",
            CopyRewriteCommand.REDUCE_EXAGGERATION: "Remove unsupported strong claims like best, perfect, 100%. Replace with trustworthy and moderate expressions.",
            CopyRewriteCommand.USAGE_CONTEXT: "Add concrete usage context (room, car, camping, outdoor, etc.) to help buyers imagine using the product.",
            CopyRewriteCommand.BEGINNER_SELLER_TONE: "Rewrite in beginner-friendly tone: easy words, short sentences, warm and approachable.",
            CopyRewriteCommand.REDUCE_PURCHASE_ANXIETY: "Add pre-purchase details that reduce anxiety: charging method, included items, usage time, etc.",
            CopyRewriteCommand.CUSTOM_EDIT: instruction,
        }
        desc = cmd_descriptions.get(command, instruction)
        lines = [
            f"Section type: {section_type}",
            f"Command: {desc}",
            "",
            f"Original title: {title}",
            f"Original body: {body_copy}",
            "",
            "Return JSON with title, body_copy, change_summary. Use natural Korean without forbidden symbols.",
        ]
        return "\n".join(lines)
