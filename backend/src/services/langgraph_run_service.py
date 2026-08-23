"""LG-1 durable LangGraph run service.

This service owns the bridge between a LangGraph checkpoint thread and the
existing ``AgentRun`` / ``AgentRunStep`` operational projection.  It does not
replace the legacy 11-agent execution path yet; LG-2 through LG-6 migrate the
domain nodes one subgraph at a time.
"""

from __future__ import annotations

import copy
import datetime
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.agents.langgraph_runtime import (
    build_lg8_compiled_graph,
    build_lg10_compiled_graph,
    build_lg11_compiled_graph,
    build_lg7_compiled_graph,
    build_lg6_compiled_graph,
    build_lg5_compiled_graph,
    build_lg4_compiled_graph,
    build_lg3_compiled_graph,
    build_lg1_compiled_graph,
    build_lg1_graph_input,
    build_lg12i_intake_compiled_graph,
    build_lg12i_intake_graph_input,
    build_lg11_edit_graph_input,
    langgraph_runtime_enabled,
    open_postgres_checkpointer,
)

# LG-2~LG-5 regression harnesses replace this long-lived injection seam with
# their stage-specific graph.  Keep that contract while LG-6 remains the
# production graph selected below.
_UNPATCHED_LG5_GRAPH_BUILDER = build_lg5_compiled_graph
from src.db.models import AgentRun, AgentRunStep, Asset, ProductProject


logger = logging.getLogger(__name__)


class GraphRunNotFound(ValueError):
    pass


class GraphRunResumeUnavailable(ValueError):
    """LG-1 has no interrupt node yet, so there is nothing to resume."""


class GraphRunCancelled(ValueError):
    pass


class GraphRunResumeRequired(ValueError):
    pass


class GraphRunExecutionFailed(ValueError):
    pass


class GraphRunThreadMismatch(ValueError):
    pass


class GraphRunReviewRequired(ValueError):
    pass


