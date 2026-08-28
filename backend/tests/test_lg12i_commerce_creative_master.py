"""TASK-12I.8 frozen Brief -> Master reference-index contract."""

from __future__ import annotations

import json
import hashlib

import pytest

from src.db.models import (
    AgentRun, Asset, BrandKit, BrandKitVersion, CommerceCreativeMasterVersion,
    ProductProject, ReviewInputVersion,
)
from src.services.creative_brief_service import (
    CreativeBriefInputError,
    compile_lg12i_product_creative_brief,
    create_lg12i_approved_fact_snapshot,
    create_review_input,
)
from src.services.product_intake_version_service import (
    IntakeVersionContractError,
    create_commerce_creative_master_version,
    lg12i_approved_asset_manifest_reference,
    lg12i_pending_production_artifact_reference,
    master_reference_index,
)
from test_lg5_image_generation_subgraph import JPEG, _create_run, auth_headers as _lg5_auth_headers
from test_lg12i_version_contract import _ref, _source_truth_confirmation


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


def _run(client, headers, db_session, tmp_path):
    return _create_run(client, headers, db_session, tmp_path)


def _brand_kit(db_session, run):
    kit = BrandKit(workspace_id=run.workspace_id, name=f"LG12I Master kit {run.id}", created_by=run.created_by)
    db_session.add(kit)
    db_session.flush()
    version = BrandKitVersion(
        brand_kit_id=kit.id, workspace_id=run.workspace_id, project_id=run.project_id,
        version=1, status="active", scope="project", color_tokens={"accent": "#0f766e"},
        typography={"body_font": "system-ui"},
        content_hash="4" * 64, created_by=run.created_by,
    )
    db_session.add(version)
    db_session.flush()
    return version


def _other_project(db_session, run):
    current = db_session.query(ProductProject).filter_by(id=run.project_id).one()
    other = ProductProject(
        workspace_id=run.workspace_id, brand_id=current.brand_id, name="Other LG12I project",
    )
    db_session.add(other)
    db_session.flush()
    return other


def _source_chain_with_asset(
    db_session, run, tmp_path, *, rights_status="rights_confirmed", source_type="uploaded",
    usage_status="seller_owned", frozen_hash=None,
):
    asset_path = tmp_path / "lg12i-final-use.jpg"
    asset_path.write_bytes(JPEG)
    digest = hashlib.sha256(JPEG).hexdigest()
    asset = Asset(
        project_id=run.project_id, source_type=source_type, usage_status=usage_status,
        filename=asset_path.name, file_path=str(asset_path), mime_type="image/jpeg",
        file_size=len(JPEG), content_hash=digest, asset_role="product_main",
        quality_status="usable", identity_status="confirmed",
    )
    db_session.add(asset)
    db_session.flush()
    asset_ref = {
        "id": str(asset.id), "version": 1, "hash": frozen_hash or digest,
        "schema_version": "lg12i-photo-asset-ref-v1", "artifact_key": "photo_asset",
        "rights_status": rights_status,
    }
    chain = _source_truth_confirmation(
        db_session, run,
        source_refs=[{key: value for key, value in asset_ref.items() if key != "rights_status"}],
        provenance={"source_asset_refs": [asset_ref]},
        rights={"status": "rights_confirmed"},
    )
    return chain, asset, asset_path


