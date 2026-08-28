"""LG-0 LangGraph runtime foundation.

This module intentionally does not replace the existing ``AgentGraph`` yet.
It proves that Sellform has a real, compiled LangGraph runtime and provides a
small, checkpoint-safe input boundary for subsequent migration sprints.
"""

from __future__ import annotations

import copy
import os
import re
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
        "asset_ids",
        "sales_channel",
        "model_options",
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
    # LG-12 keeps only frozen QA/Quality-Bar/attempt references in the
    # checkpoint.  Reports, findings, page snapshots and provider payloads
    # remain in their immutable stores.
    quality: Annotated[dict[str, Any], _merge_discovery]


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
    # LG-11 child versions enter the same TASK-12.9 Quality Bar nodes as an
    # LG-10 first render.  Only their frozen page/report/result references are
    # retained in the checkpoint.
    rendering: Annotated[dict[str, Any], _merge_discovery]
    quality: Annotated[dict[str, Any], _merge_discovery]


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


def _trusted_run_input_snapshot(state: SellformGraphState) -> dict[str, Any]:
    """Resolve raw product input from its scoped domain record, never state."""

    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LangGraph node requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=state["run_id"], workspace_id=state["workspace_id"], project_id=state["project_id"],
    ).one()
    return dict(run.input_snapshot or {})


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
        input_snapshot=_trusted_run_input_snapshot(state),
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
        input_snapshot=_trusted_run_input_snapshot(state),
    )
    return {
        "current_stage": "source_collection",
        "status": "running",
        "discovery": discovery,
        "events": [_lg2_event("source_collection")],
    }


def _lg2_product_understanding(state: SellformGraphState) -> dict[str, Any]:
    from src.agents.nodes.product_understanding.agent import ProductUnderstandingAgent

    snapshot = _trusted_run_input_snapshot(state)
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
    snapshot = _trusted_run_input_snapshot(state)
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


