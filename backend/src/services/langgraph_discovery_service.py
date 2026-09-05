"""Domain-backed, checkpoint-safe adapters for the LG-2 Discovery graph.

Graph state holds routing data, asset/capture IDs and the immutable fact
snapshot ID/hash only.  Agent-schema outputs are persisted as run artifacts,
outside LangGraph checkpoints, and can be read back through the legacy-output
adapter by the following subgraphs.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy.orm import Session

from src.agents.nodes.input_router.schema import AgentOutputSchema as InputRouterOutput
from src.agents.nodes.reference_analysis.schema import AgentOutputSchema as ReferenceAnalysisOutput
from src.agents.nodes.source_collection.schema import AgentOutputSchema as SourceCollectionOutput
from src.agents.schemas import ProductUnderstandingOutput
from src.config import settings
from src.db.database import SessionLocal
from src.db.models import AgentRun, Asset, FactSnapshot, ProductProject, SourceCapture
from src.services.commerce_policy import FINAL_OUTPUT_ASSET_STATUSES, initial_asset_usage_status


# Graph state must stay serializable and narrow, but synchronous graph nodes
# still need to take part in the request's database transaction.  Keeping the
# active Session in a ContextVar avoids placing an ORM object in checkpointed
# state and avoids a second SQLite writer (the local test runtime) racing the
# projector. Artifacts are committed before a node checkpoint; the existing
# history projector repairs any event projection missed by a process failure.
_active_graph_session: ContextVar[Session | None] = ContextVar("sellform_langgraph_session", default=None)
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def langgraph_execution_session(db: Session) -> Iterator[None]:
    token = _active_graph_session.set(db)
    try:
        yield
    finally:
        _active_graph_session.reset(token)


def current_langgraph_session() -> Session | None:
    """Return the request-scoped graph session without checkpointing it."""

    return _active_graph_session.get()


def _node_session() -> tuple[Session, bool]:
    current = _active_graph_session.get()
    return (current, False) if current is not None else (SessionLocal(), True)


def _artifact_key(stage: str) -> str:
    return stage


def _store_artifact(run_id: str, stage: str, output: dict[str, Any], *, metadata: dict[str, Any] | None = None) -> dict[str, str]:
    """Store a schema-validated node output outside checkpointed graph state."""

    db, owns_session = _node_session()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one()
        payload = dict(run.outputs_json or {})
        artifacts = dict(payload.get("langgraph_discovery_artifacts") or {})
        artifacts[_artifact_key(stage)] = {
            "schema_version": "lg2-v1",
            "output": deepcopy(output),
            "metadata": deepcopy(metadata or {}),
        }
        run.outputs_json = {**payload, "langgraph_discovery_artifacts": artifacts}
        db.add(run)
        # LangGraph checkpoints are committed after a node returns. Persist
        # the artifact first so a process failure between checkpoint and SQL
        # projection can be repaired by LG-1's history replay.
        db.commit()
        return {"artifact_key": _artifact_key(stage), "schema_version": "lg2-v1"}
    finally:
        if owns_session:
            db.close()


def _prompt_fingerprint(agent_name: str) -> str:
    """Load the established prompt contract without storing its text in state."""

    from src.services.prompt_registry import PromptRegistry

    node_prompt_dir = _BACKEND_ROOT / "src" / "agents" / "nodes"
    prompt = PromptRegistry(base_path=str(node_prompt_dir)).load_agent_prompt(agent_name)
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _system_prompt(agent_name: str) -> str:
    from src.services.prompt_registry import PromptRegistry

    system = PromptRegistry(base_path=str(_BACKEND_ROOT / "prompts")).load("system/sellform_agent_base")
    node = PromptRegistry(base_path=str(_BACKEND_ROOT / "src" / "agents" / "nodes")).load_agent_prompt(agent_name)
    return f"{system}\n{node}"


def input_routing_decision(input_snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the old InputRouter schema plus an explicit routing decision."""

    has_name = bool(str(input_snapshot.get("product_name") or "").strip())
    has_text = bool(str(input_snapshot.get("description") or input_snapshot.get("freeform_input") or "").strip())
    has_assets = bool(input_snapshot.get("asset_ids"))
    has_url = bool(input_snapshot.get("product_url") or input_snapshot.get("reference_urls"))
    source_count = sum((has_text, has_assets, has_url))
    input_type = "mixed" if source_count > 1 else "image" if has_assets else "url" if has_url else "text_only"
    output = InputRouterOutput(
        input_type=input_type,
        missing_inputs=[] if has_name else ["product_name"],
    ).model_dump()
    routing = {
        "decision": "continue_with_available_sources" if (has_name or source_count) else "await_input_review",
        "reason": "input_ready" if has_name else "missing_required_input",
        "has_reference_url": has_url,
    }
    return output, routing


