"""Sprint 3 fact normalization, evidence, conflict and generation snapshots."""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Iterable

from sqlalchemy.orm import Session

from src.db.models import (
    AssetInspectionRecord,
    DetailPageVersion,
    FactEvidence,
    FactHistory,
    FactSnapshot,
    PageSection,
    PageVersion,
    ProductFact,
    ProductProject,
)

EXTRACTOR_VERSION = "evidence-board-v2"
APPROVED_STATUSES = {"source_confirmed", "seller_confirmed"}
RISK_WORDS = ("치료", "완치", "인증", "친환경", "저소음", "수면 개선", "경추 보호", "효능")
SCOPE_TOKENS = {
    "master_carton": ("外箱", "외박스", "carton", "ctn", "6台装", "6개입", "毛重", "gross weight"),
    "individual_package": ("彩盒", "개별 포장", "individual package", "소포장"),
}
PRODUCT_SCOPE_TOKENS = ("제품", "본체", "product", "机身")


@dataclass(frozen=True)
class NormalizedCandidate:
    field_key: str
    category: str
    value: str
    unit: str | None
    scope: str
    source_text: str
    needs_review: bool = False
    model_option: str | None = None


def _nearby_scope(text: str, start: int, end: int) -> str:
    probe = f"{text[max(0, start - 80):start]} {text[end:min(len(text), end + 30)]}".lower()
    nearest: tuple[int, str] | None = None
    for scope, tokens in SCOPE_TOKENS.items():
        for token in tokens:
            position = probe.rfind(token.lower())
            if position >= 0 and (nearest is None or position > nearest[0]):
                nearest = (position, scope)
    return nearest[1] if nearest else "product"


def _model_option(text: str, start: int, end: int) -> str | None:
    probe = text[max(0, start - 60):min(len(text), end + 60)]
    models = list(dict.fromkeys(re.findall(r"\bYL[-\s]?T\d{1,3}\b", probe, re.IGNORECASE)))
    return models[0].upper().replace(" ", "-") if len(models) == 1 else None


def _project_model_option(project: ProductProject) -> str | None:
    """Return a project-wide model only when the seller selected exactly one.

    Generic marketplace attributes for a single-model project belong to that
    selected model (YL-T02 in the acceptance case). Multi-model projects remain
    common/unknown so we never merge option-specific specifications blindly.
    """
    bundle = (project.intake_snapshot or {}).get("input_bundle") or {}
    probe = " ".join(str(value or "") for value in (project.name, bundle.get("model_options")))
    models = list(dict.fromkeys(match.upper().replace(" ", "-") for match in re.findall(r"\bYL[-\s]?T0[12]\b", probe, re.IGNORECASE)))
    return models[0] if len(models) == 1 else None


def _canonical_value(field_key: str, value: str, unit: str | None) -> tuple[str, str | None]:
    try:
        numeric = float(value.replace(",", ""))
    except (TypeError, ValueError):
        numeric = None
    lowered = (unit or "").lower()
    if field_key == "weight" and numeric is not None:
        grams = numeric * 1000 if lowered == "kg" else numeric
        return (str(int(grams)) if grams.is_integer() else f"{grams:g}", "g")
    if field_key == "battery_capacity" and numeric is not None and lowered == "ah":
        mah = numeric * 1000
        return (str(int(mah)) if mah.is_integer() else f"{mah:g}", "mAh")
    if field_key == "product_size" and lowered == "mm":
        dimensions = [float(part.strip()) / 10 for part in value.split("×")]
        normalized = " × ".join(str(int(part)) if part.is_integer() else f"{part:g}" for part in dimensions)
        return normalized, "cm"
    return value, unit