def _lg5_provider_mode(state: SellformGraphState) -> str:
    return "mock" if state.get("mode") == "mock" or settings.SELLFORM_IMAGE_GENERATION_MODE.strip().lower() == "mock" else "real"


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
    if _lg5_provider_mode(state) != "mock" and not storyboard_image_generation_is_available():
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
        run_id=state["run_id"], project_id=state["project_id"], mode=_lg5_provider_mode(state), db=db,
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
        run_id=state["run_id"], project_id=state["project_id"], mode=_lg5_provider_mode(state), db=db,
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

    from src.db.models import AgentRun, CommerceCreativeMasterVersion
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
    master = (
        db.query(CommerceCreativeMasterVersion)
        .filter_by(workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id)
        .order_by(CommerceCreativeMasterVersion.version.desc())
        .first()
    )
    if master is not None:
        _lg12_quality_finalize_frozen_page_exports(
            page=version, channels=list(master.target_channels or []), db=db,
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


# TASK-12.9 --------------------------------------------------------------------
# These nodes extend the existing LG-10 compiled graph after its immutable
# renderer.  They retain only bounded refs in state and always derive the
# Quality Bar again from the persisted report before making a route decision.

_LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS = 2


_LG12_QUALITY_ROUTE_DOMAINS = {
    "IMAGE_REWORK": {"image_identity_quality"},
    "COPY_REWORK": {"korean_copy_readability"},
    "VISUAL_REWORK": {"layout_typography_brand_flow", "channel_preview_export_parity"},
    # Page-plan findings are represented by the visual evaluator today.  Keep
    # the route explicit so a later plan-specific result does not silently
    # become broad seller-controlled mutation.
    "PLAN_REWORK": {"layout_typography_brand_flow"},
}
_LG12_QUALITY_DOMAIN_PRIORITY = {
    domain_id: index
    for index, domain_id in enumerate((
        "factual_rights_policy",
        "image_identity_quality",
        "korean_copy_readability",
        "layout_typography_brand_flow",
        "channel_preview_export_parity",
    ))
}

# Quality Bar retains the evaluator's immutable ``rule_id``.  Execution must
# not compare that namespace directly to a UI-oriented action string: doing so
# made valid ``copy.spacing_inconsistency`` findings fall through to review.
# This is intentionally an allowlist, rather than a suffix parser, so a rule
# from another evaluator can never acquire copy-rewrite authority.
_LG12_QUALITY_ACTION_BY_RULE = {
    "copy.spacing_inconsistency": "spacing_inconsistency",
    "copy.punctuation_overuse": "punctuation_overuse",
    "copy.emphasis_overuse": "emphasis_overuse",
    "copy.excessive_promotional_tone": "promotional_tone",
    "copy.cta_action_unclear": "cta_clarity",
    # These layout rules may use an already-pinned replacement Brand Kit via
    # the existing TASK-11.6 selective style fork.  Other layout findings are
    # handled by the narrow Canvas/plan commands below or seller review.
    "layout.brand_kit_identity_mismatch": "style_reassembly",
    "layout.brand_color_token_mismatch": "style_reassembly",
    "layout.brand_font_token_mismatch": "style_reassembly",
    "layout.renderer_token_mismatch": "style_reassembly",
    "layout.typography_role_token_mismatch": "style_reassembly",
    "layout.visual_hierarchy_token_mismatch": "style_reassembly",
    "layout.section_order_mismatch": "plan_reorder",
    "layout.scene_order_mismatch": "plan_reorder",
    "layout.scene_identity_mismatch": "plan_reorder",
    "layout.final_spec_position": "plan_reorder",
}


def _lg12_test_failpoint(name: str) -> None:
    """Stop only a pytest graph at one durable TASK-12.9 crash boundary.

    The normal production path does not read test failpoints. Tests arm one
    variable after the preceding production node has checkpointed bounded
    state; the next node then fails before making a new business write.
    """

    if os.getenv("PYTEST_CURRENT_TEST") and os.getenv(name) == "1":
        raise RuntimeError(f"TASK-12.9 test failpoint reached: {name}")


def _lg12_quality_rework_action(value: Any) -> str | None:
    """Map one persisted evaluator rule to an explicit rework action."""

    return _LG12_QUALITY_ACTION_BY_RULE.get(str(value or ""))


def _lg12_quality_selected_target(quality: dict[str, Any]) -> dict[str, Any] | None:
    """Return one exact persisted Quality-Bar target for the active route."""

    route = str(quality.get("routing_code") or "")
    allowed_domains = _LG12_QUALITY_ROUTE_DOMAINS.get(route, set())
    candidates = [
        dict(item) for item in list(quality.get("rework_targets") or [])
        if str(dict(item).get("domain") or "") in allowed_domains
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (
        _LG12_QUALITY_DOMAIN_PRIORITY.get(
            str(item.get("domain") or ""), len(_LG12_QUALITY_DOMAIN_PRIORITY),
        ),
        str(dict(item.get("target_ref") or {}).get("type") or ""),
        str(dict(item.get("target_ref") or {}).get("id") or ""),
        str(dict(item.get("finding_ref") or {}).get("id") or ""),
    ))[0]


def _lg12_quality_node_family(target: dict[str, Any]) -> str:
    """Group equivalent target nodes across route labels, not whole runs."""

    target_type = str(dict(target.get("target_ref") or {}).get("type") or "")
    if target_type in {"asset", "scene"}:
        return "scene_reassembly"
    if target_type == "copy_field":
        return "copy_reassembly"
    if target_type in {"frozen_canvas_element", "frozen_section", "PagePlanVersion"}:
        return "layout_plan_reassembly"
    if target_type == "BrandKitVersion":
        return "style_reassembly"
    return "unresolved_target"


def _lg12_quality_attempt_key(*, node_family: str, target_ref: dict[str, Any]) -> str:
    from src.services.prompt_intelligence_service import canonical_hash

    return canonical_hash({"node_family": node_family, "target_ref": target_ref})


def _lg12_quality_attempt_entry(quality: dict[str, Any], *, target: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    target_ref = dict(target.get("logical_target_ref") or target.get("target_ref") or {})
    family = _lg12_quality_node_family(target)
    key = _lg12_quality_attempt_key(node_family=family, target_ref=target_ref)
    for entry in list(quality.get("attempt_ledger") or []):
        candidate = dict(entry)
        if str(candidate.get("attempt_key") or "") == key:
            return key, candidate
    return key, None


def _lg12_quality_upsert_ledger(quality: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Persist a bounded, deterministic checkpoint ledger (never raw QA)."""

    rows = [dict(item) for item in list(quality.get("attempt_ledger") or [])]
    rows = [item for item in rows if str(item.get("attempt_key") or "") != str(entry["attempt_key"])]
    rows.append(entry)
    # A page has a bounded frozen target set; retaining 64 keys is enough for
    # recovery while preventing the public projection from becoming a history
    # dump.  Exhaustion is deterministic rather than evicted opportunistically.
    return sorted(rows, key=lambda item: str(item.get("attempt_key") or ""))[:64]


def _lg12_quality_event(stage: str, *, status: str = "running", node_status: str = "completed") -> dict[str, Any]:
    return {"stage": stage, "status": status, "node_status": node_status, "event_type": "node_completed"}


def _lg12_quality_page_ref(state: SellformGraphState) -> dict[str, Any]:
    rendering = dict(state.get("rendering") or {})
    page = dict(rendering.get("detail_page_version") or {})
    page_id = str(page.get("id") or "")
    page_hash = str(page.get("snapshot_hash") or "")
    schema_version = str(page.get("schema_version") or "")
    if not page_id or len(page_hash) != 64 or not schema_version:
        raise ValueError("LG-12 QA requires the current immutable DetailPageVersion reference.")
    return {"id": page_id, "version": schema_version, "hash": page_hash, "type": "DetailPageVersion"}


def _lg12_quality_logical_target_ref(*, page: Any, target: dict[str, Any]) -> dict[str, Any]:
    """Return the retry identity for one target, independent of ref wrappers.

    A frozen manifest can describe the same scene by its asset or its scene
    ref.  Provider retry budget belongs to the scene, not either representation.
    Other currently-supported targets already have one stable production ID.
    """

    from src.services.prompt_intelligence_service import canonical_hash

    raw = dict(target.get("target_ref") or {})
    target_type = str(raw.get("type") or "")
    snapshot = dict(getattr(page, "sections_json", {}) or {})
    # A child page necessarily has a new snapshot hash.  Retry scope must be
    # stable across that immutable lineage: an asset replacement in scene
    # ``hero`` on a child is still the same logical scene as the parent
    # target, not a fresh third provider budget.  The persisted QA lineage is
    # the narrow authority shared by every legitimate child; fall back to the
    # page ID only for legacy frozen pages that predate that lineage sidecar.
    quality_lineage = dict(snapshot.get("lg12_quality_lineage") or {})
    master_ref = dict(quality_lineage.get("master_ref") or {})
    retry_scope = {
        "creator_run_id": str(quality_lineage.get("creator_run_id") or ""),
        "master_id": str(master_ref.get("id") or ""),
        "master_version": str(master_ref.get("version") or ""),
        "master_hash": str(master_ref.get("hash") or ""),
    }
    if not retry_scope["creator_run_id"] or not retry_scope["master_id"] or not retry_scope["master_hash"]:
        retry_scope = {"legacy_detail_page_id": str(getattr(page, "id", "") or "")}
    if target_type in {"asset", "scene"}:
        canonical = dict(dict(dict(getattr(page, "sections_json", {}) or {}).get("lg10") or {}).get("canonical_page_assembly_input") or {})
        assets = [dict(item) for item in list(dict(canonical.get("approved_asset_manifest") or {}).get("assets") or [])]
        requested = str(raw.get("id") or "")
        scene_ids = {
            str(item.get("scene_id") or "")
            for item in assets
            if requested in {str(item.get("asset_id") or ""), str(item.get("scene_id") or "")}
            and str(item.get("scene_id") or "")
        }
        if len(scene_ids) != 1:
            raise ValueError("Quality retry target is not one frozen manifest scene.")
        scene_id = next(iter(scene_ids))
        return {
            "type": "scene", "id": scene_id, "version": "frozen-scene-v1",
            "hash": canonical_hash({"retry_scope": retry_scope, "scene_id": scene_id}),
        }
    if target_type == "copy_field":
        match = re.fullmatch(r"copy-field:([^:]+):([^:]+)", str(raw.get("id") or ""))
        if match is None:
            raise ValueError("Quality retry copy target is not a stable frozen field.")
        section_id, field = match.groups()
        return {
            "type": "copy_field", "id": f"copy-field:{section_id}:{field}",
            "version": "frozen-copy-field-v1",
            "hash": canonical_hash({
                "retry_scope": retry_scope, "section_id": section_id, "field": field,
            }),
        }
    if target_type in {"frozen_canvas_element", "frozen_section", "PagePlanVersion"}:
        if not all(str(raw.get(key) or "") for key in ("id", "version", "hash")):
            raise ValueError("Quality retry target is missing frozen identity.")
        return {"type": target_type, "id": str(raw["id"]), "version": raw["version"], "hash": str(raw["hash"])}
    raise ValueError("Quality retry target type is not supported.")


def _lg12_quality_with_logical_targets(*, page: Any, targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich bounded Quality-Bar targets without changing its canonical body."""

    rows: list[dict[str, Any]] = []
    for target in targets:
        row = dict(target)
        try:
            row["logical_target_ref"] = _lg12_quality_logical_target_ref(page=page, target=row)
        except ValueError:
            # The routing node will keep this target seller-controlled.  Do not
            # manufacture a raw-ref retry identity as a fallback.
            row["logical_target_ref"] = None
        rows.append(row)
    return rows


def _lg12_quality_summary(*, page_ref: dict[str, Any], report_ref: dict[str, Any], quality_bar: dict[str, Any], attempts: int, attempt_ledger: list[dict[str, Any]] | None = None, quality_owner_run_ref: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep only reference-safe Quality Bar information in checkpoints."""

    reasons = [
        {key: reason[key] for key in ("code", "domain", "finding_ref") if key in reason}
        for reason in list(quality_bar.get("blocking_reasons") or [])
    ]
    return {
        "schema_version": "lg12-quality-graph-v1",
        "current_detail_page_ref": page_ref,
        # LG-11 can execute an edit in a child run while its frozen page keeps
        # the source-run Master lineage.  QA is owned by that persisted source
        # run, never by a caller-provided run identifier.
        "quality_owner_run_ref": dict(quality_owner_run_ref or {}),
        "quality_report_ref": report_ref,
        "quality_bar_ref": {
            "id": str(quality_bar["quality_bar_result_id"]), "version": 1,
            "hash": str(quality_bar["canonical_hash"]), "type": "QualityBarResult",
        },
        "quality_bar_verdict": str(quality_bar["verdict"]),
        "routing_code": str(quality_bar["routing_code"]),
        "rework_attempt_count": attempts,
        "max_rework_attempts": _LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS,
        "attempt_ledger": [dict(item) for item in list(attempt_ledger or [])],
        "rework_targets": [dict(item) for item in list(quality_bar.get("rework_targets") or [])],
        "last_blocking_reasons": reasons,
        "seller_review_required": bool(quality_bar.get("seller_review_required")),
    }


def _lg12_quality_evaluate(state: SellformGraphState) -> dict[str, Any]:
    """Persist/read one frozen report, then project its canonical Quality Bar."""

    if str(state.get("current_stage") or "") == "quality_rework_child_frozen":
        _lg12_test_failpoint("LG12_TEST_FAILPOINT_AFTER_CHILD_PERSIST")

    from src.db.models import AgentRun, DetailPageVersion, QualityAssessmentReportVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.quality_assessment_service import (
        QualityAssessmentContractError, build_lg12_quality_assessment_report,
        lg12_quality_report_reference,
    )
    from src.services.quality_bar_service import QualityBarContractError, aggregate_quality_bar

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 QA requires the graph database session.")
    execution_run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""), workspace_id=str(state.get("workspace_id") or ""),
        project_id=str(state.get("project_id") or ""),
    ).one_or_none()
    if execution_run is None:
        raise ValueError("LG-12 QA run is unavailable in this workspace.")
    prior_quality = dict(state.get("quality") or {})
    attempt_ledger = [dict(item) for item in list(prior_quality.get("attempt_ledger") or [])]
    attempts = sum(int(item.get("attempt_count") or 0) for item in attempt_ledger)
    page_ref: dict[str, Any] = {}
    quality_owner_run_ref: dict[str, Any] = {}
    try:
        page_ref = _lg12_quality_page_ref(state)
        page = db.query(DetailPageVersion).filter_by(
            id=str(page_ref["id"]), project_id=execution_run.project_id,
        ).one_or_none()
        lineage = dict(dict(page.sections_json or {}).get("lg12_quality_lineage") or {}) if page is not None else {}
        owner_id = str(lineage.get("creator_run_id") or execution_run.id)
        quality_owner = db.query(AgentRun).filter_by(
            id=owner_id, workspace_id=execution_run.workspace_id,
            project_id=execution_run.project_id,
        ).one_or_none()
        if quality_owner is None:
            raise QualityAssessmentContractError("Frozen page QA owner run is unavailable in this workspace.")
        quality_owner_run_ref = {"id": str(quality_owner.id), "type": "AgentRun"}
        report = build_lg12_quality_assessment_report(db, run=quality_owner, detail_page_reference=page_ref)
        db.commit(); db.refresh(report)
        report_ref = lg12_quality_report_reference(report)
        # The QA projection retains the typed reference, while the strict
        # Quality Bar input contract deliberately accepts only its immutable
        # ID/version/hash identity.  Do not leak an extra ``type`` field into
        # that exact persisted-reference boundary.
        quality_bar = aggregate_quality_bar(
            db,
            report_ref={key: report_ref[key] for key in ("id", "version", "hash")},
        )
        quality_bar = {
            **quality_bar,
            "rework_targets": _lg12_quality_with_logical_targets(
                page=page, targets=[dict(item) for item in list(quality_bar.get("rework_targets") or [])],
            ),
        }
    except (QualityAssessmentContractError, QualityBarContractError):
        # A missing or mismatched frozen lineage is never converted into a
        # synthetic PASS/retry.  It is a bounded seller-review condition.
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "quality": {
                **prior_quality, "schema_version": "lg12-quality-graph-v1",
                "quality_bar_verdict": "NEEDS_REVIEW", "routing_code": "SELLER_REVIEW",
                "current_detail_page_ref": page_ref or dict(prior_quality.get("current_detail_page_ref") or {}),
                "rework_attempt_count": attempts, "max_rework_attempts": _LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS,
                "seller_review_required": True,
                "last_blocking_reasons": [{"code": "quality_input_not_evaluable", "domain": None}],
            },
            "events": [_lg12_quality_event("quality_evaluation", node_status="needs_review")],
        }
    return {
        "current_stage": "quality_bar", "status": "running",
        "quality": {**prior_quality, **_lg12_quality_summary(
            page_ref=page_ref, report_ref=report_ref, quality_bar=quality_bar, attempts=attempts,
            attempt_ledger=attempt_ledger, quality_owner_run_ref=quality_owner_run_ref,
        )},
        "events": [_lg12_quality_event("quality_evaluation")],
    }


def _lg12_quality_route(state: SellformGraphState) -> str:
    quality = dict(state.get("quality") or {})
    route = str(quality.get("routing_code") or "SELLER_REVIEW")
    verdict = str(quality.get("quality_bar_verdict") or "NEEDS_REVIEW")
    target = _lg12_quality_selected_target(quality)
    if route == "PASS" and verdict == "PASS":
        return "quality_promotion_ready"
    if route == "SELLER_REVIEW" or route == "BLOCKED_POLICY" or verdict == "NEEDS_REVIEW":
        return "quality_seller_review"
    if route in {"IMAGE_REWORK", "COPY_REWORK", "VISUAL_REWORK", "PLAN_REWORK"} and target is not None:
        _key, entry = _lg12_quality_attempt_entry(quality, target=target)
        if str(quality.get("slo08_fallback_attempt_key") or "") == _key:
            # A seller-selected local fallback has already consumed the one
            # post-exhaustion choice for this logical target. Its child still
            # receives normal QA, but it never starts another automatic retry.
            return "quality_seller_review"
        if int((entry or {}).get("attempt_count") or 0) < _LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS:
            return "quality_selective_rework"
        return "quality_rework_exhausted"
    return "quality_seller_review"


def _lg12_quality_promotion_ready(state: SellformGraphState) -> dict[str, Any]:
    """TASK-12.9 stops before final promotion/export (TASK-12.10)."""

    quality = dict(state.get("quality") or {})
    return {
        "current_stage": "quality_promotion_ready", "status": "completed",
        "quality": {**quality, "seller_review_required": False},
        "events": [_lg12_quality_event("quality_promotion_ready", status="completed")],
    }


def _lg12_quality_review_payload(
    state: SellformGraphState, *, exhausted: bool = False, fallback_available: bool = False,
) -> dict[str, Any]:
    quality = dict(state.get("quality") or {})
    rendering = dict(state.get("rendering") or {})
    current_page = dict(rendering.get("detail_page_version") or {})
    return {
        "schema_version": "lg12i-v1", "review_stage": "quality_review",
        "title": "품질 검토 필요", "description": "고정된 품질 결과에 대해 판매자 확인 또는 허용된 선택 수정이 필요합니다.",
        "allowed_decisions": (["fallback", "wait"] if fallback_available else ["wait"])
        if exhausted else ["approve", "reject"],
        "run_id": str(state.get("run_id") or ""), "thread_id": str(state.get("thread_id") or state.get("run_id") or ""),
        "project_id": str(state.get("project_id") or ""),
        "context": {
            "quality_bar_ref": dict(quality.get("quality_bar_ref") or {}),
            "quality_report_ref": dict(quality.get("quality_report_ref") or {}),
            "current_page_ref": {
                "id": str(current_page.get("id") or ""),
                "version": str(current_page.get("schema_version") or ""),
                "hash": str(current_page.get("snapshot_hash") or ""),
                "type": "DetailPageVersion",
            },
            "routing_code": str(quality.get("routing_code") or "SELLER_REVIEW"),
            "rework_attempt_count": int(quality.get("rework_attempt_count") or 0),
            "max_rework_attempts": _LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS,
            "rework_exhausted": exhausted,
            "blocking_reasons": list(quality.get("last_blocking_reasons") or []),
            "rework_targets": list(quality.get("rework_targets") or []),
            "slo08_choice": {
                "choice_required": True,
                "available_actions": ["fallback", "wait"] if fallback_available else ["wait"],
                "automatic_attempts": _LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS,
            } if exhausted else {},
        },
        "rejection_reason": "",
    }


def _lg12_quality_seller_review(state: SellformGraphState) -> dict[str, Any]:
    """Reuse the existing interrupt/resume transport with reference-only QA context."""

    from src.services.langgraph_review_service import validate_resume_payload

    payload = _lg12_quality_review_payload(state)
    response = validate_resume_payload(interrupt(payload), "quality_review")
    quality = dict(state.get("quality") or {})
    return {
        "current_stage": "quality_seller_review", "status": "completed",
        "quality": {**quality, "seller_review_required": True, "seller_review_decision": response.decision},
        "review": {"last_resolved_stage": "quality_review", "last_decision": response.decision},
        "events": [_lg12_quality_event("quality_seller_review", status="completed")],
    }


def _lg12_quality_rework_exhausted(state: SellformGraphState) -> dict[str, Any]:
    """After the durable max-two budget, accept only seller fallback or wait."""

    from src.db.models import AgentRun, ImageGenerationJobRecord, QualityAssessmentReportVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import apply_image_review, prepare_lg11_seller_asset_replacement
    from src.services.langgraph_review_service import validate_resume_payload
    from src.services.page_finalization_service import build_lg11_scene_version_fork, persist_lg11_scene_version_fork
    from src.services.prompt_intelligence_service import canonical_hash

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 exhausted rework requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""), project_id=str(state.get("project_id") or ""),
        workspace_id=str(state.get("workspace_id") or ""),
    ).one()
    fallback = _lg12_quality_slo08_fallback_candidate(state=state, run=run, db=db)
    payload = _lg12_quality_review_payload(state, exhausted=True, fallback_available=fallback is not None)
    while True:
        response = validate_resume_payload(interrupt(payload), "quality_review")
        if response.decision not in set(payload["allowed_decisions"]):
            raise ValueError("SLO-08 action is not available for this exhausted quality target.")
        if response.decision == "wait":
            # Re-interrupt instead of scheduling/polling work. The existing
            # review projection persists this seller-controlled waiting state.
            continue
        if not response.seller_attested:
            raise ValueError("Seller fallback requires an explicit rights confirmation.")
        fallback = _lg12_quality_slo08_fallback_candidate(state=state, run=run, db=db)
        if fallback is None:
            raise ValueError("The frozen seller fallback is unavailable or stale.")
        page, scene_id, asset_id = fallback
        generation = prepare_lg11_seller_asset_replacement(
            run=run, source_version=page, scene_id=scene_id, asset_id=asset_id,
            seller_attested=True, db=db,
        )
        job = next((row for row in db.query(ImageGenerationJobRecord).filter_by(
            project_id=run.project_id, scene_id=scene_id, provider="manual_upload", output_asset_id=asset_id,
        ).all() if str((row.usage_metadata or {}).get("lg11_source_version_id") or "") == str(page.id)), None)
        if job is None:
            raise ValueError("Seller fallback did not create an owned manual scene record.")
        generation = apply_image_review(
            run_id=run.id, project_id=run.project_id, decision="approve", job_id=job.job_id, db=db,
        )
        db.refresh(job)
        if job.status != "approved":
            raise ValueError("Seller fallback must pass the existing image approval gate.")
        quality = dict(state.get("quality") or {})
        intent = {
            "target_ids": [scene_id],
            "intent_hash": canonical_hash({"slo08_fallback": True, "scene_id": scene_id, "asset_id": asset_id}),
        }
        child = persist_lg11_scene_version_fork(
            run=run,
            scene_version_fork=build_lg11_scene_version_fork(
                source_version=page, edit_run_id=run.id, intent=intent, job=job, db=db,
            ),
            db=db,
        )
        report_ref = dict(quality.get("quality_report_ref") or {})
        report = db.query(QualityAssessmentReportVersion).filter_by(
            id=str(report_ref.get("id") or ""), workspace_id=run.workspace_id, project_id=run.project_id,
        ).one_or_none()
        if report is None:
            raise ValueError("SLO-08 fallback source QualityAssessmentReport is unavailable.")
        _lg12_quality_finalize_frozen_page_exports(page=child, channels=list(report.target_channels_json or []), db=db)
        db.commit(); db.refresh(child)
        child_ref = _lg12_quality_child_ref(child)
        active_attempt = dict(quality.get("active_attempt") or {})
        fallback_attempt_key, _entry = _lg12_quality_attempt_entry(quality, target={
            "target_ref": dict(active_attempt.get("target_ref") or {}),
            "logical_target_ref": dict(active_attempt.get("logical_target_ref") or {}),
        })
        completed = _lg12_quality_complete_attempt(quality, child_ref=child_ref)
        completed["slo08_fallback_attempt_key"] = fallback_attempt_key
        completed["seller_fallback_used"] = True
        return {
            "current_stage": "quality_rework_child_frozen", "status": "running",
            "rendering": {**dict(state.get("rendering") or {}), "detail_page_version": {"id": child_ref["id"], "schema_version": child_ref["version"], "snapshot_hash": child_ref["hash"]}},
            "generation": generation,
            "quality": completed,
            "review": {"last_resolved_stage": "quality_review", "last_decision": "fallback"},
            "events": [_lg12_quality_event("quality_rework_child_frozen")],
        }


def _lg12_quality_selective_rework(state: SellformGraphState) -> dict[str, Any]:
    """Create a bounded attempt only from the persisted current Quality Bar.

    Every automatic action is derived from the verified Quality Bar's one
    narrow target.  It never accepts a client-provided target or turns a page
    reference into permission to rewrite unrelated copy/layout.
    """

    # The initial Quality Bar must still be allowed to create its first
    # attempt.  This failpoint models a later crash after a child has already
    # been frozen, re-evaluated and given its next persisted Quality Bar route.
    if any(
        str(dict(item).get("status") or "") == "child_frozen"
        for item in list(dict(state.get("quality") or {}).get("attempt_ledger") or [])
    ):
        _lg12_test_failpoint("LG12_TEST_FAILPOINT_AFTER_QB_PERSIST")

    from src.db.models import AgentRun, QualityAssessmentReportVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.quality_assessment_service import build_lg12_quality_rework_attempt
    from src.services.quality_bar_service import aggregate_quality_bar
    from src.services.prompt_intelligence_service import canonical_hash

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 selective rework requires the graph database session.")
    execution_run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""),
        project_id=str(state.get("project_id") or ""),
        workspace_id=str(state.get("workspace_id") or ""),
    ).one()
    quality = dict(state.get("quality") or {})
    report_ref = dict(quality.get("quality_report_ref") or {})
    current_page_ref = dict(quality.get("current_detail_page_ref") or {})
    # Checkpoint state retains the typed report reference. Quality Bar's
    # persisted lookup intentionally accepts only its exact immutable
    # ID/version/hash identity, so do not pass the display ``type`` field over
    # that stricter boundary.
    actual_bar = aggregate_quality_bar(
        db, report_ref={key: report_ref[key] for key in ("id", "version", "hash")},
    )
    provided_bar_ref = dict(quality.get("quality_bar_ref") or {})
    if (
        str(provided_bar_ref.get("id") or "") != str(actual_bar.get("quality_bar_result_id") or "")
        or str(provided_bar_ref.get("hash") or "") != str(actual_bar.get("canonical_hash") or "")
    ):
        raise ValueError("Stale Quality Bar result cannot start selective rework.")
    route = str(actual_bar.get("routing_code") or "")
    # The persisted bar is authoritative for scope; the checkpoint-only
    # logical identity is recovered only when its raw target remains exact.
    prior_logical = {
        canonical_hash(dict(item.get("target_ref") or {})): dict(item.get("logical_target_ref") or {})
        for item in list(quality.get("rework_targets") or [])
        if isinstance(item, dict)
    }
    verified_targets = []
    for item in list(actual_bar.get("rework_targets") or []):
        target = dict(item)
        logical = prior_logical.get(canonical_hash(dict(target.get("target_ref") or {})))
        if logical:
            target["logical_target_ref"] = logical
        verified_targets.append(target)
    verified_quality = {**quality, "routing_code": route, "rework_targets": verified_targets}
    target = _lg12_quality_selected_target(verified_quality)
    if target is None:
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "quality": {**quality, "seller_review_required": True, "routing_code": "SELLER_REVIEW"},
            "events": [_lg12_quality_event("quality_rework_target_not_actionable", node_status="needs_review")],
        }
    report = db.query(QualityAssessmentReportVersion).filter_by(
        id=str(report_ref.get("id") or ""), workspace_id=execution_run.workspace_id,
        project_id=execution_run.project_id,
    ).one_or_none()
    if report is None or str(report.canonical_hash) != str(report_ref.get("hash") or ""):
        raise ValueError("Quality rework cannot use a stale or cross-run QualityAssessmentReport.")
    owner_ref = dict(quality.get("quality_owner_run_ref") or {})
    if owner_ref != {"id": str(report.creator_run_id), "type": "AgentRun"}:
        raise ValueError("Quality rework owner run does not match the persisted frozen QA report.")
    quality_owner = db.query(AgentRun).filter_by(
        id=str(report.creator_run_id), workspace_id=execution_run.workspace_id,
        project_id=execution_run.project_id,
    ).one_or_none()
    if quality_owner is None:
        raise ValueError("Quality rework source run is unavailable in this workspace.")
    master_ref = dict((dict(report.report_json or {}).get("input_lineage") or {}).get("master_ref") or {})
    attempt_key, previous = _lg12_quality_attempt_entry(quality, target=target)
    prior_count = int((previous or {}).get("attempt_count") or 0)
    if prior_count >= _LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS:
        return {
            "current_stage": "quality_rework_exhausted", "status": "running",
            "quality": {**quality, "seller_review_required": True, "rework_exhausted": True},
            "events": [_lg12_quality_event("quality_rework_exhausted", node_status="needs_review")],
        }
    node_family = _lg12_quality_node_family(target)
    if node_family == "unresolved_target":
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "quality": {**quality, "seller_review_required": True, "routing_code": "SELLER_REVIEW"},
            "events": [_lg12_quality_event("quality_rework_target_not_actionable", node_status="needs_review")],
        }
    attempt = build_lg12_quality_rework_attempt(
        run=quality_owner, current_page_ref=current_page_ref, quality_report_ref=report_ref,
        quality_bar=actual_bar, master_ref=master_ref, attempt_number=prior_count + 1,
        selected_target=target, node_family=node_family,
        execution_run_ref={"id": str(execution_run.id), "type": "AgentRun"},
    )
    ledger_entry = {
        "attempt_key": attempt_key, "node_family": node_family,
        "target_ref": dict(target.get("target_ref") or {}),
        "logical_target_ref": dict(target.get("logical_target_ref") or {}),
        "attempt_count": prior_count + 1,
        "last_quality_bar_ref": dict(attempt.get("triggering_quality_bar_ref") or {}),
        "last_child_detail_page_ref": None, "status": "started",
    }
    action = _lg12_quality_rework_action(target.get("recommended_action"))
    next_stage = {
        "IMAGE_REWORK": "quality_image_rework",
        "COPY_REWORK": "quality_copy_rework",
        "VISUAL_REWORK": "quality_visual_rework",
        "PLAN_REWORK": "quality_plan_rework",
    }.get(route, "quality_seller_review")
    if action == "style_reassembly":
        next_stage = "quality_style_rework"
    elif action == "plan_reorder":
        # Quality Bar currently represents layout routes as VISUAL_REWORK;
        # this exact persisted action narrows it to the existing plan executor.
        next_stage = "quality_plan_rework"
    return {
        "current_stage": next_stage, "status": "running",
        "quality": {
            **quality,
            "rework_attempt_count": sum(int(item.get("attempt_count") or 0) for item in _lg12_quality_upsert_ledger(quality, ledger_entry)),
            "attempt_ledger": _lg12_quality_upsert_ledger(quality, ledger_entry),
            "active_attempt": attempt,
            # This is a bounded audit projection; full QA/finding bodies stay
            # in their immutable report rows.
            "attempt_history": [
                *list(quality.get("attempt_history") or [])[-63:],
                {"attempt_plan_hash": attempt["attempt_plan_hash"], "canonical_hash": attempt["canonical_hash"], "attempt_number": attempt["attempt_number"], "routing_code": attempt["routing_code"], "attempt_key": attempt_key},
            ],
        },
        "events": [_lg12_quality_event("quality_selective_rework")],
    }


def _lg12_quality_scene_target(*, page: Any, targets: list[dict[str, Any]]) -> str:
    """Resolve exactly one frozen manifest scene from Quality-Bar targets."""

    snapshot = dict(page.sections_json or {})
    canonical = dict(dict(snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
    assets = [dict(item) for item in list(dict(canonical.get("approved_asset_manifest") or {}).get("assets") or [])]
    requested = {
        str(ref.get("id") or "")
        for target in targets for ref in [dict(target.get("target_ref") or {})]
        if str(ref.get("type") or "") in {"asset", "scene"}
    }
    matching = [item for item in assets if str(item.get("asset_id") or "") in requested or str(item.get("scene_id") or "") in requested]
    scene_ids = {str(item.get("scene_id") or "") for item in matching if str(item.get("scene_id") or "")}
    if len(scene_ids) != 1:
        raise ValueError("IMAGE_REWORK requires one exact frozen scene/asset target from the Quality Bar.")
    return next(iter(scene_ids))


def _lg12_quality_slo08_fallback_candidate(*, state: SellformGraphState, run: Any, db: Any) -> tuple[Any, str, str] | None:
    """Return only a current, frozen seller-owned photo for the exhausted IMAGE target."""

    from src.db.models import Asset, DetailPageVersion, ImageGenerationJobRecord
    from src.services.storyboard_image_generation_service import MANUAL_FINAL_SOURCE_TYPES, resolved_asset_usage_status

    quality = dict(state.get("quality") or {})
    attempt = dict(quality.get("active_attempt") or {})
    page_ref = dict(quality.get("current_detail_page_ref") or {})
    page = db.query(DetailPageVersion).filter_by(id=str(page_ref.get("id") or ""), project_id=run.project_id).one_or_none()
    if page is None or str(dict(page.sections_json or {}).get("snapshot_hash") or "") != str(page_ref.get("hash") or ""):
        return None
    logical_target = dict(attempt.get("logical_target_ref") or {})
    if str(logical_target.get("type") or "") == "scene" and str(logical_target.get("id") or ""):
        scene_id = str(logical_target["id"])
    else:
        try:
            scene_id = _lg12_quality_scene_target(page=page, targets=list(attempt.get("target_refs") or []))
        except ValueError:
            return None
    canonical = dict(dict(page.sections_json or {}).get("lg10") or {}).get("canonical_page_assembly_input") or {}
    manifest = dict(canonical.get("approved_asset_manifest") or {})
    entry = next((dict(item) for item in list(manifest.get("assets") or []) if str(item.get("scene_id") or "") == scene_id), None)
    if entry is None:
        return None
    source_job = db.query(ImageGenerationJobRecord).filter_by(
        project_id=run.project_id, job_id=str(entry.get("job_id") or ""), status="approved",
    ).one_or_none()
    if source_job is None or str(source_job.output_asset_id or "") != str(entry.get("asset_id") or ""):
        return None
    for asset_id in list(source_job.source_asset_ids or []):
        asset = db.query(Asset).filter_by(id=asset_id, project_id=run.project_id).one_or_none()
        if (
            asset is not None and asset.source_type in MANUAL_FINAL_SOURCE_TYPES
            and resolved_asset_usage_status(asset) == "seller_owned"
        ):
            return page, scene_id, str(asset_id)
    return None


def _lg12_quality_child_ref(child: Any) -> dict[str, Any]:
    return {
        "id": str(child.id), "version": "lg10-detail-page-version-v1",
        "hash": str(dict(child.sections_json or {}).get("snapshot_hash") or ""),
        "type": "DetailPageVersion",
    }


def _lg12_quality_complete_attempt(quality: dict[str, Any], *, child_ref: dict[str, Any]) -> dict[str, Any]:
    """Attach exactly one frozen child to the active target ledger entry."""

    attempt = dict(quality.get("active_attempt") or {})
    target = {
        "target_ref": dict(attempt.get("target_ref") or {}),
        "logical_target_ref": dict(attempt.get("logical_target_ref") or {}),
    }
    attempt_key, previous = _lg12_quality_attempt_entry(quality, target=target)
    if previous is None:
        raise ValueError("Quality child has no durable target attempt ledger entry.")
    entry = {
        **previous, "status": "child_frozen", "last_child_detail_page_ref": child_ref,
        "last_quality_bar_ref": dict(attempt.get("triggering_quality_bar_ref") or previous.get("last_quality_bar_ref") or {}),
    }
    completed_attempt = {**attempt, "child_detail_page_ref": child_ref}
    from src.services.prompt_intelligence_service import canonical_hash
    completed_attempt["canonical_hash"] = canonical_hash({key: value for key, value in completed_attempt.items() if key != "canonical_hash"})
    ledger = _lg12_quality_upsert_ledger(quality, entry)
    return {
        **quality,
        "current_detail_page_ref": child_ref,
        "active_attempt": completed_attempt,
        "attempt_ledger": ledger,
        "rework_attempt_count": sum(int(item.get("attempt_count") or 0) for item in ledger),
        "attempt_history": [
            *list(quality.get("attempt_history") or [])[:-1][-63:],
            {"canonical_hash": completed_attempt["canonical_hash"], "attempt_number": completed_attempt["attempt_number"],
             "routing_code": completed_attempt["routing_code"], "attempt_key": attempt_key,
             "child_detail_page_ref": child_ref},
        ],
    }


def _lg12_quality_copy_change(*, page: Any, target_ref: dict[str, Any]) -> tuple[str, str, str]:
    """Return one conservative cosmetic-only copy change for an exact field.

    QA evidence is never a licence to invent claims.  Only punctuation,
    whitespace and visual-emphasis normalisation are deterministic here; all
    other copy findings stay seller-controlled.
    """

    target_id = str(target_ref.get("id") or "")
    match = re.fullmatch(r"copy-field:([^:]+):([^:]+)", target_id)
    if match is None:
        raise ValueError("COPY_REWORK requires an exact frozen copy-field target.")
    section_id, field = match.groups()
    snapshot = dict(page.sections_json or {})
    rendering = dict(dict(snapshot.get("lg10") or {}).get("canonical_rendering") or {})
    records = [dict(item) for item in list(rendering.get("sections") or [])]
    record = next((item for item in records if str(item.get("section_id") or "") == section_id), None)
    if record is None:
        raise ValueError("COPY_REWORK target section is not in the frozen renderer.")
    text_item = next((dict(item) for item in list(record.get("text_layer") or []) if str(item.get("field") or "") == field), None)
    if text_item is None or not isinstance(text_item.get("text"), str):
        raise ValueError("COPY_REWORK target field is not frozen renderer text.")
    source = str(text_item["text"])
    # Keep the transformation deliberately semantics-preserving.  These
    # operations cannot add numbers, feature names, certification or any other
    # factual content and are rejected if they are a no-op.
    changed = re.sub(r"[ \t]{2,}", " ", source)
    changed = re.sub(r"(?:\r?\n){3,}", "\n\n", changed)
    changed = re.sub(r"([!?])\1{1,}", r"\1", changed)
    changed = re.sub(r"([😀-🙏])(?:\1){2,}", r"\1", changed)
    if changed == source:
        raise ValueError("COPY_REWORK finding is not a deterministic cosmetic correction.")
    return section_id, field, changed


def _lg12_quality_finalize_frozen_page_exports(*, page: Any, channels: list[str], db: Any) -> None:
    """Freeze deterministic channel packages for one already-frozen page.

    The initial renderer and every rework child have their own renderer hash
    and DetailPage identity.  This invokes the existing frozen standalone
    export finalizer only; it neither renders AI images nor queues an export
    or provider job.
    """

    from src.db.models import ExportArtifact
    from src.services.channel_export_service import supported_channel_keys
    from src.services.export_service import (
        build_lg10_standalone_export_bundle,
        write_lg12_frozen_export_parity_evidence,
    )

    frozen_channels = sorted({
        str(channel)
        for channel in channels
        if str(channel) in supported_channel_keys()
    })
    if not frozen_channels:
        raise ValueError("Frozen page has no supported target channel.")
    for channel in frozen_channels:
        artifact_type = f"lg10_standalone_package:{channel}"
        artifact = db.query(ExportArtifact).filter_by(
            project_id=page.project_id, version_id=page.id, artifact_type=artifact_type,
        ).one_or_none()
        if artifact is None:
            bundle = build_lg10_standalone_export_bundle(
                db=db, project_id=page.project_id, version=page, channel=channel,
            )
            artifact = ExportArtifact(
                project_id=page.project_id, version_id=page.id,
                artifact_type=artifact_type, file_path=str(bundle["zip_path"]),
            )
            db.add(artifact)
            db.flush()
        write_lg12_frozen_export_parity_evidence(
            version=page, artifact=artifact, channel=channel,
        )


def _lg12_quality_copy_rework(state: SellformGraphState) -> dict[str, Any]:
    """Reuse TASK-11.3's copy-only immutable fork for one QA field."""

    _lg12_test_failpoint("LG12_TEST_FAILPOINT_AFTER_ATTEMPT_PERSIST")

    from src.db.models import AgentRun, DetailPageVersion, QualityAssessmentReportVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.page_finalization_service import (
        EditIntentValidationError, build_lg11_copy_version_fork,
        persist_lg11_copy_version_fork, preview_lg11_edit_intent,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 copy rework requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""),
        project_id=str(state.get("project_id") or ""),
        workspace_id=str(state.get("workspace_id") or ""),
    ).one()
    quality = dict(state.get("quality") or {})
    attempt = dict(quality.get("active_attempt") or {})
    selected = dict((list(attempt.get("target_refs") or [{}]) or [{}])[0])
    # TASK-11.3 is reused only for semantic-preserving cosmetic normalisation.
    # A length, factual, or tone finding cannot expand into permission to
    # rewrite the seller's copy automatically.
    action = _lg12_quality_rework_action(selected.get("recommended_action"))
    if action not in {
        "spacing_inconsistency", "punctuation_overuse", "emphasis_overuse",
    }:
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "quality": {**quality, "seller_review_required": True, "routing_code": "SELLER_REVIEW"},
            "events": [_lg12_quality_event("quality_copy_rework", node_status="needs_review")],
        }
    page_ref = dict(quality.get("current_detail_page_ref") or {})
    page = db.query(DetailPageVersion).filter_by(id=str(page_ref.get("id") or ""), project_id=run.project_id).one_or_none()
    if page is None or str(dict(page.sections_json or {}).get("snapshot_hash") or "") != str(page_ref.get("hash") or ""):
        raise ValueError("COPY_REWORK source page is stale or cross-project.")
    try:
        section_id, field, value = _lg12_quality_copy_change(page=page, target_ref=dict(attempt.get("target_ref") or {}))
        intent_preview = preview_lg11_edit_intent(
            version=page, scope="copy", target_ids=[section_id], operation="rewrite",
            instruction="Normalize only the frozen QA-flagged copy field without changing facts.",
            preserve_constraints={"selected_context": {"section_id": section_id}},
            copy_changes={section_id: {field: value}},
        )
        # TASK-11.3 receives the immutable EditIntent itself.  The preview
        # wrapper also contains display-only impact information and is not a
        # valid fork input.
        intent = dict(intent_preview["edit_intent"])
        fork = build_lg11_copy_version_fork(source_version=page, edit_run_id=run.id, intent=intent)
        child = persist_lg11_copy_version_fork(run=run, copy_version_fork=fork, db=db)
        report = db.query(QualityAssessmentReportVersion).filter_by(
            id=str(dict(quality.get("quality_report_ref") or {}).get("id") or ""),
            workspace_id=run.workspace_id, project_id=run.project_id,
        ).one_or_none()
        if report is None:
            raise ValueError("COPY_REWORK source QualityAssessmentReport is unavailable.")
        _lg12_quality_finalize_frozen_page_exports(page=child, channels=list(report.target_channels_json or []), db=db)
        db.commit(); db.refresh(child)
    except (EditIntentValidationError, ValueError):
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "quality": {**quality, "seller_review_required": True, "routing_code": "SELLER_REVIEW"},
            "events": [_lg12_quality_event("quality_copy_rework", node_status="needs_review")],
        }
    child_ref = _lg12_quality_child_ref(child)
    return {
        "current_stage": "quality_rework_child_frozen", "status": "running",
        "rendering": {**dict(state.get("rendering") or {}), "detail_page_version": {"id": child_ref["id"], "schema_version": child_ref["version"], "snapshot_hash": child_ref["hash"]}},
        "quality": _lg12_quality_complete_attempt(quality, child_ref=child_ref),
        "events": [_lg12_quality_event("quality_copy_rework")],
    }


def _lg12_quality_canvas_command(*, draft: dict[str, Any], target_ref: dict[str, Any], attempt_hash: str) -> dict[str, Any]:
    """Derive one existing safe Canvas command for the exact frozen target."""

    canonical = dict(draft.get("canonical_page_assembly_input") or {})
    sections = [dict(item) for item in list(canonical.get("sections") or [])]
    target_type, target_id = str(target_ref.get("type") or ""), str(target_ref.get("id") or "")
    if target_type == "frozen_section":
        section = next((item for item in sections if str(item.get("section_id") or "") == target_id), None)
        if section is None:
            raise ValueError("VISUAL_REWORK selected section is absent from the frozen canvas.")
        height = dict(section.get("canvas") or {}).get("height_px")
        if isinstance(height, int) and 160 <= height <= 2400:
            raise ValueError("VISUAL_REWORK has no deterministic Canvas correction for the selected section.")
        return {"operation_id": f"quality:{attempt_hash}:section-height", "kind": "set_height", "section_id": target_id, "height_px": 160}
    if target_type != "frozen_canvas_element":
        raise ValueError("VISUAL_REWORK target is not an existing Canvas section or element.")
    for section in sections:
        section_id = str(section.get("section_id") or "")
        section_height = int(dict(section.get("canvas") or {}).get("height_px") or 160)
        for element in list(section.get("canvas_elements") or []):
            if str(dict(element).get("element_id") or "") != target_id:
                continue
            current = dict(element)
            width, height = int(current.get("width") or 0), int(current.get("height") or 0)
            x, y = int(current.get("x") or 0), int(current.get("y") or 0)
            # Canvas validation already owns all geometry safety rules.  This
            # only clamps a demonstrably out-of-canvas element back into its
            # existing section; locked/grouped elements remain seller-owned.
            safe_width, safe_height = min(max(width, 1), 760), min(max(height, 1), section_height)
            if (safe_width, safe_height) != (width, height):
                return {"operation_id": f"quality:{attempt_hash}:element-size", "kind": "resize_element", "element_id": target_id, "width": safe_width, "height": safe_height}
            clamped_x = min(max(x, 0), max(0, 760 - width))
            clamped_y = min(max(y, 0), max(0, section_height - height))

            # An out-of-canvas frozen target can also overlap other visible
            # elements.  Reuse the existing ``move_element`` operation, but
            # select a deterministic in-section slot that avoids those
            # elements when one exists.  This deliberately changes only the
            # Quality-Bar-selected target; all sibling geometry is preserved.
            siblings = [
                dict(item)
                for item in list(section.get("canvas_elements") or [])
                if str(dict(item).get("element_id") or "") != target_id
                and str(dict(item).get("kind") or "") != "background"
                and not bool(dict(item).get("deleted"))
            ]

            def overlaps(candidate_x: int, candidate_y: int, sibling: dict[str, Any]) -> bool:
                sibling_x, sibling_y = int(sibling.get("x") or 0), int(sibling.get("y") or 0)
                sibling_width, sibling_height = int(sibling.get("width") or 0), int(sibling.get("height") or 0)
                return (
                    candidate_x < sibling_x + sibling_width
                    and sibling_x < candidate_x + width
                    and candidate_y < sibling_y + sibling_height
                    and sibling_y < candidate_y + height
                )

            candidate_xs = {0, clamped_x}
            candidate_ys = {0, clamped_y}
            for sibling in siblings:
                candidate_xs.add(int(sibling.get("x") or 0) + int(sibling.get("width") or 0))
                candidate_ys.add(int(sibling.get("y") or 0) + int(sibling.get("height") or 0))
            safe_slots = [
                (candidate_x, candidate_y)
                for candidate_y in sorted(candidate_ys)
                for candidate_x in sorted(candidate_xs)
                if 0 <= candidate_x <= 760 - width
                and 0 <= candidate_y <= section_height - height
                and not any(overlaps(candidate_x, candidate_y, sibling) for sibling in siblings)
            ]
            next_x, next_y = safe_slots[0] if safe_slots else (clamped_x, clamped_y)
            if (next_x, next_y) != (x, y):
                return {"operation_id": f"quality:{attempt_hash}:element-position", "kind": "move_element", "element_id": target_id, "dx": next_x - x, "dy": next_y - y}
            raise ValueError("VISUAL_REWORK element has no deterministic Canvas correction.")
    raise ValueError("VISUAL_REWORK selected element is absent from the frozen canvas.")


def _lg12_quality_canvas_context(*, page: Any, target_ref: dict[str, Any]) -> dict[str, str]:
    """Resolve one frozen Canvas target to its persisted section/element IDs."""

    canonical = dict(dict(dict(page.sections_json or {}).get("lg10") or {}).get("canonical_page_assembly_input") or {})
    target_type = str(target_ref.get("type") or "")
    target_id = str(target_ref.get("id") or "")
    if target_type == "frozen_section":
        if any(str(item.get("section_id") or "") == target_id for item in list(canonical.get("sections") or [])):
            return {"section_id": target_id}
        raise ValueError("VISUAL_REWORK selected section is absent from the frozen canvas.")
    if target_type == "frozen_canvas_element":
        matches = [
            str(section.get("section_id") or "")
            for section in list(canonical.get("sections") or [])
            if any(str(dict(element).get("element_id") or "") == target_id for element in list(section.get("canvas_elements") or []))
        ]
        if len(matches) == 1 and matches[0]:
            return {"section_id": matches[0], "element_id": target_id}
        raise ValueError("VISUAL_REWORK selected element is absent from the frozen canvas.")
    raise ValueError("VISUAL_REWORK target is not an existing Canvas section or element.")


def _lg12_quality_visual_rework(state: SellformGraphState) -> dict[str, Any]:
    """Reuse the LG-11 Canvas draft/safety/immutable-fork path for one target."""

    from src.db.models import AgentRun, DetailPageVersion, QualityAssessmentReportVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.page_finalization_service import (
        EditIntentValidationError, apply_lg11_canvas_command,
        build_lg11_canvas_draft, build_lg11_canvas_version_fork,
        persist_lg11_canvas_version_fork, preview_lg11_edit_intent,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 visual rework requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""),
        project_id=str(state.get("project_id") or ""),
        workspace_id=str(state.get("workspace_id") or ""),
    ).one()
    quality = dict(state.get("quality") or {})
    attempt = dict(quality.get("active_attempt") or {})
    target_ref = dict(attempt.get("target_ref") or {})
    if str(target_ref.get("type") or "") not in {"frozen_section", "frozen_canvas_element"}:
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "quality": {**quality, "seller_review_required": True, "routing_code": "SELLER_REVIEW"},
            "events": [_lg12_quality_event("quality_visual_rework", node_status="needs_review")],
        }
    page_ref = dict(quality.get("current_detail_page_ref") or {})
    page = db.query(DetailPageVersion).filter_by(id=str(page_ref.get("id") or ""), project_id=run.project_id).one_or_none()
    if page is None or str(dict(page.sections_json or {}).get("snapshot_hash") or "") != str(page_ref.get("hash") or ""):
        raise ValueError("VISUAL_REWORK source page is stale or cross-project.")
    try:
        selected_context = _lg12_quality_canvas_context(page=page, target_ref=target_ref)
        intent_preview = preview_lg11_edit_intent(
            version=page, scope="page", target_ids=[str(page.id)], operation="canvas_draft",
            instruction="Apply the frozen selected section's deterministic Canvas safety reassembly.",
            preserve_constraints={"selected_context": selected_context},
        )
        intent = dict(intent_preview["edit_intent"])
        draft = build_lg11_canvas_draft(
            source_version=page,
            edit_run_id=run.id,
            intent=intent,
            allow_unsafe_source_repair=True,
        )
        command = _lg12_quality_canvas_command(
            draft=draft, target_ref=target_ref, attempt_hash=str(attempt.get("attempt_plan_hash") or ""),
        )
        draft = apply_lg11_canvas_command(
            canvas_draft=draft, decision="apply",
            command=command,
            db=db, project_id=run.project_id,
        )
        fork = build_lg11_canvas_version_fork(run=run, source_version=page, edit_run_id=run.id, intent=intent, canvas_draft=draft)
        child = persist_lg11_canvas_version_fork(run=run, canvas_version_fork=fork, db=db)
        report = db.query(QualityAssessmentReportVersion).filter_by(
            id=str(dict(quality.get("quality_report_ref") or {}).get("id") or ""),
            workspace_id=run.workspace_id,
            project_id=run.project_id,
        ).one_or_none()
        if report is None:
            raise ValueError("VISUAL_REWORK source QualityAssessmentReport is unavailable.")
        _lg12_quality_finalize_frozen_page_exports(page=child, channels=list(report.target_channels_json or []), db=db)
        db.commit(); db.refresh(child)
    except (EditIntentValidationError, ValueError):
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "quality": {**quality, "seller_review_required": True, "routing_code": "SELLER_REVIEW"},
            "events": [_lg12_quality_event("quality_visual_rework", node_status="needs_review")],
        }
    child_ref = _lg12_quality_child_ref(child)
    return {
        "current_stage": "quality_rework_child_frozen", "status": "running",
        "rendering": {**dict(state.get("rendering") or {}), "detail_page_version": {"id": child_ref["id"], "schema_version": child_ref["version"], "snapshot_hash": child_ref["hash"]}},
        "quality": _lg12_quality_complete_attempt(quality, child_ref=child_ref),
        "events": [_lg12_quality_event("quality_visual_rework")],
    }