def run_input_router(*, run_id: str, input_snapshot: dict[str, Any]) -> dict[str, Any]:
    output, routing = input_routing_decision(input_snapshot)
    return {
        "input_router": {
            **routing,
            **_store_artifact(run_id, "input_router", output, metadata={"prompt_hash": _prompt_fingerprint("input_router")}),
        }
    }


def _asset_output(asset: Asset) -> dict[str, Any]:
    source_type = asset.source_type or "uploaded"
    # The legacy schema did not initially enumerate self-shot/sourced values.
    # Its additive Literal expansion keeps the original field while preserving
    # actual asset provenance.
    return {
        "asset_id": asset.id,
        "filename": asset.filename,
        "source_type": source_type,
        "url": asset.file_path if str(asset.file_path).startswith("http") else None,
        "asset_role": asset.asset_role or "unknown",
        "role_confidence": float(asset.role_confidence or 0.0),
        "quality_status": asset.quality_status or "warning",
        "quality_warnings": list(asset.quality_warnings or []),
        "is_representative": bool(asset.is_representative),
        "usage_status": asset.usage_status or initial_asset_usage_status(source_type),
    }


def _capture_status(capture: SourceCapture | None) -> str:
    if capture is None:
        return "not_collected"
    return str(capture.collection_status or "not_collected")