def normalize_candidates(text: str) -> list[NormalizedCandidate]:
    """Extract explicit facts while preserving source, model and packaging level."""
    compact = " ".join((text or "").split())
    if not compact:
        return []
    candidates: list[NormalizedCandidate] = []
    rules = [
        ("model_name", "model", r"(?:型号|型號|model(?:\s*(?:no|number))?|모델명?)\s*[:：]?\s*([A-Za-z]{1,8}[-\s]?[A-Za-z0-9-]{2,20})", lambda m: (m.group(1).upper().replace(" ", "-"), None)),
        ("rated_input", "electrical", r"(?:DC|直流)\s*([0-9.]+)\s*V\s*([0-9.]+)\s*A", lambda m: (f"DC {m.group(1)}V {m.group(2)}A", None)),
        ("rated_power", "electrical", r"(?:额定功率|정격\s*소비전력|소비전력)?\s*([0-9.]+)\s*W\b", lambda m: (m.group(1), "W")),
        ("battery_capacity", "battery", r"(?:电池容量|배터리\s*용량)?\s*([0-9,.]+)\s*(mAh|Ah)\b", lambda m: (m.group(1).replace(",", ""), m.group(2))),
        ("heating_temperature", "temperature", r"(?:约|약|恒温|온도|가열)?\s*([0-9.]+)\s*(?:°\s*C|℃|C)(?![A-Za-z0-9])", lambda m: (m.group(1), "°C")),
        ("product_size", "dimension", r"([0-9.]+\s*[x×*]\s*[0-9.]+\s*[x×*]\s*[0-9.]+)\s*(cm|mm)", lambda m: (re.sub(r"\s*[x*×]\s*", " × ", m.group(1)), m.group(2).lower())),
        ("weight", "weight", r"(?:重量|무게|净重|중량)?\s*([0-9.]+)\s*(kg|g)\b", lambda m: (m.group(1), m.group(2).lower())),
        ("single_operation_time", "time", r"(?:工作时间|작동\s*시간|1회\s*작동)\s*[:：]?\s*([0-9.]+)\s*(分钟|분|min)", lambda m: (m.group(1), "분")),
        ("charge_time", "time", r"(?:充电时间|충전\s*시간)\s*[:：]?\s*([0-9.]+)\s*(小时|시간|h)", lambda m: (m.group(1), "시간")),
        ("total_use_time", "time", r"(?:使用时间|사용\s*(?:가능\s*)?시간)\s*[:：]?\s*([0-9.]+)\s*(小时|시간|h)", lambda m: (m.group(1), "시간")),
        ("massage_head_count", "feature", r"(?:按摩头|마사지\s*헤드)\s*([0-9]+)\s*(以上|개\s*이상)?|([0-9]+)\s*(?:个|개)\s*(以上|이상)?\s*(?:按摩头|마사지\s*헤드)", lambda m: (f"{m.group(1) or m.group(3)}+" if (m.group(2) or m.group(4)) else (m.group(1) or m.group(3)), "개")),
    ]
    for field_key, category, pattern, formatter in rules:
        for match in re.finditer(pattern, compact, re.IGNORECASE):
            value, unit = _canonical_value(field_key, *formatter(match))
            scope = _nearby_scope(compact, match.start(), match.end()) if field_key in {"weight", "product_size"} else "product"
            # Numeric specifications are reviewed on their own merits.  A risk
            # phrase elsewhere in a long OCR block must not contaminate every
            # number found in the same block.  Temperature and approximate
            # values remain conservative because they are performance claims.
            needs_review = field_key == "heating_temperature" or "약" in match.group(0) or "约" in match.group(0)
            candidates.append(NormalizedCandidate(field_key, category, value, unit, scope, match.group(0).strip(), needs_review, _model_option(compact, match.start(), match.end())))
    port = re.search(r"type[-\s]?c", compact, re.IGNORECASE)
    if port:
        candidates.append(NormalizedCandidate("charging_port", "feature", "Type-C", None, "product", port.group(0), False, _model_option(compact, port.start(), port.end())))
    for word in RISK_WORDS:
        if word in compact:
            candidates.append(NormalizedCandidate(f"claim:{word}", "claim", word, None, "product", compact, True))
    return candidates


def fact_sentence(field_key: str | None, value: str | None, unit: str | None, scope: str | None = None) -> str:
    labels = {"rated_input": "정격 입력", "rated_power": "정격 소비전력", "battery_capacity": "배터리 용량", "heating_temperature": "표기 온도", "product_size": "제품 크기", "weight": "무게", "single_operation_time": "1회 작동 시간", "charge_time": "충전 시간", "total_use_time": "사용 가능 시간", "massage_head_count": "마사지 헤드 수", "charging_port": "충전 포트", "claim": "검토 필요 표현"}
    label_key = "claim" if (field_key or "").startswith("claim:") else field_key
    label = labels.get(label_key, "제품 정보")
    if scope == "master_carton" and field_key in {"weight", "product_size"}:
        label = "외박스 무게" if field_key == "weight" else "외박스 크기"
    elif scope == "individual_package" and field_key in {"weight", "product_size"}:
        label = "개별 포장 무게" if field_key == "weight" else "개별 포장 크기"
    return f"{label}: {value or ''}{unit or ''}"


