"""LG-0 LangGraph runtime foundation.

This module intentionally does not replace the existing ``AgentGraph`` yet.
It proves that Sellform has a real, compiled LangGraph runtime and provides a
small, checkpoint-safe input boundary for subsequent migration sprints.
"""

from __future__ import annotations

import copy
from contextlib import contextmanager
from operator import add
from typing import Any, Iterator, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import Annotated, TypedDict

from src.config import settings


GraphRuntime = Literal["legacy", "langgraph"]

LEGACY_GRAPH_RUNTIME: GraphRuntime = "legacy"
LANGGRAPH_GRAPH_RUNTIME: GraphRuntime = "langgraph"

# These are product-input values already stored on AgentRun. Provider keys,
# request headers, sessions and arbitrary caller fields must never enter a
# persisted graph checkpoint.
CHECKPOINT_SAFE_INPUT_FIELDS = frozenset(
    {
        "product_name",
        "category",
        "description",
        "feature_details",
        "components",
        "cautions",
        "product_url",
        "freeform_input",
        "asset_ids",
        "reference_urls",
        "selling_points",
        "price",
        "shipping",
        "sales_channel",
        "model_options",
        "desired_mood",
        "ux_auto_generate",
        "approved_fact_snapshot_id",
        "approved_fact_snapshot_hash",
        "prompt_intelligence_snapshot",
        "interaction_mode",
        "creative_brief_snapshot",
    }
)


