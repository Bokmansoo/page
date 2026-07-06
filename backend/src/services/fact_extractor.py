import re
from dataclasses import dataclass, field

from src.services.source_collector import CollectedSource


@dataclass(frozen=True)
class ExtractedFactCandidate:
    fact_text: str
    source_text: str
    source_asset_id: str | None
    confidence: float
    extraction_source: str
    needs_review: bool = True
    risk_flags: list[str] = field(default_factory=list)


_PATTERN_FACTS: list[tuple[re.Pattern[str], str, list[str]]] = [
    (re.compile(r"usb[-\s]?c", re.IGNORECASE), "이 상품은 USB-C 충전을 지원합니다.", []),
    (re.compile(r"3\s*(wind\s*)?speeds?|3\s*단", re.IGNORECASE), "이 상품은 3단 풍속 조절을 지원합니다.", []),
    (re.compile(r"foldable|접이", re.IGNORECASE), "이 상품은 접이식 구조입니다.", []),
    (re.compile(r"4000\s?mah", re.IGNORECASE), "이 상품의 배터리 용량은 4000mAh입니다.", []),
    (re.compile(r"180\s?g|weight\s*180", re.IGNORECASE), "이 상품의 무게는 약 180g입니다.", []),
    (re.compile(r"white|화이트", re.IGNORECASE), "이 상품은 화이트 색상 옵션을 포함합니다.", []),
    (re.compile(r"silicone|실리콘", re.IGNORECASE), "이 상품은 실리콘 소재를 사용합니다.", []),
    (re.compile(r"bpa\s*free|BPA\s*프리", re.IGNORECASE), "이 상품은 BPA free 사양으로 표기되어 있습니다.", ["certification_review"]),
    (re.compile(r"microwave|전자레인지", re.IGNORECASE), "이 상품은 전자레인지 사용 가능으로 표기되어 있습니다.", []),
    (re.compile(r"dishwasher|식기세척", re.IGNORECASE), "이 상품은 식기세척기 사용 가능으로 표기되어 있습니다.", []),
    (re.compile(r"500\s?ml|capacity\s*500", re.IGNORECASE), "이 상품의 용량은 500ml입니다.", []),
    (re.compile(r"width\s*100|100\s?cm", re.IGNORECASE), "이 상품의 가로 길이는 100cm로 표기되어 있습니다.", []),
    (re.compile(r"height\s*50|50\s?cm", re.IGNORECASE), "이 상품의 높이는 50cm로 표기되어 있습니다.", []),
    (re.compile(r"depth\s*20|20\s?cm", re.IGNORECASE), "이 상품의 깊이는 20cm로 표기되어 있습니다.", []),
]


def extract_fact_candidates(sources: list[CollectedSource]) -> list[ExtractedFactCandidate]:
    candidates: list[ExtractedFactCandidate] = []

    for source in sources:
        if source.source in ["manual_text", "url"]:
            candidates.extend(_extract_from_manual_text(source))

        elif source.source == "image":
            if source.text.startswith("Uploaded image asset:"):
                candidates.append(
                    ExtractedFactCandidate(
                        fact_text=f"업로드된 이미지 '{source.text.replace('Uploaded image asset: ', '')}'를 상품 근거 이미지로 사용합니다.",
                        source_text=source.text,
                        source_asset_id=source.asset_id,
                        confidence=0.62,
                        extraction_source="image",
                    )
                )
            else:
                image_candidates = _extract_from_manual_text(source)
                if image_candidates:
                    for candidate in image_candidates:
                        candidates.append(
                            ExtractedFactCandidate(
                                fact_text=candidate.fact_text,
                                source_text=candidate.source_text,
                                source_asset_id=source.asset_id,
                                confidence=min(candidate.confidence, 0.72),
                                extraction_source="image",
                                needs_review=True,
                                risk_flags=candidate.risk_flags,
                            )
                        )
                else:
                    candidates.append(
                        ExtractedFactCandidate(
                            fact_text=f"업로드된 이미지 '{source.text[:60]}'를 상품 근거 이미지로 사용합니다.",
                            source_text=source.text,
                            source_asset_id=source.asset_id,
                            confidence=0.62,
                            extraction_source="image",
                        )
                    )

    return _dedupe_candidates(candidates)


def _extract_from_manual_text(source: CollectedSource) -> list[ExtractedFactCandidate]:
    candidates: list[ExtractedFactCandidate] = []
    for pattern, fact_text, risk_flags in _PATTERN_FACTS:
        match = pattern.search(source.text)
        if not match:
            continue
        candidates.append(
            ExtractedFactCandidate(
                fact_text=fact_text,
                source_text=_evidence_snippet(source.text, match.start(), match.end()),
                source_asset_id=None,
                confidence=0.82 if not risk_flags else 0.68,
                extraction_source=source.source,
                risk_flags=risk_flags,
            )
        )

    if not candidates and source.text.strip():
        candidates.append(
            ExtractedFactCandidate(
                fact_text=f"상품 설명에 '{source.text.strip()[:60]}' 정보가 포함되어 있습니다.",
                source_text=source.text.strip()[:160],
                source_asset_id=None,
                confidence=0.45,
                extraction_source=source.source,
                risk_flags=["low_confidence"],
            )
        )

    return candidates



def _evidence_snippet(text: str, start: int, end: int) -> str:
    snippet_start = max(0, start - 35)
    snippet_end = min(len(text), end + 35)
    return text[snippet_start:snippet_end].strip()


def _dedupe_candidates(candidates: list[ExtractedFactCandidate]) -> list[ExtractedFactCandidate]:
    seen: set[str] = set()
    unique: list[ExtractedFactCandidate] = []
    for candidate in candidates:
        key = _normalize(candidate.fact_text)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def normalize_fact_text(text: str) -> str:
    return _normalize(text)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).strip().lower()
