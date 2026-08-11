"""LG-3 Commerce Planning adapters.

The four planning agents keep their established Pydantic schemas, but their
full results are run artifacts rather than LangGraph checkpoint state.  A
checkpoint therefore carries only artifact references, hashes and the approved
fact snapshot reference inherited from LG-2.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.agents.schemas import CopySetOutput, DetailPagePlanOutput, SalesStrategyOutput, VisualPlanOutput
from src.db.models import AgentRun, FactSnapshot, ProductCreativeBriefVersion, ProductProject
from src.services.api_ready_generation_service import build_generation_plan
from src.services.langgraph_discovery_service import _node_session, read_legacy_discovery_outputs
from src.services.rule_based_copy_service import unsupported_claims


COMMERCE_ARTIFACT_KEY = "langgraph_commerce_planning_artifacts"
COMMERCE_VERSION = "lg3-v1"
_STAGES = ("sales_strategy", "page_planning", "copywriting", "visual_planning")
_BLOCKED_COPY_TERMS = (
    "치료", "효능", "인증", "안전성", "보장", "최저", "1위", "가격", "할인",
    # Comparative superiority is never an approved product fact on its own.
    "경쟁사", "경쟁 제품", "업계 최고", "최고", "최상", "유일", "압도",
)
_STAGE_INDEX = {stage: index for index, stage in enumerate(_STAGES)}
_COPY_METADATA_FIELDS = {"schema_version", "section_fact_ids", "copy_provenance"}


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _prompt(agent_name: str) -> str:
    from src.services.prompt_registry import PromptRegistry

    backend_root = Path(__file__).resolve().parents[2]
    system = PromptRegistry(base_path=str(backend_root / "prompts")).load("system/sellform_agent_base")
    node = PromptRegistry(base_path=str(backend_root / "src" / "agents" / "nodes")).load_agent_prompt(agent_name)
    return f"{system}\n{node}"


def _store(run: AgentRun, stage: str, output: dict[str, Any], *, metadata: dict[str, Any]) -> dict[str, str]:
    db, owns_session = _node_session()
    try:
        # `run` can belong to a different request Session; always re-fetch in
        # the active graph Session before mutation.
        active_run = db.query(AgentRun).filter(AgentRun.id == run.id).with_for_update().one()
        payload = dict(active_run.outputs_json or {})
        artifacts = dict(payload.get(COMMERCE_ARTIFACT_KEY) or {})
        artifact_hash = _canonical_hash({"stage": stage, "output": output, "metadata": metadata})
        artifacts[stage] = {
            "schema_version": COMMERCE_VERSION,
            "output": deepcopy(output),
            "metadata": {**deepcopy(metadata), "artifact_hash": artifact_hash},
        }
        active_run.outputs_json = {**payload, COMMERCE_ARTIFACT_KEY: artifacts}
        db.add(active_run)
        # Persist before a LangGraph checkpoint is written. LG-1 history replay
        # repairs an operational step projection if the process stops after it.
        db.commit()
        return {"artifact_key": stage, "artifact_hash": artifact_hash, "schema_version": COMMERCE_VERSION}
    finally:
        if owns_session:
            db.close()


def _load_run(run_id: str, project_id: str) -> tuple[Session, bool, AgentRun]:
    db, owns_session = _node_session()
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.project_id == project_id).one()
    return db, owns_session, run


def _approved_snapshot(run: AgentRun, db: Session) -> FactSnapshot:
    snapshot_id = (run.input_snapshot or {}).get("approved_fact_snapshot_id")
    snapshot_hash = (run.input_snapshot or {}).get("approved_fact_snapshot_hash")
    if not snapshot_id or not snapshot_hash:
        raise ValueError("LG-3 requires the approved LG-2 fact snapshot.")
    snapshot = db.query(FactSnapshot).filter(
        FactSnapshot.id == snapshot_id, FactSnapshot.project_id == run.project_id
    ).one()
    if snapshot.snapshot_hash != snapshot_hash:
        raise ValueError("LG-3 fact snapshot hash does not match the persisted snapshot.")
    return snapshot


def _artifact_outputs(run: AgentRun) -> dict[str, dict[str, Any]]:
    artifacts = ((run.outputs_json or {}).get(COMMERCE_ARTIFACT_KEY) or {})
    return {stage: dict((artifacts.get(stage) or {}).get("output") or {}) for stage in _STAGES}


def _generate(stage: str, schema: type, *, mode: str, context: dict[str, Any], mock: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    prompt = _prompt(stage)
    metadata: dict[str, Any] = {"prompt_hash": _canonical_hash(prompt), "mode": mode}
    if mode != "real":
        return schema.model_validate(mock).model_dump(), {**metadata, "provider": "mock", "model": "mock-text"}

    from src.services.llm_router import get_text_provider_by_settings
    from src.services.provider_adapters import ProviderRequest

    result = get_text_provider_by_settings().generate_json(ProviderRequest(
        provider="router", model="configured", system_prompt=prompt,
        user_prompt=json.dumps(context, ensure_ascii=False), schema_name=stage,
        product_name=str((context.get("product_brief") or {}).get("product_name") or "상품"),
    ))
    return schema.model_validate(result["content"]).model_dump(), {
        **metadata, "provider": result.get("provider"), "model": result.get("model"),
        "token_usage": result.get("token_usage"), "cost": result.get("cost"),
    }


def _fact_context(snapshot: FactSnapshot) -> list[dict[str, Any]]:
    return [dict(item) for item in (snapshot.facts_json or []) if item.get("id") and item.get("fact_text")]


def _input_contract(run: AgentRun, db: Session) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, str]]]:
    snapshot = _approved_snapshot(run, db)
    facts = _fact_context(snapshot)
    plan = build_generation_plan(run.project, db)
    # The generation-plan brief contains useful product identity and safe asset
    # metadata, but also has raw seller text for UX editing. LG-3 strategy and
    # copy must never consume that unconfirmed text. Replace its fact list
    # with exactly the immutable snapshot and omit raw/freeform evidence.
    brief = dict(plan["product_brief"])
    brief["confirmed_facts"] = [
        {"id": item["id"], "field_key": item.get("field_key"), "text": item.get("fact_text"),
         "value": item.get("value"), "unit": item.get("unit"), "scope": item.get("scope"),
         "model_option": item.get("model_option"), "verification_status": item.get("verification_status")}
        for item in facts
    ]
    brief["seller_input"] = ""
    brief["needs_seller_confirmation"] = []
    creative_ref = dict((run.input_snapshot or {}).get("creative_brief_snapshot") or {})
    if creative_ref:
        creative = db.query(ProductCreativeBriefVersion).filter_by(
            id=creative_ref.get("id"), run_id=run.id, project_id=run.project_id,
        ).one()
        if creative.output_hash != creative_ref.get("output_hash"):
            raise ValueError("LG-7 creative brief hash does not match the pinned artifact.")
        # Downstream agents receive the same immutable creative contract. It
        # contains approved fact IDs, abstract review/reference insights and
        # Brand Kit identity, never raw review rows or copied reference text.
        brief["creative_brief"] = deepcopy(creative.brief_json)
        brief["creative_brief_version"] = creative.version
        brief["creative_brief_hash"] = creative.output_hash
    # Re-validate the actual LG-2 artifacts so the graph cannot silently fall
    # back to handwritten output.  Their raw content is deliberately not
    # handed to Sales Strategy or Copywriting: only the approved FactSnapshot
    # may supply factual/marketing input to those nodes.
    discovery_outputs = read_legacy_discovery_outputs(run, db)
    discovery = {
        stage: {"artifact_hash": _canonical_hash(output), "schema_version": "lg2-v1"}
        for stage, output in discovery_outputs.items()
    }
    return brief, facts, discovery


def _mark_planning_draft_stale(project: ProductProject, *, reason: str) -> None:
    """Keep the legacy planning UI from rendering a superseded graph result."""

    if not isinstance(project.planning_draft, dict):
        return
    draft = deepcopy(project.planning_draft)
    stale_fact_ids = list(draft.get("stale_fact_ids") or [])
    cards: list[dict[str, Any]] = []
    for card in draft.get("cards") or []:
        current = dict(card)
        current["facts_stale"] = True
        stale_fact_ids.extend(str(item) for item in (current.get("source_fact_ids") or []))
        cards.append(current)
    draft["cards"] = cards
    draft["status"] = "stale"
    draft["stale_fact_ids"] = list(dict.fromkeys(stale_fact_ids))
    history = list(draft.get("revision_history") or [])
    history.append({"revision": draft.get("revision", 1), "action": "langgraph_lg3_invalidated", "reason": reason})
    draft["revision_history"] = history[-20:]
    project.planning_draft = draft


def _invalidate_downstream(
    run: AgentRun,
    *,
    from_stage: str,
    snapshot: FactSnapshot,
    reason: str,
    previous_hashes: list[str] | None = None,
) -> list[str]:
    """Delete stale downstream artifacts and materialized planning output.

    A graph node may be rerun by an operator after it has already produced an
    artifact.  Logging that fact is not enough: each later output was computed
    from the old value and must be rebuilt before the planning UI is trusted.
    """

    db, owns_session = _node_session()
    try:
        active_run = db.query(AgentRun).filter(AgentRun.id == run.id).with_for_update().one()
        payload = dict(active_run.outputs_json or {})
        artifacts = dict(payload.get(COMMERCE_ARTIFACT_KEY) or {})
        downstream = _STAGES[_STAGE_INDEX[from_stage] + 1:]
        invalidated = [stage for stage in downstream if stage in artifacts]
        for stage in invalidated:
            artifacts.pop(stage, None)
        payload[COMMERCE_ARTIFACT_KEY] = artifacts

        projection = dict(payload.get("langgraph_commerce") or {})
        for stage in (from_stage, *downstream):
            projection.pop(stage, None)
        if projection:
            payload["langgraph_commerce"] = projection
        else:
            payload.pop("langgraph_commerce", None)

        invalidations = list(payload.get("langgraph_commerce_invalidations") or [])
        invalidations.append({
            "reason": reason,
            "from_stage": from_stage,
            "invalidated_stages": invalidated,
            "previous_hashes": previous_hashes or [],
            "current_hash": snapshot.snapshot_hash,
        })
        payload["langgraph_commerce_invalidations"] = invalidations[-20:]
        active_run.outputs_json = payload
        active_project = db.query(ProductProject).filter(ProductProject.id == active_run.project_id).with_for_update().one()
        _mark_planning_draft_stale(active_project, reason=reason)
        db.add(active_project)
        db.add(active_run)
        db.commit()
        return invalidated
    finally:
        if owns_session:
            db.close()


def _invalidate_for_rerun(run: AgentRun, *, stage: str, snapshot: FactSnapshot) -> None:
    """Invalidate after a node rerun and when its approved snapshot changed."""

    artifacts = dict(((run.outputs_json or {}).get(COMMERCE_ARTIFACT_KEY) or {}))
    if not artifacts.get(stage):
        return
    hashes = sorted({
        str((artifact.get("metadata") or {}).get("fact_snapshot_hash") or "")
        for artifact in artifacts.values() if isinstance(artifact, dict)
    })
    snapshot_changed = bool(hashes and set(hashes) != {snapshot.snapshot_hash})
    _invalidate_downstream(
        run,
        from_stage=stage,
        snapshot=snapshot,
        reason="approved_fact_snapshot_changed" if snapshot_changed else f"{stage}_rerun",
        previous_hashes=hashes,
    )


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "").casefold()


def _matching_facts(value: str, facts: list[dict[str, Any]]) -> tuple[list[str], set[str]]:
    """Return fact IDs and numeric tokens supported by full fact surfaces.

    A bare matching digit (for example ``5`` from ``DC 5V``) is never enough
    to support a different claim such as ``5시간 사용``.
    """

    normalised = _normalise_text(value)
    matching_ids: list[str] = []
    supported_numbers: set[str] = set()
    for fact in facts:
        surfaces = [str(fact.get("fact_text") or "")]
        raw_value = str(fact.get("value") or "").strip()
        unit = str(fact.get("unit") or "").strip()
        if raw_value and unit:
            surfaces.append(f"{raw_value}{unit}")
        # A bare numeric value carries no semantic unit, so it cannot justify
        # a numeric marketing statement by itself.
        surfaces = [surface for surface in surfaces if re.search(r"[^\d.,\s]", surface)]
        matched = [surface for surface in surfaces if _normalise_text(surface) in normalised]
        if matched:
            matching_ids.append(str(fact["id"]))
            for surface in matched:
                supported_numbers.update(re.findall(r"\d+(?:[.,]\d+)?", surface))
    return matching_ids, supported_numbers


def _copy_section_fact_ids(copy: dict[str, Any], provenance: dict[str, dict[str, Any]], facts: list[dict[str, Any]]) -> dict[str, list[str]]:
    sections = {
        "hero": ("hero_title", "hero_subtitle"),
        "pain_point": ("painpoint_title", "painpoint_body"),
        "feature_1": ("feature_1_title", "feature_1_body"),
        "feature_2": ("feature_2_title", "feature_2_body"),
        "feature_3": ("feature_3_title", "feature_3_body"),
        "usage_guide": ("usage_title", "usage_body"),
        "details_components": ("details_title", "details_body"),
        "product_information": ("guarantee_title", "guarantee_body"),
    }
    allowed = {str(item["id"]) for item in facts}
    preserved = {key: [fact_id for fact_id in value if fact_id in allowed]
                 for key, value in dict(copy.get("section_fact_ids") or {}).items()}
    for section, fields in sections.items():
        linked = [fact_id for field in fields for fact_id in provenance.get(field, {}).get("fact_ids", [])]
        preserved[section] = list(dict.fromkeys([*(preserved.get(section) or []), *linked]))
    return preserved


def _safe_copy(output: dict[str, Any], facts: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Block unsafe claims and preserve exact per-field fact provenance."""

    provenance: dict[str, dict[str, Any]] = {}
    cleaned = dict(output)
    for field, value in output.items():
        if field in _COPY_METADATA_FIELDS or not isinstance(value, str):
            continue
        invalid = unsupported_claims(value)
        lowered = value.casefold()
        invalid.extend(term for term in _BLOCKED_COPY_TERMS if term.casefold() in lowered)
        matching_ids, supported_numbers = _matching_facts(value, facts)
        numbers = set(re.findall(r"\d+(?:[.,]\d+)?", value))
        if numbers - supported_numbers:
            invalid.append("unconfirmed_numeric_claim")
        if invalid:
            cleaned[field] = "판매자 확인 정보 기준으로 안내합니다."
            provenance[field] = {
                "classification": "blocked_unsupported_claim", "fact_ids": [], "blocked": sorted(set(invalid)),
            }
        else:
            provenance[field] = {
                "classification": "fact_grounded" if matching_ids else "narrative_non_claim",
                "fact_ids": matching_ids,
            }
    cleaned["section_fact_ids"] = _copy_section_fact_ids(cleaned, provenance, facts)
    cleaned["copy_provenance"] = provenance
    return CopySetOutput.model_validate(cleaned).model_dump(), provenance