def _build_brief_and_master(db_session, run, chain):
    source, truth, confirmation = chain
    kit = _brand_kit(db_session, run)
    source_ref = _ref(source.id, source.version, source.canonical_hash)
    truth_ref = _ref(truth.id, truth.version, truth.canonical_hash)
    confirmation_ref = _ref(confirmation.id, confirmation.version, confirmation.canonical_hash)
    kit_ref = _ref(kit.id, kit.version, kit.content_hash)
    brief = compile_lg12i_product_creative_brief(
        db_session, run, source_reference=source_ref, truth_reference=truth_ref,
        confirmation_reference=confirmation_ref, brand_kit_reference=kit_ref,
        target_channels=["coupang", "smartstore"],
    )
    facts = create_lg12i_approved_fact_snapshot(db_session, run, creative_brief=brief)
    brief_ref = _ref(brief.id, brief.version, brief.output_hash)
    master = create_commerce_creative_master_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        creator_run_id=run.id, created_by=run.created_by,
        source_reference=source_ref, truth_reference=truth_ref, confirmation_reference=confirmation_ref,
        creative_brief_reference=brief_ref, brand_kit_reference=kit_ref,
        evidence_artifact_refs=list(truth.evidence_refs_json),
        approved_fact_snapshot_ref=_ref(facts.id, 1, facts.snapshot_hash),
        approved_asset_manifest_ref=lg12i_approved_asset_manifest_reference(
            source_reference=source_ref, usable_asset_refs=list(brief.usable_asset_refs_json),
        ),
        copy_artifact_ref=lg12i_pending_production_artifact_reference(
            artifact_key="copywriting", creative_brief_reference=brief_ref,
        ),
        page_plan_artifact_ref=lg12i_pending_production_artifact_reference(
            artifact_key="page_planning", creative_brief_reference=brief_ref,
        ),
        target_channels=["smartstore", "coupang"],
    )
    return brief, facts, master, kit


def _create_master_for_brief(db_session, run, chain, brief, kit):
    source, truth, confirmation = chain
    source_ref = _ref(source.id, source.version, source.canonical_hash)
    truth_ref = _ref(truth.id, truth.version, truth.canonical_hash)
    confirmation_ref = _ref(confirmation.id, confirmation.version, confirmation.canonical_hash)
    facts = create_lg12i_approved_fact_snapshot(db_session, run, creative_brief=brief)
    brief_ref = _ref(brief.id, brief.version, brief.output_hash)
    return create_commerce_creative_master_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        creator_run_id=run.id, created_by=run.created_by,
        source_reference=source_ref, truth_reference=truth_ref, confirmation_reference=confirmation_ref,
        creative_brief_reference=brief_ref, brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash),
        evidence_artifact_refs=list(truth.evidence_refs_json),
        approved_fact_snapshot_ref=_ref(facts.id, 1, facts.snapshot_hash),
        approved_asset_manifest_ref=lg12i_approved_asset_manifest_reference(
            source_reference=source_ref, usable_asset_refs=list(brief.usable_asset_refs_json),
        ),
        copy_artifact_ref=lg12i_pending_production_artifact_reference(
            artifact_key="copywriting", creative_brief_reference=brief_ref,
        ),
        page_plan_artifact_ref=lg12i_pending_production_artifact_reference(
            artifact_key="page_planning", creative_brief_reference=brief_ref,
        ),
        target_channels=list(brief.target_channels),
    )


def test_lg12i_brief_then_master_is_reference_only_and_idempotent(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    chain = _source_truth_confirmation(db_session, run)
    brief, facts, master, kit = _build_brief_and_master(db_session, run, chain)
    source, truth, confirmation = chain

    assert brief.source_snapshot_version_id == source.id
    assert brief.truth_version_id == truth.id
    assert brief.confirmation_version_id == confirmation.id
    assert brief.brand_kit_version_id == kit.id
    assert brief.target_channels == ["coupang", "smartstore"]
    assert master.creative_brief_version_id == brief.id
    assert master.downstream_output_refs_json == []
    assert master.evidence_artifact_refs_json == sorted(
        truth.evidence_refs_json, key=lambda item: (item["id"], item["version"], item["hash"]),
    )
    reference_index = master_reference_index(master)
    assert set(reference_index) >= {
        "source", "truth", "confirmation", "creative_brief", "brand_kit",
        "evidence_artifacts", "approved_fact_snapshot", "approved_asset_manifest",
        "copy_artifact", "page_plan_artifact", "target_channels",
    }
    assert not any(key in json.dumps(reference_index, sort_keys=True) for key in ("raw_html", "raw_body", "ocr_text", "image_bytes"))

    second_brief = compile_lg12i_product_creative_brief(
        db_session, run,
        source_reference=_ref(source.id, source.version, source.canonical_hash),
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
        brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash),
        target_channels=["smartstore", "coupang"],
    )
    assert second_brief.id == brief.id
    assert create_lg12i_approved_fact_snapshot(db_session, run, creative_brief=brief).id == facts.id
    second_master = create_commerce_creative_master_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        creator_run_id=run.id, created_by=run.created_by,
        source_reference=_ref(source.id, source.version, source.canonical_hash),
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
        creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash),
        brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash),
        evidence_artifact_refs=list(truth.evidence_refs_json),
        approved_fact_snapshot_ref=_ref(facts.id, 1, facts.snapshot_hash),
        approved_asset_manifest_ref=lg12i_approved_asset_manifest_reference(
            source_reference=_ref(source.id, source.version, source.canonical_hash),
            usable_asset_refs=list(brief.usable_asset_refs_json),
        ),
        copy_artifact_ref=lg12i_pending_production_artifact_reference(
            artifact_key="copywriting", creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash),
        ),
        page_plan_artifact_ref=lg12i_pending_production_artifact_reference(
            artifact_key="page_planning", creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash),
        ),
        target_channels=["coupang", "smartstore"],
    )
    assert second_master.id == master.id
    assert db_session.query(CommerceCreativeMasterVersion).filter_by(project_id=run.project_id).count() == 1


