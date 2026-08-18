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
        # LG-12I only persists the validated reference envelope. URL bodies,
        # image bytes and OCR/source text are intentionally not graph state.
        "unified_product_intake",
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
    # LG-10 stores only constrained component/layout selections and immutable
    # input references. Renderer markup stays outside the graph state.
    page_assembly: Annotated[dict[str, Any], _merge_discovery]
    # LG-10's deterministic HTML/CSS artifact remains separate from the
    # approved image layer; the renderer node records its immutable version ref.
    rendering: Annotated[dict[str, Any], _merge_discovery]
    # LG-6 stores classification confidence and immutable pack/Brand Kit
    # references only; full compiled prompts live in SQL artifacts.
    prompt_intelligence: Annotated[dict[str, Any], _merge_discovery]
    # LG-7 keeps only the immutable compiler artifact identity in checkpoints.
    # Review corpora and reference bodies remain in their versioned SQL tables.
    creative_brief: Annotated[dict[str, Any], _merge_discovery]
    # LG-12I keeps the versioned intake identity plus compact source refs so a
    # later adapter can recover from the same checkpoint without re-reading a
    # mutable request body.
    intake: Annotated[dict[str, Any], _merge_discovery]


class LG11EditGraphState(TypedDict, total=False):
    """Durable LG-11 edit-run state, isolated from the LG-1 through LG-10 graph.

    The source page remains the immutable DetailPageVersion reference.  This
    state deliberately retains no mutable ProductPage or image-job payload.
    """

    run_id: str
    thread_id: str
    workspace_id: str
    project_id: str
    mode: str
    current_stage: str
    status: str
    events: Annotated[list[dict[str, Any]], add]
    edit: Annotated[dict[str, Any], _merge_discovery]
    # LG-11 scene edits reuse the LG-9 durable job/outbox protocol.  Keep the
    # same small generation summary in the checkpoint so the existing worker
    # callback can resume the provider wait without reconstructing a second
    # regeneration workflow.
    generation: Annotated[dict[str, Any], _merge_discovery]
    # TASK-11.7 stores an immutable-source canvas draft in the same durable
    # LG-11 checkpoint; it never writes the source DetailPageVersion.
    canvas: Annotated[dict[str, Any], _merge_discovery]


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


def build_lg12i_intake_graph_input(
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    intake_envelope: dict[str, Any],
) -> SellformGraphState:
    """Build the narrow production state for one LG-12I intake thread.

    The envelope was validated before the run was created and is validated
    again by the router node.  That second check makes a manually altered SQL
    snapshot fail closed rather than becoming an adapter input later.
    """

    return {
        "run_id": run_id,
        "thread_id": run_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "mode": "lg12i_intake",
        "input_snapshot": checkpoint_safe_input_snapshot(
            {"unified_product_intake": intake_envelope}
        ),
        "current_stage": "unified_intake_router",
        "status": "created",
        "events": [],
        "errors": [],
    }


def build_lg11_edit_graph_input(
    *,
    run_id: str,
    workspace_id: str,
    project_id: str,
    edit: dict[str, Any],
) -> LG11EditGraphState:
    """Build the narrow LG-11 state from a frozen-version edit-run envelope."""

    return {
        "run_id": run_id,
        "thread_id": run_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "mode": "lg11_edit",
        "current_stage": "edit_intent",
        "status": "created",
        "events": [],
        "edit": copy.deepcopy(edit),
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
        run_id=state["run_id"],
        project_id=state["project_id"],
        db=db,
        scene_ids=scene_ids,
        allow_no_required_scenes=bool(state.get("_lg10_allow_no_required_scenes")),
    )
    generation = {**prior_generation, "cost_plan": cost_plan, "cost_approved": False}
    if int(cost_plan.get("scene_count") or 0) == 0:
        generation.update({
            "image_generation_required": False,
            "completion_basis": "no_required_image_scenes",
            "required_scene_count": 0,
            "remaining_required_scene_ids": [],
            "all_required_scenes_approved": True,
            "next_action": "finalize",
        })
        return {
            "current_stage": "generation_pending",
            "status": "running",
            "generation": generation,
            "events": [_lg5_event("generation_pending")],
        }
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


def _lg10_generation_pending(state: SellformGraphState) -> dict[str, Any]:
    """Enable the zero-provider branch only in the LG-10 compiled graph."""

    return _lg5_generation_pending({**state, "_lg10_allow_no_required_scenes": True})


