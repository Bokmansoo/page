"""UX-2B: deterministic Korean commerce copy from approved product facts.

This module deliberately never calls an LLM.  It only rephrases values that
already exist in the approved fact snapshot, so the same contract can later be
used by an LLM-backed implementation without weakening grounding rules.
"""

from __future__ import annotations

import re
from typing import Any


FIELD_LABELS = {
    "battery_capacity": "배터리 용량",
    "rated_power": "정격 소비전력",
    "rated_input": "정격 입력",
    "charging_port": "충전 방식",
    "single_operation_time": "1회 권장 사용 시간",
    "usage_time": "1회 권장 사용 시간",
    "product_size": "제품 크기",
    "model_name": "모델명",
    "components": "구성품",
    "color": "색상",
    "weight": "무게",
    "heating_temperature": "표기 온도",
    "charge_time": "충전 시간",
    "total_use_time": "사용 가능 시간",
    "massage_head_count": "마사지 헤드 수",
    "cautions": "사용 전 주의사항",
}

PROHIBITED_UNSUPPORTED_CLAIMS = (
    "피로 회복", "통증 완화", "안전 검증", "안전성 검증", "의료 효과", "치료 효과",
    "무상 a/s", "무상 as", "a/s 제공", "as 제공", "a/s 보장", "as 보장",
    "kc 인증", "인증 완료", "안전 보장", "품질 보증", "1년 보증",
)


def display_label(field_key: str | None, scope: str | None = None, model_option: str | None = None) -> str:
    key = (field_key or "").strip().lower()
    # Unknown internal keys must never leak to customer-facing output.
    label = FIELD_LABELS.get(key, "확인된 상품 정보")
    if key in {"product_size", "weight"}:
        if scope == "master_carton":
            label = "외박스 크기" if key == "product_size" else "외박스 무게"
        elif scope == "individual_package":
            label = "개별 포장 크기" if key == "product_size" else "개별 포장 무게"
    option = (model_option or "").strip()
    return f"{label} · {option}" if option else label


def fact_value(fact: dict[str, Any]) -> str:
    value = fact.get("value") or fact.get("normalized_value") or fact.get("fact_text") or ""
    unit = fact.get("unit") or fact.get("normalized_unit") or ""
    return f"{value}{unit}".strip()