def _checkpoint_safe_input_snapshot_reducer(
    current: dict[str, Any],
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    """Enforce the snapshot allowlist even when callers bypass the helper."""

    return {**(current or {}), **checkpoint_safe_input_snapshot(update)}


def _merge_discovery(
    current: dict[str, Any] | None,
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    """Accumulate per-agent discovery deltas without retaining raw evidence."""

    return {**(current or {}), **(update or {})}


class LG0GraphState(TypedDict):
    """Minimal state contract used only to establish the LangGraph runtime."""

    run_id: str
    project_id: str
    input_snapshot: Annotated[dict[str, Any], _checkpoint_safe_input_snapshot_reducer]
    events: Annotated[list[str], add]


class SellformGraphState(TypedDict, total=False):
    """Durable, JSON-serializable state used by the LG-1 runtime.

    It deliberately contains identifiers and approved input only. ORM sessions,
    provider clients, request headers and raw image bytes stay outside the graph
    checkpoint and are resolved by nodes in later migration sprints.
    """

    run_id: str
    thread_id: str
    workspace_id: str
    project_id: str
    mode: str
    input_snapshot: Annotated[dict[str, Any], _checkpoint_safe_input_snapshot_reducer]
    current_stage: str
    status: str
    events: Annotated[list[dict[str, Any]], add]
    errors: Annotated[list[dict[str, str]], add]
    # LG-2 keeps only operational discovery summaries in the checkpoint. Fact
    # payloads/evidence are resolved transiently from this reference in nodes.
    discovery: Annotated[dict[str, Any], _merge_discovery]
    # LG-3 persists only planning artifact references and hashes here. Full
    # strategy/copy/scene payloads are kept in run artifacts, never state.
    commerce: Annotated[dict[str, Any], _merge_discovery]
    # LG-4 keeps only review decisions and payload metadata in the checkpoint.
    # The pending request itself is also projected to AgentRun.outputs_json so
    # a refreshed browser can display it without replaying graph execution.
    review: Annotated[dict[str, Any], _merge_discovery]
    # LG-5 stores compact job IDs/statuses and approved output asset IDs only.
    # Prompts, image bytes and provider secrets remain in domain records.
    generation: Annotated[dict[str, Any], _merge_discovery]
    # LG-6 stores classification confidence and immutable pack/Brand Kit
    # references only; full compiled prompts live in SQL artifacts.
    prompt_intelligence: Annotated[dict[str, Any], _merge_discovery]
    # LG-7 keeps only the immutable compiler artifact identity in checkpoints.
    # Review corpora and reference bodies remain in their versioned SQL tables.
    creative_brief: Annotated[dict[str, Any], _merge_discovery]


def configured_graph_runtime() -> GraphRuntime:
    """Return the validated runtime selection without activating migration code."""

    return settings.SELLFORM_GRAPH_RUNTIME


def langgraph_runtime_enabled() -> bool:
    """Whether a later Sprint may route a newly created run through LangGraph."""

    return configured_graph_runtime() == LANGGRAPH_GRAPH_RUNTIME


def checkpoint_safe_input_snapshot(input_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Build a narrow, serializable graph input without provider secrets.

    The allowlist is deliberate: filtering known secret names is fragile, while
    a new arbitrary request field should not silently become durable workflow
    state. Domain snapshots and asset IDs are persisted by their own services.
    """

    snapshot = input_snapshot or {}
    return {
        key: copy.deepcopy(value)
        for key, value in snapshot.items()
        if key in CHECKPOINT_SAFE_INPUT_FIELDS
    }


def build_lg0_graph_input(
    *,
    run_id: str,
    project_id: str,
    input_snapshot: dict[str, Any] | None = None,
) -> LG0GraphState:
    """Create the only state payload permitted to enter the LG-0 graph."""

    return {
        "run_id": run_id,
        "project_id": project_id,
        "input_snapshot": checkpoint_safe_input_snapshot(input_snapshot),
        "events": [],
    }


def build_lg1_graph_input(
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    mode: str,
    input_snapshot: dict[str, Any] | None = None,
) -> SellformGraphState:
    """Build the durable initial state for one ``AgentRun`` thread.

    ``thread_id`` is intentionally the same value as ``run_id``. This one-to-
    one contract prevents a resume request from accidentally reading another
    run's history.
    """

    return {
        "run_id": run_id,
        "thread_id": run_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "mode": mode,
        "input_snapshot": checkpoint_safe_input_snapshot(input_snapshot),
        "current_stage": "intake",
        "status": "created",
        "events": [],
        "errors": [],
    }


def _bootstrap_run(_: LG0GraphState) -> dict[str, list[str]]:
    return {"events": ["bootstrap_run"]}


def _finalize_run(_: LG0GraphState) -> dict[str, list[str]]:
    return {"events": ["finalize_run"]}


def build_lg0_compiled_graph(
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
):
    """Return a real compiled StateGraph used by LG-0 tests and later Sprints.

    LG-1 replaces the minimal nodes with durable execution adapters and a
    PostgreSQL checkpointer. Keeping this graph tiny ensures LG-0 cannot alter
    the production generation path by accident.
    """

    graph = StateGraph(LG0GraphState)
    graph.add_node("bootstrap_run", _bootstrap_run)
    graph.add_node("finalize_run", _finalize_run)
    graph.add_edge(START, "bootstrap_run")
    graph.add_edge("bootstrap_run", "finalize_run")
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def _graph_node_event(stage: str, status: str) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,  # overall graph-run status after this node
        "node_status": "completed",
        "event_type": "node_completed",
    }


def _lg1_bootstrap_run(_: SellformGraphState) -> dict[str, Any]:
    return {
        "current_stage": "bootstrap_run",
        "status": "running",
        "events": [_graph_node_event("bootstrap_run", "running")],
    }


def _lg1_test_node(_: SellformGraphState) -> dict[str, Any]:
    """Temporary deterministic node proving durable multi-node execution.

    Domain agents replace this node incrementally from LG-2 onward.
    """

    return {
        "current_stage": "lg1_test_node",
        "status": "running",
        "events": [_graph_node_event("lg1_test_node", "running")],
    }


def _lg1_finalize_run(_: SellformGraphState) -> dict[str, Any]:
    return {
        "current_stage": "finalize_run",
        "status": "completed",
        "events": [_graph_node_event("finalize_run", "completed")],
    }


def _lg2_event(stage: str, *, node_status: str = "completed") -> dict[str, Any]:
    return {
        **_graph_node_event(stage, "running"),
        "node_status": node_status,
        "event_type": "node_skipped" if node_status == "skipped" else "node_completed",
    }


def _lg2_input_router(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.input_router.agent import InputRouterAgent

    discovery = InputRouterAgent().run_delta(
        run_id=state["run_id"],
        input_snapshot=state.get("input_snapshot") or {},
    )
    return {
        "current_stage": "input_router",
        "status": "running",
        "discovery": discovery,
        "events": [_lg2_event("input_router")],
    }


def _lg2_source_collection(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.source_collection.agent import SourceCollectionAgent

    discovery = SourceCollectionAgent().run_delta(
        run_id=state["run_id"],
        project_id=state["project_id"],
        input_snapshot=state.get("input_snapshot") or {},
    )
    return {
        "current_stage": "source_collection",
        "status": "running",
        "discovery": discovery,
        "events": [_lg2_event("source_collection")],
    }


def _lg2_product_understanding(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.product_understanding.agent import ProductUnderstandingAgent

    snapshot = state.get("input_snapshot") or {}
    discovery, snapshot_update = ProductUnderstandingAgent().run_delta(
        run_id=state["run_id"],
        project_id=state["project_id"],
        mode=state.get("mode") or "mock",
        input_snapshot=snapshot,
    )
    # No `facts` field is returned: raw fact/evidence data is intentionally
    # not persisted in the graph state. Later nodes use this ID/hash reference.
    return {
        "current_stage": "product_understanding",
        "status": "running",
        "discovery": discovery,
        "input_snapshot": snapshot_update,
        "events": [_lg2_event("product_understanding")],
    }


def _lg2_reference_analysis(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.reference_analysis.agent import ReferenceAnalysisAgent

    source_collection = ((state.get("discovery") or {}).get("source_collection") or {})
    return {
        "current_stage": "reference_analysis",
        "status": "running",
        "discovery": ReferenceAnalysisAgent().run_delta(run_id=state["run_id"], source_collection=source_collection),
        "events": [_lg2_event("reference_analysis")],
    }


def _lg2_reference_analysis_skipped(state: SellformGraphState) -> dict[str, Any]:
    """Record a graph-level skip without invoking a reference-analysis agent."""

    from src.services.langgraph_discovery_service import run_reference_analysis_skip

    return {
        "current_stage": "reference_analysis",
        "status": "running",
        "discovery": run_reference_analysis_skip(run_id=state["run_id"]),
        "events": [_lg2_event("reference_analysis", node_status="skipped")],
    }


def _lg2_finalize_run(_: SellformGraphState) -> dict[str, Any]:
    return {
        "current_stage": "finalize_run",
        "status": "completed",
        "events": [_graph_node_event("finalize_run", "completed")],
    }


def _lg3_sales_strategy(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.sales_strategy.agent import SalesStrategyAgent
    return {"current_stage": "sales_strategy", "status": "running", "commerce": SalesStrategyAgent().run_delta(
        run_id=state["run_id"], project_id=state["project_id"], mode=state.get("mode") or "mock"), "events": [_lg2_event("sales_strategy")]}


def _lg6_category_classifier(state: SellformGraphState) -> dict[str, Any]:
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.prompt_intelligence_service import classify_category

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-6 category classifier requires the graph database session.")
    snapshot = state.get("input_snapshot") or {}
    text = " ".join(str(snapshot.get(key) or "") for key in (
        "product_name", "category", "description", "feature_details", "components", "freeform_input"))
    classification = classify_category(text, snapshot.get("category"))
    return {
        "current_stage": "category_classifier", "status": "running",
        "prompt_intelligence": {"classification": classification},
        "events": [_lg2_event("category_classifier")],
    }


def _lg6_prompt_pack_resolver(state: SellformGraphState) -> dict[str, Any]:
    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.prompt_intelligence_service import compile_for_run, seed_prompt_packs

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-6 prompt pack resolver requires the graph database session.")
    run = db.query(AgentRun).filter_by(id=state["run_id"], workspace_id=state["workspace_id"]).one()
    classification = dict((state.get("prompt_intelligence") or {}).get("classification") or {})
    try:
        artifact = compile_for_run(db, run, classification)
    except LookupError:
        seed_prompt_packs(db, state["workspace_id"], run.created_by)
        artifact = compile_for_run(db, run, classification)
    pinned = dict((run.input_snapshot or {}).get("prompt_intelligence_snapshot") or {})
    return {
        "current_stage": "prompt_pack_resolver", "status": "running",
        "input_snapshot": {"prompt_intelligence_snapshot": pinned},
        "prompt_intelligence": {
            "classification": pinned.get("classification") or classification,
            "category_pack_version_id": artifact.category_pack_version_id,
            "category_pack_hash": artifact.category_pack_hash,
            "channel_pack_version_id": artifact.channel_pack_version_id,
            "channel_pack_hash": artifact.channel_pack_hash,
            "brand_kit_version_id": artifact.brand_kit_version_id,
            "brand_kit_hash": artifact.brand_kit_hash,
            "compiled_artifact_id": artifact.id,
            "compiled_artifact_hash": artifact.output_hash,
            "compiler_version": artifact.compiler_version,
        },
        "events": [_lg2_event("prompt_pack_resolver")],
    }


def _lg7_creative_brief_compiler(state: SellformGraphState) -> dict[str, Any]:
    from src.db.models import AgentRun
    from src.services.creative_brief_service import compile_creative_brief
    from src.services.langgraph_discovery_service import current_langgraph_session

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-7 creative brief compiler requires the graph database session.")
    run = db.query(AgentRun).filter_by(id=state["run_id"], workspace_id=state["workspace_id"]).one()
    brief = compile_creative_brief(db, run)
    pinned = dict((run.input_snapshot or {}).get("creative_brief_snapshot") or {})
    return {
        "current_stage": "creative_brief_compiler", "status": "running",
        "input_snapshot": {"creative_brief_snapshot": pinned},
        "creative_brief": {
            "id": brief.id, "version": brief.version, "input_hash": brief.input_hash,
            "output_hash": brief.output_hash, "fact_snapshot_id": brief.fact_snapshot_id,
            "fact_snapshot_hash": brief.fact_snapshot_hash,
            "compiled_prompt_artifact_id": brief.compiled_prompt_artifact_id,
            "brand_kit_version_id": brief.brand_kit_version_id,
            "brand_kit_hash": brief.brand_kit_hash,
        },
        "events": [_lg2_event("creative_brief_compiler")],
    }


def _lg3_page_planning(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.page_planning.agent import PagePlanningAgent
    return {"current_stage": "page_planning", "status": "running", "commerce": PagePlanningAgent().run_delta(
        run_id=state["run_id"], project_id=state["project_id"], mode=state.get("mode") or "mock"), "events": [_lg2_event("page_planning")]}


def _lg3_copywriting(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.copywriting.agent import CopywritingAgent
    return {"current_stage": "copywriting", "status": "running", "commerce": CopywritingAgent().run_delta(
        run_id=state["run_id"], project_id=state["project_id"], mode=state.get("mode") or "mock"), "events": [_lg2_event("copywriting")]}


def _lg3_visual_planning(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.visual_planning.agent import VisualPlanningAgent
    return {"current_stage": "visual_planning", "status": "running", "commerce": VisualPlanningAgent().run_delta(
        run_id=state["run_id"], project_id=state["project_id"], mode=state.get("mode") or "mock"), "events": [_lg2_event("visual_planning")]}


def _lg8_visual_prompt_compiler(state: SellformGraphState) -> dict[str, Any]:
    """Compile immutable scene prompts inside the checkpointed graph thread."""

    from src.db.models import ProductProject
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.visual_prompt_compiler_service import compile_project_scene_prompts

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-8 visual prompt compiler requires the graph database session.")
    project = db.query(ProductProject).filter(ProductProject.id == state["project_id"]).one()
    creative_brief = dict(state.get("creative_brief") or {})
    rows = compile_project_scene_prompts(
        project,
        db,
        run_id=state["run_id"],
        brand_kit_version_id=creative_brief.get("brand_kit_version_id"),
        brand_kit_hash=creative_brief.get("brand_kit_hash"),
    )
    artifact = {
        "schema_version": "lg8-v1",
        "compiler_version": "lg8-visual-prompt-compiler-v1",
        "scene_count": len(rows),
        "scene_prompts": [
            {
                "id": row.id,
                "scene_id": row.scene_id,
                "scene_type": row.scene_type,
                "version": row.version,
                "prompt_version": row.prompt_version,
                "prompt_hash": row.prompt_hash,
                "reference_hash": row.reference_hash,
                "brand_kit_version_id": row.brand_kit_version_id,
                "brand_kit_visual_hash": row.brand_kit_visual_hash,
            }
            for row in rows
        ],
    }
    return {
        "current_stage": "visual_prompt_compiler",
        "status": "running",
        "commerce": {"visual_prompt_compiler": artifact},
        "events": [_lg2_event("visual_prompt_compiler")],
    }


def _lg4_review_event(stage: str) -> dict[str, Any]:
    return {
        **_lg2_event(stage),
        "review": {"last_resolved_stage": stage, "last_decision": "approve"},
    }


def _lg4_wait_for_seller_review(stage: str, state: SellformGraphState) -> dict[str, Any]:
    """Pause at a durable LangGraph interrupt until the seller approves.

    A rejection does not advance any domain node.  Calling ``interrupt`` again
    records a new checkpoint with the same stage, so refreshes and duplicate
    clicks cannot cause downstream planning or provider work.
    """

    from src.db.models import AgentRun
    from src.services.creative_brief_service import normalize_interaction_mode, record_gate_event
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_review_service import approval_blocker, review_interrupt_payload, validate_resume_payload

    blocker = approval_blocker(stage, state)
    db = current_langgraph_session()
    run = None
    if db is not None:
        run = db.query(AgentRun).filter_by(
            id=state["run_id"], workspace_id=state["workspace_id"],
        ).one()
    # The database snapshot is authoritative here. A seller can switch modes
    # while the graph is interrupted; the persisted LangGraph checkpoint still
    # contains the original input snapshot until the node resumes.
    mode_value = (
        (run.input_snapshot or {}).get("interaction_mode")
        if run is not None
        else (state.get("input_snapshot") or {}).get("interaction_mode")
    )
    interaction_mode = normalize_interaction_mode(mode_value)
    # Quick mode may skip only reversible, zero-cost gates with no rights/fact
    # blocker. Cost approval, provider dispatch and generated-image review are
    # intentionally outside this allowlist.
    if interaction_mode == "quick" and stage in {"input_review", "evidence_review", "planning_review"} and not blocker:
        if db is not None and run is not None:
            record_gate_event(db, run, stage=stage, decision="approve", source="quick_auto",
                              rationale="Safe, reversible, zero-cost gate without rights or fact blockers.")
        return {
            "current_stage": stage, "status": "running",
            "review": {"last_resolved_stage": stage, "last_decision": "approve", "decision_source": "quick_auto"},
            "events": [_lg4_review_event(stage)],
        }

    rejection_reason = ""
    while True:
        raw_response = interrupt(review_interrupt_payload(
            stage, state, rejection_reason=rejection_reason, schema_version="lg4-v1",
        ))
        response = validate_resume_payload(raw_response, stage)
        if response.decision == "approve":
            blocker = approval_blocker(stage, state)
            if blocker:
                rejection_reason = blocker
                continue
            if db is not None and run is not None:
                record_gate_event(db, run, stage=stage, decision="approve", source="seller",
                                  rationale=response.comment or "Seller approved the gate.")
            return {
                "current_stage": stage,
                "status": "running",
                "review": {
                    "last_resolved_stage": stage,
                    "last_decision": response.decision,
                    "comment": response.comment,
                },
                "events": [_lg4_review_event(stage)],
            }
        rejection_reason = response.comment or "판매자가 검토를 반려했습니다. 입력 또는 기획을 수정한 뒤 다시 승인해 주세요."


def _lg4_input_review(state: SellformGraphState) -> dict[str, Any]:
    return _lg4_wait_for_seller_review("input_review", state)


def _lg4_evidence_review(state: SellformGraphState) -> dict[str, Any]:
    return _lg4_wait_for_seller_review("evidence_review", state)


def _lg4_planning_review(state: SellformGraphState) -> dict[str, Any]:
    review_result = _lg4_wait_for_seller_review("planning_review", state)
    # LG-5 must never create a chargeable image job from a merely generated
    # draft.  This maps the graph interrupt approval to the existing durable
    # storyboard approval invariant before the execution can reach its image
    # cost gate.
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import approve_graph_storyboard

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-4 planning approval requires the graph database session.")
    approval = approve_graph_storyboard(project_id=state["project_id"], db=db)
    return {
        **review_result,
        "discovery": {
            "planning_review": {
                "storyboard_status": approval["status"],
                "storyboard_revision": approval["revision"],
                "schema_version": "lg5-v1",
            }
        },
    }


def _lg5_event(stage: str, *, node_status: str = "completed") -> dict[str, Any]:
    return _lg2_event(stage, node_status=node_status)


def _lg5_generation_pending(state: SellformGraphState) -> dict[str, Any]:
    """Cost/provider gate. A defer or unavailable provider never dispatches."""

    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import ensure_generation_cost_plan, record_cost_decision
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload
    from src.services.storyboard_image_generation_service import storyboard_image_generation_is_available

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-5R cost approval requires the graph database session.")
    prior_generation = dict(state.get("generation") or {})
    scene_ids = list(prior_generation.get("regenerate_scene_ids") or []) or None
    cost_plan = ensure_generation_cost_plan(
        run_id=state["run_id"], project_id=state["project_id"], db=db, scene_ids=scene_ids,
    )
    generation = {**prior_generation, "cost_plan": cost_plan, "cost_approved": False}
    reason = "장면별 모델과 예상 비용을 확인한 뒤 승인하거나 비용 없이 대기할 수 있습니다."
    raw_response = interrupt(review_interrupt_payload(
        "generation_pending", {**state, "generation": generation}, rejection_reason=reason,
    ))
    response = validate_resume_payload(raw_response, "generation_pending")
    if response.decision == "defer":
        cost_plan = record_cost_decision(
            run_id=state["run_id"], project_id=state["project_id"], cost_plan_hash=cost_plan["cost_plan_hash"],
            decision="defer", db=db,
        )
        generation.update({"cost_plan": cost_plan, "cost_approved": False, "next_action": "cost_approval"})
        return {
            "current_stage": "generation_pending", "status": "running", "generation": generation,
            "events": [_lg5_event("generation_pending", node_status="deferred")],
        }
    if state.get("mode") != "mock" and not storyboard_image_generation_is_available():
        generation.update({"cost_approved": False, "next_action": "cost_approval", "error_code": "API_KEY_MISSING"})
        return {
            "current_stage": "generation_pending", "status": "running", "generation": generation,
            "events": [_lg5_event("generation_pending", node_status="blocked")],
        }
    cost_plan = record_cost_decision(
        run_id=state["run_id"], project_id=state["project_id"], cost_plan_hash=cost_plan["cost_plan_hash"],
        decision="approve", db=db,
    )
    generation.update({
        "cost_approved": True, "cost_plan": cost_plan, "cost_plan_hash": cost_plan["cost_plan_hash"],
        "regenerate_scene_ids": scene_ids or [], "next_action": "prepare",
    })
    return {
        "current_stage": "generation_pending", "status": "running",
        "review": {"last_resolved_stage": "generation_pending", "last_decision": "approve"},
        "generation": generation, "events": [_lg4_review_event("generation_pending")],
    }


def _lg5_generation_pending_route(state: SellformGraphState) -> str:
    return "prepare_image_jobs" if (state.get("generation") or {}).get("cost_approved") else "generation_pending"


def _lg5_prepare_image_jobs(state: SellformGraphState) -> dict[str, Any]:
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import prepare_graph_image_jobs

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-5 image preparation requires the graph database session.")
    generation = prepare_graph_image_jobs(
        run_id=state["run_id"], project_id=state["project_id"], mode=state.get("mode") or "mock", db=db,
        cost_plan_hash=str((state.get("generation") or {}).get("cost_plan_hash") or ""),
        scene_attempts=dict((state.get("generation") or {}).get("scene_attempts") or {}),
    )
    return {"current_stage": "prepare_image_jobs", "status": "running", "generation": generation, "events": [_lg5_event("prepare_image_jobs")]}


def _lg5_dispatch_image_jobs(state: SellformGraphState) -> dict[str, Any]:
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import dispatch_graph_image_jobs

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-5 image dispatch requires the graph database session.")
    generation = dispatch_graph_image_jobs(
        run_id=state["run_id"], project_id=state["project_id"], mode=state.get("mode") or "mock", db=db,
    )
    return {"current_stage": "dispatch_image_jobs", "status": "running", "generation": generation, "events": [_lg5_event("dispatch_image_jobs")]}


def _lg5_provider_wait(state: SellformGraphState) -> dict[str, Any]:
    """Interrupt only while durable provider jobs are unfinished.

    A worker resumes this exact interrupt with ``refresh`` after it commits a
    job result. A manual refresh is harmless and helps recover lost callbacks.
    """

    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import collect_graph_image_results
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-5 provider wait requires the graph database session.")
    generation = collect_graph_image_results(run_id=state["run_id"], project_id=state["project_id"], db=db)
    if generation.get("pending_count", 0):
        raw_response = interrupt(review_interrupt_payload("provider_wait", {**state, "generation": generation}))
        validate_resume_payload(raw_response, "provider_wait")
        generation = collect_graph_image_results(run_id=state["run_id"], project_id=state["project_id"], db=db)
    generation["next_action"] = "wait" if generation.get("pending_count", 0) else "collect"
    return {"current_stage": "provider_wait", "status": "running", "generation": generation, "events": [_lg5_event("provider_wait")]}


def _lg5_provider_wait_route(state: SellformGraphState) -> str:
    return "provider_wait" if (state.get("generation") or {}).get("pending_count", 0) else "collect_image_results"


def _lg5_collect_image_results(state: SellformGraphState) -> dict[str, Any]:
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import collect_graph_image_results

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-5 result collection requires the graph database session.")
    generation = collect_graph_image_results(run_id=state["run_id"], project_id=state["project_id"], db=db)
    return {"current_stage": "collect_image_results", "status": "running", "generation": generation, "events": [_lg5_event("collect_image_results")]}


def _lg5_validate_generated_images(state: SellformGraphState) -> dict[str, Any]:
    generation = dict(state.get("generation") or {})
    # The image service already persisted identity, OCR, QR/price/logo and
    # rights checks per job. State exposes only the result/asset references.
    generation["validation_complete"] = True
    generation["approved_generated_asset_ids"] = list(generation.get("approved_asset_ids") or [])
    generation["review_generated_asset_ids"] = list(generation.get("review_asset_ids") or [])
    return {"current_stage": "validate_generated_images", "status": "running", "generation": generation, "events": [_lg5_event("validate_generated_images")]}


def _lg5_image_review(state: SellformGraphState) -> dict[str, Any]:
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import apply_image_review
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-5 image review requires the graph database session.")
    generation = dict(state.get("generation") or {})
    raw_response = interrupt(review_interrupt_payload("image_review", {**state, "generation": generation}))
    response = validate_resume_payload(raw_response, "image_review")
    generation = apply_image_review(
        run_id=state["run_id"], project_id=state["project_id"], decision=response.decision,
        job_id=response.job_id, asset_id=response.asset_id, seller_attested=response.seller_attested, db=db,
    )
    return {
        "current_stage": "image_review",
        "status": "running",
        "review": {
            "last_resolved_stage": "image_review",
            "last_decision": response.decision,
            "job_id": response.job_id,
        },
        "generation": generation,
        "events": [_lg4_review_event("image_review")],
    }


def _lg5_image_review_route(state: SellformGraphState) -> str:
    action = str((state.get("generation") or {}).get("next_action") or "review")
    if action == "cost_approval":
        return "generation_pending"
    if action == "finalize":
        return "finalize_run"
    return "image_review"


def _lg2_has_reference_url(state: SellformGraphState) -> str:
    source_collection = ((state.get("discovery") or {}).get("source_collection") or {})
    return "reference_analysis" if source_collection.get("has_reference_url") else "reference_analysis_skipped"


def build_lg1_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """Compile the first durable Sellform graph against an explicit saver."""

    graph = StateGraph(SellformGraphState)
    graph.add_node("bootstrap_run", _lg1_bootstrap_run)
    graph.add_node("lg1_test_node", _lg1_test_node)
    graph.add_node("finalize_run", _lg1_finalize_run)
    graph.add_edge(START, "bootstrap_run")
    graph.add_edge("bootstrap_run", "lg1_test_node")
    graph.add_edge("lg1_test_node", "finalize_run")
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def build_lg2_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """Compile the first four actual Discovery agents as a durable subgraph."""

    graph = StateGraph(SellformGraphState)
    graph.add_node("bootstrap_run", _lg1_bootstrap_run)
    graph.add_node("input_router", _lg2_input_router)
    graph.add_node("source_collection", _lg2_source_collection)
    graph.add_node("product_understanding", _lg2_product_understanding)
    graph.add_node("reference_analysis", _lg2_reference_analysis)
    graph.add_node("reference_analysis_skipped", _lg2_reference_analysis_skipped)
    graph.add_node("finalize_run", _lg2_finalize_run)
    graph.add_edge(START, "bootstrap_run")
    graph.add_edge("bootstrap_run", "input_router")
    graph.add_edge("input_router", "source_collection")
    graph.add_edge("source_collection", "product_understanding")
    graph.add_conditional_edges(
        "product_understanding",
        _lg2_has_reference_url,
        {"reference_analysis": "reference_analysis", "reference_analysis_skipped": "reference_analysis_skipped"},
    )
    graph.add_edge("reference_analysis", "finalize_run")
    graph.add_edge("reference_analysis_skipped", "finalize_run")
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def build_lg3_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """Extend LG-2 Discovery with the four Commerce Planning agents."""

    graph = StateGraph(SellformGraphState)
    for name, node in (
        ("bootstrap_run", _lg1_bootstrap_run), ("input_router", _lg2_input_router),
        ("source_collection", _lg2_source_collection), ("product_understanding", _lg2_product_understanding),
        ("reference_analysis", _lg2_reference_analysis), ("reference_analysis_skipped", _lg2_reference_analysis_skipped),
        ("sales_strategy", _lg3_sales_strategy), ("page_planning", _lg3_page_planning),
        ("copywriting", _lg3_copywriting), ("visual_planning", _lg3_visual_planning),
        ("finalize_run", _lg2_finalize_run),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "bootstrap_run")
    graph.add_edge("bootstrap_run", "input_router")
    graph.add_edge("input_router", "source_collection")
    graph.add_edge("source_collection", "product_understanding")
    graph.add_conditional_edges("product_understanding", _lg2_has_reference_url, {
        "reference_analysis": "reference_analysis", "reference_analysis_skipped": "reference_analysis_skipped"})
    graph.add_edge("reference_analysis", "sales_strategy")
    graph.add_edge("reference_analysis_skipped", "sales_strategy")
    graph.add_edge("sales_strategy", "page_planning")
    graph.add_edge("page_planning", "copywriting")
    graph.add_edge("copywriting", "visual_planning")
    graph.add_edge("visual_planning", "finalize_run")
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def build_lg4_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """LG-4 graph with durable seller-review interrupts between subgraphs."""

    graph = StateGraph(SellformGraphState)
    for name, node in (
        ("bootstrap_run", _lg1_bootstrap_run), ("input_review", _lg4_input_review),
        ("input_router", _lg2_input_router), ("source_collection", _lg2_source_collection),
        ("product_understanding", _lg2_product_understanding),
        ("reference_analysis", _lg2_reference_analysis),
        ("reference_analysis_skipped", _lg2_reference_analysis_skipped),
        ("evidence_review", _lg4_evidence_review),
        ("sales_strategy", _lg3_sales_strategy), ("page_planning", _lg3_page_planning),
        ("copywriting", _lg3_copywriting), ("visual_planning", _lg3_visual_planning),
        ("planning_review", _lg4_planning_review),
        ("generation_pending", _lg4_generation_pending),
        ("finalize_run", _lg2_finalize_run),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "bootstrap_run")
    graph.add_edge("bootstrap_run", "input_review")
    graph.add_edge("input_review", "input_router")
    graph.add_edge("input_router", "source_collection")
    graph.add_edge("source_collection", "product_understanding")
    graph.add_conditional_edges("product_understanding", _lg2_has_reference_url, {
        "reference_analysis": "reference_analysis", "reference_analysis_skipped": "reference_analysis_skipped"})
    graph.add_edge("reference_analysis", "evidence_review")
    graph.add_edge("reference_analysis_skipped", "evidence_review")
    graph.add_edge("evidence_review", "sales_strategy")
    graph.add_edge("sales_strategy", "page_planning")
    graph.add_edge("page_planning", "copywriting")
    graph.add_edge("copywriting", "visual_planning")
    graph.add_edge("visual_planning", "planning_review")
    graph.add_edge("planning_review", "generation_pending")
    # This edge is unreachable in LG-4 because generation_pending deliberately
    # re-interrupts. Keeping it explicit reserves the canonical continuation
    # point for the LG-5 image-generation subgraph.
    graph.add_edge("generation_pending", "finalize_run")
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def build_lg5_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """LG-5 extends the LG-4 thread with durable image job orchestration."""

    graph = StateGraph(SellformGraphState)
    for name, node in (
        ("bootstrap_run", _lg1_bootstrap_run), ("input_review", _lg4_input_review),
        ("input_router", _lg2_input_router), ("source_collection", _lg2_source_collection),
        ("product_understanding", _lg2_product_understanding),
        ("reference_analysis", _lg2_reference_analysis),
        ("reference_analysis_skipped", _lg2_reference_analysis_skipped),
        ("evidence_review", _lg4_evidence_review),
        ("sales_strategy", _lg3_sales_strategy), ("page_planning", _lg3_page_planning),
        ("copywriting", _lg3_copywriting), ("visual_planning", _lg3_visual_planning),
        ("planning_review", _lg4_planning_review),
        ("generation_pending", _lg5_generation_pending),
        ("prepare_image_jobs", _lg5_prepare_image_jobs),
        ("dispatch_image_jobs", _lg5_dispatch_image_jobs),
        ("provider_wait", _lg5_provider_wait),
        ("collect_image_results", _lg5_collect_image_results),
        ("validate_generated_images", _lg5_validate_generated_images),
        ("image_review", _lg5_image_review),
        ("finalize_run", _lg2_finalize_run),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "bootstrap_run")
    graph.add_edge("bootstrap_run", "input_review")
    graph.add_edge("input_review", "input_router")
    graph.add_edge("input_router", "source_collection")
    graph.add_edge("source_collection", "product_understanding")
    graph.add_conditional_edges("product_understanding", _lg2_has_reference_url, {
        "reference_analysis": "reference_analysis", "reference_analysis_skipped": "reference_analysis_skipped"})
    graph.add_edge("reference_analysis", "evidence_review")
    graph.add_edge("reference_analysis_skipped", "evidence_review")
    graph.add_edge("evidence_review", "sales_strategy")
    graph.add_edge("sales_strategy", "page_planning")
    graph.add_edge("page_planning", "copywriting")
    graph.add_edge("copywriting", "visual_planning")
    graph.add_edge("visual_planning", "planning_review")
    graph.add_edge("planning_review", "generation_pending")
    graph.add_conditional_edges("generation_pending", _lg5_generation_pending_route, {
        "generation_pending": "generation_pending", "prepare_image_jobs": "prepare_image_jobs"})
    graph.add_edge("prepare_image_jobs", "dispatch_image_jobs")
    graph.add_edge("dispatch_image_jobs", "provider_wait")
    graph.add_conditional_edges("provider_wait", _lg5_provider_wait_route, {
        "provider_wait": "provider_wait", "collect_image_results": "collect_image_results"})
    graph.add_edge("collect_image_results", "validate_generated_images")
    graph.add_edge("validate_generated_images", "image_review")
    graph.add_conditional_edges("image_review", _lg5_image_review_route, {
        "generation_pending": "generation_pending", "finalize_run": "finalize_run", "image_review": "image_review"})
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def build_lg6_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """LG-6 inserts immutable prompt intelligence before commerce planning."""

    graph = StateGraph(SellformGraphState)
    for name, node in (
        ("bootstrap_run", _lg1_bootstrap_run), ("input_review", _lg4_input_review),
        ("input_router", _lg2_input_router), ("source_collection", _lg2_source_collection),
        ("product_understanding", _lg2_product_understanding),
        ("reference_analysis", _lg2_reference_analysis),
        ("reference_analysis_skipped", _lg2_reference_analysis_skipped),
        ("evidence_review", _lg4_evidence_review),
        ("category_classifier", _lg6_category_classifier),
        ("prompt_pack_resolver", _lg6_prompt_pack_resolver),
        ("sales_strategy", _lg3_sales_strategy), ("page_planning", _lg3_page_planning),
        ("copywriting", _lg3_copywriting), ("visual_planning", _lg3_visual_planning),
        ("planning_review", _lg4_planning_review),
        ("generation_pending", _lg5_generation_pending),
        ("prepare_image_jobs", _lg5_prepare_image_jobs),
        ("dispatch_image_jobs", _lg5_dispatch_image_jobs),
        ("provider_wait", _lg5_provider_wait),
        ("collect_image_results", _lg5_collect_image_results),
        ("validate_generated_images", _lg5_validate_generated_images),
        ("image_review", _lg5_image_review),
        ("finalize_run", _lg2_finalize_run),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "bootstrap_run")
    graph.add_edge("bootstrap_run", "input_review")
    graph.add_edge("input_review", "input_router")
    graph.add_edge("input_router", "source_collection")
    graph.add_edge("source_collection", "product_understanding")
    graph.add_conditional_edges("product_understanding", _lg2_has_reference_url, {
        "reference_analysis": "reference_analysis", "reference_analysis_skipped": "reference_analysis_skipped"})
    graph.add_edge("reference_analysis", "evidence_review")
    graph.add_edge("reference_analysis_skipped", "evidence_review")
    graph.add_edge("evidence_review", "category_classifier")
    graph.add_edge("category_classifier", "prompt_pack_resolver")
    graph.add_edge("prompt_pack_resolver", "sales_strategy")
    graph.add_edge("sales_strategy", "page_planning")
    graph.add_edge("page_planning", "copywriting")
    graph.add_edge("copywriting", "visual_planning")
    graph.add_edge("visual_planning", "planning_review")
    graph.add_edge("planning_review", "generation_pending")
    graph.add_conditional_edges("generation_pending", _lg5_generation_pending_route, {
        "generation_pending": "generation_pending", "prepare_image_jobs": "prepare_image_jobs"})
    graph.add_edge("prepare_image_jobs", "dispatch_image_jobs")
    graph.add_edge("dispatch_image_jobs", "provider_wait")
    graph.add_conditional_edges("provider_wait", _lg5_provider_wait_route, {
        "provider_wait": "provider_wait", "collect_image_results": "collect_image_results"})
    graph.add_edge("collect_image_results", "validate_generated_images")
    graph.add_edge("validate_generated_images", "image_review")
    graph.add_conditional_edges("image_review", _lg5_image_review_route, {
        "generation_pending": "generation_pending", "finalize_run": "finalize_run", "image_review": "image_review"})
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def build_lg7_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """LG-7 compiles review/reference/direction into one immutable brief."""

    graph = StateGraph(SellformGraphState)
    for name, node in (
        ("bootstrap_run", _lg1_bootstrap_run), ("input_review", _lg4_input_review),
        ("input_router", _lg2_input_router), ("source_collection", _lg2_source_collection),
        ("product_understanding", _lg2_product_understanding),
        ("reference_analysis", _lg2_reference_analysis),
        ("reference_analysis_skipped", _lg2_reference_analysis_skipped),
        ("evidence_review", _lg4_evidence_review), ("category_classifier", _lg6_category_classifier),
        ("prompt_pack_resolver", _lg6_prompt_pack_resolver),
        ("creative_brief_compiler", _lg7_creative_brief_compiler),
        ("sales_strategy", _lg3_sales_strategy), ("page_planning", _lg3_page_planning),
        ("copywriting", _lg3_copywriting), ("visual_planning", _lg3_visual_planning),
        ("planning_review", _lg4_planning_review), ("generation_pending", _lg5_generation_pending),
        ("prepare_image_jobs", _lg5_prepare_image_jobs), ("dispatch_image_jobs", _lg5_dispatch_image_jobs),
        ("provider_wait", _lg5_provider_wait), ("collect_image_results", _lg5_collect_image_results),
        ("validate_generated_images", _lg5_validate_generated_images), ("image_review", _lg5_image_review),
        ("finalize_run", _lg2_finalize_run),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "bootstrap_run"); graph.add_edge("bootstrap_run", "input_review")
    graph.add_edge("input_review", "input_router"); graph.add_edge("input_router", "source_collection")
    graph.add_edge("source_collection", "product_understanding")
    graph.add_conditional_edges("product_understanding", _lg2_has_reference_url, {
        "reference_analysis": "reference_analysis", "reference_analysis_skipped": "reference_analysis_skipped"})
    graph.add_edge("reference_analysis", "evidence_review"); graph.add_edge("reference_analysis_skipped", "evidence_review")
    graph.add_edge("evidence_review", "category_classifier"); graph.add_edge("category_classifier", "prompt_pack_resolver")
    graph.add_edge("prompt_pack_resolver", "creative_brief_compiler"); graph.add_edge("creative_brief_compiler", "sales_strategy")
    graph.add_edge("sales_strategy", "page_planning"); graph.add_edge("page_planning", "copywriting")
    graph.add_edge("copywriting", "visual_planning"); graph.add_edge("visual_planning", "planning_review")
    graph.add_edge("planning_review", "generation_pending")
    graph.add_conditional_edges("generation_pending", _lg5_generation_pending_route, {
        "generation_pending": "generation_pending", "prepare_image_jobs": "prepare_image_jobs"})
    graph.add_edge("prepare_image_jobs", "dispatch_image_jobs"); graph.add_edge("dispatch_image_jobs", "provider_wait")
    graph.add_conditional_edges("provider_wait", _lg5_provider_wait_route, {
        "provider_wait": "provider_wait", "collect_image_results": "collect_image_results"})
    graph.add_edge("collect_image_results", "validate_generated_images"); graph.add_edge("validate_generated_images", "image_review")
    graph.add_conditional_edges("image_review", _lg5_image_review_route, {
        "generation_pending": "generation_pending", "finalize_run": "finalize_run", "image_review": "image_review"})
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def build_lg8_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """LG-8 compiles immutable scene prompts before seller planning review."""

    graph = StateGraph(SellformGraphState)
    for name, node in (
        ("bootstrap_run", _lg1_bootstrap_run), ("input_review", _lg4_input_review),
        ("input_router", _lg2_input_router), ("source_collection", _lg2_source_collection),
        ("product_understanding", _lg2_product_understanding),
        ("reference_analysis", _lg2_reference_analysis),
        ("reference_analysis_skipped", _lg2_reference_analysis_skipped),
        ("evidence_review", _lg4_evidence_review), ("category_classifier", _lg6_category_classifier),
        ("prompt_pack_resolver", _lg6_prompt_pack_resolver),
        ("creative_brief_compiler", _lg7_creative_brief_compiler),
        ("sales_strategy", _lg3_sales_strategy), ("page_planning", _lg3_page_planning),
        ("copywriting", _lg3_copywriting), ("visual_planning", _lg3_visual_planning),
        ("visual_prompt_compiler", _lg8_visual_prompt_compiler),
        ("planning_review", _lg4_planning_review), ("generation_pending", _lg5_generation_pending),
        ("prepare_image_jobs", _lg5_prepare_image_jobs), ("dispatch_image_jobs", _lg5_dispatch_image_jobs),
        ("provider_wait", _lg5_provider_wait), ("collect_image_results", _lg5_collect_image_results),
        ("validate_generated_images", _lg5_validate_generated_images), ("image_review", _lg5_image_review),
        ("finalize_run", _lg2_finalize_run),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "bootstrap_run"); graph.add_edge("bootstrap_run", "input_review")
    graph.add_edge("input_review", "input_router"); graph.add_edge("input_router", "source_collection")
    graph.add_edge("source_collection", "product_understanding")
    graph.add_conditional_edges("product_understanding", _lg2_has_reference_url, {
        "reference_analysis": "reference_analysis", "reference_analysis_skipped": "reference_analysis_skipped"})
    graph.add_edge("reference_analysis", "evidence_review"); graph.add_edge("reference_analysis_skipped", "evidence_review")
    graph.add_edge("evidence_review", "category_classifier"); graph.add_edge("category_classifier", "prompt_pack_resolver")
    graph.add_edge("prompt_pack_resolver", "creative_brief_compiler"); graph.add_edge("creative_brief_compiler", "sales_strategy")
    graph.add_edge("sales_strategy", "page_planning"); graph.add_edge("page_planning", "copywriting")
    graph.add_edge("copywriting", "visual_planning"); graph.add_edge("visual_planning", "visual_prompt_compiler")
    graph.add_edge("visual_prompt_compiler", "planning_review"); graph.add_edge("planning_review", "generation_pending")
    graph.add_conditional_edges("generation_pending", _lg5_generation_pending_route, {
        "generation_pending": "generation_pending", "prepare_image_jobs": "prepare_image_jobs"})
    graph.add_edge("prepare_image_jobs", "dispatch_image_jobs"); graph.add_edge("dispatch_image_jobs", "provider_wait")
    graph.add_conditional_edges("provider_wait", _lg5_provider_wait_route, {
        "provider_wait": "provider_wait", "collect_image_results": "collect_image_results"})
    graph.add_edge("collect_image_results", "validate_generated_images"); graph.add_edge("validate_generated_images", "image_review")
    graph.add_conditional_edges("image_review", _lg5_image_review_route, {
        "generation_pending": "generation_pending", "finalize_run": "finalize_run", "image_review": "image_review"})
    graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def checkpoint_database_url(database_url: str | None = None) -> str:
    """Return a psycopg-compatible PostgreSQL URL without exposing secrets."""

    url = database_url or settings.SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL or settings.DATABASE_URL
    scheme, separator, remainder = url.partition("://")
    normalized_scheme = scheme.split("+", 1)[0]
    if separator != "://" or normalized_scheme not in {"postgresql", "postgres"}:
        raise ValueError("LangGraph checkpoints require a PostgreSQL database URL.")
    return f"postgresql://{remainder}"


@contextmanager
def open_postgres_checkpointer(
    database_url: str | None = None,
) -> Iterator[BaseCheckpointSaver[Any]]:
    """Open one synchronous PostgreSQL checkpointer for a graph operation.

    No SQLite or in-memory fallback is performed here: durable production runs
    must fail clearly rather than silently losing restart/recovery guarantees.
    ``InMemorySaver`` remains an explicit unit-test dependency.
    """

    # Imported lazily so a legacy-only deployment can boot before LG-1 is
    # activated, while the dependency remains declared and locked.
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(checkpoint_database_url(database_url)) as saver:
        if settings.SELLFORM_LANGGRAPH_CHECKPOINT_SETUP_ON_START:
            saver.setup()
        yield saver
