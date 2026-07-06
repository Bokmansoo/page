import re
from typing import Any


def _field(value: str, source: str, confidence: str) -> dict[str, str]:
    return {
        "value": value.strip(),
        "source": source,
        "confidence": confidence,
    }


def _extract_price(text: str) -> str:
    match = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원", text)
    return f"{match.group(1)}원" if match else ""


def _extract_product_name(text: str) -> str:
    normalized = text.strip()
    match = re.search(r"(.+?)(?:입니다|이에요|예요|입니다\.|이에요\.|예요\.)", normalized)
    if match:
        return match.group(1).strip()
    first_sentence = re.split(r"[.!?\n]", normalized, maxsplit=1)[0].strip()
    return first_sentence[:40]


def _extract_selling_points(text: str) -> list[dict[str, str]]:
    rules = [
        ("LED", "LED 조명"),
        ("보조바퀴", "보조바퀴 탈착 가능" if "탈착" in text else "보조바퀴"),
        ("탈착", "탈착 가능"),
        ("무료배송", "무료배송"),
    ]
    points: list[dict[str, str]] = []
    seen: set[str] = set()
    for needle, label in rules:
        if needle in text and label not in seen:
            points.append(
                {
                    "text": label,
                    "source": "freeform_input",
                    "confidence": "needs_review",
                }
            )
            seen.add(label)
    return points


def _extract_mood(text: str, explicit: str = "") -> list[str]:
    source = f"{explicit}, {text}"
    mood_map = {
        "안전": "안전한",
        "감성": "감성적인",
        "프리미엄": "프리미엄",
        "고급": "고급스러운",
        "미니멀": "미니멀",
        "자연": "내추럴",
    }
    moods: list[str] = []
    for needle, label in mood_map.items():
        if needle in source and label not in moods:
            moods.append(label)
    return moods


def structure_intake(payload: dict[str, Any]) -> dict[str, Any]:
    freeform = str(payload.get("freeform_input") or "")
    explicit_name = str(payload.get("product_name") or "").strip()
    description = str(payload.get("description") or "").strip()
    desired_mood = str(payload.get("desired_mood") or "").strip()
    product_url = str(payload.get("product_url") or "").strip()
    reference_urls = [
        str(url).strip()
        for url in payload.get("reference_urls") or []
        if str(url).strip()
    ]

    product_name = (
        _field(explicit_name, "explicit_field", "confirmed")
        if explicit_name
        else _field(_extract_product_name(freeform), "freeform_input", "needs_review")
    )
    price = _extract_price(freeform)
    shipping_value = "무료배송" if "무료배송" in freeform else ""

    selling_points = _extract_selling_points(f"{description}\n{freeform}")
    if description:
        selling_points.append(
            {
                "text": description,
                "source": "explicit_field",
                "confidence": "confirmed",
            }
        )

    return {
        "product_name": product_name,
        "description": (
            _field(description, "explicit_field", "confirmed")
            if description
            else _field("", "", "missing")
        ),
        "product_url": (
            _field(product_url, "explicit_field", "confirmed")
            if product_url
            else _field("", "", "missing")
        ),
        "reference_urls": reference_urls,
        "selling_points": selling_points,
        "price": (
            _field(price, "freeform_input", "needs_review")
            if price
            else _field("", "", "missing")
        ),
        "shipping": (
            _field(shipping_value, "freeform_input", "needs_review")
            if shipping_value
            else _field("", "", "missing")
        ),
        "desired_mood": _extract_mood(freeform, desired_mood),
        "asset_ids": list(payload.get("asset_ids") or []),
        "warnings": [],
    }
