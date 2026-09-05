from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.models import PageSection, ProductFact, ProductPage
from src.services.commerce_policy import (
    CONFIRMED_FACT_STATUSES,
    is_final_spec_section_type,
)
from src.services.seller_fact_ingestion_service import SpecDisplay, display_seller_spec


LAYOUT_BY_SECTION: dict[str, str] = {
    "comparison": "comparison_cards",
    "detail_1": "benefit_cards",
    "guarantee": "spec_table",
    "hero": "hero_overlay",
    "specifications": "spec_table",
    "product_info": "spec_table",
    "product_information": "spec_table",
    "benefit_a": "benefit_cards",
    "benefit_b": "benefit_cards",
    "benefits_summary": "numeric_highlights",
    "hero_reemphasize": "comparison_cards",
    "features": "benefit_cards",
    "lifestyle_scene": "steps",
    "lifestyle": "steps",
    "detail_1": "benefit_cards",
    "detail_2": "numeric_highlights",
    "caution": "checklist",
    "cta": "checklist",
    "components": "checklist",
}

SELLER_PRODUCT_SOURCE_TYPES = {"uploaded", "self_shot", "sourced", "local_upscaled"}
NARRATIVE_SECTION_TYPES = {
    "comparison",
    "detail_1",
    "detail_2",
    "benefit_a",
    "benefit_b",
    "hero_reemphasize",
    "features",
}
TEXT_ONLY_NARRATIVE_SECTION_TYPES = {
    "problem",
    "target_customer",
    "caution",
    "cta",
    "overall_summary",
}


def _section_facts(section: PageSection, db: Session) -> list[ProductFact]:
    """Return only confirmed facts explicitly linked to the section when set."""
    query = db.query(ProductFact).filter(
        ProductFact.project_id == section.page.project_id,
        ProductFact.verification_status.in_(CONFIRMED_FACT_STATUSES),
    )
    fact_ids = list(section.associated_fact_ids or [])
    if fact_ids:
        query = query.filter(ProductFact.id.in_(fact_ids))
    elif (section.visual_payload or {}).get("facts_intentionally_empty"):
        return []
    return query.all()


def _fact_body(fact: ProductFact) -> str:
    if fact.normalized_value not in (None, ""):
        value = str(fact.normalized_value).strip()
        if fact.field_key == "charging_port" and value.replace("-", "").lower() in {"typec", "usbc"}:
            value = "Type-C"
        unit = str(fact.normalized_unit or "").strip()
        return f"{value}{unit}"
    return (fact.source_text or fact.fact_text or "").strip()


_NUMERIC_VALUE_PATTERN = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:%|mAh|Pa|kg|g|mm|cm|ml|Hz|W|V|[A-Za-z]+|분|시간|초|회|단계|일|개월|년|개|가지|배)?"
)


def _is_numeric_seller_spec(fact: ProductFact) -> bool:
    """True when a fact is a direct seller numeric specification only."""
    return (
        fact.extraction_source == "seller_input"
        and bool(_NUMERIC_VALUE_PATTERN.fullmatch(_fact_body(fact)))
    )


def _seller_action(section: PageSection) -> dict[str, Any]:
    section_name = section.title or section.role or section.section_type
    return {
        "kind": "seller_action",
        "text": f"‘{section_name}’에 사용할 확인된 상품 정보 또는 상세 사진을 추가해 주세요.",
        "verification_status": "action_required",
        "source_fact_ids": [],
    }


def _numeric_highlights(facts: list[ProductFact]) -> list[dict[str, Any]]:
    highlights: list[dict[str, Any]] = []
    for fact in facts:
        text = _fact_body(fact)
        match = _NUMERIC_VALUE_PATTERN.search(text)
        if not match:
            continue
        highlights.append(
            {
                "label": fact.fact_text[:40],
                "value": match.group(0).strip(),
                "body": text[:100],
                "verification_status": "confirmed",
                "source_fact_ids": [fact.id],
            }
        )
    return highlights


def _hero_spec_label(fact: ProductFact) -> str:
    text = fact.fact_text or ""
    if "무게" in text:
        return "무게"
    if "배터리" in text:
        return "배터리"
    if "시간" in text:
        return "사용 시간"
    if "흡입력" in text:
        return "흡입력"
    return display_seller_spec(
        fact.fact_text,
        _fact_body(fact),
        fact.verification_status,
    ).label