def _lg12_quality_style_rework(state: SellformGraphState) -> dict[str, Any]:
    """Reuse TASK-11.6's pinned Brand Kit selective reassembly path only."""

    from src.db.models import (
        AgentRun,
        CommerceCreativeMasterVersion,
        DetailPageVersion,
        QualityAssessmentReportVersion,
    )
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.page_finalization_service import (
        EditIntentValidationError, build_lg11_style_version_fork,
        persist_lg11_style_version_fork, preview_lg11_edit_intent,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 style rework requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""), project_id=str(state.get("project_id") or ""),
        workspace_id=str(state.get("workspace_id") or ""),
    ).one()
    quality = dict(state.get("quality") or {})
    attempt = dict(quality.get("active_attempt") or {})
    selected = dict((list(attempt.get("target_refs") or [{}]) or [{}])[0])
    if _lg12_quality_rework_action(selected.get("recommended_action")) != "style_reassembly":
        return _lg12_quality_seller_review_update(quality, "quality_style_rework")
    page_ref = dict(quality.get("current_detail_page_ref") or {})
    page = db.query(DetailPageVersion).filter_by(id=str(page_ref.get("id") or ""), project_id=run.project_id).one_or_none()
    master_ref = dict(attempt.get("master_ref") or {})
    master = db.query(CommerceCreativeMasterVersion).filter_by(
        id=str(master_ref.get("id") or ""), workspace_id=run.workspace_id, project_id=run.project_id,
    ).one_or_none()
    if (
        page is None
        or str(dict(page.sections_json or {}).get("snapshot_hash") or "") != str(page_ref.get("hash") or "")
        or master is None
        or int(master.version) != int(master_ref.get("version") or -1)
        or str(master.canonical_hash) != str(master_ref.get("hash") or "")
    ):
        raise ValueError("STYLE_REWORK source page or Master is stale or cross-project.")
    target_brand_ref = {"brand_kit_version_id": str(master.brand_kit_version_id), "brand_kit_hash": str(master.brand_kit_hash)}
    frozen_brand_ref = dict(dict(dict(page.sections_json or {}).get("lg10") or {}).get("canonical_page_assembly_input") or {}).get("brand_kit_ref") or {}
    if frozen_brand_ref == target_brand_ref:
        # A stale evaluator warning is never authority to invent a new style.
        return _lg12_quality_seller_review_update(quality, "quality_style_rework")
    try:
        intent_preview = preview_lg11_edit_intent(
            version=page, scope="style", target_ids=[str(page.id)], operation="restyle",
            instruction="Reassemble only frozen renderer style tokens with the Master-pinned Brand Kit.",
            preserve_constraints={"selected_context": {}}, brand_kit_ref=target_brand_ref,
        )
        intent = dict(intent_preview["edit_intent"])
        fork = build_lg11_style_version_fork(run=run, source_version=page, edit_run_id=run.id, intent=intent, db=db)
        child = persist_lg11_style_version_fork(run=run, style_version_fork=fork, db=db)
        report = db.query(QualityAssessmentReportVersion).filter_by(
            id=str(dict(quality.get("quality_report_ref") or {}).get("id") or ""),
            workspace_id=run.workspace_id,
            project_id=run.project_id,
        ).one_or_none()
        if report is None:
            raise ValueError("STYLE_REWORK source QualityAssessmentReport is unavailable.")
        _lg12_quality_finalize_frozen_page_exports(page=child, channels=list(report.target_channels_json or []), db=db)
        db.commit(); db.refresh(child)
    except (EditIntentValidationError, ValueError):
        return _lg12_quality_seller_review_update(quality, "quality_style_rework")
    child_ref = _lg12_quality_child_ref(child)
    return {
        "current_stage": "quality_rework_child_frozen", "status": "running",
        "rendering": {**dict(state.get("rendering") or {}), "detail_page_version": {"id": child_ref["id"], "schema_version": child_ref["version"], "snapshot_hash": child_ref["hash"]}},
        "quality": _lg12_quality_complete_attempt(quality, child_ref=child_ref),
        "events": [_lg12_quality_event("quality_style_rework")],
    }