def conflict_group_key(field_key: str, scope: str, model_option: str | None) -> str:
    return f"{field_key}:{scope}:{(model_option or 'common').lower()}"


def _history(db: Session, fact: ProductFact, user_id: str, event_type: str, note: str | None = None) -> None:
    db.add(FactHistory(fact_id=fact.id, previous_fact_text=fact.fact_text, previous_source_text=fact.source_text, previous_source_asset_id=fact.source_asset_id, previous_verification_status=fact.verification_status, updated_by=user_id, event_type=event_type, previous_payload={"field_key": fact.field_key, "value": fact.normalized_value, "unit": fact.normalized_unit, "scope": fact.scope, "model_option": fact.model_option}, note=note))


def mark_fact_dependents_stale(db: Session, project_id: str, fact_ids: Iterable[str]) -> list[str]:
    changed = set(fact_ids)
    affected: list[str] = []
    for section in db.query(PageSection).join(PageSection.page).filter_by(project_id=project_id).all():
        if changed.intersection(section.associated_fact_ids or []):
            section.facts_stale = True
            affected.append(section.id)
    project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
    if project and isinstance(project.intake_snapshot, dict):
        snapshot = dict(project.intake_snapshot)
        generation_plan = snapshot.get("ux2e0_generation_plan")
        if isinstance(generation_plan, dict):
            plan = dict(generation_plan)
            changed_scenes = []
            for scene in plan.get("scenes") or []:
                current = dict(scene)
                if changed.intersection(current.get("source_fact_ids") or []) and isinstance(current.get("copy_draft"), dict):
                    copy_draft = dict(current["copy_draft"])
                    copy_draft["status"] = "stale"
                    copy_draft["stale_reason"] = "연결된 사실이 변경되어 다시 생성이 필요합니다."
                    current["copy_draft"] = copy_draft
                changed_scenes.append(current)
            plan["scenes"] = changed_scenes
            snapshot["ux2e0_generation_plan"] = plan
            project.intake_snapshot = snapshot
    if project and isinstance(project.planning_draft, dict):
        draft = dict(project.planning_draft)
        draft["stale_fact_ids"] = list(dict.fromkeys([*(draft.get("stale_fact_ids") or []), *changed]))
        draft["status"] = "stale"
        cards = []
        for card in draft.get("cards") or []:
            current = dict(card)
            if changed.intersection(current.get("source_fact_ids") or []):
                current["facts_stale"] = True
            cards.append(current)
        draft["cards"] = cards
        recommendations = []
        for recommendation in draft.get("recommendations") or []:
            current_recommendation = dict(recommendation)
            current_recommendation["facts_stale"] = any(
                changed.intersection(card.get("source_fact_ids") or [])
                for card in current_recommendation.get("cards") or []
            )
            recommendation_cards = []
            for card in current_recommendation.get("cards") or []:
                current_card = dict(card)
                if changed.intersection(current_card.get("source_fact_ids") or []):
                    current_card["facts_stale"] = True
                recommendation_cards.append(current_card)
            current_recommendation["cards"] = recommendation_cards
            recommendations.append(current_recommendation)
        if recommendations:
            draft["recommendations"] = recommendations
        project.planning_draft = draft
    return affected


