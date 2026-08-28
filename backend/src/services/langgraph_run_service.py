"""LG-1 durable LangGraph run service.

This service owns the bridge between a LangGraph checkpoint thread and the
existing ``AgentRun`` / ``AgentRunStep`` operational projection.  It does not
replace the legacy 11-agent execution path yet; LG-2 through LG-6 migrate the
domain nodes one subgraph at a time.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import logging
import math
import re
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, text
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
from src.config import settings
from src.db.models import AgentRun, AgentRunEvent, AgentRunStep, Asset, DetailPageVersion, ImageGenerationJobRecord, ImageGenerationOutboxRecord, ProductProject
from src.services.generation_status_service import bounded_error_code, seller_guidance


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


EVENT_PROJECTION_VERSION = 1
EVENT_SCHEMA_VERSION = "agent-run-event-v1"
GRAPH_RUNTIME_VERSION = "lg13-runtime-v1"
_EVENT_TYPES = frozenset({
    "graph_node_updated",
    "graph_interrupt_waiting",
    "graph_execution_failed",
    "intake_envelope_accepted",
    "source_snapshot_ready",
    "truth_ready",
    "truth_review_required",
    "seller_confirmation_pending",
    "seller_confirmation_resolved",
    "creative_brief_ready",
    "commerce_creative_master_ready",
    "lease_expired_requeued",
    "lease_expired_provider_outcome_unknown",
    "provider_wait_reconciled",
    "dead_letter_requeue",
    "stale_delivery_blocked",
    "provider_cost_recorded",
    "provider_cost_unknown",
    "main_execution_started",
    "product_understanding_started",
    "product_understanding_completed",
    "planning_copy_completed",
    "first_usable_draft_ready",
    "quality_promotion_ready",
    "review_wait_started",
    "review_wait_resolved",
    "delivery_enqueued",
    "delivery_leased",
    "retry_scheduled",
    "run_started",
    "run_completed",
    "run_failed",
    "run_cancelled",
    "run_recovered",
    "projection_rebuilt",
    "checkpoint_projected",
    "stage_started",
    "stage_completed",
    "stage_skipped",
    "stage_failed",
    "stage_blocked",
    "stage_reentered",
    "seller_choice_submitted",
    "review_resumed",
    "quality_evaluated",
    "quality_rework_required",
    "quality_re_evaluated",
    "quality_blocked",
    "quality_stale",
})
_EVENT_REFERENCE_NAMES = ("source_snapshot", "truth", "confirmation", "creative_brief", "commerce_creative_master")
_SOURCE_FIDELITY_STATES = frozenset({"unknown", "seller_entered", "captured", "ready", "partial_observation_ready", "recovery"})
_RECOVERY_EVENT_TYPES = frozenset({
    "lease_expired_requeued",
    "lease_expired_provider_outcome_unknown",
    "provider_wait_reconciled",
    "dead_letter_requeue",
    "stale_delivery_blocked",
})
_RECOVERY_RETRY_STATES = frozenset({"queued", "retry_wait", "leased", "completed", "dead_letter"})
_RECOVERY_REASON_CODES = frozenset({
    "LEASE_EXPIRED",
    "PROVIDER_OUTCOME_UNKNOWN",
    "PROVIDER_WAIT_RECONCILED",
    "OPERATOR_REQUEUE",
    "SCOPE_TUPLE_MISMATCH",
})
_COST_EVENT_TYPES = frozenset({"provider_cost_recorded", "provider_cost_unknown"})
_COST_STATES = frozenset({"NOT_DISPATCHED", "EXPLICIT_ZERO", "KNOWN", "UNKNOWN_AFTER_DISPATCH"})
_FAILURE_EVENT_CODES = frozenset({
    "GRAPH_EXECUTION_FAILED",
    "SAFE_REFERENCE_ASSET_REQUIRED",
    "IMAGE_PROVIDER_NOT_CONFIGURED",
    "IMAGE_JOB_PREPARE_FAILED",
    "IMAGE_JOB_DISPATCH_FAILED",
})
_TIMING_EVENT_TYPES = frozenset({
    "main_execution_started",
    "product_understanding_started",
    "product_understanding_completed",
    "planning_copy_completed",
    "first_usable_draft_ready",
    "quality_promotion_ready",
    "review_wait_started",
    "review_wait_resolved",
    "delivery_enqueued",
    "delivery_leased",
    "retry_scheduled",
})
_TIMING_EVENT_STAGES = {
    "main_execution_started": ("input_router", "running"),
    "product_understanding_started": ("input_router", "running"),
    "product_understanding_completed": ("product_understanding", "completed"),
    "planning_copy_completed": ("copywriting", "completed"),
    "first_usable_draft_ready": ("canonical_renderer", "completed"),
    "quality_promotion_ready": ("quality_promotion_ready", "completed"),
    "review_wait_started": ("seller_review", "awaiting_review"),
    "review_wait_resolved": ("seller_review", "running"),
    "delivery_enqueued": ("image_delivery", "queued"),
    "delivery_leased": ("image_delivery", "leased"),
    "retry_scheduled": ("image_delivery", "retry_wait"),
}
_TIMING_EVENT_FOR_COMPLETED_STAGE = {
    "product_understanding": "product_understanding_completed",
    "copywriting": "planning_copy_completed",
    "canonical_renderer": "first_usable_draft_ready",
    "quality_promotion_ready": "quality_promotion_ready",
}
_RUN_LIFECYCLE_EVENT_TYPES = frozenset({
    "run_started", "run_completed", "run_failed", "run_cancelled", "run_recovered", "projection_rebuilt", "checkpoint_projected",
})
_STAGE_LIFECYCLE_EVENT_TYPES = frozenset({
    "stage_started", "stage_completed", "stage_skipped", "stage_failed", "stage_blocked", "stage_reentered",
})
_REVIEW_LIFECYCLE_EVENT_TYPES = frozenset({"seller_choice_submitted", "review_resumed"})
_QUALITY_LIFECYCLE_EVENT_TYPES = frozenset({
    "quality_evaluated", "quality_rework_required", "quality_re_evaluated", "quality_blocked", "quality_stale",
})
_LIFECYCLE_TRANSITIONS = frozenset({"started", "completed", "skipped", "failed", "cancelled", "blocked", "reentered", "recovered", "rebuilt", "checkpointed", "submitted", "resumed"})
_SLO_EXECUTION_PROFILES = frozenset({"production", "test", "mock"})
_SLO_MINIMUM_SAMPLES = 30
_SLO_WINDOW_DAYS = 30
_SELLER_SLO_STAGE = {
    "input_router": ("product_understanding", "상품 정보를 확인하고 있습니다."),
    "source_collection": ("product_understanding", "상품 정보를 확인하고 있습니다."),
    "product_understanding": ("product_understanding", "상품 정보를 확인하고 있습니다."),
    "reference_analysis": ("planning_copy", "상품 표현을 준비하고 있습니다."),
    "sales_strategy": ("planning_copy", "상품 표현을 준비하고 있습니다."),
    "page_planning": ("planning_copy", "상품 표현을 준비하고 있습니다."),
    "copywriting": ("planning_copy", "상품 표현을 준비하고 있습니다."),
    "visual_planning": ("first_usable_draft", "상세페이지 초안을 준비하고 있습니다."),
    "generation_pending": ("first_usable_draft", "이미지 생성을 준비하고 있습니다."),
    "provider_wait": ("first_usable_draft", "이미지 생성 결과를 확인하고 있습니다."),
    "image_delivery": ("first_usable_draft", "이미지를 생성하고 있습니다."),
    "image_generation": ("first_usable_draft", "이미지를 생성하고 있습니다."),
    "page_assembly": ("first_usable_draft", "상세페이지 초안을 준비하고 있습니다."),
    "canonical_renderer": ("first_usable_draft", "상세페이지 초안을 준비하고 있습니다."),
    "qa_review": ("high_quality_final", "결과 품질을 확인하고 있습니다."),
    "quality_review": ("high_quality_final", "결과 품질을 확인하고 있습니다."),
    "quality_promotion_ready": ("high_quality_final", "최종 결과를 준비하고 있습니다."),
}
_SLO_STAGE_START_EVENTS = {
    "product_understanding": ("product_understanding_started", "main_execution_started"),
    "planning_copy": ("product_understanding_completed", "main_execution_started"),
    "first_usable_draft": ("planning_copy_completed", "main_execution_started"),
    "high_quality_final": ("first_usable_draft_ready", "main_execution_started"),
}
_SLO_COMPLETED_STAGE = {
    "product_understanding_completed": ("product_understanding", "상품 정보 확인"),
    "planning_copy_completed": ("planning_copy", "상품 표현 준비"),
    "first_usable_draft_ready": ("first_usable_draft", "상세페이지 초안"),
    "quality_promotion_ready": ("high_quality_final", "최종 결과"),
}
_SELLER_DELAY_CAUSE_KO = {
    "queue_wait": "생성 작업을 준비하고 있습니다.",
    "provider_execution": "이미지를 생성하고 있습니다.",
    "retry_backoff": "일시적인 문제로 다시 시도할 준비를 하고 있습니다.",
    "recovery_reconciled": "작업 상태를 안전하게 다시 확인하고 있습니다.",
    "graph_compute": "생성 내용을 준비하고 있습니다.",
    "rendering_quality": "결과 품질을 확인하고 있습니다.",
    "seller_review_wait": "확인이 필요한 항목이 있습니다.",
    "unknown": "작업 상태를 확인하고 있습니다.",
}
_SLO_METRICS_SQL = text("""
WITH clock AS (
  SELECT clock_timestamp() AS observed_at
), milestones(milestone, start_event, terminal_event, target_seconds, target_min_seconds) AS (
  VALUES
    ('product_understanding', 'main_execution_started', 'product_understanding_completed', 60.0::double precision, NULL::double precision),
    ('planning_copy', 'product_understanding_completed', 'planning_copy_completed', 180.0::double precision, NULL::double precision),
    ('first_usable_draft', 'main_execution_started', 'first_usable_draft_ready', 300.0::double precision, NULL::double precision),
    ('high_quality_final', 'main_execution_started', 'quality_promotion_ready', 900.0::double precision, 600.0::double precision),
    ('normal_run', 'main_execution_started', 'quality_promotion_ready', 1200.0::double precision, NULL::double precision)
), timing AS (
  SELECT event.run_id, event.event_type, event.occurred_at, event.payload_json
  FROM agent_run_events AS event, clock
  WHERE event.occurred_at <= clock.observed_at
), production_starts AS (
  SELECT run_id, MIN(occurred_at) AS started_at
  FROM timing
  WHERE event_type = 'main_execution_started'
    AND payload_json -> 'timing' ->> 'execution_profile' = 'production'
  GROUP BY run_id
), base AS (
  SELECT run.id AS run_id, milestone, milestones.target_seconds, milestones.target_min_seconds,
         boundary_start.started_at,
         terminal.terminal_at
  FROM agent_runs AS run
  JOIN production_starts AS execution_start ON execution_start.run_id = run.id
  CROSS JOIN milestones
  JOIN LATERAL (
    SELECT MIN(event.occurred_at) AS started_at
    FROM timing AS event
    WHERE event.run_id = run.id
      AND event.event_type = milestones.start_event
      AND event.occurred_at >= execution_start.started_at
  ) AS boundary_start ON boundary_start.started_at IS NOT NULL
  JOIN LATERAL (
    SELECT MIN(event.occurred_at) AS terminal_at
    FROM timing AS event
    WHERE event.run_id = run.id
      AND event.event_type = milestones.terminal_event
      AND event.occurred_at >= boundary_start.started_at
  ) AS terminal ON terminal.terminal_at IS NOT NULL
  CROSS JOIN clock
  WHERE run.mode NOT IN ('lg11_edit', 'lg12i_intake')
    AND run.status NOT IN ('cancelled', 'rejected')
    AND (CAST(:workspace_id AS VARCHAR) IS NULL OR run.workspace_id = CAST(:workspace_id AS VARCHAR))
    AND terminal.terminal_at >= clock.observed_at - INTERVAL '30 days'
), measured AS (
  SELECT base.*,
    COALESCE((
      SELECT SUM(EXTRACT(EPOCH FROM LEAST(resolved.occurred_at, base.terminal_at) - GREATEST(wait_started.occurred_at, base.started_at)))
      FROM timing AS wait_started
      JOIN LATERAL (
        SELECT MIN(wait_resolved.occurred_at) AS occurred_at
        FROM timing AS wait_resolved
        WHERE wait_resolved.run_id = base.run_id
          AND wait_resolved.event_type = 'review_wait_resolved'
          AND wait_resolved.payload_json -> 'timing' ->> 'review_cycle' = wait_started.payload_json -> 'timing' ->> 'review_cycle'
          AND wait_resolved.occurred_at >= wait_started.occurred_at
      ) AS resolved ON resolved.occurred_at IS NOT NULL
      WHERE wait_started.run_id = base.run_id
        AND wait_started.event_type = 'review_wait_started'
        AND wait_started.occurred_at < base.terminal_at
    ), 0.0) AS review_wait_seconds,
    COALESCE((
      SELECT MAX(EXTRACT(EPOCH FROM leased.occurred_at - queued.occurred_at))
      FROM timing AS queued
      JOIN LATERAL (
        SELECT MIN(next_lease.occurred_at) AS occurred_at
        FROM timing AS next_lease
        WHERE next_lease.run_id = base.run_id
          AND next_lease.event_type = 'delivery_leased'
          AND next_lease.payload_json -> 'timing' -> 'outbox' ->> 'id' = queued.payload_json -> 'timing' -> 'outbox' ->> 'id'
          AND next_lease.occurred_at >= queued.occurred_at
      ) AS leased ON leased.occurred_at IS NOT NULL
      WHERE queued.run_id = base.run_id
        AND queued.event_type = 'delivery_enqueued'
        AND queued.occurred_at >= base.started_at
        AND queued.occurred_at <= base.terminal_at
    ), 0.0) AS queue_seconds,
    COALESCE((
      SELECT MAX(EXTRACT(EPOCH FROM next_lease.occurred_at - retry.occurred_at))
      FROM timing AS retry
      JOIN LATERAL (
        SELECT MIN(leased.occurred_at) AS occurred_at
        FROM timing AS leased
        WHERE leased.run_id = base.run_id
          AND leased.event_type = 'delivery_leased'
          AND leased.payload_json -> 'timing' -> 'outbox' ->> 'id' = retry.payload_json -> 'timing' -> 'outbox' ->> 'id'
          AND (leased.payload_json -> 'timing' ->> 'attempt')::integer > (retry.payload_json -> 'timing' ->> 'attempt')::integer
          AND leased.occurred_at >= retry.occurred_at
      ) AS next_lease ON next_lease.occurred_at IS NOT NULL
      WHERE retry.run_id = base.run_id
        AND retry.event_type = 'retry_scheduled'
        AND retry.occurred_at >= base.started_at
        AND retry.occurred_at <= base.terminal_at
    ), 0.0) AS retry_seconds,
    COALESCE((
      SELECT MAX(attempt.latency_ms)::double precision / 1000.0
      FROM image_generation_provider_attempts AS attempt
      WHERE attempt.run_id = base.run_id AND attempt.latency_ms IS NOT NULL
    ), 0.0) AS provider_seconds,
    COALESCE((
      SELECT EXTRACT(EPOCH FROM base.terminal_at - MIN(draft.occurred_at))
      FROM timing AS draft
      WHERE draft.run_id = base.run_id
        AND draft.event_type = 'first_usable_draft_ready'
        AND draft.occurred_at >= base.started_at
        AND draft.occurred_at <= base.terminal_at
    ), 0.0) AS rendering_quality_seconds,
    EXISTS (
      SELECT 1 FROM timing AS recovery
      WHERE recovery.run_id = base.run_id
        AND recovery.event_type IN ('lease_expired_requeued', 'lease_expired_provider_outcome_unknown', 'provider_wait_reconciled', 'dead_letter_requeue', 'stale_delivery_blocked')
        AND recovery.occurred_at >= base.started_at
        AND recovery.occurred_at <= base.terminal_at
    ) AS has_recovery
  FROM base
), attributed AS (
  SELECT *,
    EXTRACT(EPOCH FROM terminal_at - started_at) AS wall_seconds,
    GREATEST(0.0, EXTRACT(EPOCH FROM terminal_at - started_at) - review_wait_seconds) AS active_seconds,
    CASE
      WHEN retry_seconds >= queue_seconds AND retry_seconds >= provider_seconds AND retry_seconds > 0 THEN 'retry_backoff'
      WHEN queue_seconds >= provider_seconds AND queue_seconds > 0 THEN 'queue_wait'
      WHEN provider_seconds > 0 THEN 'provider_execution'
      WHEN has_recovery THEN 'recovery_reconciled'
      WHEN rendering_quality_seconds > 0 THEN 'rendering_quality'
      WHEN EXTRACT(EPOCH FROM terminal_at - started_at) - review_wait_seconds > 0 THEN 'graph_compute'
      ELSE 'unknown'
    END AS delay_cause
  FROM measured
), stats AS (
  SELECT milestone,
         COUNT(*)::integer AS sample_count,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY active_seconds) AS p50_seconds,
         percentile_cont(0.9) WITHIN GROUP (ORDER BY active_seconds) AS p90_seconds,
         COUNT(*) FILTER (WHERE active_seconds > target_seconds)::integer AS breach_count,
         COUNT(*) FILTER (WHERE wall_seconds > target_seconds AND active_seconds <= target_seconds AND review_wait_seconds > 0)::integer AS seller_review_only_overage_count
  FROM attributed
  GROUP BY milestone
), causes AS (
  SELECT milestone, jsonb_object_agg(delay_cause, count) AS delay_cause_counts
  FROM (
    SELECT milestone, delay_cause, COUNT(*)::integer AS count
    FROM attributed
    WHERE active_seconds > target_seconds
    GROUP BY milestone, delay_cause
  ) AS grouped
  GROUP BY milestone
)
SELECT milestones.milestone, milestones.target_seconds, milestones.target_min_seconds,
       COALESCE(stats.sample_count, 0) AS sample_count,
       CASE WHEN COALESCE(stats.sample_count, 0) >= :minimum_samples THEN stats.p50_seconds END AS p50_seconds,
       CASE WHEN COALESCE(stats.sample_count, 0) >= :minimum_samples THEN stats.p90_seconds END AS p90_seconds,
       COALESCE(stats.breach_count, 0) AS breach_count,
       COALESCE(stats.seller_review_only_overage_count, 0) AS seller_review_only_overage_count,
       COALESCE(causes.delay_cause_counts, '{}'::jsonb) AS delay_cause_counts