def collect_discovery_sources(*, run_id: str, project_id: str, input_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Use existing asset/OCR services and return a legacy-schema artifact.

    Collection and inspection failures are represented as routing data. They do
    not become graph exceptions and cannot prevent seller-owned uploads from
    moving through Discovery.
    """

    db, owns_session = _node_session()
    try:
        from src.services.asset_understanding_service import (
            project_asset_understanding_blockers,
            run_project_asset_inspections,
        )

        requested_ids = list(dict.fromkeys(input_snapshot.get("asset_ids") or []))
        # This invokes the established OCR/asset-understanding domain service;
        # it is idempotent in the sense that each inspection is versioned.
        run_project_asset_inspections(project_id, db, requested_ids or None)
        asset_blockers = project_asset_understanding_blockers(project_id, db, asset_ids=requested_ids or None)

        assets_query = db.query(Asset).filter(Asset.project_id == project_id)
        assets = assets_query.filter(Asset.id.in_(requested_ids)).all() if requested_ids else assets_query.all()
        uploaded_images: list[dict[str, Any]] = []
        reference_images: list[dict[str, Any]] = []
        url_images: list[dict[str, Any]] = []
        for asset in assets:
            item = _asset_output(asset)
            if item["source_type"] in {"url-extracted", "url-imported"}:
                url_images.append(item)
            elif item["usage_status"] in FINAL_OUTPUT_ASSET_STATUSES:
                uploaded_images.append(item)
            else:
                reference_images.append(item)

        project = db.query(ProductProject).filter(ProductProject.id == project_id).one()
        product_url = str(input_snapshot.get("product_url") or project.raw_input_url or "")
        reference_urls = [str(value) for value in (input_snapshot.get("reference_urls") or []) if value]
        urls = list(dict.fromkeys([*( [product_url] if product_url else [] ), *reference_urls]))
        captures = db.query(SourceCapture).filter(SourceCapture.project_id == project_id).all()
        by_url = {capture.url: capture for capture in captures}
        completed_capture_ids: list[str] = []
        failures: list[dict[str, str]] = []
        for url in urls:
            capture = by_url.get(url)
            status = _capture_status(capture)
            if status in {"completed", "collected"}:
                completed_capture_ids.append(capture.id)
            else:
                failures.append({
                    "url": url,
                    "code": (capture.failure_code if capture else None) or status,
                    "message": (capture.error_message if capture else None) or "Source collection is unavailable; seller uploads can continue.",
                })

        output = SourceCollectionOutput(
            product_url=product_url,
            freeform_input=str(input_snapshot.get("freeform_input") or ""),
            reference_urls=reference_urls,
            uploaded_images=uploaded_images,
            url_images=url_images,
            reference_images=reference_images,
            # URL/OCR source text remains in SourceCapture/inspection records,
            # not in a checkpoint or broad graph output.
            reference_text_blocks=[],
            source_summary={
                "has_uploaded_image": bool(uploaded_images),
                "has_product_url": bool(product_url),
                "has_freeform_input": bool(input_snapshot.get("freeform_input")),
                "has_reference_url": bool(reference_urls),
                "primary_visual_source": "uploaded" if uploaded_images else "url" if product_url else "none",
            },
            collection_failures=failures,
            asset_understanding_blockers=asset_blockers,
        ).model_dump()
        routing = {
            "routing_decision": "continue_with_direct_uploads" if failures and uploaded_images else "continue_without_url_evidence" if failures else "sources_ready",
            "has_reference_url": bool(urls),
            "completed_capture_ids": completed_capture_ids,
            "asset_ids": [item["asset_id"] for item in uploaded_images],
            "reference_asset_ids": [item["asset_id"] for item in reference_images],
            "collection_failure_count": len(failures),
            "asset_blocker_count": len(asset_blockers),
        }
        return {
            "source_collection": {
                **routing,
                **_store_artifact(run_id, "source_collection", output, metadata={"prompt_hash": _prompt_fingerprint("source_collection")}),
            }
        }
    finally:
        if owns_session:
            db.close()


def _ensure_fact_snapshot(*, run_id: str, project_id: str, input_snapshot: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]], list[dict[str, str]]]:
    """Create/reuse one approved snapshot through the existing fact-board API."""

    db, owns_session = _node_session()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.project_id == project_id).one()
        snapshot_id = input_snapshot.get("approved_fact_snapshot_id") or (run.input_snapshot or {}).get("approved_fact_snapshot_id")
        snapshot_hash = input_snapshot.get("approved_fact_snapshot_hash") or (run.input_snapshot or {}).get("approved_fact_snapshot_hash")
        snapshot = None
        if snapshot_id:
            snapshot = db.query(FactSnapshot).filter(FactSnapshot.id == snapshot_id, FactSnapshot.project_id == project_id).first()
            if snapshot and snapshot_hash and snapshot.snapshot_hash != snapshot_hash:
                raise ValueError("Approved fact snapshot hash does not match the persisted snapshot.")
        if snapshot is None:
            from src.services.fact_evidence_service import approved_fact_snapshot, fact_board_blockers, refresh_evidence_board

            refresh_evidence_board(db, run.project, run.created_by)
            blockers = fact_board_blockers(db, project_id)
            snapshot = approved_fact_snapshot(db, project_id, run.created_by, purpose="langgraph_discovery")
            run.input_snapshot = {
                **(run.input_snapshot or {}),
                "approved_fact_snapshot_id": snapshot.id,
                "approved_fact_snapshot_hash": snapshot.snapshot_hash,
            }
            db.add(run)
            # The fact snapshot reference is about to enter a checkpoint, so
            # its database row must already be durable before the node exits.
            db.commit()
        else:
            from src.services.fact_evidence_service import fact_board_blockers
            blockers = fact_board_blockers(db, project_id)
        return ({"id": snapshot.id, "hash": snapshot.snapshot_hash}, list(snapshot.facts_json or []), blockers)
    finally:
        if owns_session:
            db.close()


def _product_output(*, mode: str, input_snapshot: dict[str, Any], facts: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Preserve prompt/schema use while making snapshot facts authoritative."""

    product_name = str(input_snapshot.get("product_name") or "상품")
    approved_texts = [str(item.get("fact_text") or "") for item in facts if item.get("fact_text")]
    metadata: dict[str, Any] = {"prompt_hash": _prompt_fingerprint("product_understanding")}
    if mode == "real":
        from src.services.llm_router import get_text_provider_by_settings
        from src.services.provider_adapters import ProviderRequest

        result = get_text_provider_by_settings().generate_json(ProviderRequest(
            provider="router",
            model="configured",
            system_prompt=_system_prompt("product_understanding"),
            user_prompt=json.dumps({"product_input": input_snapshot, "approved_fact_snapshot": facts}, ensure_ascii=False),
            schema_name="product_understanding",
            product_name=product_name,
        ))
        output = ProductUnderstandingOutput.model_validate(result["content"]).model_dump()
        metadata.update({"provider": result.get("provider"), "model": result.get("model"), "token_usage": result.get("token_usage"), "cost": result.get("cost")})
    else:
        from src.agents.mock_outputs import build_mock_product_understanding
        output = ProductUnderstandingOutput.model_validate(
            build_mock_product_understanding(product_name, str(input_snapshot.get("description") or ""))
        ).model_dump()
        metadata.update({"provider": "mock", "model": "mock-text"})

    # Providers may describe plausible but unsupported values. Only the fact
    # snapshot can populate verified_facts; all other generated claims remain
    # suggestions/verification requirements.
    output["verified_facts"] = approved_texts
    output["verification_required"] = list(dict.fromkeys([
        *(output.get("verification_required") or []),
        *( ["approved_product_facts"] if not approved_texts else [] ),
    ]))
    return ProductUnderstandingOutput.model_validate(output).model_dump(), metadata


def run_product_understanding(*, run_id: str, project_id: str, mode: str, input_snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    reference, facts, blockers = _ensure_fact_snapshot(run_id=run_id, project_id=project_id, input_snapshot=input_snapshot)
    output, metadata = _product_output(mode=mode, input_snapshot=input_snapshot, facts=facts)
    return (
        {
            "fact_snapshot": reference,
            "product_understanding": {
                "fact_snapshot_id": reference["id"],
                "fact_snapshot_hash": reference["hash"],
                "fact_blocker_count": len(blockers),
                **_store_artifact(run_id, "product_understanding", output, metadata=metadata),
            },
        },
        {"approved_fact_snapshot_id": reference["id"], "approved_fact_snapshot_hash": reference["hash"]},
    )


def run_reference_analysis(*, run_id: str, source_state: dict[str, Any]) -> dict[str, Any]:
    """Return the preserved ReferenceAnalysis schema from safe capture metadata."""

    completed = bool(source_state.get("completed_capture_ids"))
    if not completed:
        output = ReferenceAnalysisOutput(
            skipped=True,
            reference_available=False,
            recommended_rewrite_direction="Use seller-approved facts and original copy only.",
        ).model_dump()
        reason = "collection_failed" if source_state.get("collection_failure_count") else "no_completed_reference_capture"
    else:
        output = ReferenceAnalysisOutput(
            skipped=False,
            reference_available=True,
            structure_takeaways=["Use an original problem-to-solution information flow."],
            visual_takeaways=["Use seller-authorized assets for product proof."],
            copy_risk_notes=["Do not reproduce supplier headings, copy, or layout verbatim."],
            recommended_rewrite_direction="Create original structure and copy from approved facts.",
        ).model_dump()
        reason = ""
    return {
        "reference_analysis": {
            "skipped": bool(output["skipped"]),
            "skip_reason": reason or None,
            **_store_artifact(run_id, "reference_analysis", output, metadata={"prompt_hash": _prompt_fingerprint("reference_analysis")}),
        }
    }


def run_reference_analysis_skip(*, run_id: str) -> dict[str, Any]:
    output = ReferenceAnalysisOutput(
        skipped=True,
        reference_available=False,
        recommended_rewrite_direction="Use seller-approved facts and original copy only.",
    ).model_dump()
    return {
        "reference_analysis": {
            "skipped": True,
            "skip_reason": "no_reference_url",
            **_store_artifact(run_id, "reference_analysis", output, metadata={"prompt_hash": _prompt_fingerprint("reference_analysis")}),
        }
    }


def read_legacy_discovery_outputs(run: AgentRun, db: Session) -> dict[str, dict[str, Any]]:
    """Expose LG-2 artifacts with the existing four-agent output schemas."""

    artifacts = ((run.outputs_json or {}).get("langgraph_discovery_artifacts") or {})
    def output(stage: str) -> dict[str, Any]:
        value = (artifacts.get(stage) or {}).get("output") or {}
        return dict(value)
    return {
        "input_router": InputRouterOutput.model_validate(output("input_router")).model_dump(),
        "source_collection": SourceCollectionOutput.model_validate(output("source_collection")).model_dump(),
        "product_understanding": ProductUnderstandingOutput.model_validate(output("product_understanding")).model_dump(),
        "reference_analysis": ReferenceAnalysisOutput.model_validate(output("reference_analysis")).model_dump(),
    }


def compatible_product_brief(run: AgentRun, db: Session) -> dict[str, Any]:
    """Return the established ProductBrief shape plus LG-2 agent outputs.

    The canonical brief remains generated by the existing evidence-aware
    service; this adapter proves that LG-2 consumes the same project/fact data
    and hands later graph subgraphs a compatible representation.
    """

    from src.services.api_ready_generation_service import build_generation_plan

    plan = build_generation_plan(run.project, db)
    return {
        "product_brief": plan["product_brief"],
        "discovery_outputs": read_legacy_discovery_outputs(run, db),
    }
