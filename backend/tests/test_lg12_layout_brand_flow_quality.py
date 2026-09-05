"""TASK-12.6 deterministic frozen layout/Brand Kit evaluator."""

from __future__ import annotations

from copy import deepcopy

import pytest

from src.db.models import BrandKitVersion, DetailPageVersion, ImageGenerationCostApprovalRecord, ImageGenerationJobRecord, ImageGenerationOutboxRecord
from src.services.page_finalization_service import resolve_lg10_brand_renderer_tokens
from src.services.prompt_intelligence_service import canonical_hash
from src.services.quality_assessment_service import (
    LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION,
    QualityAssessmentContractError,
    create_quality_threshold_profile,
    evaluate_layout_typography_brand_flow_domain,
)
from src.services.renderer import render_lg10_canonical_page_html
from test_lg12_quality_report_contract import _profile_payload, _report_payload
from test_lg12i_version_contract import _create_master, _run, _source_truth_confirmation, _ref, auth_headers as _headers


@pytest.fixture
def auth_headers():
    return _headers.__wrapped__()


def _canvas_section(section_id: str, order: int, *, asset_id: str | None = None, elements=None, visible=True):
    assets = [] if asset_id is None else [{"asset_id": asset_id, "asset_content_hash": canonical_hash({"asset": asset_id})}]
    return {
        "section_id": section_id,
        "copy_ref": {"fields": [f"{section_id}_title", f"{section_id}_body"]},
        "approved_assets": assets,
        "rendering_mode": "approved_asset" if assets else "",
        "canvas": {"is_visible": visible, "height_px": 500},
        "canvas_elements": elements or [
            {"element_id": f"{section_id}:background", "kind": "background", "x": 0, "y": 0, "width": 760, "height": 500, "z_index": 0, "locked": True},
            {"element_id": f"{section_id}:text", "kind": "text", "x": 24, "y": 42, "width": 280, "height": 120, "z_index": 2, "locked": False},
            {"element_id": f"{section_id}:asset", "kind": "asset", "asset_id": asset_id or "", "x": 380, "y": 42, "width": 320, "height": 320, "z_index": 1, "locked": False},
        ],
    }


def _refresh_layout_hashes(rendering):
    evidence = dict(rendering.get("lg12_layout_evidence") or {})
    if evidence:
        renderer_body = {
            key: value for key, value in rendering.items()
            if key not in {"render_hash", "lg12_layout_evidence", "canonical_input_ref", "page_assembly_ref"}
        }
        evidence["renderer_hash"] = canonical_hash(renderer_body)
        evidence.pop("evidence_hash", None)
        evidence["evidence_hash"] = canonical_hash(evidence)
        rendering["lg12_layout_evidence"] = evidence
    rendering_body = deepcopy(rendering)
    rendering_body.pop("render_hash", None)
    rendering["render_hash"] = canonical_hash(rendering_body)