def _seller_confirmation_resume_response(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("review_stage") != "seller_confirmation":
        return None
    from src.services.langgraph_review_service import validate_resume_payload

    try:
        payload = validate_resume_payload(value, "seller_confirmation")
    except ValueError as error:
        raise GraphRunReviewRequired(str(error)) from error
    return payload.model_dump()


def _seller_confirmation_actor_for_run(run: AgentRun) -> str:
    return str(
        dict((run.input_snapshot or {}).get("unified_product_intake") or {})
        .get("actor_workspace_identity", {})
        .get("actor_id")
        or ""
    )


def _seller_confirmation_replay(
    db: Session, *, run: AgentRun, actor_id: str | None, response: dict[str, Any] | None,
) -> bool:
    """Return whether this is an already-persisted public confirmation resume."""

    if response is None:
        return False
    expected_actor = _seller_confirmation_actor_for_run(run)
    if not actor_id or actor_id != expected_actor:
        raise GraphRunReviewRequired("Only the actor that started this intake run may submit seller confirmation.")
    from src.services.product_intake_version_service import (
        SellerConfirmationContractError,
        find_seller_confirmation_resume_replay,
        seller_confirmation_answer_bundle_hash,
    )

    try:
        replay = find_seller_confirmation_resume_replay(
            db,
            run=run,
            actor_id=actor_id,
            resume_request_hash=str(response.get("confirmation_request_hash") or ""),
            answer_bundle_hash=seller_confirmation_answer_bundle_hash(
                decision=str(response.get("decision") or ""),
                answers=list(response.get("confirmation_answers") or []),
            ),
        )
    except (SellerConfirmationContractError, ValueError) as error:
        raise GraphRunReviewRequired(str(error)) from error
    return replay is not None


def _failure_contract(error: Exception | dict[str, Any], fallback_stage: str) -> dict[str, Any]:
    """Normalize internal graph errors into an actionable, browser-safe view."""

    if isinstance(error, dict):
        raw_message = str(error.get("message") or "")
        existing = dict(error)
    else:
        raw_message = str(error)
        existing = {}

    if "safe seller-owned reference asset" in raw_message:
        return {
            **existing,
            "stage": "visual_planning",
            "code": "SAFE_REFERENCE_ASSET_REQUIRED",
            "message": raw_message,
            "user_message": (
                "AI 비주얼 기획에 사용할 안전한 권리 보유 사진이 없습니다. "
                "글자·로고가 없는 제품 사진을 권리 보유 이미지로 추가해 주세요."
            ),
            "recovery_action": "upload_safe_reference_asset_and_retry",
            "source": "langgraph",
            "recoverable": True,
        }
    code = str(existing.get("code") or getattr(error, "code", "") or "GRAPH_EXECUTION_FAILED")
    if code in {"IMAGE_PROVIDER_NOT_CONFIGURED", "IMAGE_JOB_PREPARE_FAILED", "IMAGE_JOB_DISPATCH_FAILED"}:
        return {
            **existing,
            "stage": "generation_pending",
            "code": code,
            "message": raw_message,
            "user_message": raw_message or "이미지 생성 준비를 확인한 뒤 같은 실행을 다시 시작해 주세요.",
            "recovery_action": "configure_provider_or_fix_scene_and_resume",
            "source": "langgraph",
            "recoverable": True,
        }
    return {
        **existing,
        "stage": str(existing.get("stage") or fallback_stage or "graph_execution"),
        "code": code,
        "message": raw_message or "LangGraph execution failed.",
        "user_message": str(
            existing.get("user_message")
            or "그래프 실행 중 오류가 발생했습니다. 원인을 해결한 뒤 같은 실행을 다시 시도할 수 있습니다."
        ),
        "recovery_action": str(existing.get("recovery_action") or "retry_same_run"),
        "source": "langgraph",
        "recoverable": bool(existing.get("recoverable", True)),
    }


def _execution_view(run: AgentRun) -> dict[str, Any]:
    errors = [_failure_contract(item, run.current_stage) for item in (run.error_log or [])]
    return {
        "recoverable": run.status == "failed",
        "errors": errors,
        "last_error": errors[-1] if errors else None,
    }


@dataclass(frozen=True)
class GraphRunStateView:
    run_id: str
    thread_id: str
    status: str
    current_stage: str
    checkpoint_id: str | None
    values: dict[str, Any]
    next_nodes: list[str]


def _browser_checkpoint_values(run: AgentRun, snapshot: Any) -> dict[str, Any]:
    """Overlay the active interrupt context onto its pre-node checkpoint.

    LangGraph checkpoints the state *before* a node calls ``interrupt``.  LG-5R
    computes a fresh cost plan inside generation_pending and includes it in the
    durable interrupt payload, so the browser must read that payload rather
    than an older ``values.generation`` snapshot.  This keeps refresh recovery
    and scene-only regeneration cost approval consistent without mutating the
    graph checkpoint outside ``Command(resume=...)``.
    """

    values = dict(snapshot.values or {})
    review = dict(((run.outputs_json or {}).get("langgraph_review") or {}))
    # An interrupt payload is authoritative only while the run is actually
    # waiting at that interrupt.  Keeping an old pending payload after the
    # graph completed would overwrite the final checkpoint with a stale image
    # attempt on every browser refresh.
    pending = dict(review.get("pending") or {}) if run.status == "awaiting_review" else {}
    pending_generation = dict((pending.get("context") or {}).get("generation") or {})
    if pending_generation:
        values["generation"] = {
            **dict(values.get("generation") or {}),
            **pending_generation,
        }
    if run.status != "awaiting_review":
        review["pending"] = None
    values["review"] = review
    values["execution"] = _execution_view(run)
    return values


class AgentRunGraphProjector:
    """Project LangGraph node events into Sellform's existing run tables."""

    @staticmethod
    def apply_node_update(run: AgentRun, db: Session, update: dict[str, Any]) -> AgentRun:
        events = update.get("events") or []
        if not events:
            raise ValueError("LangGraph node update is missing its projection event.")
        event = events[-1]
        stage = str(event.get("stage") or "")
        status = str(event.get("status") or "")
        if not stage or status not in {"running", "completed", "failed"}:
            raise ValueError("LangGraph projection event has an invalid stage or status.")

        # Lock and refresh the projection before writing it. A cancel request
        # that won the race must never be overwritten by a later node event.
        projected_run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run.id)
            .with_for_update()
            .one()
        )
        if projected_run.status == "cancelled":
            raise GraphRunCancelled("Graph run was cancelled before the next node projection.")

        # This is the only LG-1 code path that mutates current_stage after a
        # graph run starts. The value always comes from a graph node event.
        projected_run.current_stage = stage
        projected_run.status = status
        runtime_output = dict((projected_run.outputs_json or {}).get("langgraph_runtime") or {})
        runtime_output.update(
            {
                "thread_id": projected_run.graph_thread_id,
                "last_event": dict(event),
                "last_stage": stage,
            }
        )
        projected_run.outputs_json = {
            **(projected_run.outputs_json or {}),
            "langgraph_runtime": runtime_output,
        }
        # LG-2 state deltas are already JSON-safe summaries. Keep them in a
        # namespaced projection so existing ProductBrief/evidence-board
        # consumers remain untouched while the next sprint adds their read
        # adapter. Never persist a resolved FactSnapshot's facts/evidence here.
        discovery_delta = update.get("discovery")
        if isinstance(discovery_delta, dict):
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_discovery": {
                    **((projected_run.outputs_json or {}).get("langgraph_discovery") or {}),
                    **discovery_delta,
                },
            }
        commerce_delta = update.get("commerce")
        if isinstance(commerce_delta, dict):
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_commerce": {
                    **((projected_run.outputs_json or {}).get("langgraph_commerce") or {}),
                    **commerce_delta,
                },
            }
        intake_delta = update.get("intake")
        if isinstance(intake_delta, dict):
            # LG-12I projects the same compact, validated envelope identity
            # that is held in the checkpoint.  It never projects source bodies
            # or mode-specific adapter output before those adapters exist.
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_intake": {
                    **((projected_run.outputs_json or {}).get("langgraph_intake") or {}),
                    **intake_delta,
                },
            }
        generation_delta = update.get("generation")
        if isinstance(generation_delta, dict):
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_generation": {
                    **((projected_run.outputs_json or {}).get("langgraph_generation") or {}),
                    **generation_delta,
                },
            }
        assembly_delta = update.get("page_assembly")
        if isinstance(assembly_delta, dict) and assembly_delta:
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_page_assembly": {
                    **((projected_run.outputs_json or {}).get("langgraph_page_assembly") or {}),
                    **assembly_delta,
                },
            }
        rendering_delta = update.get("rendering")
        if isinstance(rendering_delta, dict) and rendering_delta:
            # A graph checkpoint can commit before this SQL projection. Reuse
            # the deterministic version persistence helper while replaying
            # history so the frozen renderer state always points at a durable
            # DetailPageVersion after restart.
            generation = dict(update.get("generation") or {})
            assembly = dict(update.get("page_assembly") or {})
            canonical_input = generation.get("canonical_page_assembly_input")
            if isinstance(canonical_input, dict) and assembly:
                from src.services.page_finalization_service import persist_lg10_detail_page_version

                version = persist_lg10_detail_page_version(
                    run=projected_run,
                    canonical_page_assembly_input=canonical_input,
                    page_assembly=assembly,
                    rendering=rendering_delta,
                    db=db,
                )
                rendering_delta = {
                    **rendering_delta,
                    "detail_page_version": {
                        "id": version.id,
                        "schema_version": "lg10-detail-page-version-v1",
                        "snapshot_hash": str((version.sections_json or {}).get("snapshot_hash") or ""),
                    },
                }
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_page_rendering": {
                    **((projected_run.outputs_json or {}).get("langgraph_page_rendering") or {}),
                    **rendering_delta,
                },
            }
        quality_delta = update.get("quality")
        if isinstance(quality_delta, dict) and quality_delta:
            # TASK-12.9 projects only the checkpoint-safe QA summary: frozen
            # report/Quality-Bar/attempt identities plus bounded route state.
            # Domain bodies, rendered HTML, image bytes and provider payloads
            # remain in their immutable artifact stores.
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_quality": {
                    **((projected_run.outputs_json or {}).get("langgraph_quality") or {}),
                    **quality_delta,
                },
            }
        edit_delta = update.get("edit")
        if isinstance(edit_delta, dict) and edit_delta:
            copy_version_fork = edit_delta.get("copy_version_fork")
            if isinstance(copy_version_fork, dict):
                from src.services.page_finalization_service import persist_lg11_copy_version_fork

                persist_lg11_copy_version_fork(
                    run=projected_run,
                    copy_version_fork=copy_version_fork,
                    db=db,
                )
            scene_version_fork = edit_delta.get("scene_version_fork")
            if isinstance(scene_version_fork, dict):
                from src.services.page_finalization_service import persist_lg11_scene_version_fork
                persist_lg11_scene_version_fork(run=projected_run, scene_version_fork=scene_version_fork, db=db)
            style_version_fork = edit_delta.get("style_version_fork")
            if isinstance(style_version_fork, dict):
                from src.services.page_finalization_service import persist_lg11_style_version_fork

                persist_lg11_style_version_fork(
                    run=projected_run,
                    style_version_fork=style_version_fork,
                    db=db,
                )
            canvas_version_fork = edit_delta.get("canvas_version_fork")
            if isinstance(canvas_version_fork, dict):
                from src.services.page_finalization_service import persist_lg11_canvas_version_fork
                persist_lg11_canvas_version_fork(run=projected_run, canvas_version_fork=canvas_version_fork, db=db)
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_edit": {
                    **((projected_run.outputs_json or {}).get("langgraph_edit") or {}),
                    **edit_delta,
                },
            }
        canvas_delta = update.get("canvas")
        if isinstance(canvas_delta, dict) and canvas_delta:
            projected_run.outputs_json = {**projected_run.outputs_json, "langgraph_canvas": canvas_delta}
        prompt_delta = update.get("prompt_intelligence")
        if isinstance(prompt_delta, dict):
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "prompt_intelligence": {
                    **((projected_run.outputs_json or {}).get("prompt_intelligence") or {}),
                    **prompt_delta,
                },
            }
        review_delta = update.get("review")
        if isinstance(review_delta, dict):
            review_output = dict((projected_run.outputs_json or {}).get("langgraph_review") or {})
            pending = review_output.get("pending")
            if pending and pending.get("review_stage") == stage:
                review_output["pending"] = None
            review_output["last_resolution"] = dict(review_delta)
            projected_run.outputs_json = {
                **projected_run.outputs_json,
                "langgraph_review": review_output,
            }

        step = (
            db.query(AgentRunStep)
            .filter(AgentRunStep.run_id == projected_run.id, AgentRunStep.stage == stage)
            .first()
        )
        if step is None:
            step = AgentRunStep(run_id=projected_run.id, stage=stage, status="pending")

        now = datetime.datetime.utcnow()
        step.status = str(event.get("node_status") or "completed")
        step.started_at = step.started_at or now
        step.completed_at = now if step.status == "completed" else None
        step.output_json = {"event": dict(event)}
        step.error_message = None
        if status == "completed":
            projected_run.completed_at = now

        db.add(step)
        db.add(projected_run)
        db.commit()
        db.refresh(projected_run)
        return projected_run

    @staticmethod
    def apply_interrupt_wait(run: AgentRun, db: Session, payload: dict[str, Any]) -> AgentRun:
        """Project an interrupt once, without executing any downstream node."""

        stage = str(payload.get("review_stage") or "")
        if not stage:
            raise ValueError("LangGraph interrupt is missing review_stage.")
        projected_run = (
            db.query(AgentRun).filter(AgentRun.id == run.id).with_for_update().one()
        )
        if projected_run.status == "cancelled":
            raise GraphRunCancelled("Graph run was cancelled before review projection.")
        review_output = dict((projected_run.outputs_json or {}).get("langgraph_review") or {})
        previous = review_output.get("pending")
        review_output["pending"] = dict(payload)
        if previous != payload:
            review_output["history"] = [
                *(review_output.get("history") or []),
                {"event": "interrupt_waiting", "review_stage": stage, "schema_version": payload.get("schema_version")},
            ]
        projected_run.current_stage = stage
        projected_run.status = "awaiting_review"
        projected_run.completed_at = None
        projected_run.outputs_json = {
            **(projected_run.outputs_json or {}),
            "langgraph_review": review_output,
            "langgraph_runtime": {
                **((projected_run.outputs_json or {}).get("langgraph_runtime") or {}),
                "thread_id": projected_run.graph_thread_id,
                "last_stage": stage,
                "pending_interrupt": stage,
            },
        }
        step = (
            db.query(AgentRunStep)
            .filter(AgentRunStep.run_id == projected_run.id, AgentRunStep.stage == stage)
            .first()
        )
        if step is None:
            step = AgentRunStep(run_id=projected_run.id, stage=stage, status="awaiting_review")
        step.status = "awaiting_review"
        step.started_at = step.started_at or datetime.datetime.utcnow()
        step.completed_at = None
        step.output_json = {"interrupt": dict(payload)}
        step.error_message = None
        db.add_all([step, projected_run])
        db.commit()
        db.refresh(projected_run)
        return projected_run


