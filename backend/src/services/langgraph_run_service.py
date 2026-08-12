"""LG-1 durable LangGraph run service.

This service owns the bridge between a LangGraph checkpoint thread and the
existing ``AgentRun`` / ``AgentRunStep`` operational projection.  It does not
replace the legacy 11-agent execution path yet; LG-2 through LG-6 migrate the
domain nodes one subgraph at a time.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.agents.langgraph_runtime import (
    build_lg8_compiled_graph,
    build_lg10_compiled_graph,
    build_lg7_compiled_graph,
    build_lg6_compiled_graph,
    build_lg5_compiled_graph,
    build_lg4_compiled_graph,
    build_lg3_compiled_graph,
    build_lg1_compiled_graph,
    build_lg1_graph_input,
    langgraph_runtime_enabled,
    open_postgres_checkpointer,
)

# LG-2~LG-5 regression harnesses replace this long-lived injection seam with
# their stage-specific graph.  Keep that contract while LG-6 remains the
# production graph selected below.
_UNPATCHED_LG5_GRAPH_BUILDER = build_lg5_compiled_graph
from src.db.models import AgentRun, AgentRunStep


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
    def _compiled_graph(checkpointer: Any) -> Any:
        """Use the migrated graph for the explicit LangGraph rollout."""
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
    ) -> AgentRun:
        """Repair missed operational projections before a resumed execution.

        A checkpoint can be committed before the API process dies during its
        SQL projection. Replaying durable node-completed events is idempotent
        because the projector upserts one step per stage.
        """

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
                        "generation": dict((snapshot.values or {}).get("generation") or {}),
                        "page_assembly": dict((snapshot.values or {}).get("page_assembly") or {}),
                        "rendering": dict((snapshot.values or {}).get("rendering") or {}),
                    },
                )
        return run

    @classmethod
    def _execute(
        cls,
        run: AgentRun,
        db: Session,
        *,
        initial_state: dict[str, Any] | None,
        rebuild_projection: bool,
        resume_payload: dict[str, Any] | None = None,
    ) -> AgentRun:
        thread_id = cls._thread_id(run)
        config = cls._config(thread_id)
        try:
            with open_postgres_checkpointer() as checkpointer:
                graph = cls._compiled_graph(checkpointer)
                if rebuild_projection:
                    run = cls._rebuild_projection_from_history(run, db, graph, config)
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
        if run.status == "completed":
            # A browser retry must be a read, never a second thread or a second
            # set of projection rows.
            return run
        if run.status == "running":
            # The first caller owns the execution lease. Returning the same
            # projection makes duplicate browser/API requests idempotent.
            return run
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
    def get_state(cls, run_id: str, workspace_id: str, db: Session) -> GraphRunStateView:
        run = cls._find_run(run_id, workspace_id, db)
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
            graph = cls._compiled_graph(checkpointer)
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
        if not run.graph_thread_id:
            return []
        with open_postgres_checkpointer() as checkpointer:
            graph = cls._compiled_graph(checkpointer)
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
    ) -> AgentRun:
        run = cls._find_run(run_id, workspace_id, db)
        if thread_id is not None and thread_id != cls._thread_id(run):
            raise GraphRunThreadMismatch("Resume thread_id does not match this AgentRun.")
        if run.status == "cancelled":
            raise GraphRunCancelled("Cancelled graph runs cannot be resumed.")
        if run.status == "completed":
            return run
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

            try:
                validate_resume_against_interrupt(resume_payload, pending)
            except ValueError as error:
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