def _frozen_page(db, run, master, *, sections=None, mutate=None, refresh_after_mutate=True):
    sections = deepcopy(sections or [_canvas_section("hero", 0, asset_id="asset:hero"), _canvas_section("specs", 1)])
    copy_ref = dict(master.copy_artifact_ref_json)
    page_plan_ref = dict(master.page_plan_artifact_ref_json)
    for index, section in enumerate(sections):
        section["scene_ref"] = {
            "scene_id": f"scene:{section['section_id']}", "scene_type": "approved_scene", "scene_order": index,
            "page_plan_id": str(page_plan_ref.get("id") or page_plan_ref.get("artifact_id") or ""),
            "page_plan_version": page_plan_ref.get("version") or page_plan_ref.get("artifact_version"),
            "page_plan_hash": str(page_plan_ref.get("hash") or page_plan_ref.get("artifact_hash") or ""),
        }
    manifest_body = {"schema_version": "lg10-approved-asset-manifest-v1", "assets": []}
    manifest = {**manifest_body, "manifest_hash": canonical_hash(manifest_body)}
    canonical = {
        "design_direction": "balanced_sale",
        "planning_refs": {"copy": copy_ref, "page_plan": page_plan_ref},
        "brand_kit_ref": {"brand_kit_version_id": master.brand_kit_version_id, "brand_kit_hash": master.brand_kit_hash},
        "approved_asset_manifest": manifest,
        "sections": sections,
    }
    assembly = {"sections": [
        {"section_id": section["section_id"], "sort_order": index, "component_id": "media_with_copy", "layout_token": "image_text", "design_direction": "balanced_sale", "renderer_token": "balanced_sale_v1"}
        for index, section in enumerate(sections)
    ]}
    kit = db.query(BrandKitVersion).filter_by(id=master.brand_kit_version_id).one()
    tokens = resolve_lg10_brand_renderer_tokens(
        run=run, brand_kit_ref={"brand_kit_version_id": kit.id, "brand_kit_hash": kit.content_hash}, db=db,
    )
    copy_set = {field: f"{field} frozen text" for section in sections for field in section["copy_ref"]["fields"]}
    rendering = render_lg10_canonical_page_html(
        canonical_page_assembly_input=canonical, page_assembly=assembly, copy_set=copy_set, brand_tokens=tokens,
    )
    if mutate:
        mutate(canonical, rendering)
    if refresh_after_mutate:
        _refresh_layout_hashes(rendering)
    lineage = {
        "schema_version": "lg12-detail-page-quality-lineage-v1", "creator_run_id": run.id,
        "source_snapshot_ref": _ref(master.source_snapshot_version_id, master.source_snapshot_version, master.source_snapshot_hash),
        "truth_ref": _ref(master.truth_version_id, master.truth_version, master.truth_version_hash),
        "confirmation_ref": _ref(master.confirmation_version_id, master.confirmation_version, master.confirmation_version_hash),
        "master_ref": _ref(master.id, master.version, master.canonical_hash),
        "approved_asset_manifest_ref": dict(master.approved_asset_manifest_ref_json),
    }
    body = {
        "schema_version": "lg10-detail-page-version-v1",
        "lg10": {"canonical_page_assembly_input": canonical, "canonical_rendering": rendering},
        "lg11": {"schema_version": "lg11-canvas-v1"}, "lg12_quality_lineage": lineage,
        "commerce_renderer": {"sections": []}, "sections": sections,
    }
    page = DetailPageVersion(
        project_id=run.project_id, name="LG12 frozen layout fixture", style_key="balanced_sale", is_final=True,
        sections_json={**body, "snapshot_hash": canonical_hash(body)},
    )
    db.add(page); db.flush()
    return page, manifest["manifest_hash"]


def _setup(db, client, headers, tmp_path, **page_kwargs):
    run = _run(client, headers, db, tmp_path)
    chain = _source_truth_confirmation(db, run)
    master = _create_master(db, run, chain=chain)
    page, manifest_hash = _frozen_page(db, run, master, **page_kwargs)
    profile = create_quality_threshold_profile(
        db, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:layout"),
    )
    db.commit()
    return run, master, page, manifest_hash, profile


def _evaluate(db, run, master, page, manifest_hash, profile):
    return evaluate_layout_typography_brand_flow_domain(
        db,
        report_payload=_report_payload(
            run, page, manifest_hash, master, profile,
            report_id=f"layout-quality-report-{page.id}",
        ),
    )


def _codes(result):
    return {item["code"] for item in result["domain"]["findings"]}


def _submetric(result, metric_id):
    return next(item for item in result["domain"]["submetrics"] if item["metric_id"] == metric_id)