def _refresh_hero_numeric_spec_line(page: ProductPage, db: Session) -> int:
    """Turn a raw comma-separated seller spec line into a readable HERO bullet.

    Page copy can contain a direct input such as ``260g, 800mAh, 10``. Once
    confirmed facts are present, render the unit-preserving values with labels
    instead of leaving an ambiguous bare number in the sales copy.
    """
    hero = next((section for section in page.sections if section.section_type == "hero"), None)
    if hero is None or not hero.body_copy:
        return 0
    numeric_facts = [
        fact
        for fact in _section_facts(hero, db)
        if _NUMERIC_VALUE_PATTERN.fullmatch(_fact_body(fact))
    ]
    if not numeric_facts:
        return 0

    raw_lines = hero.body_copy.splitlines()
    first_bullet_index = next((index for index, line in enumerate(raw_lines) if line.strip().startswith("-")), None)
    if first_bullet_index is None:
        return 0

    raw_bullet = raw_lines[first_bullet_index].lstrip("- ").strip()
    # Only replace an existing numeric list. Marketing copy in other formats
    # should stay authored as-is.
    numeric_values = [match.group(0) for match in _NUMERIC_VALUE_PATTERN.finditer(raw_bullet)]
    if not numeric_values:
        return 0

    normalized_numbers = {re.sub(r"[^0-9.]", "", value) for value in numeric_values}
    fact_numbers = {re.sub(r"[^0-9.]", "", _fact_body(fact)) for fact in numeric_facts}
    existing_labels = {_hero_spec_label(fact) for fact in numeric_facts}
    is_existing_spec_line = any(label in raw_bullet for label in existing_labels)
    if not fact_numbers.issubset(normalized_numbers) and not is_existing_spec_line:
        return 0

    formatted = " · ".join(f"{_hero_spec_label(fact)} {_fact_body(fact)}" for fact in numeric_facts)
    replacement = f"- {formatted}"
    if raw_lines[first_bullet_index] == replacement:
        return 0
    raw_lines[first_bullet_index] = replacement
    hero.body_copy = "\n".join(raw_lines)
    return 1


def _apply_fact_display_labels(
    payload: dict[str, Any], facts: list[ProductFact]
) -> dict[str, Any]:
    """Render concise labels and honest provenance for fact-backed graphics."""
    normalized = dict(payload)
    facts_by_id = {fact.id: fact for fact in facts}

    def display_for(item: dict[str, Any]):
        fact_ids = item.get("source_fact_ids") or []
        fact = facts_by_id.get(fact_ids[0]) if fact_ids else None
        if not fact:
            return None
        display = display_seller_spec(
            fact.fact_text, _fact_body(fact), fact.verification_status
        )
        fact_text = (fact.fact_text or "").strip()
        if ":" in fact_text:
            display = SpecDisplay(
                label=fact_text.split(":", 1)[0].strip(),
                value=display.value,
                provenance_label=display.provenance_label,
            )
        return display

    for key in ("cards", "highlights", "table_rows", "steps", "items"):
        entries = normalized.get(key)
        if not isinstance(entries, list):
            continue
        rewritten: list[dict[str, Any]] = []
        for raw_item in entries:
            if not isinstance(raw_item, dict):
                rewritten.append(raw_item)
                continue
            item = dict(raw_item)
            display = display_for(item)
            if display:
                item["provenance_label"] = display.provenance_label
                if key == "highlights":
                    item.update(label=display.label, value=display.value, body=display.provenance_label)
                elif key == "table_rows":
                    item.update(label=display.label, value=display.value)
                elif key in {"cards", "steps"}:
                    item.update(title=display.label, body=display.value)
                elif key == "items":
                    item["text"] = f"{display.label}: {display.value}"
            rewritten.append(item)
        normalized[key] = rewritten
    return normalized


class BackfillReport(BaseModel):
    project_id: str
    updated: int