def _lg10_generation_pending_route(state: SellformGraphState) -> str:
    """Let only LG-10 continue when its approved plan needs no provider jobs."""

    if (state.get("generation") or {}).get("image_generation_required") is False:
        return "image_review"
    return _lg5_generation_pending_route(state)


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
    from src.services.page_finalization_service import build_canonical_page_assembly_input
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-5 image review requires the graph database session.")
    generation = dict(state.get("generation") or {})
    if (
        generation.get("image_generation_required") is False
        and int(generation.get("required_scene_count") or 0) == 0
    ):
        from src.db.models import AgentRun

        run = db.query(AgentRun).filter(AgentRun.id == state["run_id"]).one()
        generation["canonical_page_assembly_input"] = build_canonical_page_assembly_input(
            run=run,
            approved_asset_manifest=None,
            db=db,
        )
        generation.update({
            "completion_basis": "no_required_image_scenes",
            "all_required_scenes_approved": True,
            "next_action": "finalize",
        })
        return {
            "current_stage": "image_review",
            "status": "running",
            "generation": generation,
            "events": [_lg5_event("image_review")],
        }
    raw_response = interrupt(review_interrupt_payload("image_review", {**state, "generation": generation}))
    response = validate_resume_payload(raw_response, "image_review")
    generation = apply_image_review(
        run_id=state["run_id"], project_id=state["project_id"], decision=response.decision,
        job_id=response.job_id, asset_id=response.asset_id, seller_attested=response.seller_attested, db=db,
    )
    # LG-10.1 freezes its assembly input only after LG-9 has completed every
    # required approval. This stays in the existing generation state until the
    # subsequent Page Assembly node is introduced; no downstream routing is
    # changed here.
    manifest = generation.get("approved_asset_manifest")
    if isinstance(manifest, dict):
        from src.db.models import AgentRun

        run = db.query(AgentRun).filter(AgentRun.id == state["run_id"]).one()
        generation["canonical_page_assembly_input"] = build_canonical_page_assembly_input(
            run=run,
            approved_asset_manifest=manifest,
            db=db,
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


def _lg10_page_assembly(state: SellformGraphState) -> dict[str, Any]:
    """Advance a fully approved LG-9 run through constrained Page Assembly."""

    from src.services.page_finalization_service import build_page_assembly_structure

    canonical_input = (state.get("generation") or {}).get("canonical_page_assembly_input")
    if not isinstance(canonical_input, dict):
        raise RuntimeError("LG-10 Page Assembly requires the approved canonical assembly input.")
    assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical_input)
    return {
        "current_stage": "page_assembly",
        "status": "running",
        "page_assembly": assembly,
        "events": [_lg2_event("page_assembly")],
    }


def _lg10_canonical_renderer(state: SellformGraphState) -> dict[str, Any]:
    """Build the deterministic LG-10 text/asset layer artifact from frozen state."""

    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.page_finalization_service import (
        build_canonical_page_rendering_artifact,
        persist_lg10_detail_page_version,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-10 canonical renderer requires the graph database session.")
    canonical_input = (state.get("generation") or {}).get("canonical_page_assembly_input")
    assembly = state.get("page_assembly")
    if not isinstance(canonical_input, dict) or not isinstance(assembly, dict):
        raise RuntimeError("LG-10 canonical renderer requires immutable assembly state.")
    run = db.query(AgentRun).filter(AgentRun.id == state["run_id"]).one()
    rendering = build_canonical_page_rendering_artifact(
        run=run,
        canonical_page_assembly_input=canonical_input,
        page_assembly=assembly,
        db=db,
    )
    version = persist_lg10_detail_page_version(
        run=run,
        canonical_page_assembly_input=canonical_input,
        page_assembly=assembly,
        rendering=rendering,
        db=db,
    )
    rendering = {
        **rendering,
        "detail_page_version": {
            "id": version.id,
            "schema_version": "lg10-detail-page-version-v1",
            "snapshot_hash": str((version.sections_json or {}).get("snapshot_hash") or ""),
        },
    }
    return {
        "current_stage": "canonical_renderer",
        "status": "running",
        "rendering": rendering,
        "events": [_lg2_event("canonical_renderer")],
    }


def _lg5_image_review_route(state: SellformGraphState) -> str:
    action = str((state.get("generation") or {}).get("next_action") or "review")
    if action == "cost_approval":
        return "generation_pending"
    if action == "finalize":
        return "finalize_run"
    return "image_review"


def _lg10_image_review_route(state: SellformGraphState) -> str:
    """Require the LG-10 immutable input before final Page Assembly can run."""

    action = str((state.get("generation") or {}).get("next_action") or "review")
    if action == "finalize":
        return "page_assembly" if isinstance(
            (state.get("generation") or {}).get("canonical_page_assembly_input"), dict
        ) else "image_review"
    return _lg5_image_review_route(state)


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


def build_lg10_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """LG-10 runs constrained Page Assembly after every required image approval."""

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
        ("planning_review", _lg4_planning_review), ("generation_pending", _lg10_generation_pending),
        ("prepare_image_jobs", _lg5_prepare_image_jobs), ("dispatch_image_jobs", _lg5_dispatch_image_jobs),
        ("provider_wait", _lg5_provider_wait), ("collect_image_results", _lg5_collect_image_results),
        ("validate_generated_images", _lg5_validate_generated_images), ("image_review", _lg5_image_review),
        ("page_assembly", _lg10_page_assembly), ("canonical_renderer", _lg10_canonical_renderer),
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
    graph.add_conditional_edges("generation_pending", _lg10_generation_pending_route, {
        "generation_pending": "generation_pending", "prepare_image_jobs": "prepare_image_jobs",
        "image_review": "image_review"})
    graph.add_edge("prepare_image_jobs", "dispatch_image_jobs"); graph.add_edge("dispatch_image_jobs", "provider_wait")
    graph.add_conditional_edges("provider_wait", _lg5_provider_wait_route, {
        "provider_wait": "provider_wait", "collect_image_results": "collect_image_results"})
    graph.add_edge("collect_image_results", "validate_generated_images"); graph.add_edge("validate_generated_images", "image_review")
    graph.add_conditional_edges("image_review", _lg10_image_review_route, {
        "generation_pending": "generation_pending", "page_assembly": "page_assembly", "finalize_run": "finalize_run", "image_review": "image_review"})
    graph.add_edge("page_assembly", "canonical_renderer"); graph.add_edge("canonical_renderer", "finalize_run"); graph.add_edge("finalize_run", END)
    return graph.compile(checkpointer=checkpointer)


def _lg12i_unified_intake_router(state: SellformGraphState) -> dict[str, Any]:
    """Route every first-class input mode through one durable intake node.

    Adapters are deliberately not invoked here.  The only output is the
    compact, versioned command that TASK-12I.3 through TASK-12I.5 will consume.
    """

    from src.services.product_intake_version_service import (
        UNIFIED_PRODUCT_INTAKE_MODES,
        validate_unified_product_intake_envelope,
    )

    envelope = validate_unified_product_intake_envelope(
        dict((state.get("input_snapshot") or {}).get("unified_product_intake") or {})
    )
    if envelope["project_id"] != state.get("project_id"):
        raise ValueError("Unified intake envelope project_id does not match the graph run.")
    if envelope["run_identity"]["run_id"] != state.get("run_id"):
        raise ValueError("Unified intake envelope run_identity does not match the graph run.")
    mode = str(envelope["input_mode"])
    if mode not in UNIFIED_PRODUCT_INTAKE_MODES:
        raise ValueError("Unknown unified intake input_mode.")
    return {
        "current_stage": "intake_adapter_pending",
        "status": "completed",
        "intake": {
            "schema_version": envelope["schema_version"],
            "input_hash": envelope["input_hash"],
            "input_mode": mode,
            "requested_generation_mode": envelope["requested_generation_mode"],
            "target_channels": list(envelope["target_channels"]),
            "run_identity": dict(envelope["run_identity"]),
            "actor_workspace_identity": dict(envelope["actor_workspace_identity"]),
            "source_payload_refs": list(envelope["source_payload_refs"]),
            # This is a contract-only handoff, not a mode-specific adapter.
            "next_action": "task_12i_adapter_not_implemented",
            "product_source_snapshot_command": {
                "input_mode": mode,
                "input_hash": envelope["input_hash"],
                "source_payload_refs": list(envelope["source_payload_refs"]),
            },
        },
        "events": [_graph_node_event("intake_adapter_pending", "completed")],
    }


def build_lg12i_intake_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """Compile the LG-12I subgraph inside the existing production runtime."""

    graph = StateGraph(SellformGraphState)
    graph.add_node("unified_intake_router", _lg12i_unified_intake_router)
    graph.add_edge(START, "unified_intake_router")
    graph.add_edge("unified_intake_router", END)
    return graph.compile(checkpointer=checkpointer)


def _lg11_edit_event(stage: str, *, status: str = "running") -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "node_status": "completed",
        "event_type": "node_completed",
    }