def test_lg12i_master_blocks_cross_run_brief_and_allows_only_successor_downstream_refs(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    chain = _source_truth_confirmation(db_session, run)
    brief, _facts, master, kit = _build_brief_and_master(db_session, run, chain)
    source, truth, confirmation = chain

    with pytest.raises(IntakeVersionContractError, match="initial.*downstream"):
        create_commerce_creative_master_version(
            db_session, workspace_id=run.workspace_id, project_id=run.project_id,
            creator_run_id=run.id, created_by=run.created_by,
            source_reference=_ref(source.id, source.version, source.canonical_hash),
            truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
            confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
            creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash),
            brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash),
            evidence_artifact_refs=list(truth.evidence_refs_json),
            approved_fact_snapshot_ref=dict(master.approved_fact_snapshot_ref_json),
            approved_asset_manifest_ref=dict(master.approved_asset_manifest_ref_json),
            copy_artifact_ref=dict(master.copy_artifact_ref_json), page_plan_artifact_ref=dict(master.page_plan_artifact_ref_json),
            target_channels=["coupang", "smartstore"],
            downstream_output_refs=[{**_ref("detail-page:frozen"), "kind": "DetailPageVersion"}],
        )

    successor = create_commerce_creative_master_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        creator_run_id=run.id, created_by=run.created_by,
        source_reference=_ref(source.id, source.version, source.canonical_hash),
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
        creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash),
        brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash),
        evidence_artifact_refs=list(truth.evidence_refs_json),
        approved_fact_snapshot_ref=dict(master.approved_fact_snapshot_ref_json),
        approved_asset_manifest_ref=dict(master.approved_asset_manifest_ref_json),
        copy_artifact_ref=dict(master.copy_artifact_ref_json), page_plan_artifact_ref=dict(master.page_plan_artifact_ref_json),
        target_channels=["coupang", "smartstore"], parent_version_id=master.id,
        downstream_output_refs=[{**_ref("detail-page:frozen"), "kind": "DetailPageVersion"}],
    )
    assert successor.parent_version_id == master.id
    assert master.downstream_output_refs_json == []

    other_run = AgentRun(
        workspace_id=run.workspace_id, project_id=run.project_id, created_by=run.created_by,
        mode="mock", status="created", current_stage="intake", input_snapshot={}, outputs_json={},
        graph_thread_id="other-thread-for-master-contract",
    )
    db_session.add(other_run)
    db_session.flush()
    with pytest.raises(CreativeBriefInputError, match="exact run"):
        compile_lg12i_product_creative_brief(
            db_session, other_run,
            source_reference=_ref(source.id, source.version, source.canonical_hash),
            truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
            confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
            brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash), target_channels=["smartstore"],
        )