def build_grounded_html_payload(section: PageSection, db: Session) -> dict[str, Any]:
    """Build an HTML visual payload using confirmed facts only."""
    layout = LAYOUT_BY_SECTION.get(section.section_type, "image_text")

    confirmed_facts = _section_facts(section, db)

    if layout in ("comparison_cards", "benefit_cards"):
        # Weight, battery capacity, and duration are useful in one summary
        # visual or a spec table. Repeating them as generic marketing benefits
        # across several sections makes the page noisier without adding proof.
        card_facts = (
            confirmed_facts
            if section.section_type == "features"
            else [fact for fact in confirmed_facts if not _is_numeric_seller_spec(fact)]
        )
        cards = []
        for fact in card_facts:
            cards.append(
                {
                    "title": fact.fact_text[:40],
                    "body": _fact_body(fact)[:100],
                    "tone": "positive",
                    "verification_status": "confirmed",
                    "source_fact_ids": [fact.id],
                }
            )
        return {
            "layout_variant": layout,
            "cards": cards,
        }

    if layout == "numeric_highlights":
        highlights = _numeric_highlights(confirmed_facts)
        if highlights:
            return {"layout_variant": layout, "highlights": highlights}
        # A section remains useful even when the confirmed facts contain no
        # number, but it must not invent a numeric claim.
        return build_grounded_html_payload_for_layout("benefit_cards", confirmed_facts)

    if layout == "spec_table":
        rows = []
        for fact in confirmed_facts:
            rows.append(
                {
                    "label": fact.fact_text[:40],
                    "value": _fact_body(fact)[:100],
                    "verification_status": "confirmed",
                    "source_fact_ids": [fact.id],
                }
            )
        return {
            "layout_variant": layout,
            "table_rows": rows,
        }

    if layout == "steps":
        return {
            "layout_variant": layout,
            "steps": [
                {
                    "step": index + 1,
                    "title": fact.fact_text[:40],
                    "body": _fact_body(fact)[:100],
                    "verification_status": "confirmed",
                    "source_fact_ids": [fact.id],
                }
                for index, fact in enumerate(confirmed_facts[:4])
            ],
        }

    if layout == "checklist":
        return {
            "layout_variant": layout,
            "items": [
                {
                    "text": fact.fact_text[:100],
                    "verification_status": "confirmed",
                    "source_fact_ids": [fact.id],
                }
                for fact in confirmed_facts[:5]
            ],
        }

    return {"layout_variant": layout}


def build_grounded_html_payload_for_layout(
    layout: str, confirmed_facts: list[ProductFact]
) -> dict[str, Any]:
    """Build a safe fallback payload for a known layout without a section."""
    if layout != "benefit_cards":
        return {"layout_variant": layout}
    return {
        "layout_variant": "benefit_cards",
        "cards": [
            {
                "title": fact.fact_text[:40],
                "body": _fact_body(fact)[:100],
                "tone": "positive",
                "verification_status": "confirmed",
                "source_fact_ids": [fact.id],
            }
            for fact in confirmed_facts
        ],
    }


def _is_payload_complete(section: PageSection) -> bool:
    """Check if the visual payload has all required fields for its kind."""
    payload = section.visual_payload or {}
    if payload.get("facts_intentionally_empty") and payload.get("strategy") == "text_only":
        return True
    from src.services.page_visual_contract import validate_visual
    visual = {
        "visual_kind": section.visual_kind,
        "visual_payload": payload,
        "image_asset_id": section.image_asset_id,
    }
    return len(validate_visual(visual)) == 0


def _has_distinct_section_photo(section: PageSection, db: Session) -> bool:
    """Keep a separately uploaded usage/detail photograph; replace repeats."""
    if not section.image_asset_id:
        return False
    from src.db.models import Asset

    asset = db.query(Asset).filter(Asset.id == section.image_asset_id).first()
    # A legacy/external asset cannot safely be identified as a repeated HERO
    # image, so preserve it rather than unexpectedly removing it.
    if not asset:
        return True
    if asset.source_type not in SELLER_PRODUCT_SOURCE_TYPES:
        return False
    return asset.asset_role in {"usage_scene", "product_detail", "components"}