def _lg11_prepare_edit_run(state: LG11EditGraphState) -> dict[str, Any]:
    """Persist only the immutable source/version lineage before confirmation."""

    edit = dict(state.get("edit") or {})
    lineage = dict(edit.get("lineage") or {})
    base_version = dict(edit.get("base_version") or {})
    if (
        not lineage.get("edit_run_id")
        or lineage.get("edit_run_id") != state.get("run_id")
        or not lineage.get("source_detail_page_version_id")
        or not lineage.get("parent_detail_page_version_id")
        or not base_version.get("id")
        or not base_version.get("snapshot_hash")
        or not edit.get("intent_id")
        or not isinstance(edit.get("impact_preview"), dict)
    ):
        raise ValueError("LG-11 edit run requires a frozen base-version lineage and impact preview.")
    return {
        "current_stage": "edit_confirmation",
        "status": "running",
        "edit": {
            **edit,
            "confirmation": {"status": "pending"},
        },
        "events": [_lg11_edit_event("edit_intent")],
    }


def _lg11_edit_confirmation_interrupt(state: LG11EditGraphState) -> dict[str, Any]:
    edit = dict(state.get("edit") or {})
    lineage = dict(edit.get("lineage") or {})
    return {
        "schema_version": "lg11-v1",
        "review_stage": "edit_confirmation",
        "title": "변경 영향 확인",
        "description": "고정된 상세페이지 버전과 변경 영향 범위를 확인한 뒤 다음 편집 단계로 진행합니다.",
        "allowed_decisions": ["approve", "reject"],
        "run_id": str(state.get("run_id") or ""),
        "thread_id": str(state.get("thread_id") or state.get("run_id") or ""),
        "project_id": str(state.get("project_id") or ""),
        "context": {
            "edit_run_id": str(lineage.get("edit_run_id") or ""),
            "source_detail_page_version_id": str(lineage.get("source_detail_page_version_id") or ""),
            "parent_detail_page_version_id": str(lineage.get("parent_detail_page_version_id") or ""),
            "base_snapshot_hash": str(dict(edit.get("base_version") or {}).get("snapshot_hash") or ""),
            "intent_id": str(edit.get("intent_id") or ""),
            "impact_preview": dict(edit.get("impact_preview") or {}),
        },
        "rejection_reason": "",
    }


def _lg11_edit_confirmation(state: LG11EditGraphState) -> dict[str, Any]:
    """Pause before any edit execution; later LG-11 tasks own downstream work."""

    from src.services.langgraph_review_service import validate_resume_payload

    raw_response = interrupt(_lg11_edit_confirmation_interrupt(state))
    response = validate_resume_payload(raw_response, "edit_confirmation")
    edit = dict(state.get("edit") or {})
    return {
        "current_stage": "edit_confirmation",
        "status": "running",
        "edit": {
            **edit,
            "confirmation": {
                "status": "confirmed" if response.decision == "approve" else "rejected",
                "decision": response.decision,
            },
        },
        "events": [_lg11_edit_event("edit_confirmation")],
    }


