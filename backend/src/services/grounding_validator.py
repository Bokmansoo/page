from dataclasses import dataclass


@dataclass(frozen=True)
class GroundingWarning:
    risk_type: str
    phrase: str
    reason: str
    suggestion: str


NUMERIC_PATTERNS = ["-10도", "1초", "100%", "1위", "최고"]
PERFORMANCE_PATTERNS = ["업계 최고", "초강력", "최강", "압도적"]
SAFETY_PATTERNS = ["안전한", "무독성", "어린이 안전", "알레르기 걱정 없음"]
HEALTH_PATTERNS = ["의학", "치료", "예방", "개선", "효능"]
CERTIFICATION_PATTERNS = ["KC 인증", "인증 완료", "공식 인증"]


def _has_evidence(phrase: str, confirmed_facts: list[str]) -> bool:
    compact_phrase = phrase.replace(" ", "").lower()
    for fact in confirmed_facts:
        if compact_phrase in fact.replace(" ", "").lower():
            return True
    return False


def detect_claim_risks(text: str, confirmed_facts: list[str]) -> list[GroundingWarning]:
    warnings: list[GroundingWarning] = []

    for phrase in NUMERIC_PATTERNS:
        if phrase in text and not _has_evidence(phrase, confirmed_facts):
            warnings.append(
                GroundingWarning(
                    "numeric_claim_without_evidence",
                    phrase,
                    "수치 표현은 확인된 사실 카드에 근거가 있어야 합니다.",
                    "확인된 수치만 사용하거나 표현을 완화하세요.",
                )
            )

    for phrase in PERFORMANCE_PATTERNS:
        if phrase in text and not _has_evidence(phrase, confirmed_facts):
            warnings.append(
                GroundingWarning(
                    "performance_claim_without_evidence",
                    phrase,
                    "성능 우위 표현은 비교 근거가 필요합니다.",
                    "시원한 바람을 보조하는 제품처럼 완화된 표현을 사용하세요.",
                )
            )

    for phrase in SAFETY_PATTERNS + HEALTH_PATTERNS + CERTIFICATION_PATTERNS:
        if phrase in text and not _has_evidence(phrase, confirmed_facts):
            warnings.append(
                GroundingWarning(
                    "regulated_claim_without_evidence",
                    phrase,
                    "안전, 건강, 인증 표현은 명확한 근거가 필요합니다.",
                    "근거를 추가하거나 해당 표현을 삭제하세요.",
                )
            )

    return warnings


def map_section_to_facts(section_text: str, confirmed_facts: list[str]) -> list[str]:
    normalized_text = section_text.replace(",", "").replace(" ", "").lower()
    matched: list[str] = []

    for fact in confirmed_facts:
        keywords = [token for token in fact.replace(",", "").split() if len(token) >= 2]
        if not keywords:
            continue
        matching_count = sum(1 for keyword in keywords if keyword.replace(" ", "").lower() in normalized_text)
        if matching_count / len(keywords) >= 0.5:
            matched.append(fact)

    return matched


def build_grounding_review(sections: list[dict], confirmed_facts: list[str]) -> dict:
    section_reviews = []
    used_facts = set()
    warning_count = 0
    grounded_section_count = 0

    for section in sections:
        text = f"{section.get('title', '') or ''} {section.get('body', '') or ''}"
        matched_facts = map_section_to_facts(text, confirmed_facts)
        warnings = detect_claim_risks(text, confirmed_facts)

        for fact in matched_facts:
            used_facts.add(fact)
        if matched_facts:
            grounded_section_count += 1
        warning_count += len(warnings)

        section_reviews.append(
            {
                "section_key": section.get("key"),
                "matched_facts": matched_facts,
                "warnings": [warning.__dict__ for warning in warnings],
            }
        )

    return {
        "summary": {
            "warning_count": warning_count,
            "grounded_section_count": grounded_section_count,
            "used_fact_count": len(used_facts),
        },
        "sections": section_reviews,
    }