def upsert_candidate(db: Session, project_id: str, candidate: NormalizedCandidate, *, source_type: str, user_id: str, source_asset_id: str | None = None, source_url: str | None = None, bbox: dict | None = None, ocr_block_index: int | None = None, confidence: float | None = None, translated_text: str | None = None, inspection_id: str | None = None, ocr_language: str | None = None, ocr_provider: str | None = None, ocr_model: str | None = None, processed_at: datetime.datetime | None = None) -> ProductFact:
    group_key = conflict_group_key(candidate.field_key, candidate.scope, candidate.model_option)
    fact = db.query(ProductFact).filter(ProductFact.project_id == project_id, ProductFact.field_key == candidate.field_key, ProductFact.normalized_value == candidate.value, ProductFact.normalized_unit == candidate.unit, ProductFact.scope == candidate.scope, ProductFact.model_option == candidate.model_option).first()
    if not fact:
        status = "seller_confirmed" if source_type == "seller_input" and not candidate.needs_review else "needs_review" if candidate.needs_review else "extracted"
        fact = ProductFact(project_id=project_id, fact_text=fact_sentence(candidate.field_key, candidate.value, candidate.unit, candidate.scope), source_text=candidate.source_text, source_asset_id=source_asset_id, verification_status=status, extraction_source=source_type, provider=source_type, confidence=confidence if confidence is not None else (1.0 if source_type == "seller_input" else 0.75), needs_review=candidate.needs_review, risk_flags=["requires_claim_review"] if candidate.needs_review else [], field_key=candidate.field_key, fact_category=candidate.category, original_text=candidate.source_text, translated_text=translated_text, normalized_value=candidate.value, normalized_unit=candidate.unit, scope=candidate.scope, model_option=candidate.model_option, extractor_version=EXTRACTOR_VERSION, conflict_group_key=group_key)
        if status == "seller_confirmed":
            fact.seller_confirmed_at, fact.seller_confirmed_by = datetime.datetime.utcnow(), user_id
        db.add(fact)
        db.flush()
    else:
        # Reconcile cards created before the Sprint 3 review rules existed.
        # A refresh must not keep an automatically confirmed risky claim.  Only
        # the dedicated risk acknowledgement history is considered an explicit
        # seller decision and therefore survives subsequent refreshes.
        fact.fact_category = fact.fact_category or candidate.category
        fact.original_text = fact.original_text or candidate.source_text
        fact.translated_text = fact.translated_text or translated_text
        fact.extractor_version = EXTRACTOR_VERSION
        fact.conflict_group_key = group_key
        fact.fact_text = fact_sentence(candidate.field_key, candidate.value, candidate.unit, candidate.scope)
        # An OCR refresh must never displace an explicit seller-confirmed
        # fact, but a legacy seller-input risk card still has to be downgraded
        # until its risk acknowledgement history exists.
        if candidate.needs_review and not (source_type == "asset_ocr" and fact.verification_status == "seller_confirmed"):
            risk_flags = set(fact.risk_flags or [])
            risk_flags.add("requires_claim_review")
            fact.risk_flags = sorted(risk_flags)
            explicitly_acknowledged = any(history.event_type == "risk_acknowledged" for history in fact.histories)
            if not explicitly_acknowledged:
                fact.verification_status = "needs_review"
                fact.needs_review = True
                fact.seller_confirmed_at = None
                fact.seller_confirmed_by = None
    evidence = db.query(FactEvidence).filter(FactEvidence.fact_id == fact.id, FactEvidence.source_type == source_type, FactEvidence.source_asset_id == source_asset_id, FactEvidence.original_text == candidate.source_text, FactEvidence.inspection_id == inspection_id).first()
    if not evidence:
        db.add(FactEvidence(fact_id=fact.id, source_type=source_type, source_url=source_url, source_asset_id=source_asset_id, ocr_block_index=ocr_block_index, bbox=bbox, original_text=candidate.source_text, translated_text=translated_text, confidence=confidence, extractor_version=EXTRACTOR_VERSION, inspection_id=inspection_id, ocr_language=ocr_language, ocr_provider=ocr_provider, ocr_model=ocr_model, processed_at=processed_at))
    return fact


def _reconcile_scope_duplicates(db: Session, project_id: str, user_id: str) -> None:
    """Reject legacy product-scope copies when packaging context is explicit."""
    def source_explicitly_says_product(fact: ProductFact) -> bool:
        number_match = re.search(r"[0-9]+(?:\.[0-9]+)?", fact.normalized_value or "")
        if not number_match:
            return False
        number = number_match.group(0)
        texts = [fact.source_text, fact.original_text, *(item.original_text for item in fact.evidences)]
        packaging_tokens = tuple(token for tokens in SCOPE_TOKENS.values() for token in tokens)
        for text in filter(None, texts):
            lowered = str(text).lower()
            for value_match in re.finditer(re.escape(number), lowered):
                prefix = lowered[max(0, value_match.start() - 80):value_match.start()]
                product_position = max((prefix.rfind(token.lower()) for token in PRODUCT_SCOPE_TOKENS), default=-1)
                packaging_position = max((prefix.rfind(token.lower()) for token in packaging_tokens), default=-1)
                if product_position > packaging_position:
                    return True
        return False

    facts = db.query(ProductFact).filter(
        ProductFact.project_id == project_id,
        ProductFact.field_key.in_(["weight", "product_size"]),
        ProductFact.verification_status != "rejected",
    ).all()
    groups: dict[tuple[str, str | None, str | None, str | None], list[ProductFact]] = {}
    for fact in facts:
        groups.setdefault((fact.field_key, fact.normalized_value, fact.normalized_unit, fact.model_option), []).append(fact)
    for values in groups.values():
        packaging = [fact for fact in values if fact.scope in {"master_carton", "individual_package"}]
        product = [fact for fact in values if (fact.scope or "product") == "product"]
        if not packaging or not product:
            continue
        for duplicate in product:
            if source_explicitly_says_product(duplicate):
                continue
            _history(db, duplicate, user_id, "scope_reclassified", "포장 문맥이 확인되어 product 범위의 중복 후보를 제외")
            duplicate.verification_status = "rejected"
            duplicate.needs_review = False
            mark_fact_dependents_stale(db, project_id, [duplicate.id])