def _lg11_finalize_edit_run(state: LG11EditGraphState) -> dict[str, Any]:
    """Start the approved LG-11 action without widening its task boundary."""

    edit = dict(state.get("edit") or {})
    from src.db.models import AgentRun, DetailPageVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.page_finalization_service import (
        EditIntentValidationError,
        build_lg11_canvas_draft,
        build_lg11_copy_version_fork,
        build_lg11_style_version_fork,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-11 copy fork requires the graph database session.")
    run = db.query(AgentRun).filter(
        AgentRun.id == str(state.get("run_id") or ""),
        AgentRun.workspace_id == str(state.get("workspace_id") or ""),
        AgentRun.project_id == str(state.get("project_id") or ""),
        AgentRun.mode == "lg11_edit",
    ).one_or_none()
    if run is None:
        raise EditIntentValidationError("LG-11 copy fork run is not available in this workspace.")
    intent = dict((run.input_snapshot or {}).get("lg11_edit_intent") or {})
    if (
        str(intent.get("intent_hash") or "") != str(edit.get("intent_id") or "")
        or str(intent.get("intent_hash") or "") != str(edit.get("intent_hash") or "")
    ):
        raise EditIntentValidationError("LG-11 copy fork intent identity does not match the edit run.")

    scope = str(intent.get("scope") or "")
    operation = str(intent.get("operation") or "")
    if scope == "page" and operation == "restore":
        source_version = db.query(DetailPageVersion).filter(
            DetailPageVersion.id == str(dict(edit.get("base_version") or {}).get("id") or ""),
            DetailPageVersion.project_id == run.project_id,
        ).one_or_none()
        if source_version is None or not isinstance(source_version.sections_json, dict):
            raise EditIntentValidationError("LG-11 restore source is not an immutable frozen DetailPageVersion.")
        if not isinstance(source_version.sections_json.get("lg11"), dict):
            raise EditIntentValidationError("LG-11 restore only accepts an LG-11 frozen DetailPageVersion.")
        # Reactivate the immutable snapshot itself.  No draft is hydrated and
        # no child version, provider work, cost approval, or mutable page read
        # is involved.  The single transaction also makes retry/resume safe.
        db.query(DetailPageVersion).filter(
            DetailPageVersion.project_id == run.project_id,
            DetailPageVersion.is_final == True,  # noqa: E712
        ).update({DetailPageVersion.is_final: False}, synchronize_session=False)
        source_version.is_final = True
        db.commit()
        restore_state = {
            "status": "restored",
            "detail_page_version_id": source_version.id,
            "source_detail_page_version_id": source_version.id,
            "parent_detail_page_version_id": str(dict(source_version.sections_json.get("lg11") or {}).get("parent_detail_page_version_id") or source_version.id),
            "snapshot_hash": str(dict(source_version.sections_json or {}).get("snapshot_hash") or ""),
        }
        return {
            "current_stage": "version_restored", "status": "completed",
            "edit": {**edit, "next_action": "none", "version_restore": restore_state},
            "events": [_lg11_edit_event("version_restored", status="completed")],
        }
    if scope == "page" and operation == "canvas_draft":
        source_version = db.query(DetailPageVersion).filter(
            DetailPageVersion.id == str(dict(edit.get("base_version") or {}).get("id") or ""),
            DetailPageVersion.project_id == run.project_id,
        ).one_or_none()
        if source_version is None:
            raise EditIntentValidationError("LG-11 canvas source version is not in this project.")
        draft = build_lg11_canvas_draft(source_version=source_version, edit_run_id=run.id, intent=intent)
        return {
            "current_stage": "canvas_draft_ready", "status": "running", "canvas": draft,
            "edit": {**edit, "next_action": "canvas_edit"},
            "events": [_lg11_edit_event("canvas_draft_ready")],
        }
    # Fact-sensitive requests, including a selected copy request that changes
    # a frozen fact, share TASK-11.5's existing evidence-review interrupt.
    # They must never fall through to a direct copy fork.
    if bool(dict(edit.get("impact_preview") or {}).get("requires_evidence_review")):
        return {
            "current_stage": "fact_evidence_review",
            "status": "running",
            "edit": {**edit, "next_action": "fact_evidence_review"},
            "events": [_lg11_edit_event("fact_evidence_review")],
        }
    if scope == "scene" and operation in {"regenerate", "replace"}:
        source_version = db.query(DetailPageVersion).filter(
            DetailPageVersion.id == str(dict(edit.get("base_version") or {}).get("id") or ""),
            DetailPageVersion.project_id == run.project_id,
        ).one_or_none()
        if source_version is None:
            raise EditIntentValidationError("LG-11 scene edit source version is not in this project.")
        scene_id = str((intent.get("target_ids") or [""])[0] or "")
        if not scene_id or len(intent.get("target_ids") or []) != 1:
            raise EditIntentValidationError("LG-11 scene edits require exactly one frozen scene target.")
        if operation == "regenerate":
            from src.services.langgraph_image_generation_service import ensure_lg11_scene_regeneration_cost_plan

            cost_plan = ensure_lg11_scene_regeneration_cost_plan(
                run=run, source_version=source_version, scene_id=scene_id, db=db,
            )
            generation = {
                "cost_plan": cost_plan,
                "cost_plan_hash": cost_plan["cost_plan_hash"],
                "scene_ids": [scene_id],
                "next_action": "cost_approval",
            }
            return {
                "current_stage": "scene_cost_approval",
                "status": "running",
                "generation": generation,
                "edit": {**edit, "next_action": "scene_cost_approval"},
                "events": [_lg11_edit_event("scene_cost_approval")],
            }

        from src.services.langgraph_image_generation_service import prepare_lg11_seller_asset_replacement

        generation = prepare_lg11_seller_asset_replacement(
            run=run,
            source_version=source_version,
            scene_id=scene_id,
            asset_id=str(intent.get("replacement_asset_id") or ""),
            seller_attested=bool(intent.get("seller_attested")),
            db=db,
        )
        return {
            "current_stage": "scene_image_review",
            "status": "running",
            "generation": generation,
            "edit": {**edit, "next_action": "scene_image_review"},
            "events": [_lg11_edit_event("scene_asset_replacement_ready")],
        }

    if scope == "style":
        source_version = db.query(DetailPageVersion).filter(
            DetailPageVersion.id == str(dict(edit.get("base_version") or {}).get("id") or ""),
            DetailPageVersion.project_id == run.project_id,
        ).one_or_none()
        if source_version is None:
            raise EditIntentValidationError("LG-11 style fork source version is not in this project.")
        fork = build_lg11_style_version_fork(
            run=run,
            source_version=source_version,
            edit_run_id=run.id,
            intent=intent,
            db=db,
        )
        return {
            "current_stage": "style_version_reassembled",
            "status": "completed",
            "edit": {**edit, "next_action": "none", "style_version_fork": fork},
            "events": [_lg11_edit_event("style_version_reassembled", status="completed")],
        }

    # Only direct copy content is in TASK-11.3's execution scope.  Natural
    # language normalization and all non-copy work remain later LG-11 tasks.
    if scope != "copy" or not dict(intent.get("copy_changes") or {}):
        return {
            "current_stage": "edit_run_ready",
            "status": "completed",
            "edit": {**edit, "next_action": "task_11_3_edit_execution"},
            "events": [_lg11_edit_event("edit_run_ready", status="completed")],
        }
    source_version = db.query(DetailPageVersion).filter(
        DetailPageVersion.id == str(dict(edit.get("base_version") or {}).get("id") or ""),
        DetailPageVersion.project_id == run.project_id,
    ).one_or_none()
    if source_version is None:
        raise EditIntentValidationError("LG-11 copy fork source version is not in this project.")
    fork = build_lg11_copy_version_fork(
        source_version=source_version,
        edit_run_id=run.id,
        intent=intent,
    )

    return {
        "current_stage": "copy_version_forked",
        "status": "completed",
        "edit": {**edit, "next_action": "none", "copy_version_fork": fork},
        "events": [_lg11_edit_event("copy_version_forked", status="completed")],
    }


def _lg11_reject_edit_run(state: LG11EditGraphState) -> dict[str, Any]:
    """Close a rejected confirmation without exposing it to edit execution."""

    return {
        "current_stage": "edit_rejected",
        "status": "completed",
        "edit": {**dict(state.get("edit") or {}), "next_action": "none"},
        "events": [_lg11_edit_event("edit_rejected", status="completed")],
    }


def _lg11_edit_confirmation_route(state: LG11EditGraphState) -> str:
    return (
        "finalize_edit_run"
        if str(dict(state.get("edit") or {}).get("confirmation", {}).get("status") or "") == "confirmed"
        else "reject_edit_run"
    )


def _lg11_finalize_edit_run_route(state: LG11EditGraphState) -> str:
    next_action = str(dict(state.get("edit") or {}).get("next_action") or "")
    if next_action == "fact_evidence_review":
        return "fact_evidence_review"
    if next_action == "scene_cost_approval":
        return "scene_cost_approval"
    if next_action == "scene_image_review":
        return "scene_image_review"
    if next_action == "canvas_edit":
        return "canvas_edit"
    return "end"


def _lg11_canvas_edit_route(state: LG11EditGraphState) -> str:
    return "canvas_edit" if str(state.get("status") or "") == "running" else "end"


def _lg11_canvas_edit_interrupt(state: LG11EditGraphState) -> dict[str, Any]:
    canvas = dict(state.get("canvas") or {})
    return {
        "schema_version": "lg11-v1", "review_stage": "canvas_edit",
        "title": "Canvas section draft", "description": "Apply, undo, redo, or commit section-only changes.",
        "allowed_decisions": ["apply", "undo", "redo", "commit"],
        "run_id": str(state.get("run_id") or ""), "thread_id": str(state.get("thread_id") or state.get("run_id") or ""),
        "project_id": str(state.get("project_id") or ""),
        "context": {"canvas": canvas},
    }


def _lg11_canvas_edit(state: LG11EditGraphState) -> dict[str, Any]:
    """Apply one deterministic section command or commit the frozen draft."""
    from src.services.langgraph_review_service import validate_resume_payload
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.page_finalization_service import (
        EditIntentValidationError, apply_lg11_canvas_command, build_lg11_canvas_version_fork,
    )
    response = validate_resume_payload(interrupt(_lg11_canvas_edit_interrupt(state)), "canvas_edit")
    edit = dict(state.get("edit") or {})
    canvas = dict(state.get("canvas") or {})
    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-11 canvas edit requires the graph database session.")
    from src.db.models import AgentRun, DetailPageVersion
    run = db.query(AgentRun).filter(AgentRun.id == str(state.get("run_id") or ""), AgentRun.mode == "lg11_edit").one()
    intent = dict((run.input_snapshot or {}).get("lg11_edit_intent") or {})
    if response.decision == "commit":
        source = db.query(DetailPageVersion).filter(DetailPageVersion.id == str(dict(edit.get("base_version") or {}).get("id") or ""), DetailPageVersion.project_id == run.project_id).one()
        fork = build_lg11_canvas_version_fork(run=run, source_version=source, edit_run_id=run.id, intent=intent, canvas_draft=canvas)
        return {"current_stage": "canvas_version_forked", "status": "completed", "canvas": canvas,
                "edit": {**edit, "next_action": "none", "canvas_version_fork": fork},
                "events": [_lg11_edit_event("canvas_version_forked", status="completed")]}
    try:
        selected_context = dict(dict(intent.get("preserve_constraints") or {}).get("selected_context") or {})
        selected_section_id = str(selected_context.get("section_id") or "")
        selected_element_id = str(selected_context.get("element_id") or "")
        command = dict(response.canvas_operation or {})
        command_kind = str(command.get("kind") or "")
        # A conversational edit is anchored to the frozen selection captured
        # in its EditIntent.  Undo/redo are draft-history operations; every
        # mutating section/element command must stay inside that anchor.
        if selected_section_id and command_kind not in {"undo", "redo"}:
            if str(command.get("section_id") or "") != selected_section_id:
                raise EditIntentValidationError("LG-11 Canvas command is outside the selected frozen section.")
        if selected_element_id and command_kind not in {"undo", "redo"}:
            if str(command.get("element_id") or "") != selected_element_id:
                raise EditIntentValidationError("LG-11 Canvas command is outside the selected frozen element.")
        updated = apply_lg11_canvas_command(
            canvas_draft=canvas, decision=response.decision, command=command,
            db=db, project_id=run.project_id,
        )
        return {"current_stage": "canvas_draft_updated", "status": "running", "canvas": updated,
                "edit": {**edit, "next_action": "canvas_edit", "canvas_last_error": None},
                "events": [_lg11_edit_event("canvas_draft_updated")]}
    except EditIntentValidationError as error:
        return {"current_stage": "canvas_operation_rejected", "status": "running", "canvas": canvas,
                "edit": {**edit, "next_action": "canvas_edit", "canvas_last_error": str(error)},
                "events": [_lg11_edit_event("canvas_operation_rejected")]}


def _lg11_fact_evidence_review_interrupt(state: LG11EditGraphState) -> dict[str, Any]:
    """Expose frozen fact/evidence identities before marking dependencies stale."""

    edit = dict(state.get("edit") or {})
    preview = dict(edit.get("impact_preview") or {})
    affected = dict(preview.get("affected_artifacts") or {})
    return {
        "schema_version": "lg11-v1",
        "review_stage": "evidence_review",
        "title": "사실·근거 변경 검토",
        "description": "변경된 사실에 연결된 카피와 장면만 stale 처리합니다. 새 이미지 생성이나 비용 승인은 시작하지 않습니다.",
        "allowed_decisions": ["approve", "reject"],
        "run_id": str(state.get("run_id") or ""),
        "thread_id": str(state.get("thread_id") or state.get("run_id") or ""),
        "project_id": str(state.get("project_id") or ""),
        "context": {
            "lineage": copy.deepcopy(dict(edit.get("lineage") or {})),
            "base_version": copy.deepcopy(dict(edit.get("base_version") or {})),
            "intent_id": str(edit.get("intent_id") or ""),
            "fact_evidence": copy.deepcopy(list(affected.get("facts") or [])),
            "affected_section_ids": copy.deepcopy(list(affected.get("section_ids") or [])),
            "affected_scene_ids": copy.deepcopy(list(affected.get("scene_ids") or [])),
            "affected_artifacts": affected,
        },
        "rejection_reason": "",
    }


def _lg11_fact_evidence_review(state: LG11EditGraphState) -> dict[str, Any]:
    """Confirm one fact-change scope, then persist only its stale envelope."""

    from src.db.models import AgentRun, DetailPageVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_review_service import validate_resume_payload
    from src.services.page_finalization_service import build_lg11_fact_selective_stale_state

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-11 fact evidence review requires the graph database session.")
    run = db.query(AgentRun).filter_by(id=str(state.get("run_id") or ""), mode="lg11_edit").one_or_none()
    if run is None:
        raise ValueError("LG-11 fact edit run is unavailable.")
    edit = dict(state.get("edit") or {})
    raw = interrupt(_lg11_fact_evidence_review_interrupt(state))
    response = validate_resume_payload(raw, "evidence_review")
    if response.decision == "reject":
        return {
            "current_stage": "fact_evidence_rejected",
            "status": "completed",
            "edit": {
                **edit,
                "next_action": "none",
                "fact_evidence_review": {"status": "rejected"},
                "selective_stale": {"status": "not_applied", "reason": "evidence_review_rejected"},
            },
            "events": [_lg11_edit_event("fact_evidence_rejected", status="completed")],
        }
    source = db.query(DetailPageVersion).filter_by(
        id=str(dict(edit.get("base_version") or {}).get("id") or ""), project_id=run.project_id,
    ).one_or_none()
    if source is None:
        raise ValueError("LG-11 fact edit source version is unavailable.")
    stale = build_lg11_fact_selective_stale_state(
        source_version=source,
        edit_run_id=run.id,
        intent=dict((run.input_snapshot or {}).get("lg11_edit_intent") or {}),
    )
    return {
        "current_stage": "fact_selective_stale",
        "status": "completed",
        "edit": {
            **edit,
            "next_action": "none",
            "fact_evidence_review": {"status": "approved"},
            "selective_stale": stale,
        },
        "events": [_lg11_edit_event("fact_selective_stale", status="completed")],
    }


def _lg11_scene_cost_approval(state: LG11EditGraphState) -> dict[str, Any]:
    """Require a fresh LG-9 cost approval before one scene is dispatched."""

    from src.db.models import AgentRun, DetailPageVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import (
        ensure_lg11_scene_regeneration_cost_plan,
        record_cost_decision,
    )
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-11 scene cost approval requires the graph database session.")
    run = db.query(AgentRun).filter_by(id=str(state.get("run_id") or ""), mode="lg11_edit").one_or_none()
    if run is None:
        raise ValueError("LG-11 scene edit run is unavailable.")
    edit = dict(state.get("edit") or {})
    intent = dict((run.input_snapshot or {}).get("lg11_edit_intent") or {})
    source = db.query(DetailPageVersion).filter_by(
        id=str(dict(edit.get("base_version") or {}).get("id") or ""), project_id=run.project_id,
    ).one_or_none()
    if source is None:
        raise ValueError("LG-11 scene edit source version is unavailable.")
    scene_id = str((intent.get("target_ids") or [""])[0] or "")
    cost_plan = ensure_lg11_scene_regeneration_cost_plan(run=run, source_version=source, scene_id=scene_id, db=db)
    generation = {
        **dict(state.get("generation") or {}),
        "cost_plan": cost_plan,
        "cost_plan_hash": cost_plan["cost_plan_hash"],
        "scene_ids": [scene_id],
        "next_action": "cost_approval",
    }
    raw = interrupt(review_interrupt_payload(
        "generation_pending", {**state, "generation": generation}, schema_version="lg5-v1",
    ))
    response = validate_resume_payload(raw, "generation_pending")
    cost_plan = record_cost_decision(
        run_id=run.id, project_id=run.project_id, cost_plan_hash=cost_plan["cost_plan_hash"],
        decision=response.decision, db=db,
    )
    generation.update({"cost_plan": cost_plan, "cost_approved": response.decision == "approve"})
    if response.decision == "defer":
        generation["next_action"] = "cost_approval"
        return {
            "current_stage": "scene_cost_approval", "status": "running", "generation": generation,
            "edit": {**edit, "next_action": "scene_cost_approval"},
            "events": [_lg11_edit_event("scene_cost_approval", status="deferred")],
        }
    generation["next_action"] = "prepare"
    return {
        "current_stage": "scene_cost_approval", "status": "running", "generation": generation,
        "edit": {**edit, "next_action": "scene_prepare"},
        "events": [_lg11_edit_event("scene_cost_approval")],
    }


def _lg11_scene_cost_approval_route(state: LG11EditGraphState) -> str:
    return "scene_prepare" if (state.get("generation") or {}).get("cost_approved") else "scene_cost_approval"


def _lg11_scene_prepare(state: LG11EditGraphState) -> dict[str, Any]:
    from src.db.models import AgentRun, DetailPageVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import prepare_lg11_scene_regeneration

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-11 scene preparation requires the graph database session.")
    run = db.query(AgentRun).filter_by(id=str(state.get("run_id") or ""), mode="lg11_edit").one()
    edit = dict(state.get("edit") or {})
    intent = dict((run.input_snapshot or {}).get("lg11_edit_intent") or {})
    source = db.query(DetailPageVersion).filter_by(
        id=str(dict(edit.get("base_version") or {}).get("id") or ""), project_id=run.project_id,
    ).one()
    generation = prepare_lg11_scene_regeneration(
        run=run, source_version=source, scene_id=str((intent.get("target_ids") or [""])[0] or ""),
        cost_plan_hash=str((state.get("generation") or {}).get("cost_plan_hash") or ""), db=db,
    )
    return {"current_stage": "scene_prepare", "status": "running", "generation": generation,
            "edit": {**edit, "next_action": "scene_dispatch"}, "events": [_lg11_edit_event("scene_prepare")]}


def _lg11_scene_dispatch(state: LG11EditGraphState) -> dict[str, Any]:
    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import dispatch_graph_image_jobs

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-11 scene dispatch requires the graph database session.")
    run = db.query(AgentRun).filter_by(id=str(state.get("run_id") or ""), mode="lg11_edit").one()
    provider = str(dict((state.get("generation") or {}).get("cost_plan") or {}).get("provider") or "").lower()
    # The immutable source scene, rather than the LG-11 orchestration mode,
    # determines whether the pre-existing LG-9 mock adapter is allowed.
    provider_mode = "mock" if provider in {"mock", "fake"} else "real"
    generation = dispatch_graph_image_jobs(run_id=run.id, project_id=run.project_id, mode=provider_mode, db=db)
    return {"current_stage": "scene_dispatch", "status": "running", "generation": generation,
            "edit": {**dict(state.get("edit") or {}), "next_action": "scene_provider_wait"},
            "events": [_lg11_edit_event("scene_dispatch")]}


def _lg11_scene_provider_wait(state: LG11EditGraphState) -> dict[str, Any]:
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import collect_graph_image_results
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-11 scene provider wait requires the graph database session.")
    generation = collect_graph_image_results(run_id=str(state.get("run_id") or ""), project_id=str(state.get("project_id") or ""), db=db)
    if generation.get("pending_count", 0):
        raw = interrupt(review_interrupt_payload("provider_wait", {**state, "generation": generation}, schema_version="lg5-v1"))
        validate_resume_payload(raw, "provider_wait")
        generation = collect_graph_image_results(run_id=str(state.get("run_id") or ""), project_id=str(state.get("project_id") or ""), db=db)
    generation["next_action"] = "wait" if generation.get("pending_count", 0) else "review"
    return {"current_stage": "scene_provider_wait", "status": "running", "generation": generation,
            "edit": {**dict(state.get("edit") or {}), "next_action": "scene_provider_wait" if generation.get("pending_count", 0) else "scene_image_review"},
            "events": [_lg11_edit_event("scene_provider_wait")]}


def _lg11_scene_provider_wait_route(state: LG11EditGraphState) -> str:
    return "scene_provider_wait" if (state.get("generation") or {}).get("pending_count", 0) else "scene_image_review"


def _lg11_scene_image_review(state: LG11EditGraphState) -> dict[str, Any]:
    """Reuse LG-9 scene review and create the child only after approval."""

    from src.db.models import AgentRun, DetailPageVersion, ImageGenerationJobRecord
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import apply_image_review, collect_graph_image_results
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload
    from src.services.page_finalization_service import build_lg11_scene_version_fork

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-11 scene review requires the graph database session.")
    run = db.query(AgentRun).filter_by(id=str(state.get("run_id") or ""), mode="lg11_edit").one()
    edit = dict(state.get("edit") or {})
    generation = collect_graph_image_results(run_id=run.id, project_id=run.project_id, db=db)
    if generation.get("failed_job_ids"):
        return {"current_stage": "scene_generation_failed", "status": "completed", "generation": generation,
                "edit": {**edit, "next_action": "none", "scene_status": "failed"},
                "events": [_lg11_edit_event("scene_generation_failed", status="completed")]}
    raw = interrupt(review_interrupt_payload("image_review", {**state, "generation": generation}, schema_version="lg5-v1"))
    response = validate_resume_payload(raw, "image_review")
    if response.decision != "approve":
        # Regeneration within the same edit run would bypass a fresh approval.
        if response.decision not in {"reject"}:
            raise ValueError("LG-11 scene edits require a new edit run for another regeneration or upload.")
        generation = apply_image_review(run_id=run.id, project_id=run.project_id, decision="reject", job_id=response.job_id, db=db)
        return {"current_stage": "scene_edit_rejected", "status": "completed", "generation": generation,
                "edit": {**edit, "next_action": "none", "scene_status": "rejected"},
                "events": [_lg11_edit_event("scene_edit_rejected", status="completed")]}
    generation = apply_image_review(run_id=run.id, project_id=run.project_id, decision="approve", job_id=response.job_id, db=db)
    job = db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id, job_id=response.job_id).one()
    intent = dict((run.input_snapshot or {}).get("lg11_edit_intent") or {})
    source = db.query(DetailPageVersion).filter_by(id=str(dict(edit.get("base_version") or {}).get("id") or ""), project_id=run.project_id).one()
    fork = build_lg11_scene_version_fork(source_version=source, edit_run_id=run.id, intent=intent, job=job, db=db)
    return {"current_stage": "scene_version_forked", "status": "completed", "generation": generation,
            "edit": {**edit, "next_action": "none", "scene_status": "approved", "scene_version_fork": fork},
            "events": [_lg11_edit_event("scene_version_forked", status="completed")]}