def test_valid_frozen_layout_is_deterministic_reference_only_and_provider_free(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path)
    before = (db_session.query(ImageGenerationJobRecord).count(), db_session.query(ImageGenerationOutboxRecord).count(), db_session.query(ImageGenerationCostApprovalRecord).count())
    first = _evaluate(db_session, run, master, page, digest, profile)
    assert first == _evaluate(db_session, run, master, page, digest, profile)
    assert first["domain"]["status"] == "complete"
    assert first["domain"]["evaluator_version"] == LAYOUT_TYPOGRAPHY_BRAND_FLOW_EVALUATOR_VERSION
    assert len(first["domain"]["submetrics"]) == 6
    assert "frozen text" not in repr(first)
    assert before == (db_session.query(ImageGenerationJobRecord).count(), db_session.query(ImageGenerationOutboxRecord).count(), db_session.query(ImageGenerationCostApprovalRecord).count())


def test_renderer_evidence_hash_ignores_only_lg10_frozen_wrapper_refs(client, db_session, auth_headers, tmp_path):
    def add_lg10_wrapper(_canonical, rendering):
        rendering["canonical_input_ref"] = {"schema_version": "lg10-canonical-page-assembly-v1", "input_hash": "a" * 64}
        rendering["page_assembly_ref"] = {"schema_version": "lg10-page-assembly-v1", "assembly_hash": "b" * 64}

    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, mutate=add_lg10_wrapper)
    assert _evaluate(db_session, run, master, page, digest, profile)["domain"]["status"] == "complete"


def test_missing_frozen_layout_evidence_is_needs_review_not_complete(client, db_session, auth_headers, tmp_path):
    def mutate(_canonical, rendering):
        rendering.pop("lg12_layout_evidence")
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, mutate=mutate)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "needs_review"
    assert result["domain"]["score"] == 0
    assert "missing_frozen_layout_evidence" in _codes(result)


@pytest.mark.parametrize(
    "dimension,metric_id,mutate",
    [
        ("geometry_evaluable", "layout_geometry", lambda evidence: evidence["sections"][0].pop("bounds")),
        ("geometry_evaluable", "layout_geometry", lambda evidence: evidence["sections"][0]["elements"][0].pop("element_id")),
        ("typography_evaluable", "typography", lambda evidence: evidence["sections"][0].pop("typography_roles")),
        ("scene_flow_evaluable", "scene_flow", lambda evidence: evidence["sections"][0]["scene"].pop("scene_id")),
        ("pageplan_evaluable", "scene_flow", lambda evidence: evidence.pop("page_plan_ref")),
        ("brand_evaluable", "brand_kit", lambda evidence: evidence.pop("brand_kit_ref")),
    ],
)
def test_required_layout_evidence_dimensions_are_needs_review(
    client, db_session, auth_headers, tmp_path, dimension, metric_id, mutate,
):
    def alter(_canonical, rendering):
        mutate(rendering["lg12_layout_evidence"])

    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, mutate=alter)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "needs_review"
    assert f"missing_{dimension}" in _codes(result)
    assert _submetric(result, metric_id)["status"] == "needs_review"