def _lg12_quality_seller_review_update(quality: dict[str, Any], stage: str) -> dict[str, Any]:
    """Return the one fail-closed outcome shared by unavailable safe actions."""

    return {
        "current_stage": "quality_seller_review", "status": "running",
        "quality": {**quality, "seller_review_required": True, "routing_code": "SELLER_REVIEW"},
        "events": [_lg12_quality_event(stage, node_status="needs_review")],
    }


def _lg12_quality_plan_rework(state: SellformGraphState) -> dict[str, Any]:
    """Use the existing Canvas reorder path for one exact frozen PagePlan."""

    from src.db.models import (
        AgentRun, CommerceCreativeMasterVersion, DetailPageVersion,
        QualityAssessmentReportVersion,
    )
    from src.services.langgraph_commerce_planning_service import (
        create_page_plan_reorder_successor,
        resolve_commerce_planning_artifact_version,
    )
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.page_finalization_service import (
        EditIntentValidationError, apply_lg11_canvas_command, build_lg11_canvas_draft,
        build_lg11_canvas_version_fork, persist_lg11_canvas_version_fork, preview_lg11_edit_intent,
    )
    from src.services.product_intake_version_service import create_commerce_creative_master_version

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 plan rework requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""), project_id=str(state.get("project_id") or ""),
        workspace_id=str(state.get("workspace_id") or ""),
    ).one()
    quality = dict(state.get("quality") or {})
    attempt = dict(quality.get("active_attempt") or {})
    target_ref = dict(attempt.get("target_ref") or {})
    target_action = _lg12_quality_rework_action(
        dict((list(attempt.get("target_refs") or [{}]) or [{}])[0]).get("recommended_action")
    )
    if str(target_ref.get("type") or "") != "PagePlanVersion" or target_action != "plan_reorder":
        return _lg12_quality_seller_review_update(quality, "quality_plan_rework")
    page_ref = dict(quality.get("current_detail_page_ref") or {})
    page = db.query(DetailPageVersion).filter_by(id=str(page_ref.get("id") or ""), project_id=run.project_id).one_or_none()
    if page is None or str(dict(page.sections_json or {}).get("snapshot_hash") or "") != str(page_ref.get("hash") or ""):
        raise ValueError("PLAN_REWORK source page is stale or cross-project.")
    try:
        parent_master_ref = dict(attempt.get("master_ref") or {})
        parent_master = db.query(CommerceCreativeMasterVersion).filter_by(
            id=str(parent_master_ref.get("id") or ""), workspace_id=run.workspace_id,
            project_id=run.project_id, creator_run_id=run.id,
        ).one_or_none()
        if parent_master is None or (
            int(parent_master_ref.get("version") or 0) != int(parent_master.version)
            or str(parent_master_ref.get("hash") or "") != str(parent_master.canonical_hash)
            or dict(parent_master.page_plan_artifact_ref_json or {}).get("id") != target_ref.get("id")
            or int(dict(parent_master.page_plan_artifact_ref_json or {}).get("version") or 0) != int(target_ref.get("version") or 0)
            or str(dict(parent_master.page_plan_artifact_ref_json or {}).get("hash") or "") != str(target_ref.get("hash") or "")
        ):
            raise ValueError("PLAN_REWORK target is not the current frozen Master PagePlan.")
        intent_preview = preview_lg11_edit_intent(
            version=page, scope="page", target_ids=[str(page.id)], operation="canvas_draft",
            instruction="Restore only the frozen PagePlan section order with the existing Canvas command.",
            preserve_constraints={"selected_context": {}},
        )
        intent = dict(intent_preview["edit_intent"])
        draft = build_lg11_canvas_draft(source_version=page, edit_run_id=run.id, intent=intent)
        sections = [dict(item) for item in list(dict(draft.get("canonical_page_assembly_input") or {}).get("sections") or [])]
        plan_identity = (str(target_ref.get("id") or ""), str(target_ref.get("version") or ""), str(target_ref.get("hash") or ""))
        planned = [
            section for section in sections
            if (str(dict(section.get("scene_ref") or {}).get("page_plan_id") or ""), str(dict(section.get("scene_ref") or {}).get("page_plan_version") or ""), str(dict(section.get("scene_ref") or {}).get("page_plan_hash") or "")) == plan_identity
        ]
        if not planned or len(planned) != len(sections) or any(not isinstance(dict(section.get("scene_ref") or {}).get("scene_order"), int) for section in planned):
            raise ValueError("PLAN_REWORK lacks one complete frozen PagePlan ordering contract.")
        persisted_plan = resolve_commerce_planning_artifact_version(
            run=run, stage="page_planning", reference=target_ref,
        )
        scene_contract = [
            dict(item) for item in list(dict(persisted_plan.get("metadata") or {}).get("section_scene_contract") or [])
            if isinstance(item, dict)
        ]
        expected_order = [
            str(item.get("section_id") or "")
            for item in sorted(scene_contract, key=lambda item: int(item.get("section_order") or -1))
        ]
        if len(expected_order) != len(sections) or set(expected_order) != {str(section.get("section_id") or "") for section in sections}:
            raise ValueError("PLAN_REWORK PagePlan order is incomplete or tampered.")
        by_section_id = {str(section.get("section_id") or ""): section for section in sections}
        desired = [by_section_id[section_id] for section_id in expected_order]
        rendered_order = [
            str(section.get("section_id") or "")
            for section in list(dict(dict(page.sections_json or {}).get("lg10") or {}).get("canonical_rendering", {}).get("sections") or [])
            if isinstance(section, dict)
        ]
        first = next((index for index, (actual, expected) in enumerate(zip(sections, desired)) if str(actual.get("section_id") or "") != str(expected.get("section_id") or "")), None)
        if first is None and rendered_order == expected_order:
            raise ValueError("PLAN_REWORK has no deterministic PagePlan reorder.")
        plan_successor = create_page_plan_reorder_successor(
            run=run, parent_reference=target_ref,
            desired_section_ids=[str(section.get("section_id") or "") for section in desired],
        )
        master_successor = create_commerce_creative_master_version(
            db,
            workspace_id=run.workspace_id, project_id=run.project_id,
            creator_run_id=run.id, created_by=run.created_by,
            source_reference={"id": parent_master.source_snapshot_version_id, "version": parent_master.source_snapshot_version, "hash": parent_master.source_snapshot_hash},
            truth_reference={"id": parent_master.truth_version_id, "version": parent_master.truth_version, "hash": parent_master.truth_version_hash},
            confirmation_reference={"id": parent_master.confirmation_version_id, "version": parent_master.confirmation_version, "hash": parent_master.confirmation_version_hash},
            creative_brief_reference={"id": parent_master.creative_brief_version_id, "version": parent_master.creative_brief_version, "hash": parent_master.creative_brief_hash},
            brand_kit_reference={"id": parent_master.brand_kit_version_id, "version": parent_master.brand_kit_version, "hash": parent_master.brand_kit_hash},
            evidence_artifact_refs=list(parent_master.evidence_artifact_refs_json or []),
            approved_fact_snapshot_ref=dict(parent_master.approved_fact_snapshot_ref_json or {}),
            approved_asset_manifest_ref=dict(parent_master.approved_asset_manifest_ref_json or {}),
            copy_artifact_ref=dict(parent_master.copy_artifact_ref_json or {}),
            page_plan_artifact_ref={
                "id": str(plan_successor["id"]),
                "version": int(plan_successor["version"]),
                "hash": str(plan_successor["hash"]),
                "schema_version": str(plan_successor["schema_version"]),
                "artifact_key": str(plan_successor["artifact_key"]),
            },
            target_channels=list(parent_master.target_channels or []),
            parent_version_id=parent_master.id,
        )
        quality_lineage = {
            "schema_version": "lg12-detail-page-quality-lineage-v1", "creator_run_id": str(run.id),
            "source_snapshot_ref": {"id": str(master_successor.source_snapshot_version_id), "version": int(master_successor.source_snapshot_version), "hash": str(master_successor.source_snapshot_hash)},
            "truth_ref": {"id": str(master_successor.truth_version_id), "version": int(master_successor.truth_version), "hash": str(master_successor.truth_version_hash)},
            "confirmation_ref": {"id": str(master_successor.confirmation_version_id), "version": int(master_successor.confirmation_version), "hash": str(master_successor.confirmation_version_hash)},
            "master_ref": {"id": str(master_successor.id), "version": int(master_successor.version), "hash": str(master_successor.canonical_hash)},
            "approved_asset_manifest_ref": dict(master_successor.approved_asset_manifest_ref_json or {}),
        }
        if first is not None:
            command = {"operation_id": f"quality:{attempt.get('attempt_plan_hash')}:page-plan-order", "kind": "reorder", "section_id": str(desired[first].get("section_id") or ""), "position": first}
            draft = apply_lg11_canvas_command(canvas_draft=draft, decision="apply", command=command, db=db, project_id=run.project_id)
        fork = build_lg11_canvas_version_fork(
            run=run, source_version=page, edit_run_id=run.id, intent=intent,
            canvas_draft=draft, page_plan_successor_ref=plan_successor,
            page_plan_scene_contract=list(plan_successor["section_scene_contract"]),
            quality_lineage_override=quality_lineage,
        )
        child = persist_lg11_canvas_version_fork(run=run, canvas_version_fork=fork, db=db)
        report = db.query(QualityAssessmentReportVersion).filter_by(
            id=str(dict(quality.get("quality_report_ref") or {}).get("id") or ""),
            workspace_id=run.workspace_id,
            project_id=run.project_id,
        ).one_or_none()
        if report is None:
            raise ValueError("PLAN_REWORK source QualityAssessmentReport is unavailable.")
        _lg12_quality_finalize_frozen_page_exports(page=child, channels=list(report.target_channels_json or []), db=db)
        db.commit(); db.refresh(child)
    except (EditIntentValidationError, ValueError) as exc:
        failed = _lg12_quality_seller_review_update(quality, "quality_plan_rework")
        failed["quality"] = {
            **dict(failed["quality"]),
            "last_blocking_reasons": [
                *list(quality.get("last_blocking_reasons") or []),
                {"code": "plan_rework_not_actionable", "detail": str(exc)[:256]},
            ],
        }
        return failed
    child_ref = _lg12_quality_child_ref(child)
    return {
        "current_stage": "quality_rework_child_frozen", "status": "running",
        "rendering": {**dict(state.get("rendering") or {}), "detail_page_version": {"id": child_ref["id"], "schema_version": child_ref["version"], "snapshot_hash": child_ref["hash"]}},
        "quality": _lg12_quality_complete_attempt(quality, child_ref=child_ref),
        "events": [_lg12_quality_event("quality_plan_rework")],
    }


