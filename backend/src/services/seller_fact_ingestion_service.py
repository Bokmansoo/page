"""Persist and present seller-entered product specifications safely.

The intake text is first-party input, but it is still important to preserve
units and labels accurately.  A value such as ``8W`` is a power rating, not a
voltage; a value such as ``40×17×15cm`` is a three-dimensional size, not just
``15cm``.  This module keeps those distinctions through to the final spec
table.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.db.models import AgentRun, ProductFact, ProductPage
from src.services.fact_extractor import normalize_fact_text


_DIMENSION_PATTERN = re.compile(
    r"(?P<value>\d+(?:\.\d+)?\s*[x×*]\s*\d+(?:\.\d+)?\s*[x×*]\s*\d+(?:\.\d+)?)\s*(?P<unit>cm|mm)",
    re.IGNORECASE,
)
_ELECTRICAL_INPUT_PATTERN = re.compile(
    r"(?P<kind>DC|AC)\s*(?P<voltage>\d+(?:\.\d+)?)\s*V\s*(?P<current>\d+(?:\.\d+)?)\s*A",
    re.IGNORECASE,
)
_SPEC_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?P<value>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>mAh|Ah|kg|g|분|시간|초|Pa|W|V|A|Hz|ml|mL|L|cm|mm|℃|°C|%)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpecDisplay:
    label: str
    value: str
    provenance_label: str


def _normalize_value(value: str) -> str:
    return re.sub(r"\s*[x*]\s*", " × ", value.strip()).replace("×", " × ").replace("  ", " ")


def _fact_label(unit: str) -> str:
    normalized = unit.lower()
    if normalized in {"g", "kg"}:
        return "무게"
    if normalized in {"mah", "ah"}:
        return "배터리 용량"
    if unit in {"분", "시간", "초"}:
        return "사용 시간"
    if normalized == "pa":
        return "흡입력"
    if normalized == "w":
        return "정격 소비전력"
    if normalized == "v":
        return "정격 입력 전압"
    if normalized == "a":
        return "정격 입력 전류"
    if normalized == "hz":
        return "정격 주파수"
    if normalized in {"ml", "l"}:
        return "용량"
    if normalized in {"cm", "mm"}:
        return "제품 크기"
    if unit in {"℃", "°C"}:
        return "표기 온도"
    if unit == "%":
        return "수치 정보"
    return "제품 사양"


def _topic_particle(label: str) -> str:
    last = label[-1]
    codepoint = ord(last)
    has_final_consonant = 0xAC00 <= codepoint <= 0xD7A3 and (codepoint - 0xAC00) % 28 != 0
    return "은" if has_final_consonant else "는"


def _make_fact(label: str, value: str) -> tuple[str, str]:
    source_text = value.strip()
    return f"판매자 제공 사양: {label}{_topic_particle(label)} {source_text}입니다.", source_text


def extract_confirmed_seller_specs(texts: Iterable[str | None]) -> list[tuple[str, str]]:
    """Extract exact numeric specifications without inferring missing units."""
    specs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        covered_ranges: list[tuple[int, int]] = []

        for match in _ELECTRICAL_INPUT_PATTERN.finditer(text):
            value = f"{match.group('kind').upper()} {match.group('voltage')}V {match.group('current')}A"
            fact_text, source_text = _make_fact("정격 입력", value)
            key = normalize_fact_text(fact_text)
            if key not in seen:
                seen.add(key)
                specs.append((fact_text, source_text))
            covered_ranges.append(match.span())

        for match in _DIMENSION_PATTERN.finditer(text):
            value = f"{_normalize_value(match.group('value'))}{match.group('unit').lower()}"
            fact_text, source_text = _make_fact("제품 크기", value)
            key = normalize_fact_text(fact_text)
            if key not in seen:
                seen.add(key)
                specs.append((fact_text, source_text))
            covered_ranges.append(match.span())

        for match in _SPEC_PATTERN.finditer(text):
            if any(start <= match.start() and match.end() <= end for start, end in covered_ranges):
                continue
            value = f"{match.group('value')}{match.group('unit')}"
            fact_text, source_text = _make_fact(_fact_label(match.group('unit')), value)
            key = normalize_fact_text(fact_text)
            if key not in seen:
                seen.add(key)
                specs.append((fact_text, source_text))
    return specs


def display_seller_spec(fact_text: str | None, source_text: str | None, verification_status: str | None) -> SpecDisplay:
    """Return a concise label/value for cards and final specification tables.

    Existing projects may contain the older generic fact labels.  Re-parsing
    the exact ``source_text`` makes their display correct without rewriting a
    seller's stored history.
    """
    raw_value = (source_text or "").strip()
    raw_fact = (fact_text or "").strip()
    probe = raw_value or raw_fact

    input_match = _ELECTRICAL_INPUT_PATTERN.search(probe)
    dimension_match = _DIMENSION_PATTERN.search(probe)
    scalar_match = _SPEC_PATTERN.search(probe)
    if input_match:
        label = "정격 입력"
        value = f"{input_match.group('kind').upper()} {input_match.group('voltage')}V {input_match.group('current')}A"
    elif dimension_match:
        label = "제품 크기"
        value = f"{_normalize_value(dimension_match.group('value'))}{dimension_match.group('unit').lower()}"
    elif scalar_match:
        label = _fact_label(scalar_match.group('unit'))
        value = f"{scalar_match.group('value')}{scalar_match.group('unit')}"
    else:
        label = raw_fact[:40] or "제품 정보"
        value = raw_value or raw_fact[:100]

    status = (verification_status or "").lower()
    provenance_label = {
        "seller_confirmed": "판매자 제공 정보",
        "source_confirmed": "출처 확인 정보",
        "confirmed": "확인된 정보",
    }.get(status, "확인 필요 정보")
    return SpecDisplay(label=label, value=value, provenance_label=provenance_label)


def _is_richer_seller_spec(replacement: ProductFact, legacy: ProductFact) -> bool:
    """Return whether ``replacement`` preserves a legacy value more precisely.

    Older projects stored each number independently (for example ``15cm``),
    even when the seller's input also contained the complete dimension
    ``40 × 17 × 15cm``.  The newer parser retains that context.  This helper
    lets existing page section links move to the more precise fact without
    deleting the original saved history.
    """
    replacement_value = (replacement.source_text or "").replace(" ", "").lower()
    legacy_value = (legacy.source_text or "").replace(" ", "").lower()
    if not replacement_value or not legacy_value:
        return False

    replacement_is_new = (replacement.fact_text or "").startswith("판매자 제공 사양:")
    legacy_is_new = (legacy.fact_text or "").startswith("판매자 제공 사양:")
    if not replacement_is_new or legacy_is_new:
        return False

    replacement_dimension = _DIMENSION_PATTERN.search(replacement.source_text or "")
    if replacement_dimension and legacy_value in replacement_value:
        return True

    replacement_input = _ELECTRICAL_INPUT_PATTERN.search(replacement.source_text or "")
    legacy_display = display_seller_spec(
        legacy.fact_text, legacy.source_text, legacy.verification_status
    )
    if replacement_input and legacy_display.label == "정격 입력 전압" and legacy_value in replacement_value:
        return True

    replacement_display = display_seller_spec(
        replacement.fact_text, replacement.source_text, replacement.verification_status
    )
    return (
        replacement_display.label == legacy_display.label
        and replacement_display.value.replace(" ", "").lower() == legacy_value
    )


def relink_legacy_seller_specs(db: Session, project_id: str) -> int:
    """Point legacy page sections at richer seller-spec facts when available."""
    facts = db.query(ProductFact).filter(ProductFact.project_id == project_id).all()
    current_facts = [
        fact
        for fact in facts
        if (fact.fact_text or "").startswith("판매자 제공 사양:")
        and fact.verification_status == "seller_confirmed"
    ]
    legacy_facts = [
        fact
        for fact in facts
        if fact.extraction_source == "seller_input"
        and not (fact.fact_text or "").startswith("판매자 제공 사양:")
    ]
    replacements = {
        fact.id: next(
            (candidate for candidate in current_facts if _is_richer_seller_spec(candidate, fact)),
            None,
        )
        for fact in legacy_facts
    }
    replacements = {
        legacy_id: replacement.id
        for legacy_id, replacement in replacements.items()
        if replacement is not None
    }
    if not replacements:
        return 0

    updated = 0
    pages = db.query(ProductPage).filter(ProductPage.project_id == project_id).all()
    for page in pages:
        for section in page.sections:
            fact_ids = list(section.associated_fact_ids or [])
            relinked = [replacements.get(fact_id, fact_id) for fact_id in fact_ids]
            # Do not keep the same fact twice when a section was already
            # partially migrated.
            deduplicated = list(dict.fromkeys(relinked))
            if deduplicated != fact_ids:
                section.associated_fact_ids = deduplicated
                updated += 1
    return updated


def persist_confirmed_seller_specs(
    db: Session,
    project_id: str,
    texts: Iterable[str | None],
) -> list[ProductFact]:
    existing = {
        normalize_fact_text(fact.fact_text)
        for fact in db.query(ProductFact).filter(ProductFact.project_id == project_id).all()
    }
    created: list[ProductFact] = []
    for fact_text, source_text in extract_confirmed_seller_specs(texts):
        normalized = normalize_fact_text(fact_text)
        if normalized in existing:
            continue
        fact = ProductFact(
            project_id=project_id,
            fact_text=fact_text,
            source_text=source_text,
            verification_status="seller_confirmed",
            extraction_source="seller_input",
            provider="seller_input",
            confidence=1.0,
            needs_review=False,
            risk_flags=[],
        )
        db.add(fact)
        created.append(fact)
        existing.add(normalized)
    return created


def persist_saved_agent_run_seller_specs(db: Session, project_id: str) -> list[ProductFact]:
    """Backfill direct seller specifications from compatible run snapshots."""
    texts: list[str | None] = []
    runs = db.query(AgentRun).filter(AgentRun.project_id == project_id).all()
    for run in runs:
        snapshot = run.input_snapshot or {}
        texts.extend(
            [
                snapshot.get("description"),
                snapshot.get("freeform_input"),
                *(snapshot.get("selling_points") or []),
            ]
        )
    created = persist_confirmed_seller_specs(db, project_id, texts)
    # The first V2 render may already have linked older, abbreviated facts.
    # Update those links as soon as the richer parser-created facts exist.
    relink_legacy_seller_specs(db, project_id)
    return created