def test_lg12i_brand_kit_scope_is_identical_for_brief_and_master(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    chain = _source_truth_confirmation(db_session, run)
    source, truth, confirmation = chain
    kit = _brand_kit(db_session, run)
    source_ref, truth_ref, confirmation_ref = (
        _ref(source.id, source.version, source.canonical_hash),
        _ref(truth.id, truth.version, truth.canonical_hash),
        _ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
    )
    # A real workspace-global kit is reusable within its workspace.
    kit.scope, kit.project_id = "workspace", None
    db_session.flush()
    brief = compile_lg12i_product_creative_brief(
        db_session, run, source_reference=source_ref, truth_reference=truth_ref,
        confirmation_reference=confirmation_ref, brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash),
        target_channels=["smartstore"],
    )
    facts = create_lg12i_approved_fact_snapshot(db_session, run, creative_brief=brief)
    other_project = _other_project(db_session, run)
    other_kit = BrandKit(workspace_id=run.workspace_id, name="Other project kit", created_by=run.created_by)
    db_session.add(other_kit); db_session.flush()
    cross_project = BrandKitVersion(
        brand_kit_id=other_kit.id, workspace_id=run.workspace_id, project_id=other_project.id,
        version=1, status="active", scope="project", color_tokens={}, typography={},
        content_hash="8" * 64, created_by=run.created_by,
    )
    db_session.add(cross_project); db_session.flush()
    with pytest.raises(CreativeBriefInputError, match="different project"):
        compile_lg12i_product_creative_brief(
            db_session, run, source_reference=source_ref, truth_reference=truth_ref,
            confirmation_reference=confirmation_ref,
            brand_kit_reference=_ref(cross_project.id, cross_project.version, cross_project.content_hash),
            target_channels=["smartstore"],
        )
    with pytest.raises(IntakeVersionContractError, match="different project"):
        create_commerce_creative_master_version(
            db_session, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
            created_by=run.created_by, source_reference=source_ref, truth_reference=truth_ref,
            confirmation_reference=confirmation_ref, creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash),
            brand_kit_reference=_ref(cross_project.id, cross_project.version, cross_project.content_hash),
            evidence_artifact_refs=list(truth.evidence_refs_json),
            approved_fact_snapshot_ref=_ref(facts.id, 1, facts.snapshot_hash),
            approved_asset_manifest_ref=lg12i_approved_asset_manifest_reference(source_reference=source_ref, usable_asset_refs=[]),
            copy_artifact_ref=lg12i_pending_production_artifact_reference(artifact_key="copywriting", creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash)),
            page_plan_artifact_ref=lg12i_pending_production_artifact_reference(artifact_key="page_planning", creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash)),
            target_channels=["smartstore"],
        )


def test_lg12i_review_reference_must_be_a_persisted_project_artifact(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    source, truth, confirmation = _source_truth_confirmation(db_session, run)
    kit = _brand_kit(db_session, run)
    project = db_session.query(ProductProject).filter_by(id=run.project_id).one()
    review = create_review_input(
        db_session, project=project, user_id=run.created_by, input_format="paste",
        text="quiet, clean visual preference", consent_status="confirmed", rights_status="confirmed",
    )
    common = dict(
        source_reference=_ref(source.id, source.version, source.canonical_hash),
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
        brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash), target_channels=["smartstore"],
    )
    brief = compile_lg12i_product_creative_brief(
        db_session, run, **common,
        review_reference_refs=[{"id": review.id, "version": review.version, "hash": review.content_hash, "artifact_key": "review_input"}],
    )
    assert brief.review_reference_refs_json == [{"id": review.id, "version": review.version, "hash": review.content_hash, "artifact_key": "review_input"}]
    for bad_ref in (
        {"id": "missing-review", "version": 1, "hash": "a" * 64, "artifact_key": "review_input"},
        {"id": review.id, "version": review.version, "hash": "a" * 64, "artifact_key": "review_input"},
        {"id": review.id, "version": review.version + 1, "hash": review.content_hash, "artifact_key": "review_input"},
        {"id": review.id, "version": review.version, "hash": review.content_hash, "artifact_key": "asset"},
    ):
        with pytest.raises(CreativeBriefInputError):
            compile_lg12i_product_creative_brief(db_session, run, **common, review_reference_refs=[bad_ref])
    # A persisted artifact in another project cannot be injected by ID/hash.
    other = _other_project(db_session, run)
    foreign = ReviewInputVersion(
        workspace_id=run.workspace_id, project_id=other.id, version=1, input_format="paste",
        source_metadata={}, consent_status="confirmed", rights_status="confirmed",
        content_text="foreign", content_hash=hashlib.sha256(b"foreign").hexdigest(), created_by=run.created_by,
    )
    db_session.add(foreign); db_session.flush()
    with pytest.raises(CreativeBriefInputError, match="not available"):
        compile_lg12i_product_creative_brief(
            db_session, run, **common,
            review_reference_refs=[{"id": foreign.id, "version": 1, "hash": foreign.content_hash, "artifact_key": "review_input"}],
        )