def _lg12_quality_image_rework(state: SellformGraphState) -> dict[str, Any]:
    """Reuse LG-11's one-scene cost-plan and outbox preparation contract."""

    from src.db.models import AgentRun, DetailPageVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import (
        dispatch_graph_image_jobs, ensure_lg11_scene_regeneration_cost_plan,
        prepare_lg11_scene_regeneration, record_cost_decision,
    )
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 image rework requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""),
        project_id=str(state.get("project_id") or ""),
        workspace_id=str(state.get("workspace_id") or ""),
    ).one()
    quality = dict(state.get("quality") or {})
    attempt = dict(quality.get("active_attempt") or {})
    page_ref = dict(quality.get("current_detail_page_ref") or {})
    page = db.query(DetailPageVersion).filter_by(id=str(page_ref.get("id") or ""), project_id=run.project_id).one_or_none()
    if page is None or str(dict(page.sections_json or {}).get("snapshot_hash") or "") != str(page_ref.get("hash") or ""):
        raise ValueError("IMAGE_REWORK source page is stale or cross-project.")
    try:
        scene_id = _lg12_quality_scene_target(page=page, targets=list(attempt.get("target_refs") or []))
    except ValueError:
        # A broad domain/score result is not permission to regenerate an
        # arbitrary image.  Preserve the frozen page and request a seller
        # target instead of issuing a provider operation.
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "quality": {
                **quality, "seller_review_required": True,
                "routing_code": "SELLER_REVIEW",
                "last_blocking_reasons": [
                    *list(quality.get("last_blocking_reasons") or []),
                    {"code": "image_rework_target_not_actionable", "domain": "image_identity_quality"},
                ],
            },
            "events": [_lg12_quality_event("quality_image_rework", node_status="needs_review")],
        }
    plan = ensure_lg11_scene_regeneration_cost_plan(run=run, source_version=page, scene_id=scene_id, db=db)
    generation = {"schema_version": "lg12-quality-image-rework-v1", "cost_plan": plan, "cost_plan_hash": plan["cost_plan_hash"], "scene_id": scene_id, "next_action": "cost_approval"}
    raw = interrupt(review_interrupt_payload("generation_pending", {**state, "generation": generation}))
    decision = validate_resume_payload(raw, "generation_pending")
    plan = record_cost_decision(run_id=run.id, project_id=run.project_id, cost_plan_hash=plan["cost_plan_hash"], decision=decision.decision, db=db)
    if decision.decision == "defer":
        return {
            "current_stage": "quality_image_rework", "status": "running",
            "generation": {**generation, "cost_plan": plan, "next_action": "cost_approval"},
            "events": [_lg12_quality_event("quality_image_rework", node_status="deferred")],
        }
    generation = prepare_lg11_scene_regeneration(
        run=run, source_version=page, scene_id=scene_id, cost_plan_hash=str(plan["cost_plan_hash"]), db=db,
    )
    generation = dispatch_graph_image_jobs(run_id=run.id, project_id=run.project_id, mode=str(state.get("mode") or "mock"), db=db)
    return {
        "current_stage": "quality_image_provider_wait", "status": "running",
        "generation": {**generation, "scene_id": scene_id, "cost_plan_hash": str(plan["cost_plan_hash"]), "next_action": "wait"},
        "events": [_lg12_quality_event("quality_image_rework")],
    }