FROM milestones
LEFT JOIN stats USING (milestone)
LEFT JOIN causes USING (milestone)
ORDER BY CASE milestones.milestone
  WHEN 'product_understanding' THEN 1 WHEN 'planning_copy' THEN 2 WHEN 'first_usable_draft' THEN 3
  WHEN 'high_quality_final' THEN 4 ELSE 5 END
""")


_INTAKE_OPERATIONAL_METRICS_SQL = text("""
WITH clock AS (
  SELECT clock_timestamp() AS observed_at
), modes(input_mode) AS (
  VALUES ('owned_product_url'), ('photo_only'), ('manual')
), events AS (
  SELECT event.run_id, event.sequence, event.event_type, event.occurred_at, event.payload_json
  FROM agent_run_events AS event
  JOIN agent_runs AS run ON run.id = event.run_id
  CROSS JOIN clock
  WHERE event.occurred_at >= clock.observed_at - INTERVAL '30 days'
    AND event.occurred_at <= clock.observed_at
    AND (CAST(:workspace_id AS VARCHAR) IS NULL OR run.workspace_id = CAST(:workspace_id AS VARCHAR))
    AND (CAST(:project_id AS VARCHAR) IS NULL OR run.project_id = CAST(:project_id AS VARCHAR))
    AND (CAST(:run_id AS VARCHAR) IS NULL OR run.id = CAST(:run_id AS VARCHAR))
), starts AS (
  SELECT DISTINCT ON (run_id)
    run_id, payload_json ->> 'input_mode' AS input_mode, occurred_at AS started_at
  FROM events
  WHERE event_type = 'intake_envelope_accepted'
    AND payload_json ->> 'input_mode' IN ('owned_product_url', 'photo_only', 'manual')
  ORDER BY run_id, sequence
), terminals AS (
  SELECT DISTINCT ON (event.run_id)
    event.run_id,
    CASE WHEN event.event_type = 'commerce_creative_master_ready' THEN 'success' ELSE 'failure' END AS outcome,
    CASE
      WHEN event.event_type = 'commerce_creative_master_ready' THEN NULL
      WHEN event.event_type = 'graph_execution_failed' THEN CASE
        WHEN event.payload_json -> 'failure' ->> 'code' IN (
          'GRAPH_EXECUTION_FAILED', 'SAFE_REFERENCE_ASSET_REQUIRED', 'IMAGE_PROVIDER_NOT_CONFIGURED',
          'IMAGE_JOB_PREPARE_FAILED', 'IMAGE_JOB_DISPATCH_FAILED'
        ) THEN event.payload_json -> 'failure' ->> 'code'
        ELSE 'GRAPH_EXECUTION_FAILED'
      END
      WHEN event.payload_json ->> 'stage' = 'owned_url_capture_recovery' THEN 'OWNED_URL_CAPTURE_RECOVERY'
      WHEN event.payload_json ->> 'stage' = 'photo_observation_recovery' THEN 'PHOTO_OBSERVATION_RECOVERY'
      WHEN event.payload_json ->> 'stage' = 'truth_blocked_source_integrity' THEN 'SOURCE_INTEGRITY_BLOCKED'
      WHEN event.payload_json ->> 'stage' = 'creative_brief_blocked' THEN 'CREATIVE_BRIEF_BLOCKED'
      WHEN event.payload_json ->> 'stage' = 'commerce_creative_master_blocked'
        AND CASE
          WHEN COALESCE(event.payload_json -> 'metrics' ->> 'prohibited_inference_count', '') ~ '^(0|[1-9][0-9]{0,2}|1000)$'
            THEN (event.payload_json -> 'metrics' ->> 'prohibited_inference_count')::integer
          ELSE 0
        END > 0
        THEN 'PROHIBITED_INFERENCE_BLOCKED'
      ELSE 'INTAKE_BLOCKED'
    END AS failure_reason,
    event.occurred_at AS terminal_at
  FROM events AS event
  JOIN starts ON starts.run_id = event.run_id
  WHERE event.event_type IN ('commerce_creative_master_ready', 'graph_execution_failed')
     OR event.payload_json ->> 'stage' IN (
       'owned_url_capture_recovery', 'photo_observation_recovery', 'truth_blocked_source_integrity',
       'creative_brief_blocked', 'commerce_creative_master_blocked'
     )
  ORDER BY event.run_id, event.sequence DESC
), source_fidelity AS (
  SELECT DISTINCT ON (event.run_id)
    event.run_id,
    CASE WHEN event.payload_json ->> 'source_fidelity' IN ('unknown', 'seller_entered', 'captured', 'ready', 'partial_observation_ready', 'recovery')
      THEN event.payload_json ->> 'source_fidelity' ELSE 'unknown' END AS source_fidelity
  FROM events AS event
  JOIN starts ON starts.run_id = event.run_id
  WHERE event.event_type = 'source_snapshot_ready'
  ORDER BY event.run_id, event.sequence DESC
), truth_metrics AS (
  SELECT DISTINCT ON (event.run_id)
    event.run_id,
    CASE WHEN COALESCE(event.payload_json -> 'metrics' ->> 'unknown_fact_count', '') ~ '^(0|[1-9][0-9]{0,2}|1000)$'
      THEN (event.payload_json -> 'metrics' ->> 'unknown_fact_count')::integer ELSE 0 END AS unknown_fact_count,
    CASE WHEN COALESCE(event.payload_json -> 'metrics' ->> 'prohibited_inference_count', '') ~ '^(0|[1-9][0-9]{0,2}|1000)$'
      THEN (event.payload_json -> 'metrics' ->> 'prohibited_inference_count')::integer ELSE 0 END AS prohibited_inference_count,
    CASE WHEN COALESCE(event.payload_json -> 'metrics' ->> 'clarification_count', '') ~ '^(0|[1-9][0-9]{0,2}|1000)$'
      THEN (event.payload_json -> 'metrics' ->> 'clarification_count')::integer ELSE 0 END AS clarification_count
  FROM events AS event
  JOIN starts ON starts.run_id = event.run_id
  WHERE event.event_type IN ('truth_ready', 'truth_review_required')
  ORDER BY event.run_id, event.sequence DESC
), confirmation_requests AS (
  SELECT starts.input_mode, COUNT(*)::integer AS confirmation_request_count
  FROM events AS event
  JOIN starts ON starts.run_id = event.run_id
  WHERE event.event_type = 'truth_review_required'
  GROUP BY starts.input_mode
), source_counts AS (
  SELECT input_mode, jsonb_object_agg(source_fidelity, count) AS source_fidelity_counts
  FROM (
    SELECT starts.input_mode, COALESCE(source_fidelity.source_fidelity, 'unknown') AS source_fidelity, COUNT(*)::integer AS count
    FROM starts
    LEFT JOIN source_fidelity ON source_fidelity.run_id = starts.run_id
    GROUP BY starts.input_mode, COALESCE(source_fidelity.source_fidelity, 'unknown')
  ) AS grouped
  GROUP BY input_mode
), failure_counts AS (
  SELECT input_mode, jsonb_object_agg(failure_reason, count) AS failure_reason_counts
  FROM (
    SELECT starts.input_mode, terminals.failure_reason, COUNT(*)::integer AS count
    FROM starts
    JOIN terminals ON terminals.run_id = starts.run_id AND terminals.outcome = 'failure'
    GROUP BY starts.input_mode, terminals.failure_reason
  ) AS grouped
  GROUP BY input_mode
), summary AS (
  SELECT
    starts.input_mode,
    COUNT(*)::integer AS started_run_count,
    COUNT(terminals.run_id)::integer AS terminal_intake_run_count,
    COUNT(*) FILTER (WHERE terminals.outcome = 'success')::integer AS successful_intake_run_count,
    COUNT(*) FILTER (WHERE COALESCE(truth_metrics.prohibited_inference_count, 0) > 0)::integer AS unsupported_inference_blocked_run_count,
    COALESCE(SUM(truth_metrics.unknown_fact_count), 0)::integer AS unknown_fact_count,
    COALESCE(SUM(truth_metrics.prohibited_inference_count), 0)::integer AS prohibited_inference_count,
    COALESCE(SUM(truth_metrics.clarification_count), 0)::integer AS clarification_count,
    COUNT(*) FILTER (WHERE terminals.outcome = 'success' AND terminals.terminal_at >= starts.started_at)::integer AS completed_intake_count,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM terminals.terminal_at - starts.started_at))
      FILTER (WHERE terminals.outcome = 'success' AND terminals.terminal_at >= starts.started_at) AS p50_completion_seconds,
    percentile_cont(0.9) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM terminals.terminal_at - starts.started_at))
      FILTER (WHERE terminals.outcome = 'success' AND terminals.terminal_at >= starts.started_at) AS p90_completion_seconds
  FROM starts
  LEFT JOIN terminals ON terminals.run_id = starts.run_id
  LEFT JOIN truth_metrics ON truth_metrics.run_id = starts.run_id
  GROUP BY starts.input_mode
)
SELECT
  modes.input_mode,
  COALESCE(summary.started_run_count, 0) AS started_run_count,
  COALESCE(summary.terminal_intake_run_count, 0) AS terminal_intake_run_count,
  COALESCE(summary.successful_intake_run_count, 0) AS successful_intake_run_count,
  COALESCE(confirmation_requests.confirmation_request_count, 0) AS confirmation_request_count,
  COALESCE(summary.unsupported_inference_blocked_run_count, 0) AS unsupported_inference_blocked_run_count,
  COALESCE(summary.unknown_fact_count, 0) AS unknown_fact_count,
  COALESCE(summary.prohibited_inference_count, 0) AS prohibited_inference_count,
  COALESCE(summary.clarification_count, 0) AS clarification_count,
  COALESCE(summary.completed_intake_count, 0) AS completed_intake_count,
  summary.p50_completion_seconds,
  summary.p90_completion_seconds,
  COALESCE(source_counts.source_fidelity_counts, '{}'::jsonb) AS source_fidelity_counts,
  COALESCE(failure_counts.failure_reason_counts, '{}'::jsonb) AS failure_reason_counts
