"""TASK-12.9 bounded Quality-Bar routing contracts.

These tests intentionally exercise only reference-safe graph decisions.  The
actual image operation remains covered by the existing LG-9/LG-11 outbox and
cost-approval tests; no provider is available here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.agents.langgraph_runtime import (
    _LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS,
    _lg12_quality_route,
    _lg12_quality_scene_target,
    _lg12_quality_copy_change,
    _lg12_quality_evaluate,
    _lg12_quality_image_rework_route,
    _lg12_quality_logical_target_ref,
    _lg12_quality_node_family,
    _lg12_quality_rework_action,
    _lg12_quality_selective_rework_route,
    _lg12_quality_summary,
    _lg12_quality_attempt_entry,
    _lg12_quality_attempt_key,
    _lg12_quality_upsert_ledger,
    build_lg10_compiled_graph,
    build_lg11_compiled_graph,
)
from src.services.langgraph_run_service import AgentRunGraphProjector
from src.services.langgraph_review_service import validate_resume_payload
from src.services.quality_assessment_service import (
    QualityAssessmentContractError,
    build_lg12_quality_rework_attempt,
)
from src.services.prompt_intelligence_service import canonical_hash
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers


_PAGE_REF = {"id": "page-1", "version": "lg10-detail-page-version-v1", "hash": "a" * 64, "type": "DetailPageVersion"}
_REPORT_REF = {"id": "report-1", "version": 1, "hash": "b" * 64, "type": "QualityAssessmentReportVersion"}
_MASTER_REF = {"id": "master-1", "version": 1, "hash": "c" * 64, "type": "CommerceCreativeMasterVersion"}


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


def _bar(route: str, targets: list[dict] | None = None) -> dict:
    canonical_targets = sorted(
        targets or [{
            "domain": "image_identity_quality",
            "finding_ref": {"id": "finding-a", "version": 1, "hash": "d" * 64, "type": "QualityFinding"},
            "target_ref": {"id": "asset-a", "version": 1, "hash": "e" * 64, "type": "asset"},
            "recommended_action": "replace_asset",
        }],
        key=canonical_hash,
    )
    body = {
        "quality_bar_result_id": "quality-bar:report-1:1",
        "creator_run_id": "run-1",
        "frozen_target_ref": _PAGE_REF,
        "quality_report_ref": _REPORT_REF,
        "routing_code": route,
        "verdict": "PASS" if route == "PASS" else "FAIL",
        "seller_review_required": route == "SELLER_REVIEW",
        "rework_targets": canonical_targets,
    }
    return {**body, "canonical_hash": canonical_hash(body)}


@pytest.mark.parametrize(
    ("route", "verdict", "attempts", "expected"),
    [
        ("PASS", "PASS", 0, "quality_promotion_ready"),
        ("BLOCKED_POLICY", "FAIL", 0, "quality_seller_review"),
        ("SELLER_REVIEW", "NEEDS_REVIEW", 0, "quality_seller_review"),
        ("IMAGE_REWORK", "FAIL", 0, "quality_selective_rework"),
        ("COPY_REWORK", "FAIL", 0, "quality_selective_rework"),
        ("VISUAL_REWORK", "FAIL", 0, "quality_selective_rework"),
        ("PLAN_REWORK", "FAIL", 0, "quality_selective_rework"),
        ("IMAGE_REWORK", "FAIL", _LG12_QUALITY_MAX_AUTOMATIC_ATTEMPTS, "quality_rework_exhausted"),
    ],
)
def test_quality_bar_routes_are_deterministic_and_never_allow_a_third_attempt(route, verdict, attempts, expected):
    domain_by_route = {
        "IMAGE_REWORK": "image_identity_quality", "COPY_REWORK": "korean_copy_readability",
        "VISUAL_REWORK": "layout_typography_brand_flow",
        "PLAN_REWORK": "layout_typography_brand_flow",
    }
    target_by_route = {
        "IMAGE_REWORK": {"id": "asset-a", "version": 1, "hash": "e" * 64, "type": "asset"},
        "COPY_REWORK": {"id": "copy-field:section-a:headline", "version": 1, "hash": "e" * 64, "type": "copy_field"},
        "VISUAL_REWORK": {"id": "section-a", "version": 1, "hash": "e" * 64, "type": "frozen_section"},
        # A plan finding can use the existing Canvas reassembly only after the
        # Quality Bar narrows it to this frozen section; PagePlan-only targets
        # remain seller review rather than creating a second planning engine.
        "PLAN_REWORK": {"id": "section-a", "version": 1, "hash": "e" * 64, "type": "frozen_section"},
    }
    quality = {"routing_code": route, "quality_bar_verdict": verdict}
    if route in domain_by_route:
        target = {"domain": domain_by_route[route], "target_ref": target_by_route[route]}
        key = canonical_hash({"node_family": {"IMAGE_REWORK": "scene_reassembly", "COPY_REWORK": "copy_reassembly", "VISUAL_REWORK": "layout_plan_reassembly", "PLAN_REWORK": "layout_plan_reassembly"}[route], "target_ref": target_by_route[route]})
        quality["rework_targets"] = [target]
        quality["attempt_ledger"] = ([{"attempt_key": key, "attempt_count": attempts}] if attempts else [])
    assert _lg12_quality_route({"quality": quality}) == expected


def test_attempt_is_canonical_target_order_independent_and_bound_to_master():
    run = SimpleNamespace(id="run-1")
    first_target = _bar("IMAGE_REWORK")["rework_targets"][0]
    second_target = {
        "domain": "image_identity_quality", "finding_ref": {"id": "finding-b", "version": 1, "hash": "f" * 64, "type": "QualityFinding"},
        "target_ref": {"id": "asset-b", "version": 1, "hash": "0" * 64, "type": "asset"},
        "recommended_action": "replace_asset",
    }
    forward = _bar("IMAGE_REWORK", [first_target, second_target])
    reverse = _bar("IMAGE_REWORK", [second_target, first_target])
    first = build_lg12_quality_rework_attempt(
        run=run, current_page_ref=_PAGE_REF, quality_report_ref=_REPORT_REF,
        quality_bar=forward, master_ref=_MASTER_REF, attempt_number=1,
    )
    second = build_lg12_quality_rework_attempt(
        run=run, current_page_ref=_PAGE_REF, quality_report_ref=_REPORT_REF,
        quality_bar=reverse, master_ref=_MASTER_REF, attempt_number=1,
    )
    assert first["master_ref"] == _MASTER_REF
    assert first["attempt_plan_hash"] == second["attempt_plan_hash"]


def test_attempt_refuses_cross_run_or_stale_quality_bar_target():
    bar = _bar("IMAGE_REWORK")
    with pytest.raises(QualityAssessmentContractError):
        build_lg12_quality_rework_attempt(
            run=SimpleNamespace(id="different-run"), current_page_ref=_PAGE_REF,
            quality_report_ref=_REPORT_REF, quality_bar=bar, master_ref=_MASTER_REF, attempt_number=1,
        )
    tampered = {**bar, "frozen_target_ref": {**_PAGE_REF, "hash": "0" * 64}}
    with pytest.raises(QualityAssessmentContractError):
        build_lg12_quality_rework_attempt(
            run=SimpleNamespace(id="run-1"), current_page_ref=_PAGE_REF,
            quality_report_ref=_REPORT_REF, quality_bar=tampered, master_ref=_MASTER_REF, attempt_number=1,
        )


def test_image_target_must_be_one_exact_frozen_manifest_scene():
    page = SimpleNamespace(sections_json={
        "lg10": {"canonical_page_assembly_input": {"approved_asset_manifest": {"assets": [
            {"asset_id": "asset-a", "scene_id": "scene-a"},
            {"asset_id": "asset-b", "scene_id": "scene-b"},
        ]}}}
    })
    assert _lg12_quality_scene_target(page=page, targets=[{"target_ref": {"type": "asset", "id": "asset-a"}}]) == "scene-a"
    with pytest.raises(ValueError):
        _lg12_quality_scene_target(page=page, targets=[{"target_ref": {"type": "asset", "id": "asset-a"}}, {"target_ref": {"type": "asset", "id": "asset-b"}}])
    assert _lg12_quality_selective_rework_route({"current_stage": "quality_seller_review"}) == "quality_seller_review"
    assert _lg12_quality_image_rework_route({"current_stage": "quality_seller_review"}) == "quality_seller_review"


def test_copy_rework_is_limited_to_semantic_preserving_one_field_normalization():
    page = SimpleNamespace(sections_json={"lg10": {"canonical_rendering": {"sections": [{
        "section_id": "hero",
        "text_layer": [{"field": "headline", "text": "  정돈된   문장!!!  "}],
    }]}}})
    section_id, field, changed = _lg12_quality_copy_change(
        page=page,
        target_ref={"id": "copy-field:hero:headline", "version": 1, "hash": "a" * 64, "type": "copy_field"},
    )
    assert (section_id, field) == ("hero", "headline")
    assert changed == " 정돈된 문장! "
    with pytest.raises(ValueError):
        _lg12_quality_copy_change(
            page=page,
            target_ref={"id": "copy-field:hero:unknown", "version": 1, "hash": "a" * 64, "type": "copy_field"},
        )


def test_attempt_budget_is_per_exact_target_and_survives_route_label_changes():
    scene_a = {"domain": "image_identity_quality", "target_ref": {"id": "scene-a", "version": 1, "hash": "1" * 64, "type": "scene"}}
    scene_c = {"domain": "image_identity_quality", "target_ref": {"id": "scene-c", "version": 1, "hash": "2" * 64, "type": "scene"}}
    copy_b = {"domain": "korean_copy_readability", "target_ref": {"id": "copy-field:b:headline", "version": 1, "hash": "3" * 64, "type": "copy_field"}}
    quality = {"routing_code": "IMAGE_REWORK", "quality_bar_verdict": "FAIL", "rework_targets": [scene_a], "attempt_ledger": []}
    key, _ = _lg12_quality_attempt_entry(quality, target=scene_a)
    assert key == _lg12_quality_attempt_key(node_family="scene_reassembly", target_ref=scene_a["target_ref"])
    ledger = _lg12_quality_upsert_ledger(quality, {"attempt_key": key, "node_family": _lg12_quality_node_family(scene_a), "target_ref": scene_a["target_ref"], "attempt_count": 2, "status": "child_frozen"})
    exhausted = {**quality, "attempt_ledger": ledger}
    assert _lg12_quality_route({"quality": exhausted}) == "quality_rework_exhausted"
    # A different scene and a different copy field receive independent budgets.
    assert _lg12_quality_route({"quality": {**exhausted, "rework_targets": [scene_c]}}) == "quality_selective_rework"
    assert _lg12_quality_route({"quality": {**exhausted, "routing_code": "COPY_REWORK", "rework_targets": [copy_b]}}) == "quality_selective_rework"
    # Route labels cannot reset the same target key if later evaluators choose
    # another visual node family for that exact section/plan target.
    assert len(ledger) == 1 and ledger[0]["attempt_count"] == 2


def test_quality_rule_actions_are_explicit_and_cannot_cross_executor_boundaries():
    assert _lg12_quality_rework_action("copy.spacing_inconsistency") == "spacing_inconsistency"
    assert _lg12_quality_rework_action("layout.typography_role_token_mismatch") == "style_reassembly"
    assert _lg12_quality_rework_action("layout.scene_order_mismatch") == "plan_reorder"
    # A suffix alone is never authority to route an image/layout finding into
    # the copy fork.
    assert _lg12_quality_rework_action("image.spacing_inconsistency") is None
    assert _lg12_quality_rework_action("copy.unknown_future_rule") is None
    assert _lg12_quality_selective_rework_route({"current_stage": "quality_style_rework"}) == "quality_style_rework"
    assert _lg12_quality_selective_rework_route({"current_stage": "quality_plan_rework"}) == "quality_plan_rework"


def test_scene_asset_aliases_share_one_logical_retry_identity():
    page = SimpleNamespace(sections_json={
        "snapshot_hash": "a" * 64,
        "lg10": {"canonical_page_assembly_input": {"approved_asset_manifest": {"assets": [
            {"asset_id": "asset-a", "scene_id": "scene-a"},
        ]}}},
    })
    asset_target = {"target_ref": {"type": "asset", "id": "asset-a", "version": 1, "hash": "b" * 64}}
    scene_target = {"target_ref": {"type": "scene", "id": "scene-a", "version": 1, "hash": "c" * 64}}
    asset_logical = _lg12_quality_logical_target_ref(page=page, target=asset_target)
    scene_logical = _lg12_quality_logical_target_ref(page=page, target=scene_target)
    assert asset_logical == scene_logical
    key = _lg12_quality_attempt_key(node_family="scene_reassembly", target_ref=asset_logical)
    quality = {"attempt_ledger": [{"attempt_key": key, "attempt_count": 2}]}
    alias = {**scene_target, "logical_target_ref": scene_logical}
    _, existing = _lg12_quality_attempt_entry(quality, target=alias)
    assert existing and existing["attempt_count"] == 2


def test_rework_attempt_accepts_checkpoint_logical_identity_without_widening_bar_authority():
    run = SimpleNamespace(id="run-1")
    raw_target = _bar("IMAGE_REWORK")["rework_targets"][0]
    selected = {
        **raw_target,
        "logical_target_ref": {"type": "scene", "id": "scene-a", "version": "frozen-scene-v1", "hash": "f" * 64},
    }
    attempt = build_lg12_quality_rework_attempt(
        run=run, current_page_ref=_PAGE_REF, quality_report_ref=_REPORT_REF,
        quality_bar=_bar("IMAGE_REWORK"), master_ref=_MASTER_REF,
        selected_target=selected, attempt_number=1,
    )
    assert attempt["target_ref"] == raw_target["target_ref"]
    assert attempt["logical_target_ref"] == selected["logical_target_ref"]


def test_canvas_element_and_page_plan_are_not_rejected_as_unknown_target_types():
    assert _lg12_quality_node_family({"target_ref": {"type": "frozen_canvas_element"}}) == "layout_plan_reassembly"
    assert _lg12_quality_node_family({"target_ref": {"type": "PagePlanVersion"}}) == "layout_plan_reassembly"


def test_production_compiled_quality_graph_invokes_and_recovers_from_checkpoint(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    import src.agents.langgraph_runtime as runtime

    calls: list[str] = []

    def fake_quality(_state):
        calls.append("quality_evaluation")
        return {"current_stage": "quality_promotion_ready", "status": "completed", "quality": {"routing_code": "PASS"}}

    monkeypatch.setattr(runtime, "_lg12_quality_evaluate", fake_quality)
    memory = InMemorySaver()
    graph = runtime.build_lg10_compiled_graph(checkpointer=memory)
    config = {"configurable": {"thread_id": "quality-compiled-checkpoint"}}
    # Start at the persisted predecessor node, exactly as a recovered frozen
    # candidate does; this executes the real compiled edge and conditional QA
    # routing rather than only inspecting graph construction.
    graph.update_state(config, {"current_stage": "canonical_renderer", "status": "running"}, as_node="canonical_renderer")
    first = graph.invoke(None, config)
    assert first["current_stage"] == "quality_promotion_ready"
    assert calls == ["quality_evaluation"]
    replay = graph.invoke(None, config)
    assert replay["current_stage"] == "quality_promotion_ready"
    assert calls == ["quality_evaluation"]
    # LG-11 frozen edit children use the same QA nodes after their existing
    # edit-finalization edge, not an edit-only compatibility graph.
    lg11_graph = runtime.build_lg11_compiled_graph(checkpointer=InMemorySaver())
    lg11_config = {"configurable": {"thread_id": "quality-lg11-compiled-checkpoint"}}
    lg11_graph.update_state(
        lg11_config,
        {"current_stage": "quality_evaluation", "status": "running"},
        as_node="finalize_edit_run",
    )
    lg11_first = lg11_graph.invoke(None, lg11_config)
    assert lg11_first["current_stage"] == "quality_promotion_ready"
    assert calls == ["quality_evaluation", "quality_evaluation"]
    assert lg11_graph.invoke(None, lg11_config)["current_stage"] == "quality_promotion_ready"
    assert calls == ["quality_evaluation", "quality_evaluation"]


@pytest.mark.parametrize(
    ("route", "rework_stage", "node_attr"),
    [
        ("IMAGE_REWORK", "quality_image_rework", "_lg12_quality_image_rework"),
        ("COPY_REWORK", "quality_copy_rework", "_lg12_quality_copy_rework"),
        ("VISUAL_REWORK", "quality_visual_rework", "_lg12_quality_visual_rework"),
        ("PLAN_REWORK", "quality_plan_rework", "_lg12_quality_plan_rework"),
        ("VISUAL_REWORK", "quality_style_rework", "_lg12_quality_style_rework"),
    ],
)
def test_compiled_graph_reroutes_one_frozen_child_through_new_qa_bar(
    monkeypatch, route, rework_stage, node_attr,
):
    """Exercise compiled conditional edges, checkpoint replay and child-only QA.

    The selected node is a deterministic fake-provider seam.  Concrete
    LG-11 copy/style/Canvas/scene persistence is covered by its production
    regression suites; this test proves those outcomes are wired through the
    compiled LG-10 graph and cannot skip the common second QA node.
    """

    from langgraph.checkpoint.memory import InMemorySaver
    import src.agents.langgraph_runtime as runtime

    calls: list[str] = []
    evaluation_count = 0

    def fake_quality(_state):
        nonlocal evaluation_count
        evaluation_count += 1
        calls.append(f"qa:{evaluation_count}")
        if evaluation_count == 1:
            target_type = {
                "IMAGE_REWORK": "scene", "COPY_REWORK": "copy_field",
                "VISUAL_REWORK": "frozen_canvas_element", "PLAN_REWORK": "PagePlanVersion",
            }[route]
            return {
                "current_stage": "quality_selective_rework", "status": "running",
                "quality": {
                    "routing_code": route, "quality_bar_verdict": "FAIL",
                    "rework_targets": [{
                        "domain": {
                            "IMAGE_REWORK": "image_identity_quality", "COPY_REWORK": "korean_copy_readability",
                            "VISUAL_REWORK": "layout_typography_brand_flow", "PLAN_REWORK": "layout_typography_brand_flow",
                        }[route],
                        "target_ref": {"type": target_type, "id": f"target:{rework_stage}", "version": 1, "hash": "a" * 64},
                    }],
                },
            }
        return {"current_stage": "quality_promotion_ready", "status": "completed", "quality": {"routing_code": "PASS"}}

    def fake_selective(_state):
        calls.append("selective")
        return {"current_stage": rework_stage, "status": "running", "quality": {"routing_code": route}}

    def frozen_child(state):
        calls.append(rework_stage)
        return {
            "current_stage": "quality_rework_child_frozen", "status": "running",
            "rendering": {**dict(state.get("rendering") or {}), "detail_page_version": {
                "id": f"child:{rework_stage}", "schema_version": "lg10-detail-page-version-v1", "snapshot_hash": "f" * 64,
            }},
            "quality": {"routing_code": route, "child_detail_page_ref": {"id": f"child:{rework_stage}", "hash": "f" * 64}},
        }

    def fake_rework(state):
        # Image regeneration deliberately goes through the existing LG-11
        # provider-wait/review contract before it can produce a frozen child.
        # The other rework families freeze their child in their own node.
        if route == "IMAGE_REWORK":
            calls.append(rework_stage)
            return {
                "current_stage": "quality_image_provider_wait", "status": "running",
                "generation": {"pending_count": 0},
                "quality": {"routing_code": route},
            }
        return frozen_child(state)

    monkeypatch.setattr(runtime, "_lg12_quality_evaluate", fake_quality)
    monkeypatch.setattr(runtime, "_lg12_quality_selective_rework", fake_selective)
    monkeypatch.setattr(runtime, node_attr, fake_rework)
    if route == "IMAGE_REWORK":
        monkeypatch.setattr(runtime, "_lg12_quality_image_provider_wait", lambda _state: {
            "current_stage": "quality_image_review", "status": "running", "generation": {"pending_count": 0},
        })
        monkeypatch.setattr(runtime, "_lg12_quality_image_review", frozen_child)
    graph = runtime.build_lg10_compiled_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": f"compiled-{rework_stage}"}}
    graph.update_state(config, {"current_stage": "canonical_renderer", "status": "running", "rendering": {}}, as_node="canonical_renderer")
    result = graph.invoke(None, config)
    assert result["current_stage"] == "quality_promotion_ready"
    assert result["rendering"]["detail_page_version"]["id"] == f"child:{rework_stage}"
    expected_calls = ["qa:1", "selective", rework_stage]
    if route == "IMAGE_REWORK":
        expected_calls.append(rework_stage)  # provider review freezes the child
    expected_calls.append("qa:2")
    assert calls == expected_calls
    # A completed checkpoint has no scheduled rework node; replay must neither
    # recreate the child nor consume another target attempt.
    replay = graph.invoke(None, config)
    assert replay["current_stage"] == "quality_promotion_ready"
    assert calls == expected_calls


def test_seller_quality_review_reuses_the_existing_versioned_resume_contract():
    payload = validate_resume_payload({
        "schema_version": "lg12i-v1", "review_stage": "quality_review", "decision": "approve",
    }, "quality_review")
    assert payload.review_stage == "quality_review"


def test_quality_projection_stores_only_bounded_route_and_reference_state(client, db_session, auth_headers, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    bar = _bar("IMAGE_REWORK")
    quality = _lg12_quality_summary(
        page_ref=_PAGE_REF, report_ref=_REPORT_REF, quality_bar=bar, attempts=1,
    )
    projected = AgentRunGraphProjector.apply_node_update(run, db_session, {
        "events": [{"stage": "quality_evaluation", "status": "running", "node_status": "completed"}],
        "quality": quality,
    })
    result = projected.outputs_json["langgraph_quality"]
    assert result["quality_bar_ref"]["hash"] == bar["canonical_hash"]
    assert result["current_detail_page_ref"] == _PAGE_REF
    assert result["rework_attempt_count"] == 1
    assert "report_json" not in result and "image_bytes" not in result


def test_report_bridge_persists_one_immutable_report_for_one_frozen_target(
    client, db_session, auth_headers, tmp_path, monkeypatch,
):
    """TASK-12.9 assembles existing evaluator outputs without a new executor."""

    import src.services.quality_assessment_service as quality_service
    from test_lg12_quality_report_contract import _setup

    run, master, page, _manifest_hash, _profile = _setup(db_session, client, auth_headers, tmp_path)
    snapshot = dict(page.sections_json)
    snapshot.pop("snapshot_hash", None)
    snapshot["lg12_quality_lineage"] = {
        "schema_version": "lg12-detail-page-quality-lineage-v1", "creator_run_id": run.id,
        "source_snapshot_ref": {"id": master.source_snapshot_version_id, "version": master.source_snapshot_version, "hash": master.source_snapshot_hash},
        "truth_ref": {"id": master.truth_version_id, "version": master.truth_version, "hash": master.truth_version_hash},
        "confirmation_ref": {"id": master.confirmation_version_id, "version": master.confirmation_version, "hash": master.confirmation_version_hash},
        "master_ref": {"id": master.id, "version": master.version, "hash": master.canonical_hash},
        "approved_asset_manifest_ref": dict(master.approved_asset_manifest_ref_json or {}),
    }
    page.sections_json = {**snapshot, "snapshot_hash": canonical_hash(snapshot)}
    db_session.commit()

    def evaluator(domain_id):
        def run_evaluator(_db, *, report_payload, **_kwargs):
            domain = quality_service._quality_placeholder_domain(
                domain_id, report_payload=report_payload,
                evaluator_version={
                    "factual_rights_policy": quality_service.FACTUAL_RIGHTS_POLICY_EVALUATOR_VERSION,
                    "image_identity_quality": quality_service.IMAGE_IDENTITY_QUALITY_EVALUATOR_VERSION,
                    "korean_copy_readability": quality_service.KOREAN_COPY_READABILITY_EVALUATOR_VERSION,
                    "layout_typography_brand_flow": quality_service.LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION,
                    "channel_preview_export_parity": quality_service.CHANNEL_PREVIEW_EXPORT_PARITY_EVALUATOR_VERSION,
                }[domain_id],
            )
            return {"domain": {**domain, "score": 100, "status": "complete"}, "critical_violations": []}
        return run_evaluator

    monkeypatch.setattr(quality_service, "evaluate_factual_rights_policy_domain", evaluator("factual_rights_policy"))
    monkeypatch.setattr(quality_service, "evaluate_image_identity_quality_domain", evaluator("image_identity_quality"))
    monkeypatch.setattr(quality_service, "evaluate_korean_copy_readability_domain", evaluator("korean_copy_readability"))
    monkeypatch.setattr(quality_service, "evaluate_layout_typography_brand_flow_domain", evaluator("layout_typography_brand_flow"))
    monkeypatch.setattr(quality_service, "evaluate_channel_preview_export_parity_domain", evaluator("channel_preview_export_parity"))
    reference = {"id": page.id, "version": "lg10-detail-page-version-v1", "hash": page.sections_json["snapshot_hash"], "type": "DetailPageVersion"}
    first = quality_service.build_lg12_quality_assessment_report(db_session, run=run, detail_page_reference=reference)
    db_session.commit()
    second = quality_service.build_lg12_quality_assessment_report(db_session, run=run, detail_page_reference=reference)
    assert first.id == second.id
    assert quality_service.lg12_quality_report_reference(first)["hash"] == first.canonical_hash


def test_lg11_child_qa_uses_the_frozen_source_run_master_lineage(
    client, db_session, auth_headers, tmp_path, monkeypatch,
):
    """LG-11 executes the child, but QA remains bound to the page's Master run."""

    from uuid import uuid4

    from src.db.models import AgentRun
    from src.services.langgraph_discovery_service import langgraph_execution_session
    from test_lg12_quality_report_contract import _setup

    source_run, master, page, _manifest_hash, _profile = _setup(db_session, client, auth_headers, tmp_path)
    body = dict(page.sections_json)
    body.pop("snapshot_hash", None)
    body["lg12_quality_lineage"] = {
        "schema_version": "lg12-detail-page-quality-lineage-v1",
        "creator_run_id": source_run.id,
        "source_snapshot_ref": {"id": master.source_snapshot_version_id, "version": master.source_snapshot_version, "hash": master.source_snapshot_hash},
        "truth_ref": {"id": master.truth_version_id, "version": master.truth_version, "hash": master.truth_version_hash},
        "confirmation_ref": {"id": master.confirmation_version_id, "version": master.confirmation_version, "hash": master.confirmation_version_hash},
        "master_ref": {"id": master.id, "version": master.version, "hash": master.canonical_hash},
        "approved_asset_manifest_ref": dict(master.approved_asset_manifest_ref_json or {}),
    }
    page.sections_json = {**body, "snapshot_hash": canonical_hash(body)}
    edit_run = AgentRun(
        workspace_id=source_run.workspace_id, project_id=source_run.project_id,
        created_by=source_run.created_by, mode="lg11_edit", status="running",
        current_stage="quality_evaluation", input_snapshot={}, outputs_json={},
        graph_thread_id=str(uuid4()),
    )
    db_session.add(edit_run); db_session.commit()
    import src.services.quality_assessment_service as quality_service
    import src.services.quality_bar_service as quality_bar_service

    received: dict[str, str] = {}
    fake_report = SimpleNamespace(id="report-owner", version=1, canonical_hash="b" * 64)

    def fake_report_builder(_db, *, run, detail_page_reference):
        received["owner_run_id"] = run.id
        assert detail_page_reference["id"] == page.id
        return fake_report

    def fake_aggregate(_db, *, report_ref):
        assert report_ref["id"] == fake_report.id
        return _bar("PASS", [])

    monkeypatch.setattr(quality_service, "build_lg12_quality_assessment_report", fake_report_builder)
    monkeypatch.setattr(quality_bar_service, "aggregate_quality_bar", fake_aggregate)
    monkeypatch.setattr(db_session, "refresh", lambda _row: None)
    state = {
        "run_id": edit_run.id, "thread_id": edit_run.id,
        "workspace_id": edit_run.workspace_id, "project_id": edit_run.project_id,
        "rendering": {"detail_page_version": {
            "id": page.id, "schema_version": "lg10-detail-page-version-v1",
            "snapshot_hash": page.sections_json["snapshot_hash"],
        }},
    }
    with langgraph_execution_session(db_session):
        result = _lg12_quality_evaluate(state)
    assert received["owner_run_id"] == source_run.id
    assert result["quality"]["quality_owner_run_ref"] == {"id": source_run.id, "type": "AgentRun"}
    assert result["quality"]["quality_report_ref"]