def test_lg12i_final_use_assets_require_actual_file_hash_and_rights(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    chain, asset, asset_path = _source_chain_with_asset(db_session, run, tmp_path)
    source, truth, confirmation = chain
    kit = _brand_kit(db_session, run)
    common = dict(
        source_reference=_ref(source.id, source.version, source.canonical_hash),
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
        brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash), target_channels=["smartstore"],
    )
    valid = compile_lg12i_product_creative_brief(db_session, run, **common)
    assert valid.usable_asset_refs_json == [{"id": asset.id, "version": 1, "hash": asset.content_hash, "schema_version": "asset-sha256-v1"}]
    # Never change the frozen row: a changed file must be excluded from a new Brief.
    asset_path.write_bytes(JPEG + b"tampered")
    changed = compile_lg12i_product_creative_brief(
        db_session, run, **{**common, "target_channels": ["coupang"]},
    )
    assert changed.usable_asset_refs_json == []
    assert changed.brief_json["visual_direction"]["asset_exclusions"][0]["reason"] == "asset_actual_hash_mismatch"
    assert asset.content_hash == hashlib.sha256(JPEG).hexdigest()
    with pytest.raises(IntakeVersionContractError, match="tampered Brief asset"):
        _create_master_for_brief(db_session, run, chain, valid, kit)
    changed_master = _create_master_for_brief(db_session, run, chain, changed, kit)
    assert changed_master.approved_asset_manifest_ref_json == lg12i_approved_asset_manifest_reference(
        source_reference=common["source_reference"], usable_asset_refs=[],
    )


@pytest.mark.parametrize(
    ("rights_status", "source_type", "usage_status", "remove_file", "frozen_hash", "reason"),
    [
        ("unconfirmed", "uploaded", "seller_owned", False, None, "asset_rights_not_confirmed"),
        ("rights_confirmed", "supplier", "seller_owned", False, None, "asset_provenance_ineligible"),
        ("rights_confirmed", "uploaded", "seller_owned", True, None, "asset_storage_unavailable"),
        ("rights_confirmed", "uploaded", "seller_owned", False, "0" * 64, "asset_actual_hash_mismatch"),
    ],
)
def test_lg12i_final_use_asset_rejections_are_fail_closed(
    client, auth_headers, db_session, tmp_path,
    rights_status, source_type, usage_status, remove_file, frozen_hash, reason,
):
    run = _run(client, auth_headers, db_session, tmp_path)
    chain, _asset, asset_path = _source_chain_with_asset(
        db_session, run, tmp_path, rights_status=rights_status, source_type=source_type,
        usage_status=usage_status, frozen_hash=frozen_hash,
    )
    if remove_file:
        asset_path.unlink()
    source, truth, confirmation = chain
    kit = _brand_kit(db_session, run)
    brief = compile_lg12i_product_creative_brief(
        db_session, run,
        source_reference=_ref(source.id, source.version, source.canonical_hash),
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
        brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash), target_channels=["smartstore"],
    )
    assert brief.usable_asset_refs_json == []
    assert brief.brief_json["visual_direction"]["asset_exclusions"][0]["reason"] == reason