def test_missing_renderer_hash_is_not_complete(client, db_session, auth_headers, tmp_path):
    def missing_renderer_hash(_canonical, rendering):
        evidence = rendering["lg12_layout_evidence"]
        evidence.pop("renderer_hash")
        evidence.pop("evidence_hash")
        evidence["evidence_hash"] = canonical_hash(evidence)
        rendering_body = deepcopy(rendering)
        rendering_body.pop("render_hash", None)
        rendering["render_hash"] = canonical_hash(rendering_body)

    run, master, page, digest, profile = _setup(
        db_session, client, auth_headers, tmp_path,
        mutate=missing_renderer_hash, refresh_after_mutate=False,
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "needs_review"
    assert "missing_renderer_evaluable" in _codes(result)
    assert _submetric(result, "visual_hierarchy")["status"] == "needs_review"


def test_missing_evidence_hash_is_not_complete(client, db_session, auth_headers, tmp_path):
    def missing_evidence_hash(_canonical, rendering):
        rendering["lg12_layout_evidence"].pop("evidence_hash")
        rendering_body = deepcopy(rendering)
        rendering_body.pop("render_hash", None)
        rendering["render_hash"] = canonical_hash(rendering_body)

    run, master, page, digest, profile = _setup(
        db_session, client, auth_headers, tmp_path,
        mutate=missing_evidence_hash, refresh_after_mutate=False,
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "needs_review"
    assert "missing_frozen_layout_evidence" in _codes(result)


@pytest.mark.parametrize(
    "token,value",
    [
        ("size_token", "renderer_body"),
        ("weight_token", "renderer_body"),
        ("line_height_token", "renderer_text_1_2"),
        ("letter_spacing_token", "renderer_tracking_wide"),
        ("color_token", "text"),
    ],
)
def test_frozen_typography_tokens_are_evaluated_against_renderer_contract(
    client, db_session, auth_headers, tmp_path, token, value,
):
    def alter(_canonical, rendering):
        rendering["lg12_layout_evidence"]["sections"][0]["typography_roles"][0][token] = value

    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, mutate=alter)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "typography_role_token_mismatch" in _codes(result)
    if token in {"size_token", "weight_token"}:
        assert "visual_hierarchy_token_mismatch" in _codes(result)


def test_alignment_spacing_and_pinned_contrast_contract_are_evaluated(client, db_session, auth_headers, tmp_path):
    def alter(_canonical, rendering):
        evidence = rendering["lg12_layout_evidence"]
        evidence["sections"][0]["alignment"]["actual_token"] = "renderer_text_center"
        evidence["sections"][0]["section_spacing_px"] = 999
        evidence["color_tokens"]["text"] = "#ffffff"
        evidence["color_tokens"]["surface"] = "#ffffff"
        evidence["contrast"]["minimum_ratio"] = 2.0

    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, mutate=alter)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert {"alignment_token_mismatch", "spacing_token_mismatch", "contrast_ratio_below_contract"} <= _codes(result)


def test_scene_evidence_parity_distinguishes_scene_and_asset_repetition(client, db_session, auth_headers, tmp_path):
    first = _canvas_section("hero", 0, asset_id="asset:reused")
    second = _canvas_section("specs", 1, asset_id="asset:reused")
    run, master, page, digest, profile = _setup(
        db_session, client, auth_headers, tmp_path, sections=[first, second],
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "duplicate_scene_asset" in _codes(result)
    assert not ({"scene_order_mismatch", "scene_identity_mismatch", "duplicate_scene_identity"} & _codes(result))


@pytest.mark.parametrize(
    "code,mutate",
    [
        ("missing_planned_scene", lambda evidence: evidence["sections"].pop()),
        ("duplicate_scene_identity", lambda evidence: evidence["sections"].__getitem__(1)["scene"].__setitem__("scene_id", "scene:hero")),
        ("scene_identity_mismatch", lambda evidence: evidence["sections"][0]["scene"].__setitem__("scene_type", "wrong_scene_type")),
        ("scene_identity_mismatch", lambda evidence: evidence["sections"][0]["scene"]["page_plan_ref"].__setitem__("hash", "f" * 64)),
    ],
)
def test_page_plan_scene_sequence_is_checked_independently(
    client, db_session, auth_headers, tmp_path, code, mutate,
):
    def alter(_canonical, rendering):
        mutate(rendering["lg12_layout_evidence"])
        if code == "missing_planned_scene":
            rendering["sections"].pop()

    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, mutate=alter)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert code in _codes(result)
    assert _submetric(result, "scene_flow")["status"] == "failed"