def _upsert_seller_checklist(
    page: ProductPage, missing_sections: list[PageSection], db: Session
) -> int:
    """Expose missing inputs as an actionable seller checklist, not a blank body."""
    checklist_section = next((section for section in page.sections if section.section_type == "pre_purchase"), None)
    if not missing_sections:
        # Remove only an automatically generated seller-action checklist. A
        # deliberately authored pre-purchase section must remain untouched.
        existing_items = (checklist_section.visual_payload or {}).get("items", []) if checklist_section else []
        is_auto_checklist = bool(existing_items) and all(
            item.get("kind") == "seller_action" for item in existing_items if isinstance(item, dict)
        )
        if checklist_section and checklist_section.is_visible and is_auto_checklist:
            checklist_section.is_visible = False
            return 1
        return 0
    if checklist_section is None:
        checklist_section = PageSection(
            page_id=page.id,
            section_type="pre_purchase",
            title="판매자 확인 체크리스트",
            body_copy="정확한 상세페이지를 위해 아래 정보를 확인해 주세요.",
            sort_order=max((section.sort_order for section in page.sections), default=-1) + 1,
            is_visible=True,
        )
        db.add(checklist_section)
        page.sections.append(checklist_section)

    items = [_seller_action(section) for section in missing_sections]
    if not items:
        return 0

    payload = {"layout_variant": "checklist", "items": items}
    if (
        checklist_section.visual_kind != "html_graphic"
        or checklist_section.image_asset_id is not None
        or checklist_section.visual_payload != payload
        or not checklist_section.is_visible
    ):
        checklist_section.image_asset_id = None
        checklist_section.visual_kind = "html_graphic"
        checklist_section.visual_payload = payload
        checklist_section.is_visible = True
        return 1
    return 0


def _ensure_final_specifications_are_last(page: ProductPage) -> int:
    """Keep every visible seller-action section before the final specs.

    Seller checklists can be added after the planning draft has already placed
    its specifications section. Appending such a checklist made an otherwise
    valid page fail the commerce rule that specifications/notices are the final
    visible content. Preserve the existing relative order and move only final
    specification sections to the end.
    """
    ordered = sorted(page.sections, key=lambda section: section.sort_order)
    final_specs = [
        section
        for section in ordered
        if is_final_spec_section_type(section.section_type)
    ]
    if not final_specs:
        return 0

    normalized = [
        section
        for section in ordered
        if not is_final_spec_section_type(section.section_type)
    ] + final_specs
    updated = 0
    for sort_order, section in enumerate(normalized):
        if section.sort_order != sort_order:
            section.sort_order = sort_order
            updated += 1
    return updated


def apply_html_graphic_section_policy(page: ProductPage, db: Session) -> int:
    """Replace repeated/no-photo body visuals with fact-grounded graphics.

    A manually supplied secondary usage/detail photo remains intact.  All other
    mapped body sections use HTML graphics, so a single HERO product photo is
    never stretched across the whole page.
    """
    updated = 0
    missing_sections: list[PageSection] = []
    for section in page.sections:
        # UX-2 Mock pages intentionally use HTML-first information sections.
        # They already carry a valid visual contract and must not be converted
        # into hidden "missing photo" sections by the legacy fact-card backfill.
        if (section.visual_payload or {}).get("ux2_mock_output"):
            continue
        if (
            section.section_type in TEXT_ONLY_NARRATIVE_SECTION_TYPES
            and
            (section.visual_payload or {}).get("facts_intentionally_empty")
            and (section.visual_payload or {}).get("strategy") == "text_only"
        ):
            # Problem, target, caution, and similar narrative copy may be
            # intentionally fact-free. Keep its authored text visible without
            # manufacturing a graphic from unrelated specifications.
            # Text-only narrative sections still need a valid visual contract
            # for preview/export parity. ``image_text`` renders the authored
            # copy without inventing a fact-backed card or requiring an image.
            payload = dict(section.visual_payload or {})
            payload["layout_variant"] = "image_text"
            if (
                section.visual_kind != "html_graphic"
                or section.image_asset_id is not None
                or section.visual_payload != payload
            ):
                section.visual_kind = "html_graphic"
                section.image_asset_id = None
                section.visual_payload = payload
                updated += 1
            continue
        if section.section_type in {"hero", "pre_purchase"} or section.section_type not in LAYOUT_BY_SECTION:
            continue
        if _has_distinct_section_photo(section, db):
            continue

        section_facts = _section_facts(section, db)
        # With only direct numerical specifications, a narrative benefit or
        # comparison cannot be substantiated. Hide it cleanly and reserve the
        # specs for the dedicated numeric summary/product-info sections.
        if (
            section.section_type in NARRATIVE_SECTION_TYPES
            and section.section_type != "features"
            and section_facts
            and all(_is_numeric_seller_spec(fact) for fact in section_facts)
        ):
            if section.is_visible:
                section.is_visible = False
                updated += 1
            continue

        payload = _apply_fact_display_labels(
            build_grounded_html_payload(section, db), section_facts
        )
        layout = payload.get("layout_variant")
        content = (
            payload.get("cards")
            or payload.get("highlights")
            or payload.get("table_rows")
            or payload.get("steps")
            or payload.get("items")
        )
        if not content:
            # No confirmed fact means no sales claim. Hide this optional body
            # block instead of exporting an empty panel or a made-up claim.
            if section.is_visible:
                section.is_visible = False
                updated += 1
            missing_sections.append(section)
            continue

        if (
            section.visual_kind != "html_graphic"
            or section.image_asset_id is not None
            or section.visual_payload != payload
            or not section.is_visible
        ):
            section.image_asset_id = None
            section.visual_kind = "html_graphic"
            section.visual_payload = payload
            section.is_visible = True
            updated += 1
    updated += _upsert_seller_checklist(page, missing_sections, db)
    updated += _ensure_final_specifications_are_last(page)
    return updated