FROM modes
LEFT JOIN summary USING (input_mode)
LEFT JOIN confirmation_requests USING (input_mode)
LEFT JOIN source_counts USING (input_mode)
LEFT JOIN failure_counts USING (input_mode)
ORDER BY CASE modes.input_mode
  WHEN 'owned_product_url' THEN 1 WHEN 'photo_only' THEN 2 ELSE 3 END
""")


class AgentRunEventJournal:
    """Append and replay the compact, immutable AgentRun event journal."""

    @staticmethod
    def _reference(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        identifier, version, digest = value.get("id"), value.get("version"), value.get("hash")
        if not isinstance(identifier, str) or len(identifier) > 64:
            return None
        if not isinstance(version, int) or version < 1:
            return None
        if not isinstance(digest, str) or len(digest) != 64:
            return None
        return {"id": identifier, "version": version, "hash": digest}

    @classmethod
    def _payload_for_update(cls, run: AgentRun, update: dict[str, Any], event: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        intake = dict(update.get("intake") or {})
        source_name, source = next(
            ((name, dict(intake.get(name) or {})) for name in ("manual_source", "owned_url_source", "photo_source") if isinstance(intake.get(name), dict)),
            ("", {}),
        )
        references = {
            "source_snapshot": cls._reference(source.get("source_snapshot")),
            "truth": cls._reference(dict(intake.get("product_truth") or {}).get("truth_version")),
            "confirmation": cls._reference(dict(intake.get("seller_confirmation") or {}).get("confirmation_version")),
            "creative_brief": cls._reference(dict(intake.get("creative_brief") or {}).get("brief_version")),
            "commerce_creative_master": cls._reference(dict(intake.get("commerce_creative_master") or {}).get("master_version")),
        }
        references = {name: value for name, value in references.items() if value is not None}
        mode = str(intake.get("input_mode") or dict((run.input_snapshot or {}).get("unified_product_intake") or {}).get("input_mode") or "")
        source_fidelity = (
            "seller_entered" if source_name == "manual_source"
            else "captured" if source_name == "owned_url_source"
            else str(source.get("observation_status") or "ready") if source_name == "photo_source"
            else "unknown"
        )
        metrics = {
            "unknown_fact_count": len(list(dict(intake.get("product_truth") or {}).get("unknown_refs") or [])),
            "prohibited_inference_count": len(list(dict(intake.get("product_truth") or {}).get("prohibited_inference_refs") or [])),
            "clarification_count": len(list(dict(intake.get("seller_confirmation") or {}).get("clarifications") or [])),
        }
        stage = str(event.get("stage") or "")
        event_type = "graph_node_updated"
        if intake.get("input_hash"):
            event_type = "intake_envelope_accepted"
        if references.get("source_snapshot"):
            event_type = "source_snapshot_ready"
        if references.get("truth"):
            event_type = "truth_review_required" if dict(intake.get("seller_confirmation") or {}).get("confirmation_required") else "truth_ready"
        if stage in {"seller_confirmation_required", "confirmation_still_required"} and not references.get("truth"):
            event_type = "seller_confirmation_pending"
        if references.get("confirmation"):
            event_type = "seller_confirmation_resolved"
        if references.get("creative_brief"):
            event_type = "creative_brief_ready"
        if references.get("commerce_creative_master"):
            event_type = "commerce_creative_master_ready"
        payload = {
            "stage": stage,
            "status": str(event.get("status") or ""),
            "node_status": str(event.get("node_status") or "completed"),
            "input_mode": mode,
            "source_fidelity": source_fidelity,
            "references": references,
            "metrics": metrics,
        }
        cls.validate_payload(event_type, payload)
        return event_type, payload

    @staticmethod
    def validate_payload(event_type: str, payload: dict[str, Any]) -> None:
        if event_type not in _EVENT_TYPES:
            raise ValueError("Unsupported AgentRun event type.")
        expected_fields = {"stage", "status", "node_status", "input_mode", "source_fidelity", "references", "metrics"}
        if event_type in _RECOVERY_EVENT_TYPES:
            expected_fields.add("recovery")
        if event_type in _COST_EVENT_TYPES:
            expected_fields.add("cost")
        if event_type == "graph_execution_failed":
            expected_fields.add("failure")
        if event_type in _TIMING_EVENT_TYPES:
            expected_fields.add("timing")
        if event_type in _STAGE_LIFECYCLE_EVENT_TYPES or event_type in _RUN_LIFECYCLE_EVENT_TYPES or event_type in _REVIEW_LIFECYCLE_EVENT_TYPES or event_type in _QUALITY_LIFECYCLE_EVENT_TYPES:
            expected_fields.add("lifecycle")
        # Identity was added after the initial journal rollout.  Older rows
        # remain replayable, while every new append receives this bounded
        # authority record in ``append`` below.
        if "identity" in payload:
            expected_fields.add("identity")
        if set(payload) != expected_fields:
            raise ValueError("AgentRun event payload is not an allowlisted shape.")
        if not all(isinstance(payload[name], str) and len(payload[name]) <= 80 for name in ("stage", "status", "node_status", "input_mode")):
            raise ValueError("AgentRun event payload has an invalid scalar.")
        if payload["source_fidelity"] not in _SOURCE_FIDELITY_STATES:
            raise ValueError("AgentRun event source fidelity is not allowlisted.")
        references = payload["references"]
        metrics = payload["metrics"]
        if not isinstance(references, dict) or not set(references) <= set(_EVENT_REFERENCE_NAMES):
            raise ValueError("AgentRun event references are not allowlisted.")
        if not isinstance(metrics, dict) or set(metrics) != {"unknown_fact_count", "prohibited_inference_count", "clarification_count"}:
            raise ValueError("AgentRun event metrics are not allowlisted.")
        if not all(isinstance(value, int) and 0 <= value <= 1000 for value in metrics.values()):
            raise ValueError("AgentRun event metrics are invalid.")
        for reference in references.values():
            if AgentRunEventJournal._reference(reference) != reference:
                raise ValueError("AgentRun event references must be immutable identities.")
        if event_type in _RECOVERY_EVENT_TYPES:
            recovery = payload["recovery"]
            if set(recovery) != {"job", "outbox", "attempt", "retry_state", "reason_code"}:
                raise ValueError("AgentRun recovery event payload is not an allowlisted shape.")
            if any(AgentRunEventJournal._reference(recovery[name]) != recovery[name] for name in ("job", "outbox")):
                raise ValueError("AgentRun recovery event references must be immutable identities.")
            if not isinstance(recovery["attempt"], int) or not 0 <= recovery["attempt"] <= 1000:
                raise ValueError("AgentRun recovery attempt is invalid.")
            if recovery["retry_state"] not in _RECOVERY_RETRY_STATES or recovery["reason_code"] not in _RECOVERY_REASON_CODES:
                raise ValueError("AgentRun recovery state is not allowlisted.")
        if event_type in _COST_EVENT_TYPES:
            cost = payload["cost"]
            if set(cost) != {"ledger", "cost_state", "actual_cost", "currency", "provider", "model"}:
                raise ValueError("AgentRun cost event payload is not an allowlisted shape.")
            if AgentRunEventJournal._reference(cost["ledger"]) != cost["ledger"]:
                raise ValueError("AgentRun cost event ledger reference is invalid.")
            if cost["cost_state"] not in _COST_STATES:
                raise ValueError("AgentRun cost event state is invalid.")
            actual_cost = cost["actual_cost"]
            if actual_cost is not None and (isinstance(actual_cost, bool) or not isinstance(actual_cost, (int, float)) or actual_cost < 0 or actual_cost > 1_000_000_000):
                raise ValueError("AgentRun cost event actual cost is invalid.")
            if cost["cost_state"] == "UNKNOWN_AFTER_DISPATCH" and actual_cost is not None:
                raise ValueError("Unknown provider cost cannot expose a numeric actual cost.")
            if cost["cost_state"] != "UNKNOWN_AFTER_DISPATCH" and actual_cost is None:
                raise ValueError("Known provider cost state requires an explicit scalar.")
            if not all(isinstance(cost[name], str) and 0 < len(cost[name]) <= limit for name, limit in (("currency", 20), ("provider", 50), ("model", 100))):
                raise ValueError("AgentRun cost event labels are invalid.")
        if event_type == "graph_execution_failed":
            failure = payload["failure"]
            if not isinstance(failure, dict) or set(failure) != {"code", "recoverable"}:
                raise ValueError("AgentRun failure event payload is not an allowlisted shape.")
            if failure["code"] not in _FAILURE_EVENT_CODES or not isinstance(failure["recoverable"], bool):
                raise ValueError("AgentRun failure event payload is invalid.")
        if event_type in _TIMING_EVENT_TYPES:
            timing = payload["timing"]
            if not isinstance(timing, dict):
                raise ValueError("AgentRun timing event payload is invalid.")
            if event_type == "main_execution_started":
                if set(timing) != {"execution_profile"} or timing["execution_profile"] not in _SLO_EXECUTION_PROFILES:
                    raise ValueError("AgentRun execution profile is not allowlisted.")
            elif event_type in {"review_wait_started", "review_wait_resolved"}:
                if set(timing) != {"review_cycle"} or not isinstance(timing["review_cycle"], str) or len(timing["review_cycle"]) != 64:
                    raise ValueError("AgentRun review timing cycle is invalid.")
            elif event_type in {"product_understanding_started", "product_understanding_completed", "planning_copy_completed", "first_usable_draft_ready", "quality_promotion_ready"}:
                if timing:
                    raise ValueError("AgentRun stage timing payload must be empty.")
            else:
                if set(timing) != {"outbox", "attempt"}:
                    raise ValueError("AgentRun delivery timing payload is not allowlisted.")
                if AgentRunEventJournal._reference(timing["outbox"]) != timing["outbox"]:
                    raise ValueError("AgentRun delivery timing reference is invalid.")
                if not isinstance(timing["attempt"], int) or not 0 <= timing["attempt"] <= 1000:
                    raise ValueError("AgentRun delivery timing attempt is invalid.")
        if event_type in _STAGE_LIFECYCLE_EVENT_TYPES or event_type in _RUN_LIFECYCLE_EVENT_TYPES or event_type in _REVIEW_LIFECYCLE_EVENT_TYPES or event_type in _QUALITY_LIFECYCLE_EVENT_TYPES:
            lifecycle = payload["lifecycle"]
            lifecycle_keys = {"transition", "checkpoint_id"}
            if event_type == "seller_choice_submitted":
                lifecycle_keys.add("decision")
            if not isinstance(lifecycle, dict) or set(lifecycle) != lifecycle_keys:
                raise ValueError("AgentRun lifecycle payload is not an allowlisted shape.")
            if lifecycle["transition"] not in _LIFECYCLE_TRANSITIONS:
                raise ValueError("AgentRun lifecycle transition is not allowlisted.")
            if not isinstance(lifecycle["checkpoint_id"], str) or len(lifecycle["checkpoint_id"]) > 128:
                raise ValueError("AgentRun lifecycle checkpoint identity is invalid.")
            if event_type == "seller_choice_submitted":
                allowed_decisions = {"approve", "reject", "refresh", "fallback", "wait"}
                if payload["stage"] == "image_review":
                    allowed_decisions.update({"regenerate", "upload"})
                if payload["stage"] == "seller_confirmation":
                    allowed_decisions.add("submit")
                if payload["stage"] == "canvas_edit":
                    allowed_decisions.update({"apply", "undo", "redo", "commit"})
                if lifecycle["decision"] not in allowed_decisions:
                    raise ValueError("Seller review decision is not allowlisted.")
        if "identity" in payload:
            identity = payload["identity"]
            if not isinstance(identity, dict) or set(identity) != {
                "graph_version", "run_id", "thread_id", "checkpoint_id", "event_schema_version", "projection_version",
            }:
                raise ValueError("AgentRun event identity is not an allowlisted shape.")
            for key, limit in (("graph_version", 80), ("run_id", 64), ("thread_id", 64), ("checkpoint_id", 128), ("event_schema_version", 80)):
                if not isinstance(identity[key], str) or len(identity[key]) > limit:
                    raise ValueError("AgentRun event identity scalar is invalid.")
            if identity["event_schema_version"] != EVENT_SCHEMA_VERSION or not isinstance(identity["projection_version"], int) or identity["projection_version"] < 1:
                raise ValueError("AgentRun event identity version is invalid.")

    @classmethod
    def append_timing_event(
        cls,
        run: AgentRun,
        db: Session,
        *,
        event_type: str,
        timing: dict[str, Any],
    ) -> tuple[AgentRunEvent, bool, AgentRun]:
        """Append one bounded SLO boundary; PostgreSQL assigns ``occurred_at``."""

        if event_type not in _TIMING_EVENT_TYPES:
            raise ValueError("Unsupported AgentRun timing event type.")
        stage, status = _TIMING_EVENT_STAGES[event_type]
        mode = str(dict((run.input_snapshot or {}).get("unified_product_intake") or {}).get("input_mode") or "")
        event, appended, locked = cls.append(
            run,
            db,
            event_type=event_type,
            payload={
                "stage": stage,
                "status": status,
                "node_status": "completed",
                "input_mode": mode,
                "source_fidelity": "unknown",
                "references": {},
                "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
                "timing": timing,
            },
            thread_id=run.graph_thread_id or run.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
        )
        if appended:
            locked.last_applied_event_sequence = event.sequence
            locked.event_projection_version = EVENT_PROJECTION_VERSION
        return event, appended, locked

    @classmethod
    def append_failure_event(
        cls, run: AgentRun, db: Session, *, failure: dict[str, Any],
    ) -> tuple[AgentRunEvent, bool, AgentRun]:
        """Persist one normalized terminal failure without retaining error text."""

        code = str(failure.get("code") or "")
        code = code if code in _FAILURE_EVENT_CODES else "GRAPH_EXECUTION_FAILED"
        mode = str(dict((run.input_snapshot or {}).get("unified_product_intake") or {}).get("input_mode") or "")
        mode = mode if mode in {"owned_product_url", "photo_only", "manual"} else ""
        stage = str(failure.get("stage") or "")
        stage = stage if re.fullmatch(r"[a-z0-9_]{1,80}", stage) else "graph_execution"
        return cls.append(
            run,
            db,
            event_type="graph_execution_failed",
            payload={
                "stage": stage,
                "status": "failed",
                "node_status": "failed",
                "input_mode": mode,
                "source_fidelity": "unknown",
                "references": {},
                "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
                "failure": {"code": code, "recoverable": bool(failure.get("recoverable", True))},
            },
            thread_id=run.graph_thread_id or run.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
        )

    @staticmethod
    def slo_summary(db: Session, *, workspace_id: str | None = None) -> dict[str, Any]:
        """Read the fixed 30-day PostgreSQL SLO window without a rollup table."""

        if db.get_bind().dialect.name != "postgresql":
            raise ValueError("Generation SLO aggregation requires PostgreSQL.")
        milestones: dict[str, dict[str, Any]] = {}
        for row in db.execute(
            _SLO_METRICS_SQL,
            {"minimum_samples": _SLO_MINIMUM_SAMPLES, "workspace_id": workspace_id},
        ).mappings():
            sample_count = int(row["sample_count"] or 0)
            p90 = float(row["p90_seconds"]) if row["p90_seconds"] is not None else None
            target = float(row["target_seconds"])
            insufficient = sample_count < _SLO_MINIMUM_SAMPLES
            milestones[str(row["milestone"])] = {
                "sample_count": sample_count,
                "p50_seconds": float(row["p50_seconds"]) if row["p50_seconds"] is not None else None,
                "p90_seconds": p90,
                "target_seconds": target,
                "target_range_seconds": (
                    {"min": float(row["target_min_seconds"]), "max": target}
                    if row["target_min_seconds"] is not None else None
                ),
                "compliance_status": "insufficient_sample" if insufficient else ("pass" if p90 is not None and p90 <= target else "fail"),
                "insufficient_sample": insufficient,
                "breach_count": int(row["breach_count"] or 0),
                "delay_cause_counts": dict(row["delay_cause_counts"] or {}),
                "seller_review_only_overage_count": int(row["seller_review_only_overage_count"] or 0),
            }
        return {"window_days": _SLO_WINDOW_DAYS, "minimum_samples": _SLO_MINIMUM_SAMPLES, "milestones": milestones}

    @classmethod
    def seller_delay_context(
        cls,
        run: AgentRun,
        db: Session,
        *,
        observed_at: datetime.datetime | None = None,
    ) -> dict[str, Any] | None:
        """Project current bounded delay and ETA from the immutable timing journal."""

        if run.status not in {"created", "running", "awaiting_review"}:
            return None
        events = (
            db.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run.id)
            .order_by(AgentRunEvent.sequence.asc())
            .all()
        )
        if observed_at is None:
            observed_at = (
                db.execute(text("SELECT clock_timestamp()")).scalar_one()
                if db.get_bind().dialect.name == "postgresql"
                else datetime.datetime.utcnow()
            )
        milestone, stage_ko = _SELLER_SLO_STAGE.get(str(run.current_stage or ""), ("unknown", "작업을 준비하고 있습니다."))

        def payload(event: AgentRunEvent) -> dict[str, Any]:
            return dict(event.payload_json or {}) if isinstance(event.payload_json, dict) else {}

        def timing_key(event: AgentRunEvent) -> tuple[str, int] | None:
            timing = dict(payload(event).get("timing") or {})
            outbox = cls._reference(timing.get("outbox"))
            attempt = timing.get("attempt")
            if outbox is None or not isinstance(attempt, int):
                return None
            return str(outbox["hash"]), attempt

        def later_lease(event: AgentRunEvent) -> bool:
            key = timing_key(event)
            return any(
                candidate.sequence > event.sequence
                and candidate.event_type == "delivery_leased"
                and timing_key(candidate) is not None
                and timing_key(candidate)[0] == key[0]
                and timing_key(candidate)[1] >= key[1] + (1 if event.event_type == "retry_scheduled" else 0)
                for candidate in events
            ) if key else False

        last_retry = next((event for event in reversed(events) if event.event_type == "retry_scheduled" and not later_lease(event)), None)
        last_queue = next((event for event in reversed(events) if event.event_type == "delivery_enqueued" and not later_lease(event)), None)
        last_lease = next((event for event in reversed(events) if event.event_type == "delivery_leased"), None)
        last_recovery = next((event for event in reversed(events) if event.event_type in _RECOVERY_EVENT_TYPES), None)
        last_review_start = next((event for event in reversed(events) if event.event_type == "review_wait_started"), None)
        last_review_resolved = next((event for event in reversed(events) if event.event_type == "review_wait_resolved"), None)

        if run.status == "awaiting_review" and last_review_start and (
            not last_review_resolved or last_review_start.sequence > last_review_resolved.sequence
        ):
            delay_cause = "seller_review_wait"
        elif last_retry:
            delay_cause = "retry_backoff"
        elif last_queue:
            delay_cause = "queue_wait"
        elif last_lease:
            delay_cause = "provider_execution"
        elif last_recovery:
            delay_cause = "recovery_reconciled"
        elif milestone == "high_quality_final":
            delay_cause = "rendering_quality"
        elif milestone != "unknown":
            delay_cause = "graph_compute"
        else:
            delay_cause = "unknown"

        start_event = next(
            (event for event in reversed(events) if event.event_type in _SLO_STAGE_START_EVENTS.get(milestone, ())),
            events[0] if events else None,
        )
        completed = next((event for event in reversed(events) if event.event_type in _SLO_COMPLETED_STAGE), None)
        observed = observed_at.replace(tzinfo=None) if observed_at.tzinfo else observed_at
        started = start_event.occurred_at.replace(tzinfo=None) if start_event and start_event.occurred_at.tzinfo else (start_event.occurred_at if start_event else observed)
        elapsed_seconds = max(0, math.ceil((observed - started).total_seconds()))
        metrics = {}
        if db.get_bind().dialect.name == "postgresql" and milestone != "unknown":
            metrics = cls.slo_summary(db, workspace_id=run.workspace_id)["milestones"].get(milestone, {})
        sample_count = int(metrics.get("sample_count") or 0)
        eta_status = "paused_for_review" if delay_cause == "seller_review_wait" else "insufficient_sample"
        eta_range_seconds = None
        if delay_cause != "seller_review_wait" and sample_count >= _SLO_MINIMUM_SAMPLES:
            low = max(0, math.ceil(float(metrics["p50_seconds"]) - elapsed_seconds))
            high = max(0, math.ceil(float(metrics["p90_seconds"]) - elapsed_seconds))
            eta_status = "estimated" if high else "overdue"
            eta_range_seconds = {"min": low, "max": high} if high else None

        scene = (
            db.query(ImageGenerationJobRecord.scene_id)
            .join(ImageGenerationOutboxRecord, ImageGenerationOutboxRecord.image_job_id == ImageGenerationJobRecord.id)
            .filter(
                ImageGenerationOutboxRecord.run_id == run.id,
                ImageGenerationOutboxRecord.status.in_(["queued", "leased", "retry_wait"]),
            )
            .order_by(ImageGenerationOutboxRecord.updated_at.desc())
            .first()
        )
        latest = events[-1] if events else None
        context = {
            "current_stage": milestone,
            "current_stage_ko": stage_ko,
            "delay_cause": delay_cause,
            "delay_cause_ko": _SELLER_DELAY_CAUSE_KO[delay_cause],
            "eta_status": eta_status,
            "eta_range_seconds": eta_range_seconds,
            "updated_at": (latest.occurred_at if latest else observed_at).isoformat(),
            "seller_guidance": seller_guidance("running", delay_cause=delay_cause),
        }
        if scene and _PUBLIC_ID.fullmatch(str(scene[0] or "")):
            context["current_scene_id"] = scene[0]
        if completed:
            context["latest_completed_stage"], context["latest_completed_stage_ko"] = _SLO_COMPLETED_STAGE[completed.event_type]
        return context

    @staticmethod
    def intake_operational_summary(
        db: Session,
        *,
        workspace_id: str | None = None,
        project_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate bounded LG-12I operations from immutable journal events."""

        if db.get_bind().dialect.name != "postgresql":
            raise ValueError("Intake operational aggregation requires PostgreSQL.")
        modes: dict[str, dict[str, Any]] = {}
        for row in db.execute(
            _INTAKE_OPERATIONAL_METRICS_SQL,
            {"workspace_id": workspace_id, "project_id": project_id, "run_id": run_id},
        ).mappings():
            started = int(row["started_run_count"] or 0)
            terminal = int(row["terminal_intake_run_count"] or 0)
            successful = int(row["successful_intake_run_count"] or 0)
            blocked = int(row["unsupported_inference_blocked_run_count"] or 0)
            modes[str(row["input_mode"])] = {
                "started_run_count": started,
                "terminal_intake_run_count": terminal,
                "successful_intake_run_count": successful,
                "success_rate": (successful / terminal) if terminal else None,
                "confirmation_request_count": int(row["confirmation_request_count"] or 0),
                "unsupported_inference_blocked_run_count": blocked,
                "unsupported_inference_blocked_rate": (blocked / started) if started else None,
                "source_fidelity_counts": dict(row["source_fidelity_counts"] or {}),
                "unknown_fact_count": int(row["unknown_fact_count"] or 0),
                "prohibited_inference_count": int(row["prohibited_inference_count"] or 0),
                "clarification_count": int(row["clarification_count"] or 0),
                "completed_intake_count": int(row["completed_intake_count"] or 0),
                "p50_completion_seconds": float(row["p50_completion_seconds"]) if row["p50_completion_seconds"] is not None else None,
                "p90_completion_seconds": float(row["p90_completion_seconds"]) if row["p90_completion_seconds"] is not None else None,
                "failure_reason_counts": dict(row["failure_reason_counts"] or {}),
            }
        return {"window_days": _SLO_WINDOW_DAYS, "modes": modes}

    @classmethod
    def append_recovery_event(
        cls,
        run: AgentRun,
        db: Session,
        *,
        event_type: str,
        job_id: str,
        job_key: str,
        outbox_id: str,
        outbox_key: str,
        attempt: int,
        retry_state: str,
        reason_code: str,
    ) -> tuple[AgentRunEvent, bool, AgentRun]:
        """Atomically append a bounded worker-recovery event and projection."""

        mode = str(dict((run.input_snapshot or {}).get("unified_product_intake") or {}).get("input_mode") or "")
        payload = {
            "stage": str(run.current_stage or ""),
            "status": str(run.status or ""),
            "node_status": "recovered",
            "input_mode": mode,
            "source_fidelity": "recovery",
            "references": {},
            "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
            "recovery": {
                "job": {"id": job_id, "version": 1, "hash": job_key},
                "outbox": {"id": outbox_id, "version": 1, "hash": outbox_key},
                "attempt": attempt,
                "retry_state": retry_state,
                "reason_code": reason_code,
            },
        }
        event, appended, locked = cls.append(run, db, event_type=event_type, payload=payload)
        if appended:
            cls._apply_projection_record(locked, event)
        return event, appended, locked

    @classmethod
    def append_provider_cost_event(cls, run: AgentRun, db: Session, *, ledger: Any) -> tuple[AgentRunEvent, bool, AgentRun]:
        """Append one safe cost fact; raw provider usage remains in the ledger only."""

        state = str(ledger.cost_state)
        event_type = "provider_cost_unknown" if state == "UNKNOWN_AFTER_DISPATCH" else "provider_cost_recorded"
        payload = {
            "stage": "provider_cost",
            "status": "recorded" if state != "UNKNOWN_AFTER_DISPATCH" else "unknown",
            "node_status": "completed",
            "input_mode": "",
            "source_fidelity": "unknown",
            "references": {},
            "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
            "cost": {
                "ledger": {"id": str(ledger.id), "version": int(ledger.provider_adapter_attempt), "hash": str(ledger.semantic_idempotency_key)},
                "cost_state": state,
                "actual_cost": ledger.actual_cost,
                "currency": str(ledger.currency),
                "provider": str(ledger.provider),
                "model": str(ledger.model),
            },
        }
        event, appended, locked = cls.append(
            run, db, event_type=event_type, payload=payload,
            thread_id=run.graph_thread_id or run.id, workspace_id=run.workspace_id, project_id=run.project_id,
        )
        if appended:
            cls._apply_projection_record(locked, event)
        return event, appended, locked

    @staticmethod
    def _event_identity(run: AgentRun, *, checkpoint_id: str | None = None) -> dict[str, Any]:
        return {
            "graph_version": GRAPH_RUNTIME_VERSION,
            "run_id": str(run.id),
            "thread_id": str(run.graph_thread_id or run.id),
            "checkpoint_id": str(checkpoint_id or run.graph_checkpoint_id or ""),
            "event_schema_version": EVENT_SCHEMA_VERSION,
            "projection_version": EVENT_PROJECTION_VERSION,
        }

    @classmethod
    def _lifecycle_payload(
        cls,
        payload: dict[str, Any],
        *,
        transition: str,
        checkpoint_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            **payload,
            "lifecycle": {
                "transition": transition,
                "checkpoint_id": str(checkpoint_id or ""),
            },
        }

    @classmethod
    def append_run_lifecycle(
        cls,
        run: AgentRun,
        db: Session,
        *,
        event_type: str,
        transition: str,
        checkpoint_id: str | None = None,
        status: str | None = None,
    ) -> tuple[AgentRunEvent, bool, AgentRun]:
        if event_type not in _RUN_LIFECYCLE_EVENT_TYPES:
            raise ValueError("Unsupported AgentRun lifecycle event type.")
        mode = str(dict((run.input_snapshot or {}).get("unified_product_intake") or {}).get("input_mode") or "")
        payload = cls._lifecycle_payload(
            {
                "stage": str(run.current_stage or "run"),
                "status": str(status or run.status or "running"),
                "node_status": "completed" if transition in {"completed", "failed", "rebuilt", "recovered"} else transition,
                "input_mode": mode,
                "source_fidelity": "recovery" if transition in {"recovered", "rebuilt"} else "unknown",
                "references": {},
                "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
            },
            transition=transition,
            checkpoint_id=checkpoint_id,
        )
        return cls.append(
            run,
            db,
            event_type=event_type,
            payload=payload,
            thread_id=run.graph_thread_id or run.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            checkpoint_id=checkpoint_id,
        )

    @classmethod
    def append_review_lifecycle(
        cls,
        run: AgentRun,
        db: Session,
        *,
        event_type: str,
        transition: str,
        stage: str,
        decision: str | None = None,
    ) -> tuple[AgentRunEvent, bool, AgentRun]:
        if event_type not in _REVIEW_LIFECYCLE_EVENT_TYPES:
            raise ValueError("Unsupported review lifecycle event type.")
        mode = str(dict((run.input_snapshot or {}).get("unified_product_intake") or {}).get("input_mode") or "")
        payload = {
            "stage": stage[:80],
            "status": "running",
            "node_status": "seller_choice" if decision else "resumed",
            "input_mode": mode,
            "source_fidelity": "unknown",
            "references": {},
            "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
            "lifecycle": {"transition": transition, "checkpoint_id": ""},
        }
        if decision is not None:
            payload["lifecycle"]["decision"] = decision
        # Review lifecycle is deliberately represented by a bounded scalar;
        # comments, raw responses and interrupt bodies never enter the journal.
        return cls.append(
            run,
            db,
            event_type=event_type,
            payload=payload,
            thread_id=run.graph_thread_id or run.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
        )

    @classmethod
    def append_stage_lifecycle(
        cls,
        run: AgentRun,
        db: Session,
        *,
        payload: dict[str, Any],
        stage: str,
        node_status: str,
        status: str,
    ) -> list[AgentRunEvent]:
        """Record the compact stage transition around one graph node update."""

        prior = (
            db.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run.id)
            .order_by(AgentRunEvent.sequence.desc())
            .all()
        )
        prior_stage_terminal = any(
            record.event_type in {"stage_completed", "stage_skipped", "stage_failed", "stage_blocked"}
            and str((record.payload_json or {}).get("stage") or "") == stage
            for record in prior
        )
        events: list[AgentRunEvent] = []
        if prior_stage_terminal:
            event_type, transition = "stage_reentered", "reentered"
            event, _inserted, _locked = cls.append(
                run,
                db,
                event_type=event_type,
                payload=cls._lifecycle_payload(payload, transition=transition),
                thread_id=run.graph_thread_id or run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
            )
            events.append(event)
        else:
            event, _inserted, _locked = cls.append(
                run,
                db,
                event_type="stage_started",
                payload=cls._lifecycle_payload(payload, transition="started"),
                thread_id=run.graph_thread_id or run.id,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
            )
            events.append(event)
        terminal_type = {
            "skipped": "stage_skipped",
            "failed": "stage_failed",
            "blocked": "stage_blocked",
            "deferred": "stage_blocked",
            "needs_review": "stage_blocked",
        }.get(node_status, "stage_completed")
        terminal, _inserted, _locked = cls.append(
            run,
            db,
            event_type=terminal_type,
            payload=cls._lifecycle_payload(payload, transition=terminal_type.removeprefix("stage_")),
            thread_id=run.graph_thread_id or run.id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
        )
        events.append(terminal)
        return events

    @staticmethod
    def quality_lifecycle_event(stage: str, node_status: str, quality: dict[str, Any]) -> tuple[str, str] | None:
        if not quality and "quality" not in stage:
            return None
        lowered = stage.lower()
        if "stale" in lowered:
            return "quality_stale", "blocked"
        if "blocked" in lowered or node_status == "blocked":
            return "quality_blocked", "blocked"
        if "promotion_ready" in lowered:
            return None
        if "rework_child_frozen" in lowered or "re_evaluation" in lowered:
            return "quality_re_evaluated", "completed"
        if "rework" in lowered or node_status == "needs_review":
            return "quality_rework_required", "blocked"
        return "quality_evaluated", "completed"

    @classmethod
    def append(
        cls, run: AgentRun, db: Session, *, event_type: str, payload: dict[str, Any], thread_id: str | None = None,
        workspace_id: str | None = None, project_id: str | None = None, checkpoint_id: str | None = None,
    ) -> tuple[AgentRunEvent, bool, AgentRun]:
        """Append exactly once while the AgentRun row serializes its sequence."""

        payload = {**payload, "identity": cls._event_identity(run, checkpoint_id=checkpoint_id)}
        cls.validate_payload(event_type, payload)
        # Lock before SQLAlchemy can autoflush a dirty AgentRun projection.
        # Otherwise graph dispatch and the fast provider worker can each write
        # a row version, then deadlock while both try to journal the next event.
        with db.no_autoflush:
            locked = db.query(AgentRun).filter(AgentRun.id == run.id).with_for_update().one_or_none()
        if locked is None or (workspace_id is not None and locked.workspace_id != workspace_id) or (project_id is not None and locked.project_id != project_id):
            raise GraphRunNotFound("AgentRun event scope does not match the persisted run.")
        expected_thread = locked.graph_thread_id or locked.id
        if thread_id is not None and thread_id != expected_thread:
            raise GraphRunThreadMismatch("AgentRun event thread does not match the persisted run.")
        semantic_payload = dict(payload)
        semantic_payload.pop("identity", None)
        canonical = json.dumps({"event_type": event_type, "payload": semantic_payload}, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        key = hashlib.sha256(f"{locked.id}:{canonical}".encode("utf-8")).hexdigest()
        existing = db.query(AgentRunEvent).filter_by(run_id=locked.id, idempotency_key=key).one_or_none()
        if existing is not None:
            return existing, False, locked
        sequence = int(db.query(func.coalesce(func.max(AgentRunEvent.sequence), 0)).filter(AgentRunEvent.run_id == locked.id).scalar() or 0) + 1
        occurred_at = (
            db.execute(text("SELECT clock_timestamp()")).scalar_one()
            if db.get_bind().dialect.name == "postgresql"
            else datetime.datetime.utcnow()
        )
        record = AgentRunEvent(
            run_id=locked.id,
            sequence=sequence,
            event_type=event_type,
            idempotency_key=key,
            payload_json=payload,
            occurred_at=occurred_at,
        )
        db.add(record)
        db.flush()
        return record, True, locked

    @classmethod
    def rebuild_projection(
        cls, run: AgentRun, db: Session, *, from_sequence: int | None = None, thread_id: str | None = None,
    ) -> AgentRun:
        """Replay a full journal or the unapplied suffix without graph execution."""

        locked = db.query(AgentRun).filter(AgentRun.id == run.id).with_for_update().one_or_none()
        if locked is None:
            raise GraphRunNotFound("AgentRun event projection does not exist.")
        if thread_id is not None and thread_id != (locked.graph_thread_id or locked.id):
            raise GraphRunThreadMismatch("AgentRun event projection thread does not match the persisted run.")
        start = 0 if from_sequence is None else max(0, from_sequence)
        events = db.query(AgentRunEvent).filter(AgentRunEvent.run_id == locked.id, AgentRunEvent.sequence > start).order_by(AgentRunEvent.sequence).all()
        if from_sequence is None:
            outputs = dict(locked.outputs_json or {})
            outputs.pop("langgraph_event_projection", None)
            outputs.pop("provider_cost_projection", None)
            locked.outputs_json = outputs
            locked.last_applied_event_sequence = 0
            locked.actual_cost = 0.0
        for record in events:
            cls._apply_projection_record(locked, record)
        locked.event_projection_version = EVENT_PROJECTION_VERSION
        db.add(locked)
        db.commit()
        db.refresh(locked)
        return locked

    @classmethod
    def _apply_projection_record(cls, run: AgentRun, record: AgentRunEvent) -> None:
        payload = dict(record.payload_json or {})
        cls.validate_payload(record.event_type, payload)
        if record.event_type in _RUN_LIFECYCLE_EVENT_TYPES:
            run_status = {
                "run_started": "running",
                "run_completed": "completed",
                "run_failed": "failed",
                "run_cancelled": "cancelled",
            }.get(record.event_type)
            if run_status:
                run.status = run_status
                run.completed_at = record.occurred_at.replace(tzinfo=None) if run_status == "completed" else None
            run.last_applied_event_sequence = record.sequence
            return
        if record.event_type in _STAGE_LIFECYCLE_EVENT_TYPES:
            transition = str(dict(payload.get("lifecycle") or {}).get("transition") or "")
            if transition in {"completed", "skipped", "failed", "blocked", "reentered"}:
                run.current_stage = payload["stage"] or run.current_stage
                if payload["status"]:
                    run.status = payload["status"]
            run.last_applied_event_sequence = record.sequence
            return
        if record.event_type in _REVIEW_LIFECYCLE_EVENT_TYPES:
            run.last_applied_event_sequence = record.sequence
            return
        if record.event_type in _TIMING_EVENT_TYPES:
            run.last_applied_event_sequence = record.sequence
            return
        outputs = dict(run.outputs_json or {})
        if record.event_type in _COST_EVENT_TYPES:
            prior = dict(outputs.get("provider_cost_projection") or {})
            cost = payload["cost"]
            actual_cost = cost["actual_cost"]
            known_actual_cost = float(prior.get("known_actual_cost") or 0.0)
            if actual_cost is not None:
                known_actual_cost += float(actual_cost)
            unknown_attempt_count = int(prior.get("unknown_attempt_count") or 0) + int(cost["cost_state"] == "UNKNOWN_AFTER_DISPATCH")
            outputs["provider_cost_projection"] = {
                "known_actual_cost": known_actual_cost,
                "has_unknown_cost": bool(unknown_attempt_count),
                "actual_cost_complete": not bool(unknown_attempt_count),
                "attempt_count": int(prior.get("attempt_count") or 0) + 1,
                "unknown_attempt_count": unknown_attempt_count,
            }
            run.actual_cost = known_actual_cost
        else:
            outputs["langgraph_event_projection"] = {
                "input_mode": payload["input_mode"],
                "source_fidelity": payload["source_fidelity"],
                "references": payload["references"],
                "metrics": payload["metrics"],
            }
        runtime = dict(outputs.get("langgraph_runtime") or {})
        runtime.update({"thread_id": run.graph_thread_id, "last_event": {"type": record.event_type, **payload}})
        if record.event_type not in _COST_EVENT_TYPES:
            runtime["last_stage"] = payload["stage"]
        outputs["langgraph_runtime"] = runtime
        run.outputs_json = outputs
        if record.event_type not in _COST_EVENT_TYPES:
            run.current_stage = payload["stage"] or run.current_stage
            run.status = payload["status"] or run.status
        run.last_applied_event_sequence = record.sequence


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
        existing = {key: value for key, value in error.items() if key in {"code", "stage", "recovery_action", "recoverable"}}
    else:
        raw_message = str(error)
        existing = {}

    if str(existing.get("code") or getattr(error, "code", "")) == "SAFE_REFERENCE_ASSET_REQUIRED":
        return {
            **existing,
            "stage": "visual_planning",
            "code": "SAFE_REFERENCE_ASSET_REQUIRED",
            "message": "Safe reference asset is required.",
            "user_message": (
                "AI 비주얼 기획에 사용할 안전한 권리 보유 사진이 없습니다. "
                "글자·로고가 없는 제품 사진을 권리 보유 이미지로 추가해 주세요."
            ),
            "recovery_action": "upload_safe_reference_asset_and_retry",
            "source": "langgraph",
            "recoverable": True,
        }
    code = bounded_error_code(existing.get("code") or getattr(error, "code", ""))
    raw_message = ""
    if code in {"IMAGE_PROVIDER_NOT_CONFIGURED", "IMAGE_JOB_PREPARE_FAILED", "IMAGE_JOB_DISPATCH_FAILED"}:
        return {
            **existing,
            "stage": "generation_pending",
            "code": code,
            "message": "Image generation is unavailable.",
            "user_message": raw_message or "이미지 생성 준비를 확인한 뒤 같은 실행을 다시 시작해 주세요.",
            "recovery_action": "configure_provider_or_fix_scene_and_resume",
            "source": "langgraph",
            "recoverable": True,
        }
    return {
        **existing,
        "stage": str(existing.get("stage") or fallback_stage or "graph_execution"),
        "code": code,
        "message": "Graph execution failed.",
        "user_message": str(
            existing.get("user_message")
            or "그래프 실행 중 오류가 발생했습니다. 원인을 해결한 뒤 같은 실행을 다시 시도할 수 있습니다."
        ),
        "recovery_action": str(existing.get("recovery_action") or "retry_same_run"),
        "source": "langgraph",
        "recoverable": bool(existing.get("recoverable", True)),
    }


def _execution_view(
    run: AgentRun,
    delay_context: dict[str, Any] | None = None,
    progress_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = [_failure_contract(item, run.current_stage) for item in (run.error_log or [])]
    for error in errors:
        error["code"] = bounded_error_code(error.get("code"))
        error["seller_guidance"] = seller_guidance(
            "failed",
            code=error["code"],
            retryable=bool(error.get("recoverable", True)),
        )
    result = {
        "recoverable": run.status == "failed",
        "errors": errors,
        "last_error": errors[-1] if errors else None,
    }
    if delay_context is not None:
        result["delay_context"] = delay_context
    if progress_preview is not None:
        result["progress_preview"] = progress_preview
    return result


_PUBLIC_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_PUBLIC_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PUBLIC_CODE = re.compile(r"[A-Z][A-Z0-9_]{1,99}\Z")
_PUBLIC_VALIDATION_CHECKS = frozenset({"identity", "ocr", "crop", "resolution", "safety", "rights"})
_PUBLIC_VALIDATION_STATES = frozenset({"pending", "passed", "approved", "needs_review", "blocked", "failed", "not_run"})


def _public_id(value: Any) -> str | None:
    value = str(value or "")
    return value if _PUBLIC_ID.fullmatch(value) else None


def _public_hash(value: Any) -> str | None:
    value = str(value or "").lower()
    return value if _PUBLIC_HASH.fullmatch(value) else None


def _public_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _put_public_number(target: dict[str, Any], key: str, value: Any) -> None:
    """Copy a finite JSON number without dropping the public value ``0``."""
    item = _public_number(value)
    if item is not None:
        target[key] = item


def _public_ref(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    if identifier := _public_id(source.get("id")):
        result["id"] = identifier
    for key in ("version", "schema_version"):
        if isinstance(source.get(key), int) and source[key] >= 0:
            result[key] = source[key]
    for key in ("hash", "canonical_hash", "snapshot_hash"):
        if digest := _public_hash(source.get(key)):
            result[key] = digest
    return result


def _public_string_list(value: Any, *, limit: int = 20) -> list[str]:
    return [item for item in (_public_id(raw) for raw in list(value or [])[:limit]) if item]


def _public_count(value: Any) -> int:
    return min(len(value), 1000) if isinstance(value, (list, tuple)) else 0


def _public_rights(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    return {
        key: item
        for key in ("confirmation_state", "final_use_status")
        if (item := _public_id(source.get(key)))
    }


def _public_product_truth(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    if not source:
        return {}
    result = {
        "truth_version": _public_ref(source.get("truth_version")),
        "fact_count": _public_count(source.get("fact_candidates")),
        "unknown_count": _public_count(source.get("unknown_facts")),
        "conflict_count": _public_count(source.get("conflict_facts")),
        "prohibited_inference_count": _public_count(source.get("prohibited_inferences")),
        "observation_risk_count": _public_count(source.get("observation_risks")),
    }
    if schema_version := _public_id(source.get("schema_version")):
        result["schema_version"] = schema_version
    if isinstance(source.get("requires_review"), bool):
        result["requires_review"] = source["requires_review"]
    return result


def _public_cost_plan(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    if digest := _public_hash(source.get("cost_plan_hash")):
        result["cost_plan_hash"] = digest
    for key in ("provider", "model", "currency", "status"):
        if item := _public_id(source.get(key)):
            result[key] = item
    for key in ("scene_count", "total_estimated_cost"):
        _put_public_number(result, key, source.get(key))
    scenes: list[dict[str, Any]] = []
    for raw in list(source.get("scenes") or [])[:20]:
        row = dict(raw or {}) if isinstance(raw, dict) else {}
        scene: dict[str, Any] = {}
        for key in ("scene_id", "role", "model", "output_size"):
            if item := _public_id(row.get(key)):
                scene[key] = item
        # The persisted scene title can be prompt-derived; use its stable ID
        # as the browser label instead of passing text through this boundary.
        if scene_id := scene.get("scene_id"):
            scene["title"] = scene_id
        _put_public_number(scene, "estimated_cost", row.get("estimated_cost"))
        if scene:
            scenes.append(scene)
    if scenes:
        result["scenes"] = scenes
    return result


def _public_generation(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    for key in ("estimated_cost", "actual_cost", "pending_count", "review_count", "required_scene_count", "approved_count"):
        _put_public_number(result, key, source.get(key))
    for key in (
        "failed_job_ids",
        "remaining_required_scene_ids",
        "approved_generated_asset_ids",
        "review_generated_asset_ids",
    ):
        result[key] = _public_string_list(source.get(key))
    for key in ("image_generation_required", "all_required_scenes_approved", "cost_approved", "validation_complete"):
        if isinstance(source.get(key), bool):
            result[key] = source[key]
    for key in ("next_action", "error_code"):
        item = str(source.get(key) or "")
        if key == "error_code":
            if item:
                result[key] = bounded_error_code(item, "IMAGE_GENERATION_FAILED")
        elif _PUBLIC_ID.fullmatch(item):
            result[key] = item
    if source.get("error_code"):
        result["seller_guidance"] = seller_guidance("failed", code=result["error_code"])
    result["cost_plan"] = _public_cost_plan(source.get("cost_plan"))
    jobs: list[dict[str, Any]] = []
    for raw in list(source.get("jobs") or [])[:30]:
        row = dict(raw or {}) if isinstance(raw, dict) else {}
        job: dict[str, Any] = {}
        for key in ("job_id", "scene_id", "section_id", "role", "status", "output_asset_id", "outbox_status"):
            if key == "output_asset_id" and key in row:
                job[key] = _public_id(row.get(key))
            elif item := _public_id(row.get(key)):
                job[key] = item
        code = str(row.get("error_code") or "")
        if code:
            job["error_code"] = bounded_error_code(code, "IMAGE_GENERATION_FAILED")
        for key in ("estimated_cost", "actual_cost", "generation_attempt"):
            _put_public_number(job, key, row.get(key))
        if isinstance(row.get("required_for_completion"), bool):
            job["required_for_completion"] = row["required_for_completion"]
        job["source_asset_ids"] = _public_string_list(row.get("source_asset_ids"))
        validation = dict(row.get("validation") or {}) if isinstance(row.get("validation"), dict) else {}
        safe_validation: dict[str, Any] = {}
        if schema_version := _public_id(validation.get("schema_version")):
            safe_validation["schema_version"] = schema_version
        if validation.get("status") in _PUBLIC_VALIDATION_STATES:
            safe_validation["status"] = validation["status"]
        checks = {
            key: value for key, value in dict(validation.get("checks") or {}).items()
            if key in _PUBLIC_VALIDATION_CHECKS and value in _PUBLIC_VALIDATION_STATES
        }
        if checks:
            safe_validation["checks"] = checks
        risk_codes = [code for code in list(validation.get("risk_codes") or [])[:20] if _PUBLIC_CODE.fullmatch(str(code))]
        if risk_codes:
            safe_validation["risk_codes"] = risk_codes
        if safe_validation:
            job["validation"] = safe_validation
        if job.get("error_code"):
            job["seller_guidance"] = seller_guidance("failed", code=job["error_code"])
        if job:
            jobs.append(job)
    result["jobs"] = jobs
    return result


def _public_intake(value: Any, pending_confirmation: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    envelope = dict(source.get("envelope") or {}) if isinstance(source.get("envelope"), dict) else {}
    result: dict[str, Any] = {}
    for key in ("input_mode", "requested_generation_mode", "next_action"):
        item = _public_id(source.get(key) or envelope.get(key))
        if item:
            result[key] = item
    result["target_channels"] = _public_string_list(source.get("target_channels") or envelope.get("target_channels"), limit=4)
    if truth := _public_product_truth(source.get("product_truth")):
        result["product_truth"] = truth
    blocked_truth = dict(source.get("truth") or {}) if isinstance(source.get("truth"), dict) else {}
    if status := _public_id(blocked_truth.get("status")):
        result["truth"] = {"status": status, "reason_code": "SOURCE_INTEGRITY_BLOCKED"}

    mode = result.get("input_mode")
    if mode == "manual" and isinstance(source.get("manual_source"), dict):
        manual = dict(source["manual_source"])
        public_manual = {
            "source_snapshot": _public_ref(manual.get("source_snapshot")),
            "manual_artifact_ref": _public_ref(manual.get("manual_artifact_ref")),
            "fact_count": _public_count(manual.get("fact_candidates")),
            "unknown_count": _public_count(manual.get("unknown_candidates")),
            "conflict_count": _public_count(manual.get("conflict_candidates")),
            "creative_direction_count": _public_count(manual.get("creative_directions")),
            "rights": _public_rights(manual.get("rights")),
        }
        if schema_version := _public_id(manual.get("schema_version")):
            public_manual["schema_version"] = schema_version
        result["manual_source"] = public_manual
    elif mode == "owned_product_url":
        if isinstance(source.get("owned_url_source"), dict):
            owned = dict(source["owned_url_source"])
            public_owned = {
                "source_snapshot": _public_ref(owned.get("source_snapshot")),
                "capture_request_ref": _public_ref(owned.get("capture_request_ref")),
                "capture_artifact_ref": _public_ref(owned.get("capture_artifact_ref")),
                "image_asset_count": _public_count(owned.get("image_asset_refs")),
                "rights": _public_rights(owned.get("rights")),
            }
            if schema_version := _public_id(owned.get("schema_version")):
                public_owned["schema_version"] = schema_version
            result["owned_url_source"] = public_owned
        elif isinstance(source.get("owned_url_capture"), dict):
            capture = dict(source["owned_url_capture"])
            public_capture = {"capture_request_count": _public_count(capture.get("capture_request_refs"))}
            if status := _public_id(capture.get("capture_status")):
                public_capture["capture_status"] = status
            if isinstance(capture.get("recoverable"), bool):
                public_capture["recoverable"] = capture["recoverable"]
            result["owned_url_capture"] = public_capture
    elif mode == "photo_only":
        photo = source.get("photo_observation") or source.get("photo_source")
        if isinstance(photo, dict):
            photo = dict(photo)
            public_photo = {
                "source_snapshot": _public_ref(photo.get("source_snapshot")),
                "photo_observation_artifact_ref": _public_ref(photo.get("photo_observation_artifact_ref")),
                "source_asset_count": _public_count(photo.get("source_asset_refs")),
                "observation_count": _public_count(photo.get("observations")),
                "unknown_count": _public_count(photo.get("unknown_candidates")),
                "conflict_count": _public_count(photo.get("conflict_candidates")),
                "prohibited_inference_count": _public_count(photo.get("prohibited_inference_fields")),
                "rights": _public_rights(photo.get("rights")),
            }
            for key in ("observation_status", "failure_reason"):
                if item := _public_id(photo.get(key)):
                    public_photo[key] = item
            if schema_version := _public_id(photo.get("schema_version")):
                public_photo["schema_version"] = schema_version
            if isinstance(photo.get("recoverable"), bool):
                public_photo["recoverable"] = photo["recoverable"]
            result["photo_observation"] = public_photo
    for key, ref_key in (("creative_brief", "brief_version"), ("commerce_creative_master", "master_version")):
        nested = dict(source.get(key) or {}) if isinstance(source.get(key), dict) else {}
        result[key] = {ref_key: _public_ref(nested.get(ref_key))}
    confirmation = pending_confirmation if isinstance(pending_confirmation, dict) else source.get("seller_confirmation")
    plan = dict(confirmation or {}) if isinstance(confirmation, dict) else {}
    safe_plan: dict[str, Any] = {}
    for key in ("confirmation_required", "confirmation_ready"):
        if isinstance(plan.get(key), bool):
            safe_plan[key] = plan[key]
    if digest := _public_hash(plan.get("resume_request_hash")):
        safe_plan["resume_request_hash"] = digest
    if isinstance(plan.get("confirmation_cycle"), int) and plan["confirmation_cycle"] > 0:
        safe_plan["confirmation_cycle"] = plan["confirmation_cycle"]
    safe_plan["confirmation_version"] = _public_ref(plan.get("confirmation_version"))
    clarifications: list[dict[str, Any]] = []
    for raw in list(plan.get("clarifications") or [])[:3]:
        row = dict(raw or {}) if isinstance(raw, dict) else {}
        clarification = {key: item for key in ("clarification_id", "field_id") if (item := _public_id(row.get(key)))}
        for key in ("type", "question_code", "allowed_answer_type"):
            if item := _public_id(row.get(key)):
                clarification[key] = item
        if digest := _public_hash(row.get("clarification_hash")):
            clarification["clarification_hash"] = digest
        if isinstance(row.get("priority"), int) and row["priority"] >= 0:
            clarification["priority"] = row["priority"]
        if isinstance(row.get("required"), bool):
            clarification["required"] = row["required"]
        options: list[dict[str, str]] = []
        for index, raw_option in enumerate(list(row.get("allowed_options") or [])[:10]):
            option = dict(raw_option or {}) if isinstance(raw_option, dict) else {}
            if observation_id := _public_id(option.get("observation_id")):
                options.append({
                    "id": observation_id,
                    "observation_id": observation_id,
                    "label": f"관찰 {index + 1}",
                })
        if options:
            clarification["allowed_options"] = options
        if clarification:
            clarifications.append(clarification)
    safe_plan["clarifications"] = clarifications
    result["seller_confirmation"] = safe_plan
    return result


def _public_rendering(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    return {"detail_page_version": _public_ref(source.get("detail_page_version"))}


def _public_quality(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    for key in ("quality_bar_verdict", "routing_code"):
        item = str(source.get(key) or "")
        if _PUBLIC_CODE.fullmatch(item):
            result[key] = item
    for key in ("seller_review_required",):
        if isinstance(source.get(key), bool):
            result[key] = source[key]
    for key in ("rework_attempt_count", "max_rework_attempts"):
        _put_public_number(result, key, source.get(key))
    for key in ("current_detail_page_ref", "quality_report_ref", "quality_bar_ref"):
        result[key] = _public_ref(source.get(key))
    return result


def _public_canvas(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    result: dict[str, Any] = {"canonical_page_assembly_input": {"sections": []}, "element_groups": []}
    if isinstance(source.get("revision"), int) and source["revision"] >= 0:
        result["revision"] = source["revision"]
    canonical = dict(source.get("canonical_page_assembly_input") or {}) if isinstance(source.get("canonical_page_assembly_input"), dict) else {}
    for raw in list(canonical.get("sections") or [])[:30]:
        row = dict(raw or {}) if isinstance(raw, dict) else {}
        if not (section_id := _public_id(row.get("section_id"))):
            continue
        section: dict[str, Any] = {"section_id": section_id, "canvas_elements": []}
        canvas = dict(row.get("canvas") or {}) if isinstance(row.get("canvas"), dict) else {}
        safe_canvas = {key: canvas[key] for key in ("is_visible", "height_px") if isinstance(canvas.get(key), (bool, int, float))}
        if safe_canvas:
            section["canvas"] = safe_canvas
        for raw_element in list(row.get("canvas_elements") or [])[:100]:
            element = dict(raw_element or {}) if isinstance(raw_element, dict) else {}
            safe_element = {
                key: item for key in ("element_id", "kind", "group_id", "asset_id", "asset_content_hash")
                if (item := (_public_hash(element.get(key)) if key == "asset_content_hash" else _public_id(element.get(key))))
            }
            for key in ("x", "y", "width", "height", "z_index"):
                _put_public_number(safe_element, key, element.get(key))
            for key in ("locked", "deleted"):
                if isinstance(element.get(key), bool):
                    safe_element[key] = element[key]
            if safe_element:
                section["canvas_elements"].append(safe_element)
        result["canonical_page_assembly_input"]["sections"].append(section)
    for raw in list(source.get("element_groups") or [])[:100]:
        row = dict(raw or {}) if isinstance(raw, dict) else {}
        group = {key: item for key in ("group_id", "section_id") if (item := _public_id(row.get(key)))}
        group["child_element_ids"] = _public_string_list(row.get("child_element_ids"), limit=100)
        if isinstance(row.get("locked"), bool):
            group["locked"] = row["locked"]
        if group.get("group_id") and group.get("section_id"):
            result["element_groups"].append(group)
    return result


def _public_edit(value: Any) -> dict[str, Any]:
    source = dict(value or {}) if isinstance(value, dict) else {}
    restore = dict(source.get("version_restore") or {}) if isinstance(source.get("version_restore"), dict) else {}
    return {"version_restore": {"detail_page_version_id": _public_id(restore.get("detail_page_version_id"))}}


def _progressive_preview_refs(run: AgentRun, checkpoint_values: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return only persisted, server-owned frozen-version references."""

    checkpoint = checkpoint_values if isinstance(checkpoint_values, dict) else {}
    projection = dict(run.outputs_json or {})
    state_sources = (
        checkpoint,
        {
            "rendering": projection.get("langgraph_page_rendering"),
            "quality": projection.get("langgraph_quality"),
            "edit": projection.get("langgraph_edit"),
        },
    )
    refs: list[dict[str, Any]] = []
    for state in state_sources:
        rendering = dict(state.get("rendering") or {})
        quality = dict(state.get("quality") or {})
        edit = dict(state.get("edit") or {})
        refs.extend((
            dict(quality.get("current_detail_page_ref") or {}),
            dict(rendering.get("detail_page_version") or {}),
            dict(edit.get("base_version") or {}),
        ))
    return [ref for ref in refs if _public_id(ref.get("id")) and _public_hash(ref.get("hash") or ref.get("snapshot_hash"))]


def _progressive_pending_sections(
    run: AgentRun,
    checkpoint_values: dict[str, Any] | None,
    *,
    section_ids: set[str],
    scene_sections: dict[str, str],
) -> set[str]:
    """Mark only the active, exact LG-11/12 target as not preview-complete."""

    if run.status in {"completed", "failed", "cancelled"}:
        return set()
    checkpoint = checkpoint_values if isinstance(checkpoint_values, dict) else {}
    projection = dict(run.outputs_json or {})
    quality = dict(checkpoint.get("quality") or projection.get("langgraph_quality") or {})
    edit = dict(checkpoint.get("edit") or projection.get("langgraph_edit") or {})
    rework_active = "rework" in str(run.current_stage or "") or str(quality.get("quality_bar_verdict") or "") == "FAIL"
    pending: set[str] = set()
    broad_target = False

    def mark_target(value: Any) -> None:
        nonlocal broad_target
        target = dict(value or {}) if isinstance(value, dict) else {}
        target_type = str(target.get("type") or target.get("target_type") or "")
        target_id = str(target.get("section_id") or target.get("id") or target.get("target_id") or "")
        if target_type in {"scene", "asset"}:
            target_id = scene_sections.get(target_id, "")
        elif target_type in {"copy_field", "copy"}:
            match = re.fullmatch(r"copy-field:([^:]+):[^:]+", target_id)
            target_id = match.group(1) if match else target_id
        elif target_type and target_type not in {"frozen_section", "section", "scene", "asset", "copy_field", "copy"}:
            broad_target = True
            return
        if target_id in section_ids:
            pending.add(target_id)
        elif target_id:
            broad_target = True

    if rework_active:
        attempt = dict(quality.get("active_attempt") or {})
        if not attempt.get("child_detail_page_ref"):
            mark_target(attempt.get("logical_target_ref") or attempt.get("target_ref"))
            for target in list(attempt.get("target_refs") or []):
                mark_target(target)
            for target in list(quality.get("rework_targets") or []):
                item = dict(target or {}) if isinstance(target, dict) else {}
                mark_target(item.get("logical_target_ref") or item.get("target_ref"))
    if run.mode == "lg11_edit" and bool(edit.get("impact_preview")):
        affected = dict(dict(edit.get("impact_preview") or {}).get("affected_artifacts") or {})
        targets = {str(item) for item in list(affected.get("section_ids") or []) if str(item) in section_ids}
        if targets:
            pending.update(targets)
        elif any(affected.get(key) for key in ("scene_ids", "copy_artifacts", "style_layout_tokens", "facts")):
            broad_target = True
    return set(section_ids) if broad_target else pending


def seller_progressive_preview(
    run: AgentRun,
    db: Session,
    *,
    checkpoint_values: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Bounded section readiness from the current immutable page lineage.

    The projection deliberately reads no provider output or checkpoint body.
    A candidate must be the project-scoped current frozen version and must
    pass LG-11's existing immutable snapshot validator.
    """

    version: DetailPageVersion | None = None
    frozen: dict[str, Any] | None = None
    for ref in _progressive_preview_refs(run, checkpoint_values):
        candidate = (
            db.query(DetailPageVersion)
            .filter(DetailPageVersion.id == ref["id"], DetailPageVersion.project_id == run.project_id, DetailPageVersion.is_final.is_(True))
            .one_or_none()
        )
        if candidate is None or str(dict(candidate.sections_json or {}).get("snapshot_hash") or "") != str(ref.get("hash") or ref.get("snapshot_hash")):
            continue
        try:
            from src.services.page_finalization_service import EditIntentValidationError, _lg11_frozen_edit_targets

            frozen = _lg11_frozen_edit_targets(candidate)
        except (EditIntentValidationError, ValueError):
            continue
        version = candidate
        break
    if version is None or frozen is None:
        return None

    sections = dict(frozen["sections"])
    scene_sections = {
        scene_id: str(scene.get("section_id") or "")
        for scene_id, scene in dict(frozen["scenes"]).items()
        if str(scene.get("section_id") or "") in sections
    }
    eligible = {
        section_id
        for section_id, section in sections.items()
        if str(section.get("rendering_mode") or "") in {"approved_asset", "seller_owned_fallback", "information_only"}
        and (not bool(section.get("image_required")) or bool(section.get("approved_assets") or section.get("seller_owned_fallback_assets")))
    }
    if not eligible:
        return None
    pending = _progressive_pending_sections(run, checkpoint_values, section_ids=eligible, scene_sections=scene_sections)
    rendered_sections = {
        str(item.get("id") or item.get("key") or ""): dict(item)
        for item in list(dict(version.sections_json or {}).get("sections") or [])
        if isinstance(item, dict)
    }

    def completed_section(section_id: str) -> dict[str, str]:
        result = {"section_id": section_id}
        title = " ".join(str(rendered_sections.get(section_id, {}).get("title") or "").split())[:120]
        if title and "//" not in title and "@" not in title:
            result["summary"] = title
        return result

    completed_ids = sorted(eligible - pending, key=lambda item: int(dict(sections[item]).get("sort_order") or 0))
    pending_ids = sorted(pending, key=lambda item: int(dict(sections[item]).get("sort_order") or 0))
    total = len(eligible)
    completed = len(completed_ids)
    return {
        "completed_sections": [completed_section(section_id) for section_id in completed_ids],
        "pending_sections": [{"section_id": section_id} for section_id in pending_ids],
        "completed_count": completed,
        "total_sections": total,
        "progress_percent": (completed * 100) // total,
        "current_section": pending_ids[0] if pending_ids else None,
        "preview_version": _public_ref({"id": version.id, "snapshot_hash": frozen["snapshot_hash"]}),
    }


_PUBLIC_REVIEW_STAGES = frozenset({
    "input_review", "evidence_review", "planning_review", "generation_pending", "provider_wait", "image_review",
    "edit_confirmation", "canvas_edit", "seller_confirmation", "quality_review",
})
_PUBLIC_REVIEW_SCHEMAS = frozenset({"lg4-v1", "lg5-v1", "lg11-v1", "lg12i-v1"})
_PUBLIC_REVIEW_DECISIONS = {
    "input_review": ("approve", "reject"),
    "evidence_review": ("approve", "reject"),
    "planning_review": ("approve", "reject"),
    "generation_pending": ("approve", "defer"),
    "provider_wait": ("refresh",),
    "image_review": ("approve", "reject", "regenerate", "upload"),
    "edit_confirmation": ("approve", "reject"),
    "canvas_edit": ("apply", "undo", "redo", "commit"),
    "seller_confirmation": ("submit", "approve"),
    "quality_review": ("approve", "reject"),
}


def _public_review(value: Any) -> dict[str, Any] | None:
    source = dict(value or {}) if isinstance(value, dict) else {}
    stage = str(source.get("review_stage") or source.get("stage") or "")
    if stage not in _PUBLIC_REVIEW_STAGES:
        return None
    schema_version = str(source.get("schema_version") or "")
    guidance = seller_guidance("awaiting_review", review_stage=stage)
    result = {
        "schema_version": schema_version if schema_version in _PUBLIC_REVIEW_SCHEMAS else "lg4-v1",
        "review_stage": stage,
        "stage": stage,
        # Fixed labels prevent a persisted rejection comment or prompt-derived text
        # from becoming a browser response through the pending interrupt object.
        "title": guidance["cause_ko"],
        "description": guidance["action_ko"],
        "seller_guidance": guidance,
        "allowed_decisions": list(_PUBLIC_REVIEW_DECISIONS[stage]),
    }
    context = dict(source.get("context") or {}) if isinstance(source.get("context"), dict) else {}
    slo08_choice = dict(context.get("slo08_choice") or {}) if isinstance(context.get("slo08_choice"), dict) else {}
    if stage == "quality_review" and slo08_choice.get("choice_required"):
        actions = [
            decision for decision in list(source.get("allowed_decisions") or [])
            if decision in {"fallback", "wait"}
        ]
        if actions:
            guidance = {
                "status": "awaiting_review", "safe_code": None,
                "cause_ko": "이미지 생성이 두 번 완료되지 않았습니다.",
                "action_ko": "기존 사진으로 계속하거나 대기 상태를 유지해 주세요.",
                "action_type": "choose_fallback_or_wait", "retryable": False, "review_required": True,
            }
            result.update({
                "title": guidance["cause_ko"], "description": guidance["action_ko"],
                "seller_guidance": guidance, "allowed_decisions": actions,
                "seller_choice": {
                    "choice_required": True, "available_actions": actions,
                    "automatic_attempts": int(slo08_choice.get("automatic_attempts") or 2),
                },
            })
    cost_plan = _public_cost_plan(dict(context.get("generation") or {}).get("cost_plan"))
    confirmation = _public_intake({}, context.get("seller_confirmation")).get("seller_confirmation")
    if cost_plan or confirmation:
        result["context"] = {
            "generation": {"cost_plan": cost_plan},
            "seller_confirmation": confirmation,
        }
    return result


def seller_slo08_choice(run: AgentRun) -> dict[str, Any] | None:
    """Expose the same bounded exhausted-retry choice in project status."""

    if run.status != "awaiting_review":
        return None
    pending = dict((dict(run.outputs_json or {}).get("langgraph_review") or {}).get("pending") or {})
    public = _public_review(pending)
    choice = dict((public or {}).get("seller_choice") or {})
    return choice or None


@dataclass(frozen=True)
class GraphRunStateView:
    run_id: str
    thread_id: str
    status: str
    current_stage: str
    checkpoint_id: str | None
    values: dict[str, Any]
    next_nodes: list[str]


def _browser_checkpoint_values(
    run: AgentRun,
    snapshot: Any,
    *,
    delay_context: dict[str, Any] | None = None,
    progress_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Overlay the active interrupt context onto its pre-node checkpoint.

    LangGraph checkpoints the state *before* a node calls ``interrupt``.  LG-5R
    computes a fresh cost plan inside generation_pending and includes it in the
    durable interrupt payload, so the browser must read that payload rather
    than an older ``values.generation`` snapshot.  This keeps refresh recovery
    and scene-only regeneration cost approval consistent without mutating the
    graph checkpoint outside ``Command(resume=...)``.
    """

    snapshot_values = getattr(snapshot, "values", {})
    snapshot_values = dict(snapshot_values or {}) if isinstance(snapshot_values, dict) else {}
    review = dict(((run.outputs_json or {}).get("langgraph_review") or {}))
    # An interrupt payload is authoritative only while the run is actually
    # waiting at that interrupt.  Keeping an old pending payload after the
    # graph completed would overwrite the final checkpoint with a stale image
    # attempt on every browser refresh.
    pending = dict(review.get("pending") or {}) if run.status == "awaiting_review" else {}
    pending_view = _public_review(pending)
    pending_context = dict(pending.get("context") or {}) if isinstance(pending.get("context"), dict) else {}
    generation = {
        **(dict(snapshot_values.get("generation") or {}) if isinstance(snapshot_values.get("generation"), dict) else {}),
        **(dict(pending_context.get("generation") or {}) if isinstance(pending_context.get("generation"), dict) else {}),
    }
    return {
        "progress": {"status": run.status, "stage": run.current_stage},
        "review": {"pending": pending_view, "next_action": "respond" if pending else None},
        "execution": _execution_view(run, delay_context, progress_preview),
        "intake": _public_intake(snapshot_values.get("intake"), pending_context.get("seller_confirmation")),
        "generation": _public_generation(generation),
        "rendering": _public_rendering(snapshot_values.get("rendering")),
        "quality": _public_quality(snapshot_values.get("quality")),
        "canvas": _public_canvas(snapshot_values.get("canvas")),
        "edit": _public_edit(snapshot_values.get("edit")),
    }


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
        event_type, event_payload = AgentRunEventJournal._payload_for_update(projected_run, update, event)
        journal_event, _appended, projected_run = AgentRunEventJournal.append(
            projected_run,
            db,
            event_type=event_type,
            payload=event_payload,
            thread_id=projected_run.graph_thread_id or projected_run.id,
            workspace_id=projected_run.workspace_id,
            project_id=projected_run.project_id,
        )
        stage_lifecycle_events = AgentRunEventJournal.append_stage_lifecycle(
            projected_run,
            db,
            payload=event_payload,
            stage=stage,
            node_status=str(event.get("node_status") or "completed"),
            status=status,
        )
        timing_event = _TIMING_EVENT_FOR_COMPLETED_STAGE.get(stage) if status == "completed" else None
        if timing_event:
            AgentRunEventJournal.append_timing_event(projected_run, db, event_type=timing_event, timing={})

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
        projected_run.last_applied_event_sequence = max(projected_run.last_applied_event_sequence, journal_event.sequence)
        projected_run.event_projection_version = EVENT_PROJECTION_VERSION

        if status == "completed":
            run_lifecycle_event, _run_lifecycle_inserted, _locked = AgentRunEventJournal.append_run_lifecycle(
                projected_run,
                db,
                event_type="run_completed",
                transition="completed",
                status="completed",
            )
            projected_run.last_applied_event_sequence = max(
                projected_run.last_applied_event_sequence,
                run_lifecycle_event.sequence,
            )
        if stage_lifecycle_events:
            projected_run.last_applied_event_sequence = max(
                projected_run.last_applied_event_sequence,
                *(event.sequence for event in stage_lifecycle_events),
            )
        quality_event = AgentRunEventJournal.quality_lifecycle_event(
            stage,
            str(event.get("node_status") or "completed"),
            dict(update.get("quality") or {}),
        )
        if quality_event is not None:
            quality_type, quality_transition = quality_event
            quality_record, _quality_inserted, _locked = AgentRunEventJournal.append(
                projected_run,
                db,
                event_type=quality_type,
                payload=AgentRunEventJournal._lifecycle_payload(
                    event_payload,
                    transition=quality_transition,
                ),
                thread_id=projected_run.graph_thread_id or projected_run.id,
                workspace_id=projected_run.workspace_id,
                project_id=projected_run.project_id,
            )
            projected_run.last_applied_event_sequence = max(projected_run.last_applied_event_sequence, quality_record.sequence)

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
        mode = str(dict((projected_run.input_snapshot or {}).get("unified_product_intake") or {}).get("input_mode") or "")
        event_type = "seller_confirmation_pending" if stage == "seller_confirmation" else "graph_interrupt_waiting"
        journal_event, _appended, projected_run = AgentRunEventJournal.append(
            projected_run,
            db,
            event_type=event_type,
            payload={
                "stage": stage,
                "status": "awaiting_review",
                "node_status": "awaiting_review",
                "input_mode": mode,
                "source_fidelity": "unknown",
                "references": {},
                "metrics": {"unknown_fact_count": 0, "prohibited_inference_count": 0, "clarification_count": 0},
            },
            thread_id=projected_run.graph_thread_id or projected_run.id,
            workspace_id=projected_run.workspace_id,
            project_id=projected_run.project_id,
        )
        review_output = dict((projected_run.outputs_json or {}).get("langgraph_review") or {})
        if stage != "provider_wait":
            review_cycle = journal_event.idempotency_key
            AgentRunEventJournal.append_timing_event(
                projected_run,
                db,
                event_type="review_wait_started",
                timing={"review_cycle": review_cycle},
            )
            review_output["timing_review_cycle"] = review_cycle
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
        projected_run.last_applied_event_sequence = max(projected_run.last_applied_event_sequence, journal_event.sequence)
        projected_run.event_projection_version = EVENT_PROJECTION_VERSION
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

    @classmethod
    def rebuild_event_projection(
        cls,
        run_id: str,
        workspace_id: str,
        db: Session,
        *,
        from_sequence: int | None = None,
        thread_id: str | None = None,
    ) -> AgentRun:
        """Rebuild the compact projection from its immutable journal only."""

        return AgentRunEventJournal.rebuild_projection(
            cls._find_run(run_id, workspace_id, db),
            db,
            from_sequence=from_sequence,
            thread_id=thread_id,
        )

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
            if str(run.current_stage or "") in {
                "sales_strategy", "page_planning", "copywriting", "visual_planning",
                "planning_review", "generation_pending", "prepare_image_jobs", "dispatch_image_jobs",
                "provider_wait", "collect_image_results", "validate_generated_images", "image_review",
                "page_assembly", "canonical_renderer", "quality_evaluation", "quality_promotion_ready",
            } or bool((run.input_snapshot or {}).get("canonical_handoff")):
                return build_lg10_compiled_graph(checkpointer=checkpointer, entry_node="sales_strategy")
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
    def _handoff_master_to_planning(cls, run: AgentRun, db: Session) -> AgentRun:
        """Continue one frozen LG-12I Master on the existing LG-10 graph."""

        if run.mode != "lg12i_intake" or run.current_stage != "master_ready":
            return run
        intake = dict((run.outputs_json or {}).get("langgraph_intake") or {})
        master_ref = dict(dict(intake.get("commerce_creative_master") or {}).get("master_version") or {})
        brief_ref = dict(dict(intake.get("creative_brief") or {}).get("brief_version") or {})
        fact_ref = dict(dict(intake.get("creative_brief") or {}).get("approved_fact_snapshot") or {})
        if not master_ref.get("id") or not brief_ref.get("id") or not fact_ref.get("id"):
            raise GraphRunResumeUnavailable("LG-12I Master handoff requires frozen Brief and fact references.")
        from src.db.models import CommerceCreativeMasterVersion, ProductCreativeBriefVersion

        master = db.query(CommerceCreativeMasterVersion).filter_by(
            id=master_ref.get("id"), workspace_id=run.workspace_id, project_id=run.project_id,
            creator_run_id=run.id,
        ).one_or_none()
        brief = db.query(ProductCreativeBriefVersion).filter_by(
            id=brief_ref.get("id"), project_id=run.project_id, run_id=run.id,
        ).one_or_none()
        if master is None or brief is None:
            raise GraphRunResumeUnavailable("LG-12I Master handoff references are not persisted for this run.")
        snapshot = dict(run.input_snapshot or {})
        snapshot.update({
            "approved_fact_snapshot_id": fact_ref.get("id"),
            "approved_fact_snapshot_hash": fact_ref.get("hash"),
            "creative_brief_snapshot": {
                "id": brief.id, "version": brief.version, "output_hash": brief.output_hash,
            },
            "canonical_handoff": {
                "master_id": master.id, "master_version": master.version,
                "master_hash": master.canonical_hash,
            },
        })
        run.input_snapshot = snapshot
        run.status = "running"
        run.current_stage = "sales_strategy"
        db.add(run)
        db.commit()
        initial = build_lg1_graph_input(
            run_id=run.id, workspace_id=run.workspace_id, project_id=run.project_id,
            mode=run.mode, input_snapshot=snapshot,
        )
        initial["intake"] = intake
        return cls._execute(
            run, db, initial_state=initial, rebuild_projection=False,
        )

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
        failure_event, _appended, run = AgentRunEventJournal.append_failure_event(run, db, failure=failure)
        run_failed_event, _run_failed_inserted, _locked = AgentRunEventJournal.append_run_lifecycle(
            run,
            db,
            event_type="run_failed",
            transition="failed",
            status="failed",
        )
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
        step.error_message = str(failure["code"])
        run.last_applied_event_sequence = max(run.last_applied_event_sequence, failure_event.sequence, run_failed_event.sequence)
        run.event_projection_version = EVENT_PROJECTION_VERSION
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
        checkpoint_id = ((snapshot.config.get("configurable") or {}).get("checkpoint_id"))
        recovered_event, _inserted, _locked = AgentRunEventJournal.append_run_lifecycle(
            run,
            db,
            event_type="run_recovered",
            transition="recovered",
            checkpoint_id=str(checkpoint_id or ""),
            status=run.status,
        )
        run.last_applied_event_sequence = max(run.last_applied_event_sequence, recovered_event.sequence)
        db.add(run)
        db.commit()
        db.refresh(run)
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
        checkpoint_event = dict(expected["last_event"] or {})
        checkpoint_event.update({"stage": expected["stage"], "status": expected["status"]})
        event_type, event_payload = AgentRunEventJournal._payload_for_update(
            projected,
            {"intake": expected["intake"]},
            checkpoint_event,
        )
        journal_event, _appended, projected = AgentRunEventJournal.append(
            projected,
            db,
            event_type=event_type,
            payload=event_payload,
            thread_id=projected.graph_thread_id or projected.id,
            workspace_id=projected.workspace_id,
            project_id=projected.project_id,
            checkpoint_id=expected["checkpoint_id"],
        )
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
        checkpoint_event, _inserted, _locked = AgentRunEventJournal.append_run_lifecycle(
            projected,
            db,
            event_type="checkpoint_projected",
            transition="checkpointed",
            checkpoint_id=expected["checkpoint_id"],
            status=projected.status,
        )
        projected.last_applied_event_sequence = max(journal_event.sequence, checkpoint_event.sequence)
        projected.event_projection_version = EVENT_PROJECTION_VERSION
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
                latest_sequence = int(
                    db.query(func.coalesce(func.max(AgentRunEvent.sequence), 0))
                    .filter(AgentRunEvent.run_id == run.id)
                    .scalar() or 0
                )
                if (
                    latest_sequence == run.last_applied_event_sequence
                    and run.event_projection_version == EVENT_PROJECTION_VERSION
                    and latest_sequence > 0
                ):
                    return run
                # A checkpoint can be healthy while its SQL journal write was
                # interrupted. Reconcile only its bounded event metadata.
                return cls._apply_lg12i_checkpoint_projection(run, db, snapshot)
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
                    checkpoint_event, _inserted, _locked = AgentRunEventJournal.append_run_lifecycle(
                        run,
                        db,
                        event_type="checkpoint_projected",
                        transition="checkpointed",
                        checkpoint_id=str(checkpoint_id or ""),
                        status=run.status,
                    )
                    run.last_applied_event_sequence = max(run.last_applied_event_sequence, checkpoint_event.sequence)
                    db.add(run)
                    db.commit()
                    db.refresh(run)
                return run
        except GraphRunCancelled:
            db.rollback()
            return db.query(AgentRun).filter(AgentRun.id == run.id).one()
        except Exception as error:
            logger.error("LangGraph execution failed for run %s at stage %s", run.id, run.current_stage)
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
        if claimed != 1:
            db.rollback()
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
        if run.mode not in {"lg11_edit", "lg12i_intake"}:
            profile = (
                "production"
                if str(settings.APP_ENV).lower() == "production"
                and str(settings.SELLFORM_GENERATION_MODE).lower() != "mock"
                and str(settings.SELLFORM_IMAGE_GENERATION_MODE).lower() != "mock"
                else "test" if str(settings.APP_ENV).lower() in {"test", "testing"} else "mock"
            )
            AgentRunEventJournal.append_timing_event(
                run, db, event_type="main_execution_started", timing={"execution_profile": profile},
            )
            AgentRunEventJournal.append_timing_event(
                run, db, event_type="product_understanding_started", timing={},
            )
        AgentRunEventJournal.append_run_lifecycle(
            run,
            db,
            event_type="run_started",
            transition="started",
            status="running",
        )
        db.commit()

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
                    existing = cls.start(existing.id, workspace_id, db)
                return cls._handoff_master_to_planning(existing, db)

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
        return cls._handoff_master_to_planning(cls.start(run.id, workspace_id, db), db)

    @classmethod
    def get_state(cls, run_id: str, workspace_id: str, db: Session) -> GraphRunStateView:
        run = cls._find_run(run_id, workspace_id, db)
        if run.mode == "lg12i_intake" and run.graph_thread_id:
            run = cls._recover_running_lg12i_projection(run, db)
        thread_id = cls._thread_id(run)
        delay_context = AgentRunEventJournal.seller_delay_context(run, db)
        if not run.graph_thread_id:
            projection = dict(run.outputs_json or {})
            snapshot = SimpleNamespace(values={
                "rendering": projection.get("langgraph_page_rendering"),
                "quality": projection.get("langgraph_quality"),
                "edit": projection.get("langgraph_edit"),
            })
            return GraphRunStateView(
                run_id=run.id,
                thread_id=thread_id,
                status=run.status,
                current_stage=run.current_stage,
                checkpoint_id=None,
                values=_browser_checkpoint_values(
                    run,
                    snapshot,
                    delay_context=delay_context,
                    progress_preview=seller_progressive_preview(run, db, checkpoint_values=snapshot.values),
                ),
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
            values=_browser_checkpoint_values(
                run,
                snapshot,
                delay_context=delay_context,
                progress_preview=seller_progressive_preview(run, db, checkpoint_values=getattr(snapshot, "values", None)),
            ),
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
                values=_browser_checkpoint_values(
                    run,
                    snapshot,
                    progress_preview=seller_progressive_preview(run, db, checkpoint_values=getattr(snapshot, "values", None)),
                ),
                next_nodes=[],
            )
            for snapshot in snapshots
        ]

    @classmethod
    def cancel(cls, run_id: str, workspace_id: str, db: Session) -> AgentRun:
        run = cls._find_run(run_id, workspace_id, db, lock=True)
        if run.status == "completed":
            return run
        run.status = "cancelled"
        cancelled_event, _inserted, _locked = AgentRunEventJournal.append_run_lifecycle(
            run,
            db,
            event_type="run_cancelled",
            transition="cancelled",
            status="cancelled",
        )
        run.last_applied_event_sequence = max(run.last_applied_event_sequence, cancelled_event.sequence)
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
            if run.status == "awaiting_review" and run.current_stage == "planning_review":
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
            return cls._handoff_master_to_planning(cls._execute(
                run,
                db,
                initial_state=None,
                rebuild_projection=True,
                continuation_after="seller_confirmation",
            ), db)
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
            return cls._handoff_master_to_planning(run, db)
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
        if claimed != 1:
            db.rollback()
            run = cls._find_run(run_id, workspace_id, db)
            if run.status in {"running", "completed"}:
                return run
            if run.status == "cancelled":
                raise GraphRunCancelled("Cancelled graph runs cannot be resumed.")
            raise ValueError("Could not acquire the graph resume lease.")
        run = cls._find_run(run_id, workspace_id, db)
        review = dict((run.outputs_json or {}).get("langgraph_review") or {})
        review_cycle = str(review.get("timing_review_cycle") or "")
        pending_stage = str(dict(review.get("pending") or {}).get("review_stage") or "")
        lifecycle_events: list[AgentRunEvent] = []
        if is_review_resume and pending_stage:
            decision = str((resume_payload or {}).get("decision") or "")
            if decision:
                lifecycle_events.append(
                    AgentRunEventJournal.append_review_lifecycle(
                        run,
                        db,
                        event_type="seller_choice_submitted",
                        transition="submitted",
                        stage=pending_stage,
                        decision=decision,
                    )[0]
                )
            lifecycle_events.append(
                AgentRunEventJournal.append_review_lifecycle(
                    run,
                    db,
                    event_type="review_resumed",
                    transition="resumed",
                    stage=pending_stage,
                )[0]
            )
        if is_review_resume and pending_stage != "provider_wait" and len(review_cycle) == 64:
            AgentRunEventJournal.append_timing_event(
                run, db, event_type="review_wait_resolved", timing={"review_cycle": review_cycle},
            )
        if lifecycle_events:
            run.last_applied_event_sequence = max(run.last_applied_event_sequence, *(event.sequence for event in lifecycle_events))
        db.commit()
        return cls._handoff_master_to_planning(cls._execute(
            run,
            db,
            initial_state=None,
            rebuild_projection=True,
            resume_payload=resume_payload,
        ), db)

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