def _lg12_quality_image_provider_wait(state: SellformGraphState) -> dict[str, Any]:
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import collect_graph_image_results
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 image rework provider wait requires the graph database session.")
    generation = collect_graph_image_results(run_id=str(state["run_id"]), project_id=str(state["project_id"]), db=db)
    generation["scene_id"] = str(dict(state.get("generation") or {}).get("scene_id") or "")
    if int(generation.get("pending_count") or 0):
        validate_resume_payload(interrupt(review_interrupt_payload("provider_wait", {**state, "generation": generation})), "provider_wait")
        generation = collect_graph_image_results(run_id=str(state["run_id"]), project_id=str(state["project_id"]), db=db)
        generation["scene_id"] = str(dict(state.get("generation") or {}).get("scene_id") or "")
    return {
        "current_stage": "quality_image_provider_wait" if int(generation.get("pending_count") or 0) else "quality_image_review",
        "status": "running", "generation": generation,
        "events": [_lg12_quality_event("quality_image_provider_wait")],
    }


def _lg12_quality_image_wait_route(state: SellformGraphState) -> str:
    return "quality_image_provider_wait" if int(dict(state.get("generation") or {}).get("pending_count") or 0) else "quality_image_review"


def _lg12_quality_selective_rework_route(state: SellformGraphState) -> str:
    return {
        "quality_image_rework": "quality_image_rework",
        "quality_copy_rework": "quality_copy_rework",
        "quality_visual_rework": "quality_visual_rework",
        "quality_style_rework": "quality_style_rework",
        "quality_plan_rework": "quality_plan_rework",
    }.get(str(state.get("current_stage") or ""), "quality_seller_review")


def _lg12_quality_image_rework_route(state: SellformGraphState) -> str:
    stage = str(state.get("current_stage") or "")
    if stage == "quality_image_provider_wait":
        return "quality_image_provider_wait"
    if stage == "quality_seller_review":
        return "quality_seller_review"
    return "quality_image_rework"