def backfill_page_visuals(db: Session, project_id: str) -> BackfillReport:
    """Idempotently backfill visual_kind and visual_payload for legacy PageSection rows.

    Fills both missing visual_kind AND incomplete visual_payload (cards, rows, etc.).
    """
    page = (
        db.query(ProductPage)
        .filter(ProductPage.project_id == project_id)
        .order_by(ProductPage.created_at.asc(), ProductPage.id.asc())
        .first()
    )
    if not page:
        return BackfillReport(project_id=project_id, updated=0)

    # The page can already be present in the SQLAlchemy identity map while a
    # caller has just inserted a new section by page_id. Reload the collection
    # so the visual policy covers that section in the same request as well.
    db.flush()
    # Compatibility for projects created before direct seller specs were
    # stored as ProductFacts.  The original form input is retained on the run,
    # so numeric values such as 260g / 10분 / 800mAh can still create grounded
    # visuals rather than being treated as missing information.
    from src.services.seller_fact_ingestion_service import persist_saved_agent_run_seller_specs
    persist_saved_agent_run_seller_specs(db, project_id)
    db.flush()
    db.expire(page, ["sections"])

    updated = _refresh_hero_numeric_spec_line(page, db)
    updated += apply_html_graphic_section_policy(page, db)
    for section in page.sections:
        if not section.is_visible:
            continue
        if section.visual_kind and _is_payload_complete(section):
            continue  # already fully backfilled

        existing_payload = dict(section.visual_payload or {})
        if section.image_asset_id:
            section.visual_kind = "image"
            section.visual_payload = {
                "layout_variant": "hero_overlay" if section.section_type == "hero" else "image_text",
                **{
                    key: existing_payload[key]
                    for key in (
                        "low_quality_hero_confirmed",
                        "ux2c_selection_state",
                        "asset_id",
                    )
                    if key in existing_payload
                },
            }
        else:
            section.visual_kind = "html_graphic"
            section.visual_payload = _apply_fact_display_labels(
                build_grounded_html_payload(section, db), _section_facts(section, db)
            )

        updated += 1

    # Ensure Sprint 2 classification/representative metadata exists before
    # Sprint 3 evaluates a legacy HERO.  The result page requests page/assets
    # concurrently, so relying on the assets endpoint would create a race.
    from src.services.image_asset_inspector import backfill_project_asset_metadata
    backfill_project_asset_metadata(project_id, db)

    # Sprint 3: a legacy default HERO can safely become a composed product
    # visual.  Custom image layouts remain compatible and are not overwritten.
    from src.services.hero_composition import apply_composed_product_hero
    if apply_composed_product_hero(
        page,
        db,
        getattr(page.project, "selected_style", None) if page.project else None,
    ):
        updated += 1

    db.commit()
    return BackfillReport(project_id=project_id, updated=updated)