def _normalise_sales_strategy(output: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Make candidate selection explicit even for legacy provider responses."""

    value = dict(output)
    allowed_fact_ids = [str(item["id"]) for item in facts]
    candidates = list(value.get("candidates") or [])
    if not candidates:
        candidates = [{
            "id": "primary", "headline": str(value.get("hook_headline") or "상품 정보 확인"),
            "main_claim": str(value.get("main_claim") or value.get("recommended_direction") or ""),
            "supporting_fact_ids": allowed_fact_ids,
        }]
    normalised_candidates = []
    for index, candidate in enumerate(candidates):
        current = dict(candidate)
        current["id"] = str(current.get("id") or f"candidate-{index + 1}")
        current["headline"] = str(current.get("headline") or value.get("hook_headline") or "상품 정보 확인")
        current["main_claim"] = str(current.get("main_claim") or "")
        current["supporting_fact_ids"] = [fact_id for fact_id in current.get("supporting_fact_ids") or [] if fact_id in allowed_fact_ids]
        normalised_candidates.append(current)
    value["candidates"] = normalised_candidates
    candidate_ids = {item["id"] for item in normalised_candidates}
    value["selected_candidate_id"] = str(value.get("selected_candidate_id") or normalised_candidates[0]["id"])
    if value["selected_candidate_id"] not in candidate_ids:
        value["selected_candidate_id"] = normalised_candidates[0]["id"]
    value["selection_reason"] = str(value.get("selection_reason") or value.get("reason") or "승인된 사실 스냅샷을 기준으로 선택")
    value["reason"] = str(value.get("reason") or value["selection_reason"])
    return SalesStrategyOutput.model_validate(value).model_dump()


def _normalise_page_plan(output: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Freeze page-section purpose and approved-fact scope in the artifact."""

    value = dict(output)
    allowed_fact_ids = [str(item["id"]) for item in facts]
    sections = []
    for section in value.get("sections") or []:
        current = dict(section)
        current["purpose"] = str(current.get("purpose") or current.get("name") or "상품 정보 안내")
        supplied_ids = [str(item) for item in current.get("source_fact_ids") or []]
        current["source_fact_ids"] = [item for item in supplied_ids if item in allowed_fact_ids] or allowed_fact_ids
        sections.append(current)
    value["sections"] = sections
    return DetailPagePlanOutput.model_validate(value).model_dump()


def _scene_generation_mode(scene: dict[str, Any]) -> str:
    if scene.get("rendering_strategy") == "safe_existing_photo":
        return "safe_existing_photo"
    if scene.get("mock_status") == "generation_pending":
        return "ai_redesign"
    return "html_information_fallback"


def _frozen_scene_plan(plan: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project UX-2E scenes into a deterministic, validated LG-3 contract."""

    allowed_fact_ids = {str(item["id"]) for item in facts}
    fallback_asset_ids = [str(item["id"]) for item in (plan.get("product_brief") or {}).get("safe_reference_assets") or [] if item.get("id")]
    if not fallback_asset_ids:
        raise ValueError("LG-3 Visual Planning requires at least one safe seller-owned reference asset.")

    contracts: list[dict[str, Any]] = []
    for scene in plan.get("scenes") or []:
        source_fact_ids = [str(item) for item in scene.get("source_fact_ids") or [] if str(item) in allowed_fact_ids]
        # A broad product scene is still explicitly grounded in the immutable
        # snapshot when UX-2E did not nominate one individual fact.
        if not source_fact_ids:
            source_fact_ids = sorted(allowed_fact_ids)
        # A previous planning draft is an output of this same subgraph, not a
        # new LG-3 input.  Reusing its per-card asset choice would make an
        # identical rerun depend on an earlier output.  Use the deterministic
        # first approved reference; later seller changes become explicit LG-4
        # inputs and produce a new graph run.
        reference_asset_ids = fallback_asset_ids[:1]
        contracts.append({
            "id": str(scene.get("id") or "scene"),
            "scene_type": str(scene.get("scene_type") or "feature_closeup"),
            "objective": str(scene.get("objective") or "구매 정보 안내"),
            "source_fact_ids": source_fact_ids,
            "reference_asset_ids": reference_asset_ids,
            "generation_mode": _scene_generation_mode(scene),
            "requested_output": str(scene.get("requested_output") or "html_graphic"),
            "rendering_strategy": str(scene.get("rendering_strategy") or "html_information_fallback"),
            "mock_status": str(scene.get("mock_status") or "information_fallback"),
        })
    visual_contract = VisualPlanOutput.model_validate({
        "hero_image_prompt": "contract-validation", "detail_image_prompt": "contract-validation",
        "color_palette": [], "scene_plan": contracts,
    })
    if not isinstance(visual_contract.scene_plan, list) or not visual_contract.scene_plan:
        raise ValueError("LG-3 Visual Planning requires at least one ScenePlan entry.")
    return [scene.model_dump() for scene in visual_contract.scene_plan]


def run_sales_strategy(*, run_id: str, project_id: str, mode: str) -> dict[str, Any]:
    db, owns_session, run = _load_run(run_id, project_id)
    try:
        snapshot = _approved_snapshot(run, db)
        _invalidate_for_rerun(run, stage="sales_strategy", snapshot=snapshot)
        brief, facts, discovery = _input_contract(run, db)
        from src.agents.mock_outputs import build_mock_sales_strategy
        output, metadata = _generate("sales_strategy", SalesStrategyOutput, mode=mode, context={
            "product_brief": brief, "approved_facts": facts,
            "discovery_contract": discovery,
        }, mock=build_mock_sales_strategy(brief["product_name"], ""))
        output = _normalise_sales_strategy(output, facts)
        return {"sales_strategy": {"fact_snapshot_id": snapshot.id, **_store(run, "sales_strategy", output, metadata={
            **metadata, "fact_snapshot_hash": snapshot.snapshot_hash, "input_hash": _canonical_hash([brief, facts, discovery]),
        })}}
    finally:
        if owns_session:
            db.close()


def run_page_planning(*, run_id: str, project_id: str, mode: str) -> dict[str, Any]:
    db, owns_session, run = _load_run(run_id, project_id)
    try:
        snapshot = _approved_snapshot(run, db)
        brief, facts, _ = _input_contract(run, db)
        strategy = _artifact_outputs(run)["sales_strategy"]
        if not strategy:
            raise ValueError("LG-3 page planning requires Sales Strategy output.")
        _invalidate_for_rerun(run, stage="page_planning", snapshot=snapshot)
        from src.agents.mock_outputs import build_mock_page_plan
        output, metadata = _generate("page_planning", DetailPagePlanOutput, mode=mode, context={
            "product_brief": brief, "approved_facts": facts, "sales_strategy": strategy,
        }, mock=build_mock_page_plan(brief["product_name"]))
        output = _normalise_page_plan(output, facts)
        return {"page_planning": {"fact_snapshot_id": snapshot.id, **_store(run, "page_planning", output, metadata={
            **metadata, "fact_snapshot_hash": snapshot.snapshot_hash, "input_hash": _canonical_hash([brief, facts, strategy]),
        })}}
    finally:
        if owns_session:
            db.close()


def run_copywriting(*, run_id: str, project_id: str, mode: str) -> dict[str, Any]:
    db, owns_session, run = _load_run(run_id, project_id)
    try:
        snapshot = _approved_snapshot(run, db)
        brief, facts, discovery = _input_contract(run, db)
        artifacts = _artifact_outputs(run)
        if not artifacts["sales_strategy"] or not artifacts["page_planning"]:
            raise ValueError("LG-3 copywriting requires Sales Strategy and Page Planning output.")
        _invalidate_for_rerun(run, stage="copywriting", snapshot=snapshot)
        from src.agents.mock_outputs import build_mock_copy_set
        mock = build_mock_copy_set(brief["product_name"], "", category=brief.get("category"), facts=facts)
        output, metadata = _generate("copywriting", CopySetOutput, mode=mode, context={
            "product_brief": brief, "approved_facts": facts, "discovery_contract": discovery,
            "sales_strategy": artifacts["sales_strategy"], "page_plan": artifacts["page_planning"],
        }, mock=mock)
        output, provenance = _safe_copy(output, facts)
        return {"copywriting": {"fact_snapshot_id": snapshot.id, **_store(run, "copywriting", output, metadata={
            **metadata, "fact_snapshot_hash": snapshot.snapshot_hash, "input_hash": _canonical_hash([brief, facts, artifacts["sales_strategy"], artifacts["page_planning"]]),
            "copy_provenance": provenance,
        })}}
    finally:
        if owns_session:
            db.close()


def _planning_draft(plan: dict[str, Any], page_plan: dict[str, Any], copy: dict[str, Any], snapshot: FactSnapshot) -> dict[str, Any]:
    scene_by_type = {str(scene.get("scene_type")): scene for scene in plan.get("scenes") or []}
    copy_fields = {
        "hero": ("hero_title", "hero_subtitle"), "pain_point": ("painpoint_title", "painpoint_body"),
        "feature_1": ("feature_1_title", "feature_1_body"), "feature_2": ("feature_2_title", "feature_2_body"),
        "feature_3": ("feature_3_title", "feature_3_body"), "usage_guide": ("usage_title", "usage_body"),
        "details_components": ("details_title", "details_body"), "product_information": ("guarantee_title", "guarantee_body"),
    }
    cards: list[dict[str, Any]] = []
    all_fact_ids = [str(item.get("id")) for item in (snapshot.facts_json or []) if item.get("id")]
    for index, section in enumerate(page_plan.get("sections") or []):
        section_id = str(section.get("id") or f"section-{index + 1}")
        title_key, body_key = copy_fields.get(section_id, ("guarantee_title", "guarantee_body"))
        scene = scene_by_type.get("hero_product" if section_id == "hero" else "usage_scene" if section_id == "usage_guide" else "spec_graphic" if section_id in {"details_components", "product_information"} else "feature_closeup") or {}
        fact_ids = list(scene.get("source_fact_ids") or copy.get("section_fact_ids", {}).get(section_id) or [])
        # The storyboard validator requires a final specifications card to be
        # last. Keep the stable page-section ID, but map its semantic type to
        # the canonical storyboard final-spec type.
        card_type = "product_specifications" if section_id == "product_information" else section_id
        cards.append({
            "id": section_id, "type": card_type, "label": str(section.get("name") or section_id),
            "title": str(copy.get(title_key) or section.get("name") or section_id),
            "bullets": [str(copy.get(body_key) or "판매자 확인 정보 기준으로 안내합니다.")],
            "source_fact_ids": fact_ids if fact_ids else (all_fact_ids if section_id == "product_information" else []),
            "target": str(section.get("target") or section.get("name") or section_id),
            "objective": str(scene.get("objective") or section.get("objective") or ""),
            "copy_classification": "fact" if (fact_ids or section_id == "product_information") else "creative",
            "visual_strategy": str(scene.get("rendering_strategy") or "html_graphic"), "is_enabled": True,
            "sort_order": index, "image_asset_id": (scene.get("reference_asset_ids") or [None])[0],
            "candidate_asset_ids": list(scene.get("reference_asset_ids") or []),
            "image_requirement": "ai_redesign_required" if scene.get("mock_status") == "generation_pending" else "derived_graphic",
            "scene_request": str(scene.get("objective") or ""), "rendering_template": "langgraph_commerce_planning",
            "facts_stale": False, "missing_reasons": [],
        })
    return {"cards": cards, "storyboard_version": 1, "fact_snapshot_id": snapshot.id,
            "fact_snapshot_hash": snapshot.snapshot_hash, "status": "draft", "stale_fact_ids": [],
            "estimated_cost": 0.0, "revision": 1, "revision_history": [{"revision": 1, "action": "langgraph_lg3_generated"}]}


def run_visual_planning(*, run_id: str, project_id: str, mode: str) -> dict[str, Any]:
    db, owns_session, run = _load_run(run_id, project_id)
    try:
        snapshot = _approved_snapshot(run, db)
        brief, facts, _ = _input_contract(run, db)
        artifacts = _artifact_outputs(run)
        if not artifacts["page_planning"] or not artifacts["copywriting"]:
            raise ValueError("LG-3 visual planning requires Page Planning and Copywriting output.")
        _invalidate_for_rerun(run, stage="visual_planning", snapshot=snapshot)
        from src.agents.mock_outputs import build_mock_visual_plan
        output, metadata = _generate("visual_planning", VisualPlanOutput, mode=mode, context={
            "product_brief": brief, "approved_facts": facts, "page_plan": artifacts["page_planning"],
            "copy_set": artifacts["copywriting"], "sales_strategy": artifacts["sales_strategy"],
        }, mock=build_mock_visual_plan(brief["product_name"]))
        generation_plan = build_generation_plan(run.project, db)
        scene_plan = _frozen_scene_plan(generation_plan, facts)
        # The provider's visual suggestions and the immutable ScenePlan are a
        # single versioned result.  Dynamic UX-2E audit timestamps stay out of
        # this artifact, so equal mock inputs produce an equal artifact hash.
        output = VisualPlanOutput.model_validate({**output, "scene_plan": scene_plan}).model_dump()
        draft = _planning_draft({"scenes": scene_plan}, artifacts["page_planning"], artifacts["copywriting"], snapshot)
        active_project = db.query(ProductProject).filter(ProductProject.id == project_id).with_for_update().one()
        active_project.planning_draft = draft
        db.add(active_project)
        db.commit()
        return {"visual_planning": {"fact_snapshot_id": snapshot.id, "scene_count": len(scene_plan), **_store(run, "visual_planning", output, metadata={
            **metadata, "fact_snapshot_hash": snapshot.snapshot_hash,
            # ``brief`` contains UX operational status that can legitimately
            # change while the approved facts and planning inputs have not.
            # The frozen scene contract is the complete visual input instead.
            "input_hash": _canonical_hash([facts, artifacts["page_planning"], artifacts["copywriting"], scene_plan]),
            "scene_plan": scene_plan, "planning_draft_revision": 1,
        })}}
    finally:
        if owns_session:
            db.close()


def read_commerce_planning_outputs(run: AgentRun) -> dict[str, dict[str, Any]]:
    values = _artifact_outputs(run)
    return {
        "sales_strategy": SalesStrategyOutput.model_validate(values["sales_strategy"]).model_dump(),
        "page_planning": DetailPagePlanOutput.model_validate(values["page_planning"]).model_dump(),
        "copywriting": CopySetOutput.model_validate(values["copywriting"]).model_dump(),
        "visual_planning": VisualPlanOutput.model_validate(values["visual_planning"]).model_dump(),
    }