def normalized_facts(facts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for fact in facts or []:
        value = fact_value(fact)
        key = str(fact.get("field_key") or "").strip()
        marker = f"{key}:{value}"
        if not value or marker in seen:
            continue
        seen.add(marker)
        result.append({
            "id": fact.get("id"), "field_key": key,
            "label": display_label(key, fact.get("scope"), fact.get("model_option")),
            "value": value, "scope": fact.get("scope"), "model_option": fact.get("model_option"),
        })
    return result


def _topic_particle(label: str) -> str:
    last = label.rstrip()[-1:]
    if not last:
        return "은"
    codepoint = ord(last)
    return "은" if 0xAC00 <= codepoint <= 0xD7A3 and (codepoint - 0xAC00) % 28 != 0 else "는"


def _sentence(fact: dict[str, Any]) -> str:
    return f"{fact['label']}{_topic_particle(fact['label'])} {fact['value']}입니다."


def _safe_seller_copy(text: str, fallback: str) -> str:
    """Keep seller wording only when it does not contain unsupported claims."""
    return fallback if unsupported_claims(text) else (text or "").strip() or fallback


def build_rule_based_copy(
    product_name: str,
    *,
    description: str = "",
    category: str | None = None,
    facts: list[dict[str, Any]] | None = None,
    components: str | None = None,
    cautions: str | None = None,
) -> dict[str, Any]:
    """Return the legacy CopySet shape with UX-2B grounded Korean copy."""
    name = (product_name or "상품").strip() or "상품"
    cards = normalized_facts(facts)
    massage = any(word in f"{name} {category or ''}".lower() for word in ("마사지", "massag"))
    hero_title = f"목과 어깨 사용을 고려한 {name}" if massage else f"{name} 제품 정보 한눈에 보기"
    description_text = (description or "").strip()
    # Numerical specifications must be shown only in sections with explicit
    # fact links, never copied as an unlinked HERO sentence.
    hero_subtitle = (
        _safe_seller_copy(description_text, "판매자가 확인한 제품 사양을 한눈에 정리했습니다.")
        if not any(char.isdigit() for char in description_text)
        else "판매자가 확인한 제품 사양을 한눈에 정리했습니다."
    )
    # A repeated field must still be distinguishable by scope/model.  When it
    # is not distinguishable, do not spend another key-information slot on it.
    preferred_feature_keys = (
        "battery_capacity", "rated_input", "rated_power", "single_operation_time",
        "usage_time", "charging_port", "charge_time", "total_use_time",
    )
    by_key = {str(card["field_key"]).lower(): card for card in cards}
    selected: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for key in preferred_feature_keys:
        card = by_key.get(key)
        if card and card["label"] not in seen_labels:
            selected.append(card)
            seen_labels.add(card["label"])
    for card in cards:
        if card["label"] in seen_labels:
            continue
        selected.append(card)
        seen_labels.add(card["label"])
        if len(selected) == 3:
            break
    feature = []
    fallback_feature_copy = [
        ("전원·배터리 정보 확인", "전원과 배터리 관련 표기 사양을 구매 전에 확인해 주세요."),
        ("제품 크기 확인", "설치·보관 전 제품 크기와 사용 공간을 확인해 주세요."),
        ("사용 시간 확인", "권장 사용 시간과 사용 방법은 제품 안내를 확인해 주세요."),
    ]
    for index in range(3):
        fact = selected[index] if index < len(selected) else None
        feature.append((fact["label"], _sentence(fact)) if fact else fallback_feature_copy[index])

    power_facts = [fact for fact in cards if fact["field_key"].lower() in {"rated_input", "rated_power", "charging_port", "single_operation_time", "usage_time", "charge_time", "total_use_time"}]
    has_charging_fact = any(fact["field_key"].lower() in {"charging_port", "charge_time"} for fact in power_facts)
    usage_title = "충전·전원 정보 확인" if has_charging_fact else "전원·사용 정보 확인" if power_facts else "사용 전 안내"
    usage_body = " ".join(_sentence(fact) for fact in power_facts) or "사용 방법과 주의사항은 판매자 제공 정보를 확인한 뒤 사용해 주세요."
    component_fact = next((fact for fact in cards if fact["field_key"].lower() == "components"), None)
    caution_fact = next((fact for fact in cards if fact["field_key"].lower() == "cautions"), None)
    # Components must originate from an approved ProductFact. Raw intake text
    # is converted into such a fact before this generator is called.
    component_value = component_fact["value"] if component_fact else ""
    details_title = "구성품 확인" if component_value else "제품 사양과 옵션 확인"
    details_body = f"구성품은 {component_value}입니다." if component_value else "모델, 규격, 옵션과 세부 사양을 구매 전에 확인해 주세요."
    caution = _safe_seller_copy(caution_fact["value"] if caution_fact else "", "")
    if caution:
        details_body = f"{details_body} 사용 전 안내: {caution}"

    section_fact_ids = {
        "feature_1": [selected[0]["id"]] if len(selected) >= 1 and selected[0].get("id") else [],
        "feature_2": [selected[1]["id"]] if len(selected) >= 2 and selected[1].get("id") else [],
        "feature_3": [selected[2]["id"]] if len(selected) >= 3 and selected[2].get("id") else [],
        "usage_guide": [fact["id"] for fact in power_facts if fact.get("id")],
        "details_components": [
            fact["id"] for fact in (component_fact, caution_fact)
            if fact and fact.get("id") and (fact is not caution_fact or caution)
        ],
    }
    return {
        "hero_title": hero_title, "hero_subtitle": hero_subtitle,
        "painpoint_title": "사용 부위와 제품 크기를 먼저 확인하세요",
        "painpoint_body": "사용 환경에 맞는 크기와 구성, 사용 전 주의사항을 먼저 확인해 주세요.",
        "feature_1_title": feature[0][0], "feature_1_body": feature[0][1],
        "feature_2_title": feature[1][0], "feature_2_body": feature[1][1],
        "feature_3_title": feature[2][0], "feature_3_body": feature[2][1],
        "usage_title": usage_title, "usage_body": usage_body,
        "details_title": details_title, "details_body": details_body,
        "guarantee_title": "최종 사양·주의사항 확인",
        "guarantee_body": "모델명, 규격, 구성품과 사용 전 주의사항을 마지막으로 확인해 주세요.",
        "cta_text": "상품 정보 확인하기",
        # Mock-only metadata used by page assembly. It has no generated text
        # and preserves fact provenance through save/restore/export.
        "section_fact_ids": section_fact_ids,
    }


def unsupported_claims(text: str) -> list[str]:
    lowered = (text or "").lower()
    found = [claim for claim in PROHIBITED_UNSUPPORTED_CLAIMS if claim in lowered]
    # Broad category words are also reviewed, but avoid duplicate warnings
    # when a more useful, specific phrase is already present.
    broad_categories = (
        ("인증", ("kc 인증", "인증 완료")),
        ("안전", ("안전 검증", "안전성 검증", "안전 보장")),
        ("치료", ("치료 효과", "의료 효과", "통증 완화", "피로 회복")),
        ("보증", ("품질 보증", "1년 보증")),
        ("a/s", ("무상 a/s", "a/s 제공", "a/s 보장")),
        ("as", ("무상 as", "as 제공", "as 보장")),
    )
    for category, specifics in broad_categories:
        category_present = (
            bool(re.search(r"(?<![a-z])as(?![a-z])", lowered))
            if category == "as"
            else category in lowered
        )
        if category_present and not any(item in found for item in specifics):
            found.append(category)
    return found