def build_lg11_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """Compile LG-11 separately so LG-5 through LG-10 routes remain unchanged."""

    graph = StateGraph(LG11EditGraphState)
    graph.add_node("prepare_edit_run", _lg11_prepare_edit_run)
    graph.add_node("edit_confirmation", _lg11_edit_confirmation)
    graph.add_node("finalize_edit_run", _lg11_finalize_edit_run)
    graph.add_node("canvas_edit", _lg11_canvas_edit)
    graph.add_node("fact_evidence_review", _lg11_fact_evidence_review)
    graph.add_node("scene_cost_approval", _lg11_scene_cost_approval)
    graph.add_node("scene_prepare", _lg11_scene_prepare)
    graph.add_node("scene_dispatch", _lg11_scene_dispatch)
    graph.add_node("scene_provider_wait", _lg11_scene_provider_wait)
    graph.add_node("scene_image_review", _lg11_scene_image_review)
    graph.add_node("reject_edit_run", _lg11_reject_edit_run)
    graph.add_edge(START, "prepare_edit_run")
    graph.add_edge("prepare_edit_run", "edit_confirmation")
    graph.add_conditional_edges("edit_confirmation", _lg11_edit_confirmation_route, {
        "finalize_edit_run": "finalize_edit_run", "reject_edit_run": "reject_edit_run",
    })
    graph.add_conditional_edges("finalize_edit_run", _lg11_finalize_edit_run_route, {
        "fact_evidence_review": "fact_evidence_review", "scene_cost_approval": "scene_cost_approval", "scene_image_review": "scene_image_review", "canvas_edit": "canvas_edit", "end": END,
    })
    graph.add_edge("fact_evidence_review", END)
    graph.add_conditional_edges("scene_cost_approval", _lg11_scene_cost_approval_route, {
        "scene_cost_approval": "scene_cost_approval", "scene_prepare": "scene_prepare",
    })
    graph.add_edge("scene_prepare", "scene_dispatch")
    graph.add_edge("scene_dispatch", "scene_provider_wait")
    graph.add_conditional_edges("scene_provider_wait", _lg11_scene_provider_wait_route, {
        "scene_provider_wait": "scene_provider_wait", "scene_image_review": "scene_image_review",
    })
    graph.add_edge("scene_image_review", END)
    graph.add_conditional_edges("canvas_edit", _lg11_canvas_edit_route, {"canvas_edit": "canvas_edit", "end": END})
    graph.add_edge("reject_edit_run", END)
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