def refresh_evidence_board(db: Session, project: ProductProject, user_id: str) -> list[ProductFact]:
    found: list[ProductFact] = []
    selected_model = _project_model_option(project)
    bundle = (project.intake_snapshot or {}).get("input_bundle") or {}
    seller_texts = [project.raw_input_text, bundle.get("description"), bundle.get("feature_details"), bundle.get("components"), bundle.get("cautions"), *(bundle.get("selling_points") or [])]
    for candidate in normalize_candidates("\n".join(str(text) for text in seller_texts if text)):
        if selected_model and not candidate.model_option:
            candidate = replace(candidate, model_option=selected_model)
        found.append(upsert_candidate(db, project.id, candidate, source_type="seller_input", source_url=project.raw_input_url, user_id=user_id))

    # Components and selected model options are first-party facts too. They
    # cannot be derived safely from a bare number, so store the seller's exact
    # wording as grounded facts before UX-2B creates copy from them.
    components = str(bundle.get("components") or "").strip()
    if components:
        found.append(upsert_candidate(
            db, project.id,
            NormalizedCandidate("components", "components", components, None, "product", components, False, selected_model),
            source_type="seller_input", source_url=project.raw_input_url, user_id=user_id,
        ))
    cautions = str(bundle.get("cautions") or "").strip()
    if cautions:
        found.append(upsert_candidate(
            db, project.id,
            NormalizedCandidate("cautions", "cautions", cautions, None, "product", cautions, False, selected_model),
            source_type="seller_input", source_url=project.raw_input_url, user_id=user_id,
        ))
    model_options = str(bundle.get("model_options") or "").strip()
    if model_options:
        found.append(upsert_candidate(
            db, project.id,
            NormalizedCandidate("model_name", "model", model_options, None, "product", model_options, False, None),
            source_type="seller_input", source_url=project.raw_input_url, user_id=user_id,
        ))
    inspections = db.query(AssetInspectionRecord).filter(AssetInspectionRecord.project_id == project.id).order_by(AssetInspectionRecord.created_at.desc()).all()
    seen_assets: set[str] = set()
    for inspection in inspections:
        if inspection.asset_id in seen_assets or inspection.status != "completed":
            continue
        seen_assets.add(inspection.asset_id)
        translations = inspection.translation_blocks or []
        for index, block in enumerate(inspection.ocr_blocks or []):
            source = block.get("text", "")
            translated = next((item.get("translated_text") for item in translations if item.get("source_text") == source), None)
            for candidate in normalize_candidates(f"{source} {translated or ''}"):
                if selected_model and not candidate.model_option:
                    candidate = replace(candidate, model_option=selected_model)
                found.append(upsert_candidate(db, project.id, candidate, source_type="asset_ocr", source_asset_id=inspection.asset_id, source_url=project.raw_input_url, user_id=user_id, bbox=block.get("bbox"), ocr_block_index=index, confidence=block.get("confidence"), translated_text=translated))
    db.flush()
    _reconcile_scope_duplicates(db, project.id, user_id)
    apply_conflicts(db, project.id)
    return found


def apply_conflicts(db: Session, project_id: str) -> None:
    facts = db.query(ProductFact).filter(ProductFact.project_id == project_id, ProductFact.field_key.isnot(None), ProductFact.verification_status != "rejected").all()
    groups: dict[str, list[ProductFact]] = {}
    for fact in facts:
        groups.setdefault(fact.conflict_group_key or conflict_group_key(fact.field_key, fact.scope or "product", fact.model_option), []).append(fact)
    for values in groups.values():
        if len({(fact.normalized_value, fact.normalized_unit) for fact in values}) > 1:
            # A seller's explicit decision remains a trusted baseline.  New
            # OCR/source candidates are flagged for resolution without
            # silently downgrading the already confirmed product fact.
            seller_confirmed = [fact for fact in values if fact.verification_status == "seller_confirmed"]
            candidates = [fact for fact in values if fact not in seller_confirmed] or values
            for fact in candidates:
                fact.verification_status, fact.needs_review = "conflicted", True