@pytest.mark.parametrize("kind,code", [("overflow", "element_overflow"), ("overlap", "element_overlap")])
def test_frozen_canvas_geometry_reuses_lg11_contract(client, db_session, auth_headers, tmp_path, kind, code):
    elements = _canvas_section("hero", 0, asset_id="asset:hero")["canvas_elements"]
    if kind == "overflow":
        elements[2]["x"] = 600
    else:
        elements[2]["x"] = 100; elements[2]["y"] = 80
    run, master, page, digest, profile = _setup(
        db_session, client, auth_headers, tmp_path,
        sections=[_canvas_section("hero", 0, asset_id="asset:hero", elements=elements), _canvas_section("specs", 1)],
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert code in _codes(result)
    finding = next(item for item in result["domain"]["findings"] if item["code"] == code)
    assert any(ref["type"] == "frozen_canvas_element" for ref in finding["target_refs"])


def test_hidden_and_allowed_decorative_overlap_do_not_false_positive(client, db_session, auth_headers, tmp_path):
    elements = _canvas_section("hero", 0, asset_id="asset:hero")["canvas_elements"]
    elements.append({"element_id": "hero:deco", "kind": "decorative", "x": 100, "y": 80, "width": 100, "height": 100, "z_index": 3, "locked": False, "allowed_overlap_with": ["hero:text"]})
    elements[-2]["x"] = 100; elements[-2]["y"] = 80
    run, master, page, digest, profile = _setup(
        db_session, client, auth_headers, tmp_path,
        sections=[_canvas_section("hero", 0, asset_id="asset:hero", elements=elements, visible=False), _canvas_section("specs", 1)],
    )
    assert "element_overlap" not in _codes(_evaluate(db_session, run, master, page, digest, profile))


def test_brand_and_page_plan_parity_are_checked_from_frozen_identity(client, db_session, auth_headers, tmp_path):
    def mutate(canonical, rendering):
        canonical["brand_kit_ref"]["brand_kit_hash"] = "f" * 64
        rendering["brand_tokens"]["color_tokens"]["accent"] = "#ffffff"
        evidence = dict(rendering["lg12_layout_evidence"]); evidence["color_tokens"]["accent"] = "#ffffff"
        evidence_body = deepcopy(evidence); evidence_body.pop("evidence_hash")
        evidence["evidence_hash"] = canonical_hash(evidence_body); rendering["lg12_layout_evidence"] = evidence
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, mutate=mutate)
    codes = _codes(_evaluate(db_session, run, master, page, digest, profile))
    assert {"brand_kit_identity_mismatch", "brand_color_token_mismatch"} <= codes


def test_scene_flow_order_and_duplicate_asset_are_structured(client, db_session, auth_headers, tmp_path):
    first = _canvas_section("hero", 0, asset_id="asset:reused")
    second = _canvas_section("specs", 1, asset_id="asset:reused")
    def mutate(_canonical, rendering):
        rendering["sections"] = list(reversed(rendering["sections"]))
        evidence = dict(rendering["lg12_layout_evidence"]); evidence["sections"] = list(reversed(evidence["sections"]))
        body = deepcopy(evidence); body.pop("evidence_hash")
        evidence["evidence_hash"] = canonical_hash(body); rendering["lg12_layout_evidence"] = evidence
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=[first, second], mutate=mutate)
    result = _evaluate(db_session, run, master, page, digest, profile)
    codes = _codes(result)
    assert {"section_order_mismatch", "scene_order_mismatch", "duplicate_scene_asset"} <= codes
    assert _submetric(result, "scene_flow")["status"] == "failed"


def test_tampered_layout_evidence_fails_closed(client, db_session, auth_headers, tmp_path):
    def mutate(_canonical, rendering):
        rendering["lg12_layout_evidence"]["renderer_width"] = 1
    run, master, page, digest, profile = _setup(
        db_session, client, auth_headers, tmp_path, mutate=mutate, refresh_after_mutate=False,
    )
    with pytest.raises(QualityAssessmentContractError, match="layout evidence hash"):
        _evaluate(db_session, run, master, page, digest, profile)