def _lg12_quality_image_review(state: SellformGraphState) -> dict[str, Any]:
    """Approve one existing scene job, freeze a child, then force child-only QA."""

    from src.db.models import AgentRun, DetailPageVersion, ImageGenerationJobRecord, QualityAssessmentReportVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_image_generation_service import apply_image_review
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload
    from src.services.page_finalization_service import build_lg11_scene_version_fork, persist_lg11_scene_version_fork
    from src.services.prompt_intelligence_service import canonical_hash

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12 image rework review requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""),
        project_id=str(state.get("project_id") or ""),
        workspace_id=str(state.get("workspace_id") or ""),
    ).one()
    generation = dict(state.get("generation") or {})
    scene_id = str(generation.get("scene_id") or "")
    quality = dict(state.get("quality") or {})
    attempt = dict(quality.get("active_attempt") or {})
    raw = interrupt(review_interrupt_payload("image_review", {**state, "generation": generation}))
    response = validate_resume_payload(raw, "image_review")
    generation = apply_image_review(
        run_id=run.id, project_id=run.project_id, decision=response.decision,
        job_id=response.job_id, asset_id=response.asset_id, seller_attested=response.seller_attested, db=db,
    )
    if response.decision != "approve":
        return {
            "current_stage": "quality_seller_review", "status": "running",
            "generation": generation, "quality": {**quality, "seller_review_required": True, "routing_code": "SELLER_REVIEW"},
            "events": [_lg12_quality_event("quality_image_review", node_status="needs_review")],
        }
    _lg12_test_failpoint("LG12_TEST_FAILPOINT_AFTER_PROVIDER_RESULT")
    page_ref = dict(quality.get("current_detail_page_ref") or {})
    page = db.query(DetailPageVersion).filter_by(id=str(page_ref.get("id") or ""), project_id=run.project_id).one()
    job = db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id, job_id=response.job_id, status="approved").one_or_none()
    if job is None or str(job.scene_id or "") != scene_id:
        raise ValueError("Approved image-review job is not the exact Quality Bar scene target.")
    intent = {"target_ids": [scene_id], "intent_hash": canonical_hash({"quality_attempt": attempt.get("canonical_hash"), "scene_id": scene_id})}
    fork = build_lg11_scene_version_fork(source_version=page, edit_run_id=run.id, intent=intent, job=job, db=db)
    child = persist_lg11_scene_version_fork(run=run, scene_version_fork=fork, db=db)
    # The new frozen scene changes the page/renderer identity, so its
    # channel-parity artifacts must be frozen again before child-only QA.  This
    # is the same production finalization boundary used by every other
    # selective rework executor; it does not promote/export the child.
    report_ref = dict(quality.get("quality_report_ref") or {})
    report = db.query(QualityAssessmentReportVersion).filter_by(
        id=str(report_ref.get("id") or ""),
        workspace_id=run.workspace_id,
        project_id=run.project_id,
    ).one_or_none()
    if report is None:
        raise ValueError("IMAGE_REWORK source QualityAssessmentReport is unavailable.")
    _lg12_quality_finalize_frozen_page_exports(page=child, channels=list(report.target_channels_json or []), db=db)
    db.commit(); db.refresh(child)
    child_ref = _lg12_quality_child_ref(child)
    completed_quality = _lg12_quality_complete_attempt(quality, child_ref=child_ref)
    completed_attempt = {
        **dict(completed_quality.get("active_attempt") or {}),
        "provider_operation_ref": {"id": job.job_id, "version": int(job.generation_attempt or 1), "hash": str(job.idempotency_key), "type": "ImageGenerationJobRecord"},
    }
    completed_attempt["canonical_hash"] = canonical_hash({key: value for key, value in completed_attempt.items() if key != "canonical_hash"})
    completed_quality["active_attempt"] = completed_attempt
    return {
        "current_stage": "quality_rework_child_frozen", "status": "running",
        "rendering": {**dict(state.get("rendering") or {}), "detail_page_version": {"id": child_ref["id"], "schema_version": child_ref["version"], "snapshot_hash": child_ref["hash"]}},
        "generation": generation,
        "quality": completed_quality,
        "events": [_lg12_quality_event("quality_rework_child_frozen")],
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


def build_lg10_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any], entry_node: str | None = None):
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
        ("quality_evaluation", _lg12_quality_evaluate),
        ("quality_promotion_ready", _lg12_quality_promotion_ready),
        ("quality_selective_rework", _lg12_quality_selective_rework),
        ("quality_image_rework", _lg12_quality_image_rework),
        ("quality_copy_rework", _lg12_quality_copy_rework),
        ("quality_visual_rework", _lg12_quality_visual_rework),
        ("quality_style_rework", _lg12_quality_style_rework),
        ("quality_plan_rework", _lg12_quality_plan_rework),
        ("quality_image_provider_wait", _lg12_quality_image_provider_wait),
        ("quality_image_review", _lg12_quality_image_review),
        ("quality_seller_review", _lg12_quality_seller_review),
        ("quality_rework_exhausted", _lg12_quality_rework_exhausted),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, entry_node or "bootstrap_run"); graph.add_edge("bootstrap_run", "input_review")
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
        "generation_pending": "generation_pending", "page_assembly": "page_assembly", "finalize_run": "page_assembly", "image_review": "image_review"})
    graph.add_edge("page_assembly", "canonical_renderer")
    graph.add_edge("canonical_renderer", "quality_evaluation")
    graph.add_conditional_edges("quality_evaluation", _lg12_quality_route, {
        "quality_promotion_ready": "quality_promotion_ready",
        "quality_selective_rework": "quality_selective_rework",
        "quality_seller_review": "quality_seller_review",
        "quality_rework_exhausted": "quality_rework_exhausted",
    })
    graph.add_conditional_edges("quality_selective_rework", _lg12_quality_selective_rework_route, {
        "quality_image_rework": "quality_image_rework",
        "quality_copy_rework": "quality_copy_rework",
        "quality_visual_rework": "quality_visual_rework",
        "quality_style_rework": "quality_style_rework",
        "quality_plan_rework": "quality_plan_rework",
        "quality_seller_review": "quality_seller_review",
    })
    graph.add_conditional_edges("quality_copy_rework", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen"
        else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_conditional_edges("quality_visual_rework", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen"
        else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_conditional_edges("quality_style_rework", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen"
        else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_conditional_edges("quality_plan_rework", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen"
        else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_conditional_edges("quality_image_rework", _lg12_quality_image_rework_route, {
        "quality_image_rework": "quality_image_rework",
        "quality_image_provider_wait": "quality_image_provider_wait",
        "quality_seller_review": "quality_seller_review",
    })
    graph.add_conditional_edges("quality_image_provider_wait", _lg12_quality_image_wait_route, {
        "quality_image_provider_wait": "quality_image_provider_wait",
        "quality_image_review": "quality_image_review",
    })
    graph.add_conditional_edges("quality_image_review", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen"
        else "quality_seller_review"
    ), {
        "quality_evaluation": "quality_evaluation",
        "quality_seller_review": "quality_seller_review",
    })
    graph.add_edge("quality_promotion_ready", END)
    graph.add_edge("quality_seller_review", END)
    graph.add_conditional_edges("quality_rework_exhausted", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen" else END
    ), {"quality_evaluation": "quality_evaluation", END: END})
    return graph.compile(checkpointer=checkpointer)


def _lg12i_unified_intake_router(state: SellformGraphState) -> dict[str, Any]:
    """Route every first-class input mode through one durable intake node.

    All first-class intake modes share this compiled intake graph; each mode
    only selects its bounded adapter node after the common durable router.
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
    manual_enabled = mode == "manual"
    owned_url_enabled = mode == "owned_product_url"
    photo_enabled = mode == "photo_only"
    next_adapter = (
        "manual_input_adapter" if manual_enabled
        else "owned_product_url_capture_adapter" if owned_url_enabled
        else "photo_only_observation_adapter" if photo_enabled
        else "intake_adapter_pending"
    )
    return {
        "current_stage": next_adapter,
        "status": "running" if manual_enabled or owned_url_enabled or photo_enabled else "completed",
        "intake": {
            "schema_version": envelope["schema_version"],
            "input_hash": envelope["input_hash"],
            "input_mode": mode,
            "requested_generation_mode": envelope["requested_generation_mode"],
            "target_channels": list(envelope["target_channels"]),
            "run_identity": dict(envelope["run_identity"]),
            "actor_workspace_identity": dict(envelope["actor_workspace_identity"]),
            "source_payload_refs": list(envelope["source_payload_refs"]),
            "next_action": next_adapter if manual_enabled or owned_url_enabled or photo_enabled else "task_12i_adapter_not_implemented",
            "product_source_snapshot_command": {
                "input_mode": mode,
                "input_hash": envelope["input_hash"],
                "source_payload_refs": list(envelope["source_payload_refs"]),
            },
        },
        "events": [_graph_node_event(
            next_adapter,
            "running" if manual_enabled or owned_url_enabled or photo_enabled else "completed",
        )],
    }


def _lg12i_manual_input_adapter(state: SellformGraphState) -> dict[str, Any]:
    """Create the immutable manual source snapshot in the production intake graph.

    The request-scoped DB session is deliberately kept outside state.  The
    adapter returns only artifact/version identities and bounded seller field
    candidates; its raw free-form source body never crosses this boundary.
    """

    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.product_intake_version_service import adapt_manual_input_to_source_snapshot

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12I manual input adapter requires the graph database session.")
    envelope = dict((state.get("input_snapshot") or {}).get("unified_product_intake") or {})
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == str(state.get("run_id") or ""),
            AgentRun.workspace_id == str(state.get("workspace_id") or ""),
            AgentRun.project_id == str(state.get("project_id") or ""),
            AgentRun.mode == "lg12i_intake",
        )
        .one_or_none()
    )
    if run is None:
        raise ValueError("LG-12I manual input graph run is not available in this workspace.")
    manual_source = adapt_manual_input_to_source_snapshot(db, run=run, envelope=envelope)
    intake = dict(state.get("intake") or {})
    return {
        "current_stage": "manual_source_snapshot_ready",
        "status": "completed",
        "intake": {
            **intake,
            "manual_source": manual_source,
            "next_action": "task_12i_truth_normalization_pending",
        },
        "events": [_graph_node_event("manual_source_snapshot_ready", "completed")],
    }


def _lg12i_owned_product_url_capture_adapter(state: SellformGraphState) -> dict[str, Any]:
    """Capture an owned product URL into a source snapshot in the LG-12I graph.

    Capture failures are intentionally recoverable: they retain only the
    pinned request identity and a manual/photo fallback action, never a raw
    response body or a partially-mutated source version.
    """

    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.product_intake_version_service import (
        OwnedProductURLIntakeContractError,
        adapt_owned_product_url_to_source_snapshot,
    )
    from src.services.url_evidence_collector import OwnedURLCaptureError

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12I owned product URL capture adapter requires the graph database session.")
    envelope = dict((state.get("input_snapshot") or {}).get("unified_product_intake") or {})
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == str(state.get("run_id") or ""),
            AgentRun.workspace_id == str(state.get("workspace_id") or ""),
            AgentRun.project_id == str(state.get("project_id") or ""),
            AgentRun.mode == "lg12i_intake",
        )
        .one_or_none()
    )
    if run is None:
        raise ValueError("LG-12I owned product URL graph run is not available in this workspace.")
    intake = dict(state.get("intake") or {})
    try:
        owned_source = adapt_owned_product_url_to_source_snapshot(db, run=run, envelope=envelope)
    except OwnedURLCaptureError as exc:
        request_ref = list(intake.get("source_payload_refs") or [])
        return {
            "current_stage": "owned_url_capture_recovery",
            "status": "completed",
            "intake": {
                **intake,
                "owned_url_capture": {
                    "capture_status": exc.code,
                    "capture_request_refs": request_ref,
                    "recoverable": True,
                },
                "next_action": "task_12i_manual_or_photo_fallback",
            },
            "events": [_graph_node_event("owned_url_capture_recovery", "completed")],
        }
    except OwnedProductURLIntakeContractError:
        # Request/ref integrity is a fail-closed boundary rather than a remote
        # capture outcome; do not silently turn tampering into fallback.
        raise
    return {
        "current_stage": "owned_url_source_snapshot_ready",
        "status": "completed",
        "intake": {
            **intake,
            "owned_url_source": owned_source,
            "next_action": "task_12i_truth_normalization_pending",
        },
        "events": [_graph_node_event("owned_url_source_snapshot_ready", "completed")],
    }


def _lg12i_photo_only_observation_adapter(state: SellformGraphState) -> dict[str, Any]:
    """Pin bounded photo observations into an immutable source snapshot.

    Image bytes and raw OCR output remain outside LangGraph state.  Failures
    in the optional/local observation step are recoverable; tampered asset
    references remain a fail-closed contract error.
    """

    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.product_intake_version_service import (
        PhotoOnlyIntakeContractError,
        PhotoOnlyObservationRecoverableError,
        adapt_photo_only_input_to_source_snapshot,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12I photo-only observation adapter requires the graph database session.")
    envelope = dict((state.get("input_snapshot") or {}).get("unified_product_intake") or {})
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == str(state.get("run_id") or ""),
            AgentRun.workspace_id == str(state.get("workspace_id") or ""),
            AgentRun.project_id == str(state.get("project_id") or ""),
            AgentRun.mode == "lg12i_intake",
        )
        .one_or_none()
    )
    if run is None:
        raise ValueError("LG-12I photo-only graph run is not available in this workspace.")
    intake = dict(state.get("intake") or {})
    try:
        photo_source = adapt_photo_only_input_to_source_snapshot(db, run=run, envelope=envelope)
    except PhotoOnlyObservationRecoverableError as exc:
        return {
            "current_stage": "photo_observation_recovery",
            "status": "completed",
            "intake": {
                **intake,
                "photo_observation": {
                    "observation_status": "recovery",
                    "failure_reason": exc.code,
                    "extractor_status": exc.extractor_status,
                    "source_asset_refs": exc.source_asset_refs or list(intake.get("source_payload_refs") or []),
                    "photo_observation_artifact_ref": exc.observation_artifact_ref,
                    "recoverable": True,
                },
                "next_action": "task_12i_manual_or_owned_url_fallback",
            },
            "events": [_graph_node_event("photo_observation_recovery", "completed")],
        }
    except PhotoOnlyIntakeContractError:
        raise
    observation_status = str(photo_source.get("observation_status") or "ready")
    current_stage = (
        "photo_observation_partial_ready"
        if observation_status == "partial_observation_ready"
        else "photo_source_snapshot_ready"
    )
    return {
        "current_stage": current_stage,
        "status": "completed",
        "intake": {
            **intake,
            "photo_source": photo_source,
            "next_action": "task_12i_truth_normalization_pending",
        },
        "events": [_graph_node_event(current_stage, "completed")],
    }


def _lg12i_product_truth_normalization(state: SellformGraphState) -> dict[str, Any]:
    """Normalize a pinned intake source into unapproved, immutable Truth."""

    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.product_intake_version_service import (
        IntakeVersionContractError,
        build_seller_confirmation_plan,
        ensure_seller_confirmation_not_required,
        normalize_product_truth_from_source_snapshot,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12I Product Truth normalization requires the graph database session.")
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == str(state.get("run_id") or ""),
            AgentRun.workspace_id == str(state.get("workspace_id") or ""),
            AgentRun.project_id == str(state.get("project_id") or ""),
            AgentRun.mode == "lg12i_intake",
        )
        .one_or_none()
    )
    if run is None:
        raise ValueError("LG-12I Product Truth graph run is not available in this workspace.")
    intake = dict(state.get("intake") or {})
    source_payload = (
        dict(intake.get("manual_source") or {})
        or dict(intake.get("owned_url_source") or {})
        or dict(intake.get("photo_source") or {})
    )
    source_reference = dict(source_payload.get("source_snapshot") or {})
    try:
        truth = normalize_product_truth_from_source_snapshot(db, run=run, source_reference=source_reference)
    except IntakeVersionContractError as exc:
        return {
            "current_stage": "truth_blocked_source_integrity",
            "status": "completed",
            "intake": {
                **intake,
                "truth": {"status": "blocked_source_integrity", "reason": str(exc)},
                "next_action": "task_12i_source_integrity_recovery",
            },
            "events": [_graph_node_event("truth_blocked_source_integrity", "completed")],
        }
    confirmation_plan = build_seller_confirmation_plan(
        db,
        run=run,
        truth_reference=dict(truth["truth_version"]),
    )
    confirmation_required = bool(confirmation_plan["confirmation_required"])
    stage = "seller_confirmation_required" if confirmation_required else "seller_confirmation_not_required"
    confirmation_result: dict[str, Any] = confirmation_plan
    if not confirmation_required:
        confirmation = ensure_seller_confirmation_not_required(
            db, run=run, truth_reference=dict(truth["truth_version"]),
        )
        db.commit()
        db.refresh(confirmation)
        confirmation_result = {
            **confirmation_plan,
            "confirmation_required": False,
            "confirmation_ready": True,
            "confirmation_version": {
                "id": confirmation.id, "version": confirmation.version, "hash": confirmation.canonical_hash,
            },
        }
    return {
        "current_stage": stage,
        "status": "running",
        "intake": {
            **intake,
            "product_truth": truth,
            "seller_confirmation": confirmation_result,
            "next_action": "seller_confirmation" if confirmation_required else "product_creative_brief",
        },
        "events": [_graph_node_event(stage, "running")],
    }


def _lg12i_seller_confirmation(state: SellformGraphState) -> dict[str, Any]:
    """Pause only for the bounded, frozen Truth clarification cycle."""

    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.langgraph_review_service import review_interrupt_payload, validate_resume_payload
    from src.services.product_intake_version_service import (
        SellerConfirmationContractError,
        apply_seller_confirmation_cycle,
        seller_confirmation_resume_request_hash,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12I seller confirmation requires the graph database session.")
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.id == str(state.get("run_id") or ""),
            AgentRun.workspace_id == str(state.get("workspace_id") or ""),
            AgentRun.project_id == str(state.get("project_id") or ""),
            AgentRun.mode == "lg12i_intake",
        )
        .one_or_none()
    )
    if run is None:
        raise ValueError("LG-12I seller confirmation graph run is not available in this workspace.")
    intake = dict(state.get("intake") or {})
    plan = dict(intake.get("seller_confirmation") or {})
    if not plan.get("confirmation_required") or not list(plan.get("clarifications") or []):
        return {
            "current_stage": "seller_confirmation_not_required",
            "status": "running",
            "intake": {**intake, "next_action": "product_creative_brief"},
            "events": [_graph_node_event("seller_confirmation_not_required", "completed")],
        }
    raw = interrupt(review_interrupt_payload("seller_confirmation", {**state, "intake": intake}, schema_version="lg12i-v1"))
    response = validate_resume_payload(raw, "seller_confirmation")
    envelope = dict((state.get("input_snapshot") or {}).get("unified_product_intake") or {})
    actor_id = str(dict(envelope.get("actor_workspace_identity") or {}).get("actor_id") or "")
    try:
        result = apply_seller_confirmation_cycle(
            db,
            run=run,
            plan=plan,
            answers=list(response.confirmation_answers or []),
            actor_id=actor_id,
            resume_request_hash=response.confirmation_request_hash,
            resume_decision=response.decision,
        )
    except SellerConfirmationContractError:
        raise
    if result["confirmation_ready"]:
        return {
            "current_stage": "confirmation_ready",
            "status": "running",
            "intake": {
                **intake,
                "seller_confirmation": {**result, "confirmation_required": False},
                "next_action": "task_12i_creative_brief_pending",
            },
            "events": [_graph_node_event("confirmation_ready", "completed")],
        }
    next_plan = {
        "schema_version": plan.get("schema_version"),
        "truth_version": dict(plan.get("truth_version") or {}),
        "run_identity": dict(plan.get("run_identity") or {}),
        "confirmation_cycle": int(result["confirmation_cycle"]) + 1,
        "confirmation_required": True,
        "clarifications": result["clarifications"],
        "unresolved_queue": result["unresolved_queue"],
        "parent_confirmation_version": result["confirmation_version"],
        "last_confirmation_version": result["confirmation_version"],
        "unresolved_refs": result["unresolved_refs"],
        "rights_decisions": result["rights_decisions"],
    }
    next_plan["resume_request_hash"] = seller_confirmation_resume_request_hash(
        run=run, plan=next_plan, actor_id=actor_id,
    )
    return {
        "current_stage": "confirmation_still_required",
        "status": "running",
        "intake": {**intake, "seller_confirmation": next_plan, "next_action": "seller_confirmation"},
        "events": [_graph_node_event("confirmation_still_required", "running")],
    }


def _lg12i_product_creative_brief(state: SellformGraphState) -> dict[str, Any]:
    """Compile the frozen Brief directly from intake lineage, never from Master."""

    from src.db.models import AgentRun
    from src.services.creative_brief_service import (
        CreativeBriefInputError,
        compile_lg12i_product_creative_brief,
        create_lg12i_approved_fact_snapshot,
    )
    from src.services.langgraph_discovery_service import current_langgraph_session

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12I Product Creative Brief requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""), workspace_id=str(state.get("workspace_id") or ""),
        project_id=str(state.get("project_id") or ""), mode="lg12i_intake",
    ).one_or_none()
    if run is None:
        raise ValueError("LG-12I Product Creative Brief graph run is unavailable in this workspace.")
    intake = dict(state.get("intake") or {})
    truth = dict(intake.get("product_truth") or {}).get("truth_version")
    confirmation = dict(intake.get("seller_confirmation") or {}).get("confirmation_version")
    source_payload = (
        dict(intake.get("manual_source") or {}) or dict(intake.get("owned_url_source") or {})
        or dict(intake.get("photo_source") or {})
    )
    source = source_payload.get("source_snapshot")
    envelope = dict((state.get("input_snapshot") or {}).get("unified_product_intake") or {})
    try:
        brief = compile_lg12i_product_creative_brief(
            db, run, source_reference=dict(source or {}), truth_reference=dict(truth or {}),
            confirmation_reference=dict(confirmation or {}),
            target_channels=list(envelope.get("target_channels") or []),
        )
        facts = create_lg12i_approved_fact_snapshot(db, run, creative_brief=brief)
        db.commit()
        db.refresh(brief); db.refresh(facts)
    except CreativeBriefInputError as exc:
        return {
            "current_stage": "creative_brief_blocked", "status": "completed",
            "intake": {**intake, "creative_brief": {"status": "blocked", "reason": exc.code}, "next_action": "task_12i_confirmation_or_brand_recovery"},
            "events": [_graph_node_event("creative_brief_blocked", "completed")],
        }
    brief_ref = {"id": brief.id, "version": brief.version, "hash": brief.output_hash}
    return {
        "current_stage": "product_creative_brief", "status": "running",
        "intake": {
            **intake,
            "creative_brief": {"brief_version": brief_ref, "approved_fact_snapshot": {"id": facts.id, "version": 1, "hash": facts.snapshot_hash}},
            "next_action": "commerce_creative_master",
        },
        "events": [_graph_node_event("product_creative_brief", "completed")],
    }


def _lg12i_commerce_creative_master(state: SellformGraphState) -> dict[str, Any]:
    """Create the initial immutable reference index after the Brief is frozen."""

    from src.db.models import AgentRun, BrandKitVersion, ProductCreativeBriefVersion, ProductTruthVersion
    from src.services.langgraph_discovery_service import current_langgraph_session
    from src.services.product_intake_version_service import (
        IntakeVersionContractError,
        create_commerce_creative_master_version,
        lg12i_approved_asset_manifest_reference,
        lg12i_pending_production_artifact_reference,
    )

    db = current_langgraph_session()
    if db is None:
        raise RuntimeError("LG-12I Commerce Creative Master requires the graph database session.")
    run = db.query(AgentRun).filter_by(
        id=str(state.get("run_id") or ""), workspace_id=str(state.get("workspace_id") or ""),
        project_id=str(state.get("project_id") or ""), mode="lg12i_intake",
    ).one_or_none()
    if run is None:
        raise ValueError("LG-12I Commerce Creative Master graph run is unavailable in this workspace.")
    intake = dict(state.get("intake") or {})
    source_payload = (
        dict(intake.get("manual_source") or {}) or dict(intake.get("owned_url_source") or {})
        or dict(intake.get("photo_source") or {})
    )
    source = dict(source_payload.get("source_snapshot") or {})
    truth = dict(dict(intake.get("product_truth") or {}).get("truth_version") or {})
    confirmation = dict(dict(intake.get("seller_confirmation") or {}).get("confirmation_version") or {})
    brief = dict(dict(intake.get("creative_brief") or {}).get("brief_version") or {})
    fact_snapshot = dict(dict(intake.get("creative_brief") or {}).get("approved_fact_snapshot") or {})
    envelope = dict((state.get("input_snapshot") or {}).get("unified_product_intake") or {})
    brief_row = db.query(ProductCreativeBriefVersion).filter_by(id=brief.get("id"), project_id=run.project_id).one_or_none()
    if brief_row is None:
        raise IntakeVersionContractError("LG-12I Creative Brief is missing before Master creation.")
    manifest = lg12i_approved_asset_manifest_reference(source_reference=source, usable_asset_refs=list(brief_row.usable_asset_refs_json or []))
    brand_kit = db.query(BrandKitVersion).filter_by(id=brief_row.brand_kit_version_id, workspace_id=run.workspace_id).one_or_none()
    truth_row = db.query(ProductTruthVersion).filter_by(id=truth.get("id"), project_id=run.project_id).one_or_none()
    if brand_kit is None or truth_row is None:
        raise IntakeVersionContractError("LG-12I Master dependencies are missing.")
    try:
        master = create_commerce_creative_master_version(
            db, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id, created_by=run.created_by,
            source_reference=source, truth_reference=truth, confirmation_reference=confirmation,
            creative_brief_reference=brief,
            brand_kit_reference={"id": brand_kit.id, "version": brand_kit.version, "hash": brand_kit.content_hash},
            evidence_artifact_refs=list(truth_row.evidence_refs_json or []),
            approved_fact_snapshot_ref=fact_snapshot, approved_asset_manifest_ref=manifest,
            copy_artifact_ref=lg12i_pending_production_artifact_reference(artifact_key="copywriting", creative_brief_reference=brief),
            page_plan_artifact_ref=lg12i_pending_production_artifact_reference(artifact_key="page_planning", creative_brief_reference=brief),
            target_channels=list(envelope.get("target_channels") or []),
        )
        db.commit(); db.refresh(master)
    except IntakeVersionContractError as exc:
        return {
            "current_stage": "commerce_creative_master_blocked", "status": "completed",
            "intake": {**intake, "commerce_creative_master": {"status": "blocked", "reason": str(exc)}, "next_action": "task_12i_master_recovery"},
            "events": [_graph_node_event("commerce_creative_master_blocked", "completed")],
        }
    return {
        "current_stage": "master_ready", "status": "completed",
        "intake": {**intake, "commerce_creative_master": {"master_version": {"id": master.id, "version": master.version, "hash": master.canonical_hash}}, "next_action": "task_12i_planning_pending"},
        "events": [_graph_node_event("commerce_creative_master", "completed")],
    }


def _lg12i_source_snapshot_route(state: SellformGraphState) -> str:
    """Never normalize a recoverable capture/observation failure."""

    stage = str(state.get("current_stage") or "")
    return "product_truth_normalization" if (
        stage.endswith("snapshot_ready") or stage == "photo_observation_partial_ready"
    ) else "finish"


def _lg12i_intake_router_route(state: SellformGraphState) -> str:
    mode = str(dict(state.get("intake") or {}).get("input_mode") or "")
    if mode == "manual":
        return "manual_input_adapter"
    if mode == "owned_product_url":
        return "owned_product_url_capture_adapter"
    if mode == "photo_only":
        return "photo_only_observation_adapter"
    return "finish"


def _lg12i_confirmation_route(state: SellformGraphState) -> str:
    stage = str(state.get("current_stage") or "")
    if stage == "confirmation_still_required":
        return "seller_confirmation"
    if stage in {"confirmation_ready", "seller_confirmation_not_required"}:
        return "product_creative_brief"
    return "finish"


def _lg12i_truth_route(state: SellformGraphState) -> str:
    """Only a completed frozen Truth may advance into confirmation or Brief."""

    stage = str(state.get("current_stage") or "")
    if stage == "seller_confirmation_required":
        return "seller_confirmation"
    if stage == "seller_confirmation_not_required":
        return "product_creative_brief"
    return "finish"


def _lg12i_creative_brief_route(state: SellformGraphState) -> str:
    """A blocked Brief is a terminal recovery state, never a Master input."""

    return "commerce_creative_master" if str(state.get("current_stage") or "") == "product_creative_brief" else "finish"


def build_lg12i_intake_compiled_graph(*, checkpointer: BaseCheckpointSaver[Any]):
    """Compile the LG-12I subgraph inside the existing production runtime."""

    graph = StateGraph(SellformGraphState)
    graph.add_node("unified_intake_router", _lg12i_unified_intake_router)
    graph.add_node("manual_input_adapter", _lg12i_manual_input_adapter)
    graph.add_node("owned_product_url_capture_adapter", _lg12i_owned_product_url_capture_adapter)
    graph.add_node("photo_only_observation_adapter", _lg12i_photo_only_observation_adapter)
    graph.add_node("product_truth_normalization", _lg12i_product_truth_normalization)
    graph.add_node("seller_confirmation", _lg12i_seller_confirmation)
    graph.add_node("product_creative_brief", _lg12i_product_creative_brief)
    graph.add_node("commerce_creative_master", _lg12i_commerce_creative_master)
    graph.add_edge(START, "unified_intake_router")
    graph.add_conditional_edges(
        "unified_intake_router",
        _lg12i_intake_router_route,
        {
            "manual_input_adapter": "manual_input_adapter",
            "owned_product_url_capture_adapter": "owned_product_url_capture_adapter",
            "photo_only_observation_adapter": "photo_only_observation_adapter",
            "finish": END,
        },
    )
    for adapter in ("manual_input_adapter", "owned_product_url_capture_adapter", "photo_only_observation_adapter"):
        graph.add_conditional_edges(adapter, _lg12i_source_snapshot_route, {
            "product_truth_normalization": "product_truth_normalization", "finish": END,
        })
    graph.add_conditional_edges(
        "product_truth_normalization",
        _lg12i_truth_route,
        {
            "seller_confirmation": "seller_confirmation",
            "product_creative_brief": "product_creative_brief",
            "finish": END,
        },
    )
    graph.add_conditional_edges(
        "seller_confirmation",
        _lg12i_confirmation_route,
        {"seller_confirmation": "seller_confirmation", "product_creative_brief": "product_creative_brief", "finish": END},
    )
    graph.add_conditional_edges(
        "product_creative_brief",
        _lg12i_creative_brief_route,
        {"commerce_creative_master": "commerce_creative_master", "finish": END},
    )
    graph.add_edge("commerce_creative_master", END)
    return graph.compile(checkpointer=checkpointer)


def _lg11_edit_event(stage: str, *, status: str = "running") -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "node_status": "completed",
        "event_type": "node_completed",
    }


def _lg11_quality_handoff(*, child: Any) -> dict[str, Any]:
    """Project one persisted LG-11 immutable child into the shared QA input."""

    child_ref = _lg12_quality_child_ref(child)
    return {
        "current_stage": "quality_evaluation", "status": "running",
        "rendering": {
            "detail_page_version": {
                "id": child_ref["id"], "schema_version": child_ref["version"],
                "snapshot_hash": child_ref["hash"],
            },
        },
        "quality": {"schema_version": "lg12-quality-graph-v1", "current_detail_page_ref": child_ref, "attempt_ledger": []},
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
        persist_lg11_copy_version_fork,
        persist_lg11_style_version_fork,
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
        child = persist_lg11_style_version_fork(run=run, style_version_fork=fork, db=db)
        db.commit(); db.refresh(child)
        return {
            **_lg11_quality_handoff(child=child),
            "edit": {**edit, "next_action": "none", "style_version_fork": fork},
            "events": [_lg11_edit_event("style_version_reassembled")],
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
    child = persist_lg11_copy_version_fork(run=run, copy_version_fork=fork, db=db)
    db.commit(); db.refresh(child)

    return {
        **_lg11_quality_handoff(child=child),
        "edit": {**edit, "next_action": "none", "copy_version_fork": fork},
        "events": [_lg11_edit_event("copy_version_forked")],
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
    if str(state.get("current_stage") or "") == "quality_evaluation":
        return "quality_evaluation"
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
    if str(state.get("current_stage") or "") == "quality_evaluation":
        return "quality_evaluation"
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
        persist_lg11_canvas_version_fork,
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
        child = persist_lg11_canvas_version_fork(run=run, canvas_version_fork=fork, db=db)
        db.commit(); db.refresh(child)
        return {**_lg11_quality_handoff(child=child), "canvas": canvas,
                "edit": {**edit, "next_action": "none", "canvas_version_fork": fork},
                "events": [_lg11_edit_event("canvas_version_forked")]}
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
    from src.services.page_finalization_service import build_lg11_scene_version_fork, persist_lg11_scene_version_fork

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
    child = persist_lg11_scene_version_fork(run=run, scene_version_fork=fork, db=db)
    db.commit(); db.refresh(child)
    return {**_lg11_quality_handoff(child=child), "generation": generation,
            "edit": {**edit, "next_action": "none", "scene_status": "approved", "scene_version_fork": fork},
            "events": [_lg11_edit_event("scene_version_forked")]}


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
    # The exact same TASK-12.9 nodes used by LG-10 evaluate every persisted
    # LG-11 child.  No second, edit-only QA implementation is introduced.
    graph.add_node("quality_evaluation", _lg12_quality_evaluate)
    graph.add_node("quality_promotion_ready", _lg12_quality_promotion_ready)
    graph.add_node("quality_selective_rework", _lg12_quality_selective_rework)
    graph.add_node("quality_image_rework", _lg12_quality_image_rework)
    graph.add_node("quality_copy_rework", _lg12_quality_copy_rework)
    graph.add_node("quality_visual_rework", _lg12_quality_visual_rework)
    graph.add_node("quality_style_rework", _lg12_quality_style_rework)
    graph.add_node("quality_plan_rework", _lg12_quality_plan_rework)
    graph.add_node("quality_image_provider_wait", _lg12_quality_image_provider_wait)
    graph.add_node("quality_image_review", _lg12_quality_image_review)
    graph.add_node("quality_seller_review", _lg12_quality_seller_review)
    graph.add_node("quality_rework_exhausted", _lg12_quality_rework_exhausted)
    graph.add_node("reject_edit_run", _lg11_reject_edit_run)
    graph.add_edge(START, "prepare_edit_run")
    graph.add_edge("prepare_edit_run", "edit_confirmation")
    graph.add_conditional_edges("edit_confirmation", _lg11_edit_confirmation_route, {
        "finalize_edit_run": "finalize_edit_run", "reject_edit_run": "reject_edit_run",
    })
    graph.add_conditional_edges("finalize_edit_run", _lg11_finalize_edit_run_route, {
        "fact_evidence_review": "fact_evidence_review", "scene_cost_approval": "scene_cost_approval", "scene_image_review": "scene_image_review", "canvas_edit": "canvas_edit", "quality_evaluation": "quality_evaluation", "end": END,
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
    graph.add_conditional_edges("scene_image_review", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_evaluation" else "end"
    ), {"quality_evaluation": "quality_evaluation", "end": END})
    graph.add_conditional_edges("canvas_edit", _lg11_canvas_edit_route, {"canvas_edit": "canvas_edit", "quality_evaluation": "quality_evaluation", "end": END})
    graph.add_conditional_edges("quality_evaluation", _lg12_quality_route, {
        "quality_promotion_ready": "quality_promotion_ready", "quality_selective_rework": "quality_selective_rework",
        "quality_seller_review": "quality_seller_review", "quality_rework_exhausted": "quality_rework_exhausted",
    })
    graph.add_conditional_edges("quality_selective_rework", _lg12_quality_selective_rework_route, {
        "quality_image_rework": "quality_image_rework", "quality_copy_rework": "quality_copy_rework",
        "quality_visual_rework": "quality_visual_rework", "quality_style_rework": "quality_style_rework",
        "quality_plan_rework": "quality_plan_rework", "quality_seller_review": "quality_seller_review",
    })
    graph.add_conditional_edges("quality_copy_rework", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen" else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_conditional_edges("quality_visual_rework", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen" else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_conditional_edges("quality_style_rework", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen" else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_conditional_edges("quality_plan_rework", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen" else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_conditional_edges("quality_image_rework", _lg12_quality_image_rework_route, {
        "quality_image_rework": "quality_image_rework", "quality_image_provider_wait": "quality_image_provider_wait", "quality_seller_review": "quality_seller_review",
    })
    graph.add_conditional_edges("quality_image_provider_wait", _lg12_quality_image_wait_route, {
        "quality_image_provider_wait": "quality_image_provider_wait", "quality_image_review": "quality_image_review",
    })
    graph.add_conditional_edges("quality_image_review", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen" else "quality_seller_review"
    ), {"quality_evaluation": "quality_evaluation", "quality_seller_review": "quality_seller_review"})
    graph.add_edge("quality_promotion_ready", END)
    graph.add_edge("quality_seller_review", END)
    graph.add_conditional_edges("quality_rework_exhausted", lambda state: (
        "quality_evaluation" if str(state.get("current_stage") or "") == "quality_rework_child_frozen" else END
    ), {"quality_evaluation": "quality_evaluation", END: END})
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