def fact_impact_summary(db: Session, fact: ProductFact) -> dict[str, list[str]]:
    section_ids = [section.id for page in fact.project.pages for section in page.sections if fact.id in (section.associated_fact_ids or [])]
    page_version_ids: list[str] = []
    for version in db.query(PageVersion).join(PageVersion.page).filter_by(project_id=fact.project_id).all():
        if any(item.get("id") == fact.id for item in (version.page_data or {}).get("facts_snapshot", [])):
            page_version_ids.append(version.id)
    detail_version_ids: list[str] = []
    for version in db.query(DetailPageVersion).filter(DetailPageVersion.project_id == fact.project_id).all():
        sections = version.sections_json.get("sections", []) if isinstance(version.sections_json, dict) else version.sections_json
        if any(fact.id in (section.get("associated_fact_ids") or section.get("source_fact_ids") or []) for section in (sections or [])):
            detail_version_ids.append(version.id)
    draft = fact.project.planning_draft or {}
    storyboard_ids = [str(card.get("id") or card.get("key") or index) for index, card in enumerate(draft.get("cards") or []) if fact.id in (card.get("source_fact_ids") or [])]
    return {"page_section_ids": section_ids, "page_version_ids": page_version_ids, "detail_page_version_ids": detail_version_ids, "storyboard_card_ids": storyboard_ids}


def fact_board_blockers(db: Session, project_id: str) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    facts = db.query(ProductFact).filter(ProductFact.project_id == project_id, ProductFact.field_key.isnot(None)).all()
    for fact in facts:
        if fact.verification_status == "rejected":
            continue
        if fact.verification_status not in APPROVED_STATUSES or fact.needs_review:
            blockers.append({"fact_id": fact.id, "code": f"fact_{fact.verification_status}", "message": f"{fact.fact_text}: 판매자 확인 또는 명시적 제외가 필요합니다."})
        elif not fact.evidences:
            blockers.append({"fact_id": fact.id, "code": "fact_missing_evidence", "message": f"{fact.fact_text}: 연결된 근거가 없습니다."})
    return blockers


def approved_fact_snapshot(db: Session, project_id: str, user_id: str | None, purpose: str = "generation") -> FactSnapshot:
    facts = db.query(ProductFact).filter(ProductFact.project_id == project_id, ProductFact.verification_status.in_(APPROVED_STATUSES), ProductFact.needs_review.is_(False), ProductFact.field_key.isnot(None)).order_by(ProductFact.field_key, ProductFact.normalized_value).all()
    facts = [fact for fact in facts if fact.evidences]
    payload = []
    for fact in facts:
        evidence = [{"id": item.id, "source_type": item.source_type, "source_url": item.source_url, "source_asset_id": item.source_asset_id, "ocr_block_index": item.ocr_block_index, "bbox": item.bbox, "original_text": item.original_text, "translated_text": item.translated_text, "confidence": item.confidence, "extractor_version": item.extractor_version, "inspection_id": item.inspection_id, "ocr_language": item.ocr_language, "ocr_provider": item.ocr_provider, "ocr_model": item.ocr_model, "processed_at": item.processed_at.isoformat() if item.processed_at else None} for item in sorted(fact.evidences, key=lambda row: row.id)]
        payload.append({
            "id": fact.id,
            "field_key": fact.field_key,
            "category": fact.fact_category,
            "value": fact.normalized_value,
            "unit": fact.normalized_unit,
            "scope": fact.scope,
            "model_option": fact.model_option,
            "fact_text": fact.fact_text,
            "original_text": fact.original_text,
            "translated_text": fact.translated_text,
            "verification_status": fact.verification_status,
            "extractor_version": fact.extractor_version,
            "evidence_ids": [item["id"] for item in evidence],
            "evidence": evidence,
        })
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    snapshot = FactSnapshot(project_id=project_id, purpose=purpose, snapshot_hash=hashlib.sha256(encoded.encode("utf-8")).hexdigest(), facts_json=payload, created_by=user_id)
    db.add(snapshot)
    db.flush()
    return snapshot
