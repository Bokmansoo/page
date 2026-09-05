"""V2 commerce-studio policy primitives shared by API, readiness and export.

The policy deliberately separates where an image came from (``source_type``)
from whether it is allowed to appear in a seller's final commercial output
(``usage_status``).  Supplier captures remain useful references, but are not
final-page assets by default.
"""

from __future__ import annotations

from collections.abc import Iterable


ASSET_USAGE_STATUSES = frozenset(
    {"reference_only", "seller_owned", "ai_generated", "derived_graphic", "blocked"}
)
FINAL_OUTPUT_ASSET_STATUSES = frozenset(
    {"seller_owned", "ai_generated", "derived_graphic"}
)

FACT_STATUSES = frozenset(
    {
        "extracted",
        "source_confirmed",
        "seller_confirmed",
        "needs_review",
        "conflicted",
        "rejected",
    }
)
# Existing projects created before V2 keep working while they are gradually
# migrated through the fact-review screen.
LEGACY_FACT_STATUSES = frozenset({"unknown", "confirmed", "needs_revision"})
CONFIRMED_FACT_STATUSES = frozenset({"source_confirmed", "seller_confirmed", "confirmed"})

REFERENCE_SOURCE_TYPES = frozenset({"sourced", "url-extracted", "url-imported"})
SELLER_OWNED_SOURCE_TYPES = frozenset({"uploaded", "self_shot"})
AI_SOURCE_TYPES = frozenset(
    {"ai_generated", "ai-generated", "generated_image", "mock-generated", "real-generated"}
)
DERIVED_SOURCE_TYPES = frozenset({"html-graphic"})
FINAL_SPEC_SECTION_TYPES = frozenset(
    {"specifications", "final_specifications", "product_specifications", "product_info", "product_information"}
)


def initial_asset_usage_status(source_type: str | None) -> str:
    """Infer a safe initial status for newly persisted assets."""
    normalized = (source_type or "").strip().lower()
    if normalized in REFERENCE_SOURCE_TYPES:
        return "reference_only"
    if normalized in AI_SOURCE_TYPES:
        return "ai_generated"
    if normalized in DERIVED_SOURCE_TYPES:
        return "derived_graphic"
    if normalized in SELLER_OWNED_SOURCE_TYPES:
        return "seller_owned"
    if normalized.startswith("exported") or normalized in {"missing-image", "regeneration-required"}:
        return "blocked"
    return "blocked"


def resolved_asset_usage_status(asset: object) -> str:
    """Return the persisted V2 status, with a conservative legacy fallback."""
    raw_status = (getattr(asset, "usage_status", None) or "").strip().lower()
    if raw_status in ASSET_USAGE_STATUSES:
        return raw_status
    return initial_asset_usage_status(getattr(asset, "source_type", None))


def is_asset_final_output_eligible(asset: object) -> bool:
    return resolved_asset_usage_status(asset) in FINAL_OUTPUT_ASSET_STATUSES


def is_confirmed_fact_status(status: str | None) -> bool:
    return (status or "").strip().lower() in CONFIRMED_FACT_STATUSES


def normalize_legacy_fact_status(status: str | None, *, seller_origin: bool = False) -> str:
    normalized = (status or "").strip().lower()
    if normalized == "confirmed":
        return "seller_confirmed" if seller_origin else "source_confirmed"
    if normalized == "unknown":
        return "extracted"
    if normalized == "needs_revision":
        return "needs_review"
    return normalized if normalized in FACT_STATUSES else "needs_review"


def fact_status_requires_review(status: str | None) -> bool:
    return normalize_legacy_fact_status(status) in {"extracted", "needs_review", "conflicted"}


def is_final_spec_section_type(section_type: str | None) -> bool:
    return (section_type or "").strip().lower() in FINAL_SPEC_SECTION_TYPES


def has_final_spec_section(sections: Iterable[object]) -> bool:
    return any(
        getattr(section, "is_visible", True)
        and is_final_spec_section_type(getattr(section, "section_type", None))
        for section in sections
    )


def final_spec_is_last(sections: Iterable[object]) -> bool:
    """Visible final-spec sections, when present, must end the page."""
    visible = sorted(
        (section for section in sections if getattr(section, "is_visible", True)),
        key=lambda section: getattr(section, "sort_order", 0),
    )
    indices = [
        index
        for index, section in enumerate(visible)
        if is_final_spec_section_type(getattr(section, "section_type", None))
    ]
    return not indices or indices[-1] == len(visible) - 1 and indices == list(range(indices[0], len(visible)))


def fact_status_is_allowed(status: str | None) -> bool:
    return (status or "").strip().lower() in FACT_STATUSES | LEGACY_FACT_STATUSES