class LangGraphRunService:
    @staticmethod
    def quality_assessment_projection(report: dict[str, Any]) -> dict[str, Any]:
        """Expose the TASK-12.2 bounded report projector for future QA nodes.

        TASK-12.2 intentionally does not add a graph node.  Keeping this
        entry point on the production run service ensures the later node and
        checkpoint rebuild use exactly the persistence serialization.
        """
        from src.schemas.lg12_quality_report import quality_assessment_projection

        return quality_assessment_projection(report)

    """Start, inspect and safely control the LG-1 durable test graph."""

    @staticmethod
    def _find_run(run_id: str, workspace_id: str, db: Session, *, lock: bool = False) -> AgentRun:
        query = db.query(AgentRun).filter(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace_id,
        )
        if lock:
            query = query.with_for_update()
        run = query.first()
        if run is None:
            raise GraphRunNotFound(f"AgentRun not found: {run_id}")
        return run

    @staticmethod
    def _thread_id(run: AgentRun) -> str:
        if run.graph_thread_id and run.graph_thread_id != run.id:
            raise ValueError("AgentRun graph thread contract is invalid.")
        return run.id

    @staticmethod
    def _config(thread_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": thread_id}}

    @staticmethod
    def _compiled_graph(checkpointer: Any, *, run: AgentRun | None = None) -> Any:
        """Use the migrated graph for the explicit LangGraph rollout."""
        if run is not None and run.mode == "lg12i_intake":
            return build_lg12i_intake_compiled_graph(checkpointer=checkpointer)
        if run is not None and run.mode == "lg11_edit":
            return build_lg11_compiled_graph(checkpointer=checkpointer)
        if not langgraph_runtime_enabled():
            return build_lg1_compiled_graph(checkpointer=checkpointer)
        builder = build_lg10_compiled_graph
        if build_lg5_compiled_graph is not _UNPATCHED_LG5_GRAPH_BUILDER:
            builder = build_lg5_compiled_graph
        return builder(checkpointer=checkpointer)

    @classmethod
    def _mark_execution_failed(
        cls,
        run_id: str,
        db: Session,
        error: Exception,
    ) -> AgentRun:
        """Persist a recoverable graph failure without moving current_stage."""

        db.rollback()
        run = db.query(AgentRun).filter(AgentRun.id == run_id).with_for_update().one()
        if run.status == "cancelled":
            return run
        now = datetime.datetime.utcnow()
        failure = _failure_contract(error, run.current_stage or "bootstrap_run")
        stage = str(failure["stage"])
        run.status = "failed"
        run.current_stage = stage
        run.completed_at = None
        run.error_log = [
            *(run.error_log or []),
            failure,
        ]
        step = (
            db.query(AgentRunStep)
            .filter(AgentRunStep.run_id == run.id, AgentRunStep.stage == stage)
            .first()
        )
        if step is None:
            step = AgentRunStep(run_id=run.id, stage=stage, status="failed")
        step.status = "failed"
        step.started_at = step.started_at or now
        step.completed_at = now
        step.error_message = str(error)
        db.add(step)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    @classmethod
    def _rebuild_projection_from_history(
        cls,
        run: AgentRun,
        db: Session,
        graph: Any,
        config: dict[str, dict[str, str]],
        *,
        checkpoint_authoritative: bool = False,
    ) -> AgentRun:
        """Repair missed operational projections before a resumed execution.

        A checkpoint can be committed before the API process dies during its
        SQL projection. Replaying durable node-completed events is idempotent
        because the projector upserts one step per stage.
        """

        # An LG-12I checkpoint is the durable source of truth.  In the rare
        # inverse ordering (a SQL projection was written but its checkpoint
        # was not), do not merge that newer-looking SQL state back into the
        # graph.  Clear only this graph's operational projection and replay
        # durable history.  Domain version rows remain immutable and are never
        # recreated by this repair.
        if checkpoint_authoritative and run.mode == "lg12i_intake":
            run = cls._reset_lg12i_projection(run, db)

        snapshots = list(graph.get_state_history(config))
        for snapshot in reversed(snapshots):
            events = list((snapshot.values or {}).get("events") or [])
            if events:
                # A Discovery checkpoint may contain a safe state delta that
                # reached PostgreSQL before this SQL projection. Replaying it
                # restores the operational summary too; raw fact payloads are
                # absent from the state by contract.
                run = AgentRunGraphProjector.apply_node_update(
                    run,
                    db,
                    {
                        "events": [events[-1]],
                        "discovery": dict((snapshot.values or {}).get("discovery") or {}),
                        "commerce": dict((snapshot.values or {}).get("commerce") or {}),
                        "intake": dict((snapshot.values or {}).get("intake") or {}),
                        "generation": dict((snapshot.values or {}).get("generation") or {}),
                        "page_assembly": dict((snapshot.values or {}).get("page_assembly") or {}),
                        "rendering": dict((snapshot.values or {}).get("rendering") or {}),
                        "quality": dict((snapshot.values or {}).get("quality") or {}),
                        "edit": dict((snapshot.values or {}).get("edit") or {}),
                        "canvas": dict((snapshot.values or {}).get("canvas") or {}),
                    },
                )
        snapshot = graph.get_state(config)
        interrupt_payload = cls._interrupt_payload(snapshot)
        if interrupt_payload is not None:
            run = AgentRunGraphProjector.apply_interrupt_wait(run, db, interrupt_payload)
        if run.mode == "lg12i_intake":
            run = cls._apply_lg12i_checkpoint_projection(run, db, snapshot)
        return run

    @staticmethod
    def _lg12i_checkpoint_signature(snapshot: Any) -> dict[str, Any] | None:
        """Return the bounded LG-12I state that is safe to mirror to SQL.

        ``intake`` intentionally contains only immutable identities and
        compact provenance summaries.  Raw source/OCR/image payloads are
        rejected by the adapters before they enter graph state.
        """

        values = dict(getattr(snapshot, "values", {}) or {})
        intake = values.get("intake")
        if not isinstance(intake, dict):
            return None
        interrupt = LangGraphRunService._interrupt_payload(snapshot)
        stage = str(
            (interrupt or {}).get("review_stage")
            or values.get("current_stage")
            or ""
        )
        status = "awaiting_review" if interrupt is not None else str(values.get("status") or "")
        if not stage or status not in {"running", "completed", "awaiting_review"}:
            return None
        checkpoint_id = (
            (dict(getattr(snapshot, "config", {}) or {}).get("configurable") or {})
            .get("checkpoint_id")
        )
        events = list(values.get("events") or [])
        return {
            "intake": copy.deepcopy(intake),
            "stage": stage,
            "status": status,
            "interrupt": copy.deepcopy(interrupt) if interrupt is not None else None,
            "checkpoint_id": str(checkpoint_id or ""),
            "last_event": copy.deepcopy(events[-1]) if events and isinstance(events[-1], dict) else None,
        }

    @classmethod
    def _lg12i_projection_is_current(cls, run: AgentRun, snapshot: Any) -> bool:
        expected = cls._lg12i_checkpoint_signature(snapshot)
        if expected is None:
            return True
        outputs = dict(run.outputs_json or {})
        pending = dict((dict(outputs.get("langgraph_review") or {}).get("pending") or {}))
        expected_pending = dict(expected["interrupt"] or {})
        return (
            dict(outputs.get("langgraph_intake") or {}) == expected["intake"]
            and run.current_stage == expected["stage"]
            and run.status == expected["status"]
            and pending == expected_pending
            and str(run.graph_checkpoint_id or "") == expected["checkpoint_id"]
        )

    @staticmethod
    def _reset_lg12i_projection(run: AgentRun, db: Session) -> AgentRun:
        """Discard only stale LG-12I operational projection data.

        AgentRunStep is a derived projection, unlike the immutable source,
        truth, confirmation, Brief and Master rows.  Clearing it before a
        durable-history replay prevents SQL-only future stages from surviving
        a checkpoint-authoritative rebuild.
        """

        projected = db.query(AgentRun).filter(AgentRun.id == run.id).with_for_update().one()
        outputs = dict(projected.outputs_json or {})
        for key in ("langgraph_intake", "langgraph_review", "langgraph_runtime"):
            outputs.pop(key, None)
        projected.outputs_json = outputs
        projected.current_stage = "unified_intake_router"
        projected.status = "running"
        projected.completed_at = None
        db.query(AgentRunStep).filter(AgentRunStep.run_id == projected.id).delete(
            synchronize_session=False,
        )
        db.add(projected)
        db.commit()
        db.refresh(projected)
        return projected

    @staticmethod
    def _apply_lg12i_checkpoint_projection(run: AgentRun, db: Session, snapshot: Any) -> AgentRun:
        """Finish an LG-12I projection from the latest durable checkpoint.

        This same helper is called after normal history replay and after a
        checkpoint-before-projection recovery, preventing the two paths from
        drifting on stage/status or the bounded intake identity.
        """

        expected = LangGraphRunService._lg12i_checkpoint_signature(snapshot)
        if expected is None:
            return run
        projected = db.query(AgentRun).filter(AgentRun.id == run.id).with_for_update().one()
        outputs = dict(projected.outputs_json or {})
        outputs["langgraph_intake"] = expected["intake"]
        runtime = dict(outputs.get("langgraph_runtime") or {})
        runtime.update(
            {
                "thread_id": projected.graph_thread_id,
                "last_stage": expected["stage"],
            }
        )
        if expected["last_event"] is not None:
            runtime["last_event"] = expected["last_event"]
        outputs["langgraph_runtime"] = runtime
        projected.outputs_json = outputs
        projected.current_stage = expected["stage"]
        projected.status = expected["status"]
        projected.completed_at = (
            datetime.datetime.utcnow() if expected["status"] == "completed" else None
        )
        projected.graph_checkpoint_id = expected["checkpoint_id"] or None
        db.add(projected)
        db.commit()
        db.refresh(projected)
        return projected

    @classmethod
    def _recover_running_lg11_projection(cls, run: AgentRun, db: Session) -> AgentRun:
        """Recover only an LG-11 SQL projection that lags its durable checkpoint.

        A normal in-flight run still owns its execution lease.  We replay
        history only when the checkpoint has edit/interrupt state that is
        absent or different in the durable projection, so browser retries do
        not repeatedly project a healthy run.
        """

        if run.mode != "lg11_edit" or run.status != "running" or not run.graph_thread_id:
            return run
        config = cls._config(cls._thread_id(run))
        with open_postgres_checkpointer() as checkpointer:
            graph = cls._compiled_graph(checkpointer, run=run)
            snapshot = graph.get_state(config)
            checkpoint_edit = dict((snapshot.values or {}).get("edit") or {})
            checkpoint_pending = cls._interrupt_payload(snapshot)
            projected_outputs = dict(run.outputs_json or {})
            projected_edit = dict(projected_outputs.get("langgraph_edit") or {})
            projected_pending = dict(
                (dict(projected_outputs.get("langgraph_review") or {}).get("pending") or {})
            )
            checkpoint_canvas = dict((snapshot.values or {}).get("canvas") or {})
            projected_canvas = dict(projected_outputs.get("langgraph_canvas") or {})
            stale = (
                bool(checkpoint_edit) and projected_edit != checkpoint_edit
            ) or (
                checkpoint_pending is not None and projected_pending != checkpoint_pending
            ) or (
                bool(checkpoint_canvas) and projected_canvas != checkpoint_canvas
            )
            if not stale:
                return run
            run = cls._rebuild_projection_from_history(run, db, graph, config)
            # A checkpoint can be interrupted after its node update but before
            # the interrupt projection. Rebuild both halves so public resume
            # exposes the same durable canvas/edit review state after restart.
            restored_pending = cls._interrupt_payload(snapshot)
            if restored_pending is not None:
                run = AgentRunGraphProjector.apply_interrupt_wait(run, db, restored_pending)
            run.graph_checkpoint_id = (
                (snapshot.config.get("configurable") or {}).get("checkpoint_id")
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            return run

    @classmethod
    def _recover_running_lg12i_projection(cls, run: AgentRun, db: Session) -> AgentRun:
        """Repair an LG-12I projection from its durable checkpoint.

        Unlike normal in-flight SQL state, a persisted checkpoint is also
        authoritative when it is older than a speculative SQL projection.
        That asymmetric rule keeps restart recovery from inventing graph state
        out of a projection that LangGraph never durably committed.
        """

        if (
            run.mode != "lg12i_intake"
            or run.status == "cancelled"
            or not run.graph_thread_id
        ):
            return run
        config = cls._config(cls._thread_id(run))
        with open_postgres_checkpointer() as checkpointer:
            graph = cls._compiled_graph(checkpointer, run=run)
            snapshot = graph.get_state(config)
            if cls._lg12i_projection_is_current(run, snapshot):
                return run
            run = cls._rebuild_projection_from_history(
                run,
                db,
                graph,
                config,
                checkpoint_authoritative=True,
            )
            return run

    @classmethod
    def _recover_running_projection(cls, run: AgentRun, db: Session) -> AgentRun:
        if run.mode == "lg11_edit":
            return cls._recover_running_lg11_projection(run, db)
        if run.mode == "lg12i_intake":
            return cls._recover_running_lg12i_projection(run, db)
        # TASK-12.9 extends the ordinary production LG-10 graph.  When a
        # process stops between checkpoint commit and SQL projection, recover
        # the compact QA route/attempt state from history before returning a
        # running lease.  This never replays a provider call: graph history is
        # projected only, while the provider path has its own LG-9 keys.
        # A process can die immediately after the checkpoint saver commits a
        # node update but before this service projects that update to SQL.  The
        # execution wrapper records that transport failure as ``failed``;
        # recovery must still treat the durable checkpoint as authoritative for
        # the compact TASK-12.9 QA state.  This remains projection-only: it
        # never invokes a graph node or resumes a provider/review action.
        if run.status in {"running", "failed"} and run.graph_thread_id:
            config = cls._config(cls._thread_id(run))
            with open_postgres_checkpointer() as checkpointer:
                graph = cls._compiled_graph(checkpointer, run=run)
                snapshot = graph.get_state(config)
                checkpoint_quality = dict((snapshot.values or {}).get("quality") or {})
                projected_quality = dict((run.outputs_json or {}).get("langgraph_quality") or {})
                pending = cls._interrupt_payload(snapshot)
                projected_pending = dict(
                    (dict((run.outputs_json or {}).get("langgraph_review") or {}).get("pending") or {})
                )
                if (
                    checkpoint_quality and checkpoint_quality != projected_quality
                ) or (pending is not None and projected_pending != pending):
                    return cls._rebuild_projection_from_history(run, db, graph, config)
        return run

    @staticmethod
    def _supports_explicit_checkpoint_recovery(run: AgentRun) -> bool:
        """Return only production graph modes with a durable recovery contract.

        ``mode='recover'`` is deliberately not a generic retry switch.  These
        are the compiled graph modes whose checkpoint/history projection can be
        rebuilt without delivering a LangGraph ``Command(resume=...)``.
        """

        return bool(run.graph_thread_id) and str(run.mode or "") in {
            "mock", "real", "lg11_edit", "lg12i_intake",
        }

    @classmethod
    def _execute(
        cls,
        run: AgentRun,
        db: Session,
        *,
        initial_state: dict[str, Any] | None,
        rebuild_projection: bool,
        resume_payload: dict[str, Any] | None = None,
        continuation_after: str | None = None,
    ) -> AgentRun:
        thread_id = cls._thread_id(run)
        config = cls._config(thread_id)
        try:
            with open_postgres_checkpointer() as checkpointer:
                graph = cls._compiled_graph(checkpointer, run=run)
                if rebuild_projection:
                    run = cls._rebuild_projection_from_history(run, db, graph, config)
                    restored = graph.get_state(config)
                    if continuation_after == "seller_confirmation":
                        # A prerequisite can be supplied after a terminal
                        # fail-closed Brief block (for example a project Brand
                        # Kit).  Resume only from the frozen confirmation
                        # checkpoint: Source, Truth and Confirmation are
                        # already immutable and must never be replayed.
                        values = dict(restored.values or {})
                        intake = dict(values.get("intake") or {})
                        brief = dict(intake.get("creative_brief") or {})
                        if (
                            str(values.get("current_stage") or "") != "creative_brief_blocked"
                            or str(brief.get("reason") or "") != "brand_kit_missing"
                        ):
                            raise GraphRunResumeUnavailable(
                                "This LG-12I run is not blocked on a recoverable Brand Kit prerequisite."
                            )
                        intake["next_action"] = "product_creative_brief"
                        graph.update_state(
                            config,
                            {"current_stage": "confirmation_ready", "status": "running", "intake": intake},
                            as_node="seller_confirmation",
                        )
                        restored = graph.get_state(config)
                    if not restored.next and resume_payload is None:
                        # The final checkpoint may have committed just before a
                        # process crash. Repair its projection without rerunning
                        # any node. A versioned review response must still be
                        # delivered through Command(resume=...), because a node
                        # that re-interrupted after validation may expose no
                        # conventional ``next`` entry while remaining resumable.
                        run.graph_checkpoint_id = (
                            (restored.config.get("configurable") or {}).get("checkpoint_id")
                        )
                        db.add(run)
                        db.commit()
                        db.refresh(run)
                        return run

                # Domain nodes use this request-scoped transaction for their
                # artifact/fact-board writes. The Session never enters graph
                # state; it only makes each node and its SQL projection one
                # atomic unit.
                from src.services.langgraph_discovery_service import langgraph_execution_session

                with langgraph_execution_session(db):
                    from langgraph.types import Command

                    graph_input: Any = Command(resume=resume_payload) if resume_payload is not None else initial_state
                    for update in graph.stream(
                        graph_input,
                        config=config,
                        stream_mode="updates",
                    ):
                        for node_name, node_update in update.items():
                            # LangGraph emits interrupt records separately from
                            # node deltas. They are projected after get_state.
                            if node_name == "__interrupt__" or not isinstance(node_update, dict):
                                continue
                            run = AgentRunGraphProjector.apply_node_update(run, db, node_update)

                snapshot = graph.get_state(config)
                checkpoint_id = (snapshot.config.get("configurable") or {}).get("checkpoint_id")
                interrupt_payload = cls._interrupt_payload(snapshot)
                if interrupt_payload is not None:
                    run = AgentRunGraphProjector.apply_interrupt_wait(run, db, interrupt_payload)
                if run.mode == "lg12i_intake":
                    run = cls._apply_lg12i_checkpoint_projection(run, db, snapshot)
                else:
                    run.graph_checkpoint_id = checkpoint_id
                    db.add(run)
                    db.commit()
                    db.refresh(run)
                return run
        except GraphRunCancelled:
            db.rollback()
            return db.query(AgentRun).filter(AgentRun.id == run.id).one()
        except Exception as error:
            logger.exception("LangGraph execution failed for run %s at stage %s", run.id, run.current_stage)
            failed_run = cls._mark_execution_failed(run.id, db, error)
            if failed_run.status == "cancelled":
                return failed_run
            raise GraphRunExecutionFailed(
                "LangGraph execution failed. Resume the same run after resolving the cause."
            ) from error

    @staticmethod
    def _interrupt_payload(snapshot: Any) -> dict[str, Any] | None:
        """Read the first durable LangGraph interrupt without relying on UI data."""

        for task in getattr(snapshot, "tasks", ()) or ():
            for item in getattr(task, "interrupts", ()) or ():
                value = getattr(item, "value", item)
                if isinstance(value, dict) and value.get("review_stage"):
                    return dict(value)
        return None

    @classmethod
    def start(cls, run_id: str, workspace_id: str, db: Session) -> AgentRun:
        run = cls._find_run(run_id, workspace_id, db)
        if run.status == "cancelled":
            raise GraphRunCancelled("Cancelled graph runs cannot be started again.")
        # Public start is also a read/recovery entrypoint for LG-12I.  A
        # process can die after checkpoint commit while the run row still says
        # completed/running at an earlier stage.
        if run.mode == "lg12i_intake" and run.graph_thread_id:
            run = cls._recover_running_lg12i_projection(run, db)
            if run.status == "awaiting_review":
                # ``/start`` is idempotent for an already-persisted seller
                # interrupt.  It is a recovery read, not an attempt to claim
                # a new execution lease or create another confirmation cycle.
                return run
        if run.status == "completed":
            # A browser retry must be a read, never a second thread or a second
            # set of projection rows.
            return run
        if run.status == "running":
            # The first caller usually owns the execution lease. An LG-11
            # checkpoint may nevertheless be newer than its SQL projection if
            # the process stopped after the checkpoint commit; repair only
            # that stale projection before returning the same run.
            return cls._recover_running_projection(run, db)
        if run.status == "failed":
            raise GraphRunResumeRequired("This graph run failed; resume the same thread instead of starting again.")

        thread_id = cls._thread_id(run)
        # Claim execution with a conditional update rather than relying solely
        # on a row lock. This remains correct on PostgreSQL and protects local
        # SQLite/test environments where SELECT FOR UPDATE is a no-op.
        claimed = (
            db.query(AgentRun)
            .filter(
                AgentRun.id == run.id,
                AgentRun.workspace_id == workspace_id,
                AgentRun.status == "created",
            )
            .update(
                {
                    AgentRun.status: "running",
                    AgentRun.graph_thread_id: thread_id,
                    AgentRun.graph_checkpoint_id: None,
                    AgentRun.completed_at: None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if claimed != 1:
            # Another caller acquired the lease while this request was reading
            # the run. It must never start a second graph execution.
            run = cls._find_run(run_id, workspace_id, db)
            if run.status in {"running", "completed"}:
                return run
            if run.status == "cancelled":
                raise GraphRunCancelled("Cancelled graph runs cannot be started again.")
            if run.status == "failed":
                raise GraphRunResumeRequired("This graph run failed; resume the same thread instead of starting again.")
            raise ValueError("Could not acquire the graph execution lease.")
        run = cls._find_run(run_id, workspace_id, db)

        if run.mode == "lg11_edit":
            initial_state = build_lg11_edit_graph_input(
                run_id=run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                edit=dict((run.input_snapshot or {}).get("lg11_edit") or {}),
            )
        elif run.mode == "lg12i_intake":
            initial_state = build_lg12i_intake_graph_input(
                run_id=run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                intake_envelope=dict((run.input_snapshot or {}).get("unified_product_intake") or {}),
            )
        else:
            initial_state = build_lg1_graph_input(
                run_id=run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                mode=run.mode,
                input_snapshot=run.input_snapshot or {},
            )

        return cls._execute(
            run,
            db,
            initial_state=initial_state,
            rebuild_projection=False,
        )

    @classmethod
    def start_unified_product_intake(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        actor_id: str,
        request: dict[str, Any],
        db: Session,
    ) -> AgentRun:
        """Create or reuse one LG-12I intake thread, then use normal start.

        This is deliberately only a run-envelope boundary.  It neither fetches
        sources nor creates a ProductSourceSnapshotVersion; later adapter
        tasks receive the persisted command from the compiled graph state.
        """

        from src.services.product_intake_version_service import (
            UNIFIED_PRODUCT_INTAKE_SCHEMA_VERSION,
            canonical_unified_intake_input_hash,
            validate_photo_only_asset_eligibility,
            validate_owned_product_url_capture_request_reference,
            validate_unified_product_intake_envelope,
        )

        project = (
            db.query(ProductProject)
            .filter(ProductProject.id == project_id, ProductProject.workspace_id == workspace_id)
            .with_for_update()
            .one_or_none()
        )
        if project is None:
            raise GraphRunNotFound("Product project was not found in this workspace.")
        base_envelope = {
            "schema_version": UNIFIED_PRODUCT_INTAKE_SCHEMA_VERSION,
            "project_id": project_id,
            "input_mode": request.get("input_mode"),
            "source_payload_refs": list(request.get("source_payload_refs") or []),
            "requested_generation_mode": request.get("requested_generation_mode"),
            "target_channels": list(request.get("target_channels") or []),
            "actor_workspace_identity": {
                "actor_id": actor_id,
                "workspace_id": workspace_id,
            },
            # These values are deliberately excluded from the input hash.
            "run_identity": {"run_id": "pending", "thread_id": "pending"},
            "created_at": "pending",
        }
        base_envelope["input_hash"] = canonical_unified_intake_input_hash(base_envelope)
        # Validate the caller's source references before allocating an AgentRun.
        base_envelope = validate_unified_product_intake_envelope(base_envelope)
        if base_envelope["input_mode"] == "owned_product_url":
            # Reject a tampered/non-owned reference before it reaches the
            # graph.  Remote capture itself remains the adapter's job.
            validate_owned_product_url_capture_request_reference(
                db,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_id=actor_id,
                source_refs=base_envelope["source_payload_refs"],
            )
        if base_envelope["input_mode"] == "photo_only":
            # The picker and adapter share one persisted provenance/rights/hash
            # gate; a caller label cannot make supplier/reference bytes eligible.
            source_refs = list(base_envelope["source_payload_refs"])
            assets = {
                str(asset.id): asset
                for asset in db.query(Asset).filter(
                    Asset.project_id == project_id,
                    Asset.id.in_([str(item["id"]) for item in source_refs]),
                ).all()
            }
            for reference in source_refs:
                validate_photo_only_asset_eligibility(
                    db,
                    asset=assets.get(str(reference["id"])),
                    reference=reference,
                    project_id=project_id,
                )

        # Reuse the existing AgentRun start/idempotency behavior. JSON lookup
        # stays portable across the supported SQL dialects; this candidate set
        # is scoped by project/workspace/mode and contains only compact runs.
        existing_runs = (
            db.query(AgentRun)
            .filter(
                AgentRun.project_id == project_id,
                AgentRun.workspace_id == workspace_id,
                AgentRun.mode == "lg12i_intake",
            )
            .order_by(AgentRun.created_at.desc())
            .all()
        )
        for existing in existing_runs:
            stored = dict((existing.input_snapshot or {}).get("unified_product_intake") or {})
            if stored.get("input_hash") == base_envelope["input_hash"]:
                if existing.status == "created":
                    return cls.start(existing.id, workspace_id, db)
                return existing

        run_id = str(uuid.uuid4())
        envelope = {
            **base_envelope,
            "run_identity": {"run_id": run_id, "thread_id": run_id},
            "created_at": datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        envelope = validate_unified_product_intake_envelope(envelope)
        run = AgentRun(
            id=run_id,
            workspace_id=workspace_id,
            project_id=project_id,
            mode="lg12i_intake",
            status="created",
            current_stage="unified_intake_router",
            input_snapshot={"unified_product_intake": envelope},
            outputs_json={},
            cost_approval_status="not_required",
            created_by=actor_id,
        )
        db.add(run)
        db.commit()
        return cls.start(run.id, workspace_id, db)

    @classmethod
    def get_state(cls, run_id: str, workspace_id: str, db: Session) -> GraphRunStateView:
        run = cls._find_run(run_id, workspace_id, db)
        if run.mode == "lg12i_intake" and run.graph_thread_id:
            run = cls._recover_running_lg12i_projection(run, db)
        thread_id = cls._thread_id(run)
        if not run.graph_thread_id:
            return GraphRunStateView(
                run_id=run.id,
                thread_id=thread_id,
                status=run.status,
                current_stage=run.current_stage,
                checkpoint_id=None,
                values={"execution": _execution_view(run)},
                next_nodes=[],
            )
        with open_postgres_checkpointer() as checkpointer:
            graph = cls._compiled_graph(checkpointer, run=run)
            snapshot = graph.get_state(cls._config(thread_id))
        checkpoint_id = (snapshot.config.get("configurable") or {}).get("checkpoint_id")
        return GraphRunStateView(
            run_id=run.id,
            thread_id=thread_id,
            status=run.status,
            current_stage=run.current_stage,
            checkpoint_id=checkpoint_id,
            values=_browser_checkpoint_values(run, snapshot),
            next_nodes=list(snapshot.next or ()),
        )

    @classmethod
    def history(cls, run_id: str, workspace_id: str, db: Session) -> list[GraphRunStateView]:
        run = cls._find_run(run_id, workspace_id, db)
        if run.mode == "lg12i_intake" and run.graph_thread_id:
            run = cls._recover_running_lg12i_projection(run, db)
        if not run.graph_thread_id:
            return []
        with open_postgres_checkpointer() as checkpointer:
            graph = cls._compiled_graph(checkpointer, run=run)
            snapshots = list(graph.get_state_history(cls._config(run.graph_thread_id)))
        return [
            GraphRunStateView(
                run_id=run.id,
                thread_id=run.graph_thread_id,
                status=str((snapshot.values or {}).get("status") or run.status),
                current_stage=str((snapshot.values or {}).get("current_stage") or run.current_stage),
                checkpoint_id=(snapshot.config.get("configurable") or {}).get("checkpoint_id"),
                values=dict(snapshot.values or {}),
                next_nodes=list(snapshot.next or ()),
            )
            for snapshot in snapshots
        ]

    @classmethod
    def cancel(cls, run_id: str, workspace_id: str, db: Session) -> AgentRun:
        run = cls._find_run(run_id, workspace_id, db, lock=True)
        if run.status == "completed":
            return run
        run.status = "cancelled"
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    @classmethod
    def resume(
        cls,
        run_id: str,
        workspace_id: str,
        db: Session,
        *,
        thread_id: str | None = None,
        resume_payload: dict[str, Any] | None = None,
        recovery_only: bool = False,
        continue_after_prerequisite: bool = False,
        actor_id: str | None = None,
    ) -> AgentRun:
        run = cls._find_run(run_id, workspace_id, db)
        if thread_id is not None and thread_id != cls._thread_id(run):
            raise GraphRunThreadMismatch("Resume thread_id does not match this AgentRun.")
        if run.status == "cancelled":
            raise GraphRunCancelled("Cancelled graph runs cannot be resumed.")
        if continue_after_prerequisite:
            if resume_payload is not None:
                raise GraphRunReviewRequired("Prerequisite continuation does not accept a seller response.")
            if run.mode != "lg12i_intake" or not run.graph_thread_id:
                raise GraphRunResumeUnavailable("This graph run has no continuable LG-12I checkpoint.")
            expected_actor = _seller_confirmation_actor_for_run(run)
            if not actor_id or actor_id != expected_actor:
                raise GraphRunReviewRequired("Only the actor that started this intake run may continue after a prerequisite is fixed.")
            # The checkpoint/history is authoritative before deciding whether
            # the only allowed terminal block can continue.
            run = cls._recover_running_lg12i_projection(run, db)
            intake = dict((run.outputs_json or {}).get("langgraph_intake") or {})
            brief = dict(intake.get("creative_brief") or {})
            if run.status == "completed" and run.current_stage == "master_ready":
                return run
            if (
                run.status != "completed"
                or run.current_stage != "creative_brief_blocked"
                or brief.get("reason") != "brand_kit_missing"
            ):
                raise GraphRunResumeUnavailable(
                    "Only a completed LG-12I Brand Kit prerequisite block may continue."
                )
            # Validate the currently persisted project-scoped/global Brand Kit
            # before claiming the graph.  The compiler repeats the exact scope
            # validation while compiling the immutable Brief.
            from src.services.brand_kit_service import resolved_project_version
            from src.services.product_intake_version_service import validate_lg12i_brand_kit_scope

            kit = resolved_project_version(db, run.workspace_id, run.project_id)
            validate_lg12i_brand_kit_scope(
                kit, workspace_id=run.workspace_id, project_id=run.project_id,
            )
            claimed = (
                db.query(AgentRun)
                .filter(
                    AgentRun.id == run.id,
                    AgentRun.workspace_id == workspace_id,
                    AgentRun.status == "completed",
                    AgentRun.current_stage == "creative_brief_blocked",
                )
                .update({AgentRun.status: "running"}, synchronize_session=False)
            )
            db.commit()
            if claimed != 1:
                run = cls._find_run(run_id, workspace_id, db)
                if run.status in {"running", "completed"}:
                    return run
                raise GraphRunResumeUnavailable("Could not claim the LG-12I prerequisite continuation.")
            run = cls._find_run(run_id, workspace_id, db)
            return cls._execute(
                run,
                db,
                initial_state=None,
                rebuild_projection=True,
                continuation_after="seller_confirmation",
            )
        if recovery_only:
            if resume_payload is not None:
                raise GraphRunReviewRequired("Checkpoint recovery does not accept a seller response.")
            if not cls._supports_explicit_checkpoint_recovery(run):
                raise GraphRunResumeUnavailable("This graph run has no supported checkpoint-only recovery contract.")
            if run.mode == "lg12i_intake":
                expected_actor = _seller_confirmation_actor_for_run(run)
                if not actor_id or actor_id != expected_actor:
                    raise GraphRunReviewRequired("Only the actor that started this intake run may recover its checkpoint.")
            # This path only reads checkpoint/history and mirrors the durable
            # projection.  It never delivers Command(resume=...), so it cannot
            # approve cost, enqueue an outbox record, or advance a business
            # node.  LG-11 uses the same recovery boundary for a pending cost
            # interrupt as LG-12I uses for seller confirmation.
            run = cls._recover_running_projection(run, db)
            return run
        seller_confirmation_response = _seller_confirmation_resume_response(resume_payload)
        if run.status == "completed":
            if seller_confirmation_response is not None:
                if not _seller_confirmation_replay(
                    db, run=run, actor_id=actor_id, response=seller_confirmation_response,
                ):
                    raise GraphRunReviewRequired("Seller confirmation response does not match a persisted confirmation cycle.")
            return run
        recovered_from_running = run.status == "running"
        if recovered_from_running:
            run = cls._recover_running_projection(run, db)
            if run.status == "running":
                return run
        if not run.graph_thread_id:
            raise GraphRunResumeUnavailable("This graph run has no checkpoint to resume.")
        is_review_resume = run.status == "awaiting_review"
        if is_review_resume:
            pending = ((run.outputs_json or {}).get("langgraph_review") or {}).get("pending")
            if not pending:
                raise GraphRunReviewRequired("This graph run has no persisted seller-review interrupt.")
            if resume_payload is None:
                raise GraphRunReviewRequired("A versioned review response is required to resume this graph run.")
            from src.services.langgraph_review_service import validate_resume_against_interrupt

            if seller_confirmation_response is not None and _seller_confirmation_replay(
                db, run=run, actor_id=actor_id, response=seller_confirmation_response,
            ):
                # The first request has already written an immutable cycle and
                # advanced the checkpoint.  Return its current durable state;
                # never feed the stale response into the next interrupt.
                return run
            try:
                validate_resume_against_interrupt(resume_payload, pending)
            except ValueError as error:
                raise GraphRunReviewRequired(str(error)) from error
            if pending.get("review_stage") == "seller_confirmation":
                expected_actor = _seller_confirmation_actor_for_run(run)
                if not actor_id or actor_id != expected_actor:
                    raise GraphRunReviewRequired("Only the actor that started this intake run may submit seller confirmation.")
                from src.services.product_intake_version_service import (
                    SellerConfirmationContractError,
                    validate_seller_confirmation_answers,
                )

                try:
                    confirmation_plan = dict(
                        dict((pending.get("context") or {}).get("seller_confirmation") or {})
                    )
                    validate_seller_confirmation_answers(
                        plan=confirmation_plan,
                        answers=list((seller_confirmation_response or {}).get("confirmation_answers") or []),
                    )
                except SellerConfirmationContractError as error:
                    raise GraphRunReviewRequired(str(error)) from error
        elif resume_payload is not None:
            raise GraphRunReviewRequired("This graph run is not waiting for a seller-review response.")
        claimed = (
            db.query(AgentRun)
            .filter(
                AgentRun.id == run.id,
                AgentRun.workspace_id == workspace_id,
                AgentRun.status == ("awaiting_review" if is_review_resume else "failed"),
            )
            .update({AgentRun.status: "running"}, synchronize_session=False)
        )
        db.commit()
        if claimed != 1:
            run = cls._find_run(run_id, workspace_id, db)
            if run.status in {"running", "completed"}:
                return run
            if run.status == "cancelled":
                raise GraphRunCancelled("Cancelled graph runs cannot be resumed.")
            raise ValueError("Could not acquire the graph resume lease.")
        run = cls._find_run(run_id, workspace_id, db)
        return cls._execute(
            run,
            db,
            initial_state=None,
            rebuild_projection=True,
            resume_payload=resume_payload,
        )

    @classmethod
    def resume_provider_wait(cls, run_id: str) -> AgentRun | None:
        """Internal worker callback for an LG-5 provider completion.

        The callback has no browser/session authority. It can resume only the
        matching persisted ``provider_wait`` interrupt and only with the fixed
        `refresh` payload; seller approval stages still require the public
        authenticated endpoint and a versioned seller response.
        """

        from src.db.database import SessionLocal

        db = SessionLocal()
        try:
            run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
            if run is None or run.status != "awaiting_review":
                return run
            pending = ((run.outputs_json or {}).get("langgraph_review") or {}).get("pending") or {}
            if pending.get("review_stage") != "provider_wait":
                return run
            return cls.resume(
                run_id,
                run.workspace_id,
                db,
                thread_id=run.graph_thread_id or run.id,
                resume_payload={"schema_version": "lg5-v1", "review_stage": "provider_wait", "decision": "refresh"},
            )
        finally:
            db.close()
