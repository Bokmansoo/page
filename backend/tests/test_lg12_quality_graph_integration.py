"""Persisted LG-12 quality-graph integration foundations.

TASK-12.9A builds this fixture incrementally: immutable intake lineage first,
then a frozen PagePlan/DetailPage, followed by reference-only frozen QA
evidence.  Evaluators, Quality Bar, and graph QA routing intentionally remain
outside this integration foundation.
"""

from __future__ import annotations

import hashlib
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from PIL import Image

from src.db.models import (
    AgentRun,
    Asset,
    BrandKitVersion,
    CommerceCreativeMasterVersion,
    DetailPageVersion,
    ExportArtifact,
    ImageGenerationCostApprovalRecord,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductCreativeBriefVersion,
    ProductProject,
    ProductSourceSnapshotVersion,
    ProductTruthVersion,
    QualityAssessmentReportVersion,
    QualityThresholdProfileVersion,
    SellerConfirmationVersion,
    Workspace,
)
from src.agents.schemas import CopySetOutput, DetailPagePlanOutput, VisualPlanOutput
from src.services.brand_kit_service import create_kit, create_version
from src.services.creative_brief_service import (
    compile_lg12i_product_creative_brief,
    create_lg12i_approved_fact_snapshot,
)
from src.services.product_intake_version_service import (
    canonical_version_hash,
    create_commerce_creative_master_version,
    create_product_source_snapshot_version,
    create_product_truth_version,
    create_seller_confirmation_version,
    lg12i_approved_asset_manifest_reference,
    lg12i_pending_production_artifact_reference,
)
from src.services.langgraph_commerce_planning_service import (
    COMMERCE_VERSION,
    _store as store_commerce_planning_artifact,
    resolve_commerce_planning_artifact_version,
)
from src.services.langgraph_discovery_service import langgraph_execution_session
from src.services.langgraph_run_service import AgentRunGraphProjector
from src.services.product_identity_validator import build_frozen_image_quality_evidence
from src.services.page_finalization_service import (
    build_canonical_page_assembly_input,
    build_canonical_page_rendering_artifact,
    build_page_assembly_structure,
    build_lg11_copy_version_fork,
    build_lg11_style_version_fork,
    persist_lg10_detail_page_version,
    persist_lg11_copy_version_fork,
    persist_lg11_style_version_fork,
    preview_lg11_edit_intent,
)
from src.services.export_service import (
    build_lg10_standalone_export_bundle,
    write_lg12_frozen_export_parity_evidence,
)
from src.services.prompt_intelligence_service import canonical_hash
from src.services.quality_assessment_service import (
    build_lg12_quality_assessment_report,
    validate_quality_assessment_report_version,
)
from src.services.quality_bar_service import aggregate_quality_bar


# TASK-12.11 runs this persisted, zero-cost production graph coverage together
# with its semantic baseline comparator.  The only provider seam in this file
# is the existing deterministic fake image provider used by IMAGE_REWORK.
pytestmark = [pytest.mark.integration, pytest.mark.lg12_fake_quality_gate]


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Keep this integration fixture independent of other test helpers."""

    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def _reference(identifier: str, version: int = 1, digest: str | None = None, **extra: str) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "id": identifier,
        "version": version,
        "hash": digest or canonical_version_hash({"id": identifier, "version": version}),
    }
    reference.update(extra)
    return reference


def _confirmed_fact_reference(
    *,
    truth_fact: dict[str, Any],
    source_ref: dict[str, Any],
    evidence_ref: dict[str, Any],
    actor_id: str,
    fact_id: str = "fact:product:model",
    field_id: str = "model",
    normalized_value: str = "SF-100",
    unit: str | None = None,
) -> dict[str, Any]:
    """Create the production value-bearing confirmation reference, not an audit-only answer."""

    clarification_ref = _reference(
        "clarification:product-model", schema_version="lg12i-seller-clarification-v1"
    )
    answer_ref = _reference(
        "seller-answer:product-model", schema_version="lg12i-seller-answer-v1"
    )
    identity = {
        "original_truth_item_ref": truth_fact,
        "fact_id": fact_id,
        "field_id": field_id,
        "normalized_value": normalized_value,
        "unit": unit,
        "source_kind": "product_truth_candidate",
        "clarification_ref": clarification_ref,
        "answer_ref": answer_ref,
        "seller_actor_id": actor_id,
        "confirmation_cycle": 1,
        "source_refs": [source_ref],
        "evidence_refs": [evidence_ref],
        "selected_observation_ref": None,
        "conflicting_observation_refs": [],
        "decision_status": "confirmed",
    }
    provenance_hash = canonical_version_hash(identity)
    return {
        **truth_fact,
        "provenance_ref": evidence_ref,
        "confirmed_fact_id": "seller-confirmed-fact:" + provenance_hash[:24],
        "fact_id": fact_id,
        "field_id": field_id,
        "normalized_value": normalized_value,
        "unit": unit,
        "value_structure": {"value": normalized_value, "unit": unit},
        "source_kind": "product_truth_candidate",
        "original_truth_item_ref": truth_fact,
        "clarification_ref": clarification_ref,
        "answer_ref": answer_ref,
        "seller_actor_id": actor_id,
        "confirmation_cycle": 1,
        "source_refs": [source_ref],
        "evidence_refs": [evidence_ref],
        "selected_observation_ref": None,
        "conflicting_observation_refs": [],
        "provenance_hash": provenance_hash,
        "decision_status": "confirmed",
    }


def _create_run(
    client,
    headers: dict[str, str],
    db_session,
    *,
    product_name: str = "LG-12 quality integration product",
) -> AgentRun:
    """Use the public production run scaffold rather than importing another test's helper."""

    response = client.post(
        "/api/agent-runs",
        headers=headers,
        json={
            "product_name": product_name,
            "description": "A small persisted lineage fixture.",
        },
    )
    assert response.status_code == 201, response.text
    return db_session.query(AgentRun).filter_by(id=response.json()["id"]).one()


def build_valid_lg12_master_lineage(
    client,
    headers: dict[str, str],
    db_session,
    *,
    product_name: str = "LG-12 quality integration product",
) -> dict[str, Any]:
    """Persist the minimal valid Source -> Truth -> Confirmation -> Brief -> Master lineage.

    The fixture intentionally has no asset, PagePlan, DetailPage, renderer, QA,
    or Quality Bar artifacts.  It uses a clean seller-confirmed model identity
    and the production immutable-version/Brief/Master services only.
    """

    run = _create_run(client, headers, db_session, product_name=product_name)
    source_input_ref = _reference("seller-source:manual:sf-100", schema_version="lg12i-test-source-ref-v1")
    source = create_product_source_snapshot_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        input_mode="manual",
        source_refs=[source_input_ref],
        provenance={"source": "seller_entered", "source_kind": "manual"},
        rights={"status": "rights_confirmed"},
        source_fidelity={"status": "complete"},
    )
    source_ref = _reference(source.id, source.version, source.canonical_hash)
    fact_ref = _reference("fact:product:model")
    evidence_ref = _reference("evidence:seller:product-model")
    truth = create_product_truth_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_reference=source_ref,
        fact_refs=[fact_ref],
        evidence_refs=[evidence_ref],
        normalization={"normalization_version": "lg12-quality-graph-integration-v1"},
    )
    truth_ref = _reference(truth.id, truth.version, truth.canonical_hash)
    confirmation = create_seller_confirmation_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        truth_reference=truth_ref,
        answers=[{"question_id": "confirm-product-model", "answer": "SF-100"}],
        confirmed_fact_refs=[
            _confirmed_fact_reference(
                truth_fact=fact_ref, source_ref=source_input_ref,
                evidence_ref=evidence_ref, actor_id=run.created_by,
            )
        ],
        rejected_fact_refs=[],
        unknown_fact_refs=[],
        rights_confirmations=[{"source_ref": source_input_ref["id"], "status": "rights_confirmed"}],
    )
    confirmation_ref = _reference(confirmation.id, confirmation.version, confirmation.canonical_hash)

    # Brand Kit service is intentionally used instead of direct BrandKit ORM
    # construction, because Brief/Master both enforce its persisted scope/hash.
    brand_kit = create_kit(
        db_session, run.workspace_id, run.created_by, f"LG-12 quality integration {run.id}"
    )
    brand_kit_version = create_version(
        db_session,
        run.workspace_id,
        run.created_by,
        brand_kit.id,
        {
            "color_tokens": {"accent": "#0f766e"},
            # Use the persisted Brand Kit token name read by the production
            # frozen renderer; layout evidence must therefore reflect this
            # immutable Kit rather than a renderer fallback.
            "typography": {"body": "system-ui, sans-serif"},
        },
        scope="project",
        project_id=run.project_id,
    )
    brand_kit_ref = _reference(
        brand_kit_version.id, brand_kit_version.version, brand_kit_version.content_hash
    )
    brief = compile_lg12i_product_creative_brief(
        db_session,
        run,
        source_reference=source_ref,
        truth_reference=truth_ref,
        confirmation_reference=confirmation_ref,
        brand_kit_reference=brand_kit_ref,
        target_channels=["smartstore"],
    )
    approved_facts = create_lg12i_approved_fact_snapshot(db_session, run, creative_brief=brief)
    brief_ref = _reference(brief.id, brief.version, brief.output_hash)
    master = create_commerce_creative_master_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_reference=source_ref,
        truth_reference=truth_ref,
        confirmation_reference=confirmation_ref,
        creative_brief_reference=brief_ref,
        brand_kit_reference=brand_kit_ref,
        evidence_artifact_refs=list(truth.evidence_refs_json),
        approved_fact_snapshot_ref=_reference(approved_facts.id, 1, approved_facts.snapshot_hash),
        approved_asset_manifest_ref=lg12i_approved_asset_manifest_reference(
            source_reference=source_ref, usable_asset_refs=list(brief.usable_asset_refs_json),
        ),
        copy_artifact_ref=lg12i_pending_production_artifact_reference(
            artifact_key="copywriting", creative_brief_reference=brief_ref,
        ),
        page_plan_artifact_ref=lg12i_pending_production_artifact_reference(
            artifact_key="page_planning", creative_brief_reference=brief_ref,
        ),
        target_channels=["smartstore"],
    )
    return {
        "run": run,
        "source": source,
        "truth": truth,
        "confirmation": confirmation,
        "brand_kit": brand_kit_version,
        "brief": brief,
        "master": master,
    }


def _master_reference(master: CommerceCreativeMasterVersion) -> dict[str, Any]:
    return _reference(master.id, master.version, master.canonical_hash)


def _persist_commerce_artifact(
    *,
    run: AgentRun,
    stage: str,
    output: dict[str, Any],
    metadata: dict[str, Any],
    db_session,
) -> dict[str, Any]:
    """Persist a current LG-3 artifact through its production storage boundary."""

    with langgraph_execution_session(db_session):
        reference = store_commerce_planning_artifact(
            run,
            stage,
            output,
            metadata=metadata,
        )
    db_session.refresh(run)
    return reference


def build_valid_lg12_page_plan(lineage: dict[str, Any], db_session) -> dict[str, Any]:
    """Create a deterministic, persisted current-production PagePlan artifact.

    The current production contract stores the versioned PagePlan in the
    LangGraph commerce-planning artifact projection rather than a separate
    ``PagePlanVersion`` table.  The artifact hash is therefore the immutable
    PagePlan hash used by the Master and the LG-10 finalizer.
    """

    run = lineage["run"]
    parent_master = lineage["master"]
    brand_kit = lineage["brand_kit"]
    brief = lineage["brief"]
    fact_id = "fact:product:model"
    # The public LG-10 finalizer reads this narrow pinned Brief reference from
    # the production run projection.  The LG-12I compiler intentionally does
    # not mutate run state itself, so the integration fixture establishes the
    # same projection explicitly before persisting its derived artifacts.
    run.input_snapshot = {
        **dict(run.input_snapshot or {}),
        "design_direction": "balanced_sale",
        "creative_brief_snapshot": {
            "id": brief.id,
            "version": brief.version,
            "input_hash": brief.input_hash,
            "output_hash": brief.output_hash,
            "brand_kit_version_id": brief.brand_kit_version_id,
            "brand_kit_hash": brief.brand_kit_hash,
        },
    }
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    sections = [
        {
            "id": "hero",
            "name": "Hero",
            "purpose": "제품 모델을 명확히 소개합니다.",
            "source_fact_ids": [fact_id],
        },
        {
            "id": "feature_1",
            "name": "Detail",
            "purpose": "확인된 제품 정보를 설명합니다.",
            "source_fact_ids": [fact_id],
        },
        {
            "id": "product_information",
            "name": "CTA",
            "purpose": "구매 전 제품 정보를 다시 확인하도록 안내합니다.",
            "source_fact_ids": [fact_id],
        },
    ]
    page_plan_output = DetailPagePlanOutput.model_validate(
        {"layout_concept": "information_hierarchy", "sections": sections}
    ).model_dump()
    page_plan_id = "page-plan:" + canonical_version_hash(page_plan_output)[:24]
    page_plan_ref = _persist_commerce_artifact(
        run=run,
        stage="page_planning",
        output=page_plan_output,
        metadata={
            "mode": "integration",
            "provider": "deterministic-test-contract",
            "artifact_id": page_plan_id,
            "artifact_version": 1,
            "master_ref": _master_reference(parent_master),
            "brand_kit_ref": _reference(brand_kit.id, brand_kit.version, brand_kit.content_hash),
            "section_scene_contract": [
                {
                    "section_id": section["id"],
                    "section_order": index,
                    "scene_id": f"scene:{section['id']}",
                    "scene_type": scene_type,
                    "scene_order": index,
                    "element_ids": [f"element:{section['id']}:title"],
                    "expected_layout_token": "information_hierarchy",
                    "expected_text_roles": ["headline", "subcopy"],
                }
                for index, (section, scene_type) in enumerate(
                    zip(sections, ("hero_product", "detail_information", "cta_information"), strict=True)
                )
            ],
        },
        db_session=db_session,
    )
    # The finalizer consumes the existing compact artifact ref.  The Master
    # additionally pins the same hash as a typed immutable PagePlan reference.
    typed_page_plan_ref = _reference(
        page_plan_id,
        1,
        page_plan_ref["artifact_hash"],
        schema_version=COMMERCE_VERSION,
        artifact_key="page_planning",
    )

    copy_output = CopySetOutput.model_validate(
        {
            "hero_title": "SF-100",
            "hero_subtitle": "판매자 확인 제품 모델",
            "painpoint_title": "",
            "painpoint_body": "",
            "feature_1_title": "제품 정보",
            "feature_1_body": "확인된 모델 정보를 안내합니다.",
            "feature_2_title": "",
            "feature_2_body": "",
            "guarantee_title": "구매 전 확인",
            "guarantee_body": "제품 정보를 확인해 주세요.",
            "cta_text": "제품 정보 확인",
            "section_fact_ids": {
                "hero": [fact_id],
                "feature_1": [fact_id],
                "product_information": [fact_id],
            },
            "copy_provenance": {},
        }
    ).model_dump()
    copy_ref = _persist_commerce_artifact(
        run=run,
        stage="copywriting",
        output=copy_output,
        metadata={
            "mode": "integration",
            "provider": "deterministic-test-contract",
            "artifact_id": "copy:" + canonical_version_hash(copy_output)[:24],
            "artifact_version": 1,
        },
        db_session=db_session,
    )
    visual_output = VisualPlanOutput.model_validate(
        {
            "hero_image_prompt": "information-only",
            "detail_image_prompt": "information-only",
            "color_palette": ["#0f766e"],
            # These are current ScenePlan records, not image-generation jobs.
            # Their matching section IDs are required by the production LG-10
            # assembly lookup; semantic scene IDs remain frozen in PagePlan
            # metadata above for later scene-flow parity work.
            "scene_plan": [
                {
                    "id": section["id"],
                    "scene_type": scene_type,
                    "objective": section["purpose"],
                    "source_fact_ids": [fact_id],
                    "reference_asset_ids": [],
                    "generation_mode": "html_information_fallback",
                    "requested_output": "html_graphic",
                    "rendering_strategy": "html_information_fallback",
                    "mock_status": "information_fallback",
                }
                for section, scene_type in zip(
                    sections, ("hero_product", "detail_information", "cta_information"), strict=True
                )
            ],
        }
    ).model_dump()
    _persist_commerce_artifact(
        run=run,
        stage="visual_planning",
        output=visual_output,
        metadata={"mode": "integration", "provider": "deterministic-test-contract"},
        db_session=db_session,
    )

    master = create_commerce_creative_master_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_reference=_reference(lineage["source"].id, lineage["source"].version, lineage["source"].canonical_hash),
        truth_reference=_reference(lineage["truth"].id, lineage["truth"].version, lineage["truth"].canonical_hash),
        confirmation_reference=_reference(
            lineage["confirmation"].id,
            lineage["confirmation"].version,
            lineage["confirmation"].canonical_hash,
        ),
        creative_brief_reference=_reference(brief.id, brief.version, brief.output_hash),
        brand_kit_reference=_reference(brand_kit.id, brand_kit.version, brand_kit.content_hash),
        evidence_artifact_refs=list(lineage["truth"].evidence_refs_json),
        approved_fact_snapshot_ref=dict(parent_master.approved_fact_snapshot_ref_json),
        approved_asset_manifest_ref=dict(parent_master.approved_asset_manifest_ref_json),
        copy_artifact_ref=_reference(
            f"copy:{copy_ref['artifact_hash'][:24]}",
            1,
            copy_ref["artifact_hash"],
            schema_version=COMMERCE_VERSION,
            artifact_key="copywriting",
        ),
        page_plan_artifact_ref=typed_page_plan_ref,
        target_channels=["smartstore"],
        parent_version_id=parent_master.id,
    )
    db_session.flush()
    return {
        "parent_master": parent_master,
        "master": master,
        "page_plan_output": page_plan_output,
        "page_plan_ref": typed_page_plan_ref,
        "page_plan_artifact_ref": page_plan_ref,
        "copy_artifact_ref": copy_ref,
        "brand_kit": brand_kit,
    }


def build_valid_lg12_frozen_detail_page(
    lineage: dict[str, Any], page_plan: dict[str, Any], db_session
) -> DetailPageVersion:
    """Finalize through the real LG-10 immutable page assembly/render path."""

    run = lineage["run"]
    canonical_input = build_canonical_page_assembly_input(
        run=run,
        approved_asset_manifest=None,
        db=db_session,
    )
    page_assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical_input)
    rendering = build_canonical_page_rendering_artifact(
        run=run,
        canonical_page_assembly_input=canonical_input,
        page_assembly=page_assembly,
        db=db_session,
    )
    page = persist_lg10_detail_page_version(
        run=run,
        canonical_page_assembly_input=canonical_input,
        page_assembly=page_assembly,
        rendering=rendering,
        db=db_session,
    )
    db_session.flush()
    return page


def _write_deterministic_png(tmp_path: Path) -> tuple[Path, str]:
    """Create real image bytes; no fabricated asset checksum enters the fixture."""

    path = tmp_path / "lg12-quality-black-product.png"
    Image.new("RGB", (800, 800), color=(16, 24, 32)).save(path, format="PNG")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _seller_owned_asset(*, lineage: dict[str, Any], tmp_path: Path, db_session) -> Asset:
    path, file_hash = _write_deterministic_png(tmp_path)
    asset = Asset(
        project_id=lineage["run"].project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename=path.name,
        file_path=str(path),
        mime_type="image/png",
        file_size=path.stat().st_size,
        asset_role="product_main",
        role_confidence=1.0,
        role_source="manual",
        quality_status="usable",
        identity_status="confirmed",
        product_identity_preserved=True,
        width=800,
        height=800,
        image_format="PNG",
        quality_warnings=[],
        content_hash=file_hash,
        safe_crop_status="safe",
        is_representative=True,
        representative_source="manual",
        classification_version=2,
    )
    db_session.add(asset)
    db_session.flush()
    return asset


def attach_valid_lg12_image_evidence(*, asset: Asset, job: ImageGenerationJobRecord) -> dict[str, Any]:
    """Use the production freezer, which rereads the actual PNG and its hash."""

    evidence = build_frozen_image_quality_evidence(asset=asset, job=job)
    assert evidence["asset"] == {"id": asset.id, "version": 1, "hash": asset.content_hash}
    assert evidence["file"]["content_hash"] == asset.content_hash
    assert evidence["file"]["width"] == 800 and evidence["file"]["height"] == 800
    assert evidence["metadata"]["identity_metadata"] == {
        "color": "black", "model": "SF-100", "variant": "standard"
    }
    return evidence


def _asset_reference(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "version": 1,
        "hash": str(asset.content_hash),
        "schema_version": "asset-sha256-v1",
        "artifact_key": "asset",
        "rights_status": "rights_confirmed",
    }


def _build_asset_bound_master(
    *, lineage: dict[str, Any], page_plan: dict[str, Any], asset: Asset, db_session
) -> dict[str, Any]:
    """Append a source lineage that can legally approve the real seller asset.

    Source/Truth/Confirmation rows are immutable.  Therefore this does not
    mutate the A-1.1 lineage; it produces a second, same-run frozen source
    branch and a Master pinned to that branch and to the actual asset hash.
    """

    run = lineage["run"]
    asset_ref = _asset_reference(asset)
    source_ref_contract = {
        key: asset_ref[key]
        for key in ("id", "version", "hash", "schema_version", "artifact_key")
    }
    source = create_product_source_snapshot_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        input_mode="photo_only",
        source_refs=[source_ref_contract],
        provenance={"source": "seller_owned_upload", "source_asset_refs": [asset_ref]},
        rights={"status": "rights_confirmed", "confirmation_state": "rights_confirmed", "final_use_status": "not_approved"},
        source_fidelity={"status": "complete", "source_kind": "seller_owned_image"},
    )
    source_ref = _reference(source.id, source.version, source.canonical_hash)
    model_fact = _reference("fact:product:model")
    color_fact = _reference("fact:product:color")
    evidence_model = _reference("evidence:seller:product-model")
    evidence_color = _reference("evidence:seller:product-color")
    truth = create_product_truth_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_reference=source_ref,
        fact_refs=[model_fact, color_fact],
        evidence_refs=[evidence_model, evidence_color],
        normalization={
            "normalization_version": "lg12-quality-graph-integration-v1",
            "identity_observations": {"model": "SF-100", "color": "black", "variant": "standard"},
        },
    )
    truth_ref = _reference(truth.id, truth.version, truth.canonical_hash)
    confirmation = create_seller_confirmation_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        truth_reference=truth_ref,
        answers=[
            {"question_id": "confirm-model", "answer": "SF-100"},
            {"question_id": "confirm-color", "answer": "black"},
        ],
        confirmed_fact_refs=[
            _confirmed_fact_reference(
                truth_fact=model_fact, source_ref=source_ref_contract, evidence_ref=evidence_model,
                actor_id=run.created_by,
            ),
            _confirmed_fact_reference(
                truth_fact=color_fact, source_ref=source_ref_contract, evidence_ref=evidence_color,
                actor_id=run.created_by, fact_id="fact:product:color", field_id="color",
                normalized_value="black",
            ),
        ],
        rejected_fact_refs=[], unknown_fact_refs=[],
        rights_confirmations=[{"source_ref": asset.id, "status": "rights_confirmed"}],
    )
    confirmation_ref = _reference(confirmation.id, confirmation.version, confirmation.canonical_hash)
    brand_kit = lineage["brand_kit"]
    brand_ref = _reference(brand_kit.id, brand_kit.version, brand_kit.content_hash)
    brief = compile_lg12i_product_creative_brief(
        db_session, run, source_reference=source_ref, truth_reference=truth_ref,
        confirmation_reference=confirmation_ref, brand_kit_reference=brand_ref,
        target_channels=["smartstore"],
    )
    approved_facts = create_lg12i_approved_fact_snapshot(db_session, run, creative_brief=brief)
    artifacts = run.outputs_json["langgraph_commerce_planning_artifacts"]
    copy_hash = artifacts["copywriting"]["metadata"]["artifact_hash"]
    copy_ref = _reference(
        artifacts["copywriting"]["metadata"]["artifact_id"], 1, copy_hash,
        schema_version=COMMERCE_VERSION, artifact_key="copywriting",
    )
    master = create_commerce_creative_master_version(
        db_session,
        workspace_id=run.workspace_id, project_id=run.project_id,
        creator_run_id=run.id, created_by=run.created_by,
        source_reference=source_ref, truth_reference=truth_ref,
        confirmation_reference=confirmation_ref,
        creative_brief_reference=_reference(brief.id, brief.version, brief.output_hash),
        brand_kit_reference=brand_ref,
        evidence_artifact_refs=list(truth.evidence_refs_json),
        approved_fact_snapshot_ref=_reference(approved_facts.id, 1, approved_facts.snapshot_hash),
        approved_asset_manifest_ref=lg12i_approved_asset_manifest_reference(
            source_reference=source_ref, usable_asset_refs=list(brief.usable_asset_refs_json),
        ),
        copy_artifact_ref=copy_ref,
        page_plan_artifact_ref=dict(page_plan["page_plan_ref"]),
        target_channels=["smartstore"],
    )
    run.input_snapshot = {
        **dict(run.input_snapshot or {}),
        "creative_brief_snapshot": {
            "id": brief.id, "version": brief.version, "input_hash": brief.input_hash,
            "output_hash": brief.output_hash, "brand_kit_version_id": brief.brand_kit_version_id,
            "brand_kit_hash": brief.brand_kit_hash,
        },
    }
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return {
        "source": source, "truth": truth, "confirmation": confirmation,
        "brief": brief, "master": master, "asset_ref": asset_ref,
    }


def attach_valid_lg12_copy_evidence(*, page: DetailPageVersion) -> list[dict[str, Any]]:
    """Read copy only from the frozen canonical renderer text layer."""

    rendering = page.sections_json["lg10"]["canonical_rendering"]
    canonical = page.sections_json["lg10"]["canonical_page_assembly_input"]
    copy_ref = dict(canonical["planning_refs"]["copy"])
    refs: list[dict[str, Any]] = []
    for section in rendering["sections"]:
        for entry in section.get("text_layer") or []:
            text = str(entry["text"])
            refs.append({
                "copy_id": "copy:" + canonical_hash({
                    "section_id": section["section_id"], "field": entry["field"],
                    "text": text, "copy_artifact_hash": copy_ref["artifact_hash"],
                })[:24],
                "section_id": section["section_id"],
                "field": entry["field"], "role": (
                    "cta" if entry["field"] == "cta_text"
                    else "subheadline" if "subtitle" in entry["field"]
                    else "headline" if "title" in entry["field"]
                    else "body"
                ),
                "text_hash": canonical_hash(text),
                "copy_artifact_ref": {
                    "id": str(copy_ref.get("artifact_id") or ""),
                    "version": copy_ref.get("artifact_version"),
                    "hash": copy_ref["artifact_hash"],
                },
            })
    assert refs and all(item["copy_id"] and item["copy_artifact_ref"]["id"] for item in refs)
    return refs


def attach_valid_lg12_layout_evidence(*, page: DetailPageVersion) -> dict[str, Any]:
    """Return the production renderer's frozen layout evidence after integrity checks."""

    evidence = dict(page.sections_json["lg10"]["canonical_rendering"]["lg12_layout_evidence"])
    evidence_hash = evidence.pop("evidence_hash")
    assert evidence_hash == canonical_hash(evidence)
    evidence["evidence_hash"] = evidence_hash
    assert evidence["page_plan_ref"]["id"] and evidence["page_plan_ref"]["version"]
    assert evidence["brand_kit_ref"]["id"] and evidence["brand_kit_ref"]["version"]
    assert all(section["elements"] and section["typography_roles"] for section in evidence["sections"])
    return evidence


def _approved_asset_manifest(
    *, run: AgentRun, asset: Asset, job: ImageGenerationJobRecord, image_evidence: dict[str, Any]
) -> dict[str, Any]:
    payload = {
        "schema_version": "lg10-approved-asset-manifest-v1",
        "run_id": run.id,
        "project_id": run.project_id,
        "assets": [{
            "scene_id": "hero", "section_id": "hero", "asset_id": asset.id,
            "asset_content_hash": asset.content_hash, "job_id": job.job_id,
            "generation_attempt": int(job.generation_attempt),
            "provenance": "seller_owned", "rights_status": "rights_confirmed",
            "lg12_frozen_image_evidence": image_evidence,
        }],
    }
    return {**payload, "manifest_hash": canonical_hash(payload)}


def _replace_current_visual_plan_with_approved_hero(*, run: AgentRun, db_session) -> None:
    artifacts = dict(run.outputs_json["langgraph_commerce_planning_artifacts"])
    visual_output = deepcopy(artifacts["visual_planning"]["output"])
    for scene in visual_output["scene_plan"]:
        if scene["id"] == "hero":
            scene.update({
                "generation_mode": "safe_existing_photo",
                "requested_output": "approved_asset",
                "rendering_strategy": "safe_existing_photo",
                "mock_status": "approved_asset",
            })
    _persist_commerce_artifact(
        run=run,
        stage="visual_planning",
        output=visual_output,
        metadata={
            "mode": "integration", "provider": "deterministic-test-contract",
            "artifact_id": "visual-plan:" + canonical_version_hash(visual_output)[:24],
            "artifact_version": 1,
        },
        db_session=db_session,
    )


def _attach_frozen_canvas_evidence(*, canonical_input: dict[str, Any], asset: Asset) -> dict[str, Any]:
    """Pin deterministic Canvas geometry before the production renderer freezes it."""

    canonical = deepcopy(canonical_input)
    for section in canonical["sections"]:
        section_id = section["section_id"]
        elements = [{
            "element_id": f"{section_id}:background", "kind": "background",
            "x": 0, "y": 0, "width": 760, "height": 160,
            "z_index": 0, "locked": True,
        }, {
            "element_id": f"{section_id}:text", "kind": "text",
            "x": 24, "y": 24, "width": 712, "height": 120,
            "z_index": 2, "locked": True,
        }]
        if section_id == "hero":
            elements.insert(0, {
                "element_id": "hero:asset", "kind": "asset",
                "asset_id": asset.id, "asset_content_hash": asset.content_hash,
                "x": 24, "y": 156, "width": 712, "height": 320,
                "z_index": 1, "locked": True,
            })
        section["canvas"] = {"is_visible": True, "height_px": 520}
        section["canvas_elements"] = elements
    canonical.pop("input_hash", None)
    return {**canonical, "input_hash": canonical_hash(canonical)}


def _build_quality_evidence_page(
    *, lineage: dict[str, Any], page_plan: dict[str, Any], tmp_path: Path, db_session
) -> dict[str, Any]:
    """Create an immutable child DetailPage backed by real frozen QA inputs."""

    run = lineage["run"]
    asset = _seller_owned_asset(lineage=lineage, tmp_path=tmp_path, db_session=db_session)
    job = ImageGenerationJobRecord(
        project_id=run.project_id,
        job_id="lg12-quality-evidence:" + run.id,
        section_id="hero", scene_id="hero", role="hero",
        source_asset_ids=[asset.id], prompt="seller-owned SF-100 black product",
        preserve_product_identity=True, output_size="800x800", cost_tier="test",
        status="approved", provider="deterministic-test-contract", model="no-provider",
        output_asset_id=asset.id, attempt_count=0, generation_attempt=1,
        required_for_completion=True,
        validation_result={
            "status": "approved",
            "details": {"identity": {"status": "pass", "observed_identity": {
                "model": "SF-100", "color": "black", "variant": "standard",
            }}},
            "warnings": [], "risk_codes": [],
        },
        # LG-11 copies this immutable scene input into one regeneration job.
        # The deterministic fake-provider test supplies matching bounded
        # reference/output regions, so image review remains a real review
        # rather than an artificial metadata-only pass.
        input_snapshot={
            "scene_prompt": {
                "identity_constraints": {
                    "feature_regions": {
                        feature: [{
                            "reference_index": 0,
                            "reference_box": [0.0, 0.0, 0.1, 0.1],
                            "output_box": [0.0, 0.0, 0.1, 0.1],
                        }]
                        for feature in ("buttons", "ports", "components", "logo")
                    },
                },
            },
        },
        usage_metadata={"langgraph_run_id": run.id, "fixture": "lg12-quality-evidence"},
    )
    db_session.add(job)
    db_session.flush()
    image_evidence = attach_valid_lg12_image_evidence(asset=asset, job=job)
    asset_lineage = _build_asset_bound_master(
        lineage=lineage, page_plan=page_plan, asset=asset, db_session=db_session,
    )
    _replace_current_visual_plan_with_approved_hero(run=run, db_session=db_session)
    manifest = _approved_asset_manifest(
        run=run, asset=asset, job=job, image_evidence=image_evidence,
    )
    canonical_input = build_canonical_page_assembly_input(
        run=run, approved_asset_manifest=manifest, db=db_session,
    )
    canonical_input = _attach_frozen_canvas_evidence(canonical_input=canonical_input, asset=asset)
    page_assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical_input)
    rendering = build_canonical_page_rendering_artifact(
        run=run, canonical_page_assembly_input=canonical_input,
        page_assembly=page_assembly, db=db_session,
    )
    page = persist_lg10_detail_page_version(
        run=run, canonical_page_assembly_input=canonical_input,
        page_assembly=page_assembly, rendering=rendering, db=db_session,
    )
    db_session.flush()
    return {
        "page": page, "asset": asset, "job": job, "manifest": manifest,
        "image_evidence": image_evidence, "asset_lineage": asset_lineage,
    }


def attach_valid_lg12_channel_parity_evidence(
    *, page: DetailPageVersion, db_session, tmp_path: Path
) -> tuple[ExportArtifact, dict[str, Any]]:
    """Build a local SmartStore standalone artifact then freeze its parity sidecar."""

    bundle = build_lg10_standalone_export_bundle(
        db=db_session, project_id=page.project_id, version=page,
        output_dir=str(tmp_path / "exports"), channel="smartstore",
    )
    artifact = ExportArtifact(
        project_id=page.project_id, version_id=page.id,
        artifact_type="lg10_standalone_package:smartstore", file_path=bundle["zip_path"],
    )
    db_session.add(artifact)
    db_session.flush()
    evidence = write_lg12_frozen_export_parity_evidence(
        version=page, artifact=artifact, channel="smartstore",
    )
    return artifact, evidence


def _frozen_detail_page_reference(page: DetailPageVersion) -> dict[str, str]:
    """Construct the bounded frozen target reference expected by production QA."""

    snapshot = dict(page.sections_json or {})
    return {
        "id": str(page.id),
        "version": str(snapshot["schema_version"]),
        "hash": str(snapshot["snapshot_hash"]),
        "type": "DetailPageVersion",
    }


def evaluate_all_lg12_quality_domains(*, run: AgentRun, page: DetailPageVersion, db_session) -> dict[str, Any]:
    """Run the five production evaluators through the immutable report builder.

    This intentionally does not aggregate a Quality Bar or advance a graph.
    The builder is the production owner of the report-binding seed and invokes
    every LG-12 dimension against the same frozen DetailPage reference.
    """

    report = build_lg12_quality_assessment_report(
        db_session, run=run, detail_page_reference=_frozen_detail_page_reference(page),
    )
    validate_quality_assessment_report_version(db_session, report)
    domains = {str(item["domain_id"]): dict(item) for item in report.report_json["domain_scores"]}
    return {"qa_report": report, "domain_results": domains}


def aggregate_valid_lg12_quality_bar(*, qa_report: QualityAssessmentReportVersion, db_session) -> dict[str, Any]:
    """Aggregate the exact persisted report with its pinned profile only."""

    profile = db_session.get(QualityThresholdProfileVersion, qa_report.threshold_profile_id)
    assert profile is not None
    report_ref = {
        "id": str(qa_report.id), "version": int(qa_report.version),
        "hash": str(qa_report.canonical_hash),
    }
    quality_bar = aggregate_quality_bar(db_session, report_ref=report_ref)
    return {"threshold_profile": profile, "quality_bar": quality_bar}


def _seed_compiled_quality_graph(
    *, run: AgentRun, page: DetailPageVersion, db_session, checkpointer: Any,
    attempt_ledger: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist the bounded renderer predecessor used by the production QA graph."""

    from src.agents.langgraph_runtime import build_lg10_compiled_graph

    snapshot = dict(page.sections_json or {})
    run.graph_thread_id = run.id
    run.status = "running"
    run.current_stage = "canonical_renderer"
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)

    graph = build_lg10_compiled_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": run.graph_thread_id}}
    graph.update_state(
        config,
        {
            "run_id": run.id,
            "thread_id": run.graph_thread_id,
            "workspace_id": run.workspace_id,
            "project_id": run.project_id,
            "mode": run.mode,
            "current_stage": "canonical_renderer",
            "status": "running",
            "rendering": {
                "detail_page_version": {
                    "id": page.id,
                    "schema_version": snapshot["schema_version"],
                    "snapshot_hash": snapshot["snapshot_hash"],
                },
            },
            "quality": {"attempt_ledger": [dict(item) for item in list(attempt_ledger or [])]},
        },
        as_node="canonical_renderer",
    )
    return {"graph": graph, "config": config, "run": run}


def _quality_crash_counts(*, db_session, run: AgentRun) -> dict[str, int]:
    """Count durable artifacts affected by TASK-12.9 recovery, not raw bodies."""

    return {
        "children": db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count(),
        "reports": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count(),
    }


def _invoke_compiled_quality_pass_path(
    *, run: AgentRun, page: DetailPageVersion, db_session, checkpointer: Any | None = None,
    attempt_ledger: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Enter the production LG-10 graph at its persisted renderer predecessor.

    The test harness only restores the bounded checkpoint state which the
    canonical renderer would have committed after freezing ``page``.  The
    actual compiled graph, actual quality node, conditional Quality-Bar route,
    and existing SQL projector then execute without evaluator or route seams.
    """

    seeded = _seed_compiled_quality_graph(
        run=run,
        page=page,
        db_session=db_session,
        checkpointer=checkpointer or InMemorySaver(),
        attempt_ledger=attempt_ledger,
    )
    graph, config = seeded["graph"], seeded["config"]
    with langgraph_execution_session(db_session):
        for update in graph.stream(None, config=config, stream_mode="updates"):
            for node_update in update.values():
                if isinstance(node_update, dict):
                    run = AgentRunGraphProjector.apply_node_update(run, db_session, node_update)
    return {"graph": graph, "config": config, "run": run, "checkpoint": graph.get_state(config)}


def build_copy_spacing_failure_fixture(*, run: AgentRun, page: DetailPageVersion, db_session) -> dict[str, Any]:
    """Create one immutable, fact-preserving spacing-failure child via TASK-11.3.

    The text has eight whitespace-normalisation units in one frozen field.
    It is deliberately just below the copy threshold without changing facts;
    the production COPY_REWORK normalizer can repair the exact same field.
    """

    # The extra trailing whitespace changes no word, value, or fact cue.  It
    # is one copy-field defect with eight deterministic normalisation units.
    # Select an existing renderer field that production TASK-11.3 classifies
    # as a cosmetic (not evidence-review) edit; the fixture must exercise the
    # same authorisation boundary as the graph executor.
    selected: tuple[str, str, str, str, dict[str, Any]] | None = None
    rejected_candidates: list[tuple[str, str, list[str]]] = []
    for section in page.sections_json["lg10"]["canonical_rendering"]["sections"]:
        section_id = str(section["section_id"])
        for text_item in section["text_layer"]:
            field = str(text_item["field"])
            source_text = str(text_item["text"])
            failing_text = source_text + (" " * 9)
            candidate = preview_lg11_edit_intent(
                version=page,
                scope="copy",
                target_ids=[section_id],
                operation="rewrite",
                instruction="Prepare one frozen spacing-only QA fixture without changing product facts.",
                preserve_constraints={"selected_context": {"section_id": section_id}},
                copy_changes={section_id: {field: failing_text}},
            )
            if not candidate["impact_preview"]["requires_evidence_review"]:
                selected = (section_id, field, source_text, failing_text, candidate)
                break
            rejected_candidates.append((
                section_id, field,
                list(candidate["impact_preview"].get("confirmation_reasons") or []),
            ))
        if selected is not None:
            break
    assert selected is not None, f"fixture requires one production-approved cosmetic copy field: {rejected_candidates}"
    section_id, field, source_text, failing_text, intent_preview = selected
    intent = dict(intent_preview["edit_intent"])
    fork = build_lg11_copy_version_fork(source_version=page, edit_run_id=run.id, intent=intent)
    child = persist_lg11_copy_version_fork(run=run, copy_version_fork=fork, db=db_session)
    db_session.commit()
    db_session.refresh(child)
    return {
        "page": child, "section_id": section_id, "field": field,
        "source_text": source_text, "failing_text": failing_text,
    }


def build_visual_overflow_failure_fixture(
    *, run: AgentRun, page: DetailPageVersion, db_session
) -> dict[str, Any]:
    """Freeze one renderer-valid page whose Canvas asset overflows its section.

    The fixture uses the normal LG-10 immutable renderer/persister rather than
    editing a stored page row.  It models a frozen legacy assembly defect that
    the TASK-11 Canvas executor can deterministically clamp back into bounds.
    """

    canonical = deepcopy(page.sections_json["lg10"]["canonical_page_assembly_input"])
    selected: tuple[str, str, int, int] | None = None
    for section in canonical["sections"]:
        section_id = str(section["section_id"])
        # Convert the LG-10 render evidence into the exact, allow-listed
        # element identities TASK-11 Canvas derives.  This keeps the fixture
        # renderer-valid while letting the actual Canvas executor own the
        # rework; no stored snapshot is edited in place.
        source_asset = next(
            (dict(element) for element in list(section.get("canvas_elements") or [])
             if str(dict(element).get("kind") or "") == "asset"),
            None,
        )
        section["canvas_elements"] = [
            {
                "element_id": f"{section_id}:background", "kind": "background",
                "x": 0, "y": 0, "width": 760, "height": 160,
                "z_index": 0, "locked": False, "group_id": None,
            },
            {
                "element_id": f"{section_id}:text", "kind": "text",
                "x": 24, "y": 24, "width": 712, "height": 120,
                "z_index": 2, "locked": True, "group_id": None,
            },
        ]
        if source_asset is not None:
            section["canvas_elements"].append({
                "element_id": f"{section_id}:asset", "kind": "asset",
                "asset_id": str(source_asset["asset_id"]),
                "asset_content_hash": str(source_asset["asset_content_hash"]),
                "x": 24, "y": 156, "width": 712, "height": 320,
                "z_index": 1, "locked": False, "group_id": None,
            })
        if selected is not None:
            continue
        for element in list(section.get("canvas_elements") or []):
            if str(element.get("kind") or "") != "asset":
                continue
            selected = (
                section_id,
                str(element["element_id"]),
                int(element["x"]),
                int(element["width"]),
            )
            # One target creates three real major Canvas findings: a right
            # overflow and overlap with two derived text elements.  The
            # production executor must move only this unlocked asset to a
            # deterministic free slot, then the common QA node re-evaluates
            # the child.  The peers stay immutable/frozen.
            element.update({"x": 680, "y": 400, "width": 100, "height": 100, "locked": False})
            section["canvas_elements"].extend([
                {
                    "element_id": f"{section_id}:text:quality-overlap-1",
                    "origin_element_id": f"{section_id}:text",
                    "kind": "text", "x": 680, "y": 400,
                    "width": 40, "height": 40, "z_index": 3, "locked": True,
                },
                {
                    "element_id": f"{section_id}:text:quality-overlap-2",
                    "origin_element_id": f"{section_id}:text",
                    "kind": "text", "x": 720, "y": 460,
                    "width": 40, "height": 40, "z_index": 4, "locked": True,
                },
            ])
            break
    assert selected is not None, "fixture requires one frozen Canvas asset"
    assert all(
        str(dict(element).get("element_id") or "").startswith(f"{section['section_id']}:")
        and str(dict(element).get("kind") or "") in {"background", "text", "asset"}
        for section in canonical["sections"]
        for element in list(section.get("canvas_elements") or [])
    )
    payload = deepcopy(canonical)
    payload.pop("input_hash", None)
    canonical = {**payload, "input_hash": canonical_hash(payload)}
    assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical)
    rendering = build_canonical_page_rendering_artifact(
        run=run,
        canonical_page_assembly_input=canonical,
        page_assembly=assembly,
        db=db_session,
    )
    child = persist_lg10_detail_page_version(
        run=run,
        canonical_page_assembly_input=canonical,
        page_assembly=assembly,
        rendering=rendering,
        db=db_session,
    )
    db_session.commit()
    db_session.refresh(child)
    frozen_sections = child.sections_json["lg10"]["canonical_page_assembly_input"]["sections"]
    assert all(
        str(dict(element).get("element_id") or "").startswith(f"{section['section_id']}:")
        and str(dict(element).get("kind") or "") in {"background", "text", "asset"}
        for section in frozen_sections
        for element in list(section.get("canvas_elements") or [])
    )
    return {
        "page": child,
        "section_id": selected[0],
        "element_id": selected[1],
        "source_x": selected[2],
        "width": selected[3],
    }


def build_plan_order_failure_fixture(
    *, run: AgentRun, page: DetailPageVersion, db_session
) -> dict[str, Any]:
    """Freeze real renderer parity drift against the immutable PagePlan.

    The failure is a new immutable frozen rendering, never an in-place page
    edit: its section/scene evidence has an old assembly order while canonical
    input retains the persisted PagePlan order.  The existing Canvas reorder
    executor can restore this exact planning subtree.
    """

    canonical = deepcopy(page.sections_json["lg10"]["canonical_page_assembly_input"])
    sections = [dict(item) for item in list(canonical["sections"])]
    by_id = {str(section["section_id"]): section for section in sections}
    desired = [str(section["section_id"]) for section in sections]
    assert "product_information" in by_id and desired[-1] == "product_information"
    # Keep every section/asset/copy identity unchanged, but use an old frozen
    # renderer order.  Hero remains first so one scene-order metadata drift is
    # independently observable; together these are three real planning
    # findings (section order, scene order, scene identity) below threshold.
    failing_order = [desired[0], desired[2], desired[1]]
    assert failing_order != desired
    assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical)
    rendering = build_canonical_page_rendering_artifact(
        run=run, canonical_page_assembly_input=canonical,
        page_assembly=assembly, db=db_session,
    )
    rendering = deepcopy(rendering)
    rendering["sections"] = [
        deepcopy(next(section for section in rendering["sections"] if section["section_id"] == identifier))
        for identifier in failing_order
    ]
    evidence = deepcopy(rendering["lg12_layout_evidence"])
    evidence["sections"] = [
        deepcopy(next(section for section in evidence["sections"] if section["section_id"] == identifier))
        for identifier in failing_order
    ]
    evidence["sections"][0]["scene"] = {
        **dict(evidence["sections"][0]["scene"]), "scene_order": 99,
    }
    rendering["lg12_layout_evidence"] = evidence
    renderer_body = {
        key: value for key, value in rendering.items()
        if key not in {"lg12_layout_evidence", "render_hash", "canonical_input_ref", "page_assembly_ref"}
    }
    evidence["renderer_hash"] = canonical_hash(renderer_body)
    evidence_payload = deepcopy(evidence)
    evidence_payload.pop("evidence_hash", None)
    rendering["lg12_layout_evidence"] = {**evidence_payload, "evidence_hash": canonical_hash(evidence_payload)}
    render_payload = deepcopy(rendering)
    render_payload.pop("render_hash", None)
    rendering["render_hash"] = canonical_hash(render_payload)
    child = persist_lg10_detail_page_version(
        run=run, canonical_page_assembly_input=canonical,
        page_assembly=assembly, rendering=rendering, db=db_session,
    )
    db_session.commit()
    db_session.refresh(child)
    return {"page": child, "desired_order": desired, "failing_order": failing_order}


def build_image_identity_failure_fixture(
    *, run: AgentRun, asset: Asset, job: ImageGenerationJobRecord, db_session,
) -> DetailPageVersion:
    """Freeze one genuine TASK-12.4 model mismatch for the image route.

    The source asset remains seller-owned and byte-valid.  The mismatched
    identity is pinned to a distinct persisted frozen-job record; the original
    approved job is never mutated.  This mirrors a genuinely frozen bad
    generation result, rather than manufacturing a QA-only inconsistency.
    """

    failing_validation = deepcopy(job.validation_result)
    identity = dict(dict(failing_validation.get("details") or {}).get("identity") or {})
    identity["observed_identity"] = {
        "model": "SF-999", "color": "black", "variant": "standard",
    }
    failing_validation["details"] = {
        **dict(failing_validation.get("details") or {}), "identity": identity,
    }
    failing_job = ImageGenerationJobRecord(
        project_id=job.project_id,
        job_id=f"{job.job_id}:frozen-identity-mismatch",
        section_id=job.section_id, scene_id=job.scene_id, role=job.role,
        source_asset_ids=deepcopy(job.source_asset_ids), prompt=job.prompt,
        negative_prompt=job.negative_prompt,
        preserve_product_identity=job.preserve_product_identity,
        output_size=job.output_size, cost_tier=job.cost_tier,
        status=job.status, provider=job.provider, model=job.model,
        attempt_count=job.attempt_count, output_asset_id=asset.id,
        input_snapshot=deepcopy(job.input_snapshot),
        validation_result=failing_validation,
        estimated_cost=job.estimated_cost, actual_cost=job.actual_cost,
        usage_metadata=deepcopy(job.usage_metadata), seed=job.seed,
        prompt_version=job.prompt_version, prompt_hash=job.prompt_hash,
        reference_hash=job.reference_hash, planning_hash=job.planning_hash,
        input_hash=job.input_hash, generation_attempt=int(job.generation_attempt or 1) + 1,
        required_for_completion=job.required_for_completion,
        scene_prompt_version_id=job.scene_prompt_version_id,
    )
    db_session.add(failing_job)
    # The new frozen result is the sole required scene for this replacement
    # fixture.  Keep the original job only as historical source evidence.
    job.required_for_completion = False
    db_session.flush()
    failing_evidence = build_frozen_image_quality_evidence(asset=asset, job=failing_job)

    manifest = _approved_asset_manifest(
        run=run, asset=asset, job=failing_job, image_evidence=failing_evidence,
    )
    canonical_input = build_canonical_page_assembly_input(
        run=run, approved_asset_manifest=manifest, db=db_session,
    )
    canonical_input = _attach_frozen_canvas_evidence(
        canonical_input=canonical_input, asset=asset,
    )
    assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical_input)
    rendering = build_canonical_page_rendering_artifact(
        run=run, canonical_page_assembly_input=canonical_input,
        page_assembly=assembly, db=db_session,
    )
    page = persist_lg10_detail_page_version(
        run=run, canonical_page_assembly_input=canonical_input,
        page_assembly=assembly, rendering=rendering, db=db_session,
    )
    db_session.commit()
    db_session.refresh(page)
    return page


def build_style_brand_mismatch_failure_fixture(
    *, run: AgentRun, page: DetailPageVersion, db_session
) -> dict[str, Any]:
    """Use the real TASK-11.6 fork to freeze a wrong-but-valid project Kit."""

    alternate_kit = create_kit(
        db_session, run.workspace_id, run.created_by,
        f"LG-12 alternate style fixture {run.id}",
    )
    alternate_version = create_version(
        db_session,
        run.workspace_id,
        run.created_by,
        alternate_kit.id,
        {
            "color_tokens": {"accent": "#6d28d9"},
            "typography": {"body": "Arial"},
        },
        scope="project",
        project_id=run.project_id,
    )
    alternate_ref = {
        "brand_kit_version_id": str(alternate_version.id),
        "brand_kit_hash": str(alternate_version.content_hash),
    }
    preview = preview_lg11_edit_intent(
        version=page,
        scope="style",
        target_ids=[str(page.id)],
        operation="restyle",
        instruction="Freeze a deterministic alternate project Brand Kit fixture.",
        preserve_constraints={"selected_context": {}},
        brand_kit_ref=alternate_ref,
    )
    fork = build_lg11_style_version_fork(
        run=run,
        source_version=page,
        edit_run_id=run.id,
        intent=dict(preview["edit_intent"]),
        db=db_session,
    )
    child = persist_lg11_style_version_fork(
        run=run,
        style_version_fork=fork,
        db=db_session,
    )
    db_session.commit()
    db_session.refresh(child)
    return {"page": child, "alternate_brand_kit": alternate_version}


def test_builds_persisted_lg12_master_lineage(client, auth_headers, db_session):
    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    run = lineage["run"]
    source = lineage["source"]
    truth = lineage["truth"]
    confirmation = lineage["confirmation"]
    brand_kit = lineage["brand_kit"]
    brief = lineage["brief"]
    master = lineage["master"]

    assert db_session.get(Workspace, run.workspace_id) is not None
    assert db_session.get(ProductProject, run.project_id) is not None
    assert db_session.get(AgentRun, run.id) is not None
    assert db_session.get(ProductSourceSnapshotVersion, source.id) is not None
    assert db_session.get(ProductTruthVersion, truth.id) is not None
    assert db_session.get(SellerConfirmationVersion, confirmation.id) is not None
    assert db_session.get(ProductCreativeBriefVersion, brief.id) is not None
    assert db_session.get(CommerceCreativeMasterVersion, master.id) is not None
    assert db_session.get(BrandKitVersion, brand_kit.id) is not None

    for versioned_row, hash_field in (
        (source, "canonical_hash"), (truth, "canonical_hash"), (confirmation, "canonical_hash"),
        (brief, "output_hash"), (master, "canonical_hash"), (brand_kit, "content_hash"),
    ):
        assert versioned_row.id
        assert versioned_row.version >= 1
        assert getattr(versioned_row, hash_field)
        assert versioned_row.workspace_id == run.workspace_id
        assert versioned_row.project_id == run.project_id

    assert source.creator_run_id == run.id
    assert truth.creator_run_id == run.id
    assert truth.source_snapshot_version_id == source.id
    assert truth.source_snapshot_hash == source.canonical_hash
    assert confirmation.creator_run_id == run.id
    assert confirmation.truth_version_id == truth.id
    assert confirmation.truth_version_hash == truth.canonical_hash
    assert brief.run_id == run.id
    assert brief.source_snapshot_version_id == source.id
    assert brief.truth_version_id == truth.id
    assert brief.confirmation_version_id == confirmation.id
    assert master.creator_run_id == run.id
    assert master.creative_brief_version_id == brief.id
    assert master.source_snapshot_version_id == source.id
    assert master.truth_version_id == truth.id
    assert master.confirmation_version_id == confirmation.id
    assert master.brand_kit_version_id == brand_kit.id
    assert brand_kit.scope == "project"
    assert brand_kit.project_id == run.project_id


def test_builds_persisted_lg12_page_plan_and_frozen_detail_page(client, auth_headers, db_session):
    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    immutable_parent_hashes = {
        "source": lineage["source"].canonical_hash,
        "truth": lineage["truth"].canonical_hash,
        "confirmation": lineage["confirmation"].canonical_hash,
        "brief": lineage["brief"].output_hash,
        "master": lineage["master"].canonical_hash,
    }
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    page = build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    run = lineage["run"]
    successor_master = page_plan["master"]
    snapshot = dict(page.sections_json)
    canonical_input = dict(snapshot["lg10"]["canonical_page_assembly_input"])
    quality_lineage = dict(snapshot["lg12_quality_lineage"])

    assert db_session.get(DetailPageVersion, page.id) is not None
    assert page.id and page.is_final is True
    assert snapshot["snapshot_hash"]
    assert snapshot["lg10"]["canonical_rendering"]["render_hash"]
    assert run.workspace_id == lineage["source"].workspace_id == successor_master.workspace_id
    assert run.project_id == page.project_id == successor_master.project_id
    assert successor_master.creator_run_id == run.id
    assert successor_master.parent_version_id == lineage["master"].id
    assert successor_master.parent_version_hash == immutable_parent_hashes["master"]
    assert successor_master.brand_kit_version_id == lineage["brand_kit"].id
    assert successor_master.brand_kit_hash == lineage["brand_kit"].content_hash
    assert successor_master.page_plan_artifact_ref_json == page_plan["page_plan_ref"]
    assert successor_master.target_channels == ["smartstore"]

    assert canonical_input["planning_refs"]["page_plan"]["artifact_key"] == "page_planning"
    assert (
        canonical_input["planning_refs"]["page_plan"]["artifact_hash"]
        == page_plan["page_plan_ref"]["hash"]
    )
    assert canonical_input["brand_kit_ref"] == {
        "brand_kit_version_id": lineage["brand_kit"].id,
        "brand_kit_hash": lineage["brand_kit"].content_hash,
    }
    assert quality_lineage["creator_run_id"] == run.id
    assert quality_lineage["master_ref"] == _master_reference(successor_master)
    assert quality_lineage["source_snapshot_ref"] == _reference(
        lineage["source"].id, lineage["source"].version, lineage["source"].canonical_hash
    )
    assert quality_lineage["truth_ref"] == _reference(
        lineage["truth"].id, lineage["truth"].version, lineage["truth"].canonical_hash
    )
    assert quality_lineage["confirmation_ref"] == _reference(
        lineage["confirmation"].id,
        lineage["confirmation"].version,
        lineage["confirmation"].canonical_hash,
    )

    artifacts = run.outputs_json["langgraph_commerce_planning_artifacts"]
    scene_contract = artifacts["page_planning"]["metadata"]["section_scene_contract"]
    assert [(item["section_id"], item["section_order"]) for item in scene_contract] == [
        ("hero", 0), ("feature_1", 1), ("product_information", 2)
    ]
    assert [item["scene_id"] for item in scene_contract] == [
        "scene:hero", "scene:feature_1", "scene:product_information"
    ]
    assert all(item["element_ids"] and item["expected_text_roles"] for item in scene_contract)
    assert [section["section_id"] for section in canonical_input["sections"]] == [
        "hero", "feature_1", "product_information"
    ]
    assert all(section["rendering_mode"] == "information_only" for section in canonical_input["sections"])

    # Every parent remains the original immutable row; only the Master
    # successor and the frozen DetailPage are appended for this page plan.
    assert db_session.get(ProductSourceSnapshotVersion, lineage["source"].id).canonical_hash == immutable_parent_hashes["source"]
    assert db_session.get(ProductTruthVersion, lineage["truth"].id).canonical_hash == immutable_parent_hashes["truth"]
    assert db_session.get(SellerConfirmationVersion, lineage["confirmation"].id).canonical_hash == immutable_parent_hashes["confirmation"]
    assert db_session.get(ProductCreativeBriefVersion, lineage["brief"].id).output_hash == immutable_parent_hashes["brief"]
    assert db_session.get(CommerceCreativeMasterVersion, lineage["master"].id).canonical_hash == immutable_parent_hashes["master"]


def test_builds_persisted_lg12_frozen_quality_evidence(client, auth_headers, db_session, tmp_path):
    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    frozen_parent = build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    parent_hashes = {
        "source": lineage["source"].canonical_hash,
        "truth": lineage["truth"].canonical_hash,
        "confirmation": lineage["confirmation"].canonical_hash,
        "brief": lineage["brief"].output_hash,
        "master": lineage["master"].canonical_hash,
        "brand_kit": lineage["brand_kit"].content_hash,
        "page_plan": page_plan["page_plan_ref"]["hash"],
        "page": frozen_parent.sections_json["snapshot_hash"],
    }

    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    page = evidence_page["page"]
    asset = evidence_page["asset"]
    image_evidence = evidence_page["image_evidence"]
    copy_refs = attach_valid_lg12_copy_evidence(page=page)
    layout_evidence = attach_valid_lg12_layout_evidence(page=page)
    artifact, parity_evidence = attach_valid_lg12_channel_parity_evidence(
        page=page, db_session=db_session, tmp_path=tmp_path,
    )

    # Image evidence is based on real bytes, not mutable Asset warnings or a
    # fabricated checksum.  The frozen manifest carries the same evidence.
    assert Path(asset.file_path).is_file()
    assert hashlib.sha256(Path(asset.file_path).read_bytes()).hexdigest() == image_evidence["file"]["content_hash"]
    frozen_manifest = page.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]
    assert frozen_manifest["manifest_hash"] == canonical_hash({key: value for key, value in frozen_manifest.items() if key != "manifest_hash"})
    assert frozen_manifest["assets"][0]["lg12_frozen_image_evidence"] == image_evidence
    assert frozen_manifest["assets"][0]["asset_id"] == asset.id
    asset_master = evidence_page["asset_lineage"]["master"]
    quality_lineage = page.sections_json["lg12_quality_lineage"]
    assert quality_lineage["master_ref"] == _master_reference(asset_master)
    assert asset_master.approved_asset_manifest_ref_json == lg12i_approved_asset_manifest_reference(
        source_reference=_reference(
            evidence_page["asset_lineage"]["source"].id,
            evidence_page["asset_lineage"]["source"].version,
            evidence_page["asset_lineage"]["source"].canonical_hash,
        ),
        usable_asset_refs=list(evidence_page["asset_lineage"]["brief"].usable_asset_refs_json),
    )

    # Canonical renderer text is the only copy semantic source.  It includes
    # each required role and stable, hash-addressed source references.
    assert {item["role"] for item in copy_refs} >= {"headline", "subheadline", "body", "cta"}
    assert all(len(item["text_hash"]) == 64 for item in copy_refs)
    assert any(item["field"] == "cta_text" and item["role"] == "cta" for item in copy_refs)

    # Renderer-created layout evidence has complete typed PagePlan/BrandKit
    # refs and the expected frozen Hero -> detail -> CTA scene order.
    assert layout_evidence["page_plan_ref"] == {
        "id": page_plan["page_plan_ref"]["id"], "version": 1,
        "hash": page_plan["page_plan_ref"]["hash"],
    }
    assert layout_evidence["brand_kit_ref"] == {
        "id": lineage["brand_kit"].id, "version": lineage["brand_kit"].version,
        "hash": lineage["brand_kit"].content_hash,
    }
    assert [section["scene"]["scene_id"] for section in layout_evidence["sections"]] == [
        "hero", "feature_1", "product_information"
    ]
    assert [section["scene"]["scene_type"] for section in layout_evidence["sections"]] == [
        "hero_product", "detail_information", "cta_information"
    ]

    # A real SmartStore bundle and its production sidecar pin the same page,
    # renderer, manifest, PagePlan and BrandKit identities.
    assert Path(artifact.file_path).is_file()
    assert parity_evidence["channel"] == "smartstore"
    assert parity_evidence["file_sha256"] == hashlib.sha256(Path(artifact.file_path).read_bytes()).hexdigest()
    assert parity_evidence["page_ref"]["id"] == page.id
    assert parity_evidence["manifest_hash"] == frozen_manifest["manifest_hash"]
    assert parity_evidence["page_plan_ref"] == {
        "type": "PagePlanVersion", **layout_evidence["page_plan_ref"],
    }
    assert parity_evidence["brand_kit_ref"] == {
        "type": "BrandKitVersion",
        **{**layout_evidence["brand_kit_ref"], "version": str(layout_evidence["brand_kit_ref"]["version"])},
    }
    assert parity_evidence["layout_evidence_hash"] == layout_evidence["evidence_hash"]
    assert (Path(artifact.file_path).with_name(Path(artifact.file_path).name + ".lg12-parity.json")).is_file()

    # The evidence-complete page is a later immutable frozen version.  Its
    # predecessor and all original immutable lineage hashes remain intact.
    assert page.id != frozen_parent.id
    assert frozen_parent.sections_json["snapshot_hash"] == parent_hashes["page"]
    assert db_session.get(ProductSourceSnapshotVersion, lineage["source"].id).canonical_hash == parent_hashes["source"]
    assert db_session.get(ProductTruthVersion, lineage["truth"].id).canonical_hash == parent_hashes["truth"]
    assert db_session.get(SellerConfirmationVersion, lineage["confirmation"].id).canonical_hash == parent_hashes["confirmation"]
    assert db_session.get(ProductCreativeBriefVersion, lineage["brief"].id).output_hash == parent_hashes["brief"]
    assert db_session.get(CommerceCreativeMasterVersion, lineage["master"].id).canonical_hash == parent_hashes["master"]
    assert db_session.get(BrandKitVersion, lineage["brand_kit"].id).content_hash == parent_hashes["brand_kit"]
    assert page_plan["page_plan_ref"]["hash"] == parent_hashes["page_plan"]
    # The fixture persists a generation-record identity for frozen evidence,
    # but never dispatches a provider or creates cost/outbox state.
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count() == 0


def test_evaluates_all_lg12_domains_and_persists_quality_report(client, auth_headers, db_session, tmp_path):
    """A-1.4: production QA reads the one persisted A-1.3 frozen target."""

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=page)
    layout_evidence = attach_valid_lg12_layout_evidence(page=page)
    attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)
    quality_lineage = dict(page.sections_json["lg12_quality_lineage"])
    source = evidence_page["asset_lineage"]["source"]
    truth = evidence_page["asset_lineage"]["truth"]
    confirmation = evidence_page["asset_lineage"]["confirmation"]
    brief = evidence_page["asset_lineage"]["brief"]
    master = evidence_page["asset_lineage"]["master"]
    immutable_parent_hashes = {
        "page": page.sections_json["snapshot_hash"],
        "source": source.canonical_hash,
        "truth": truth.canonical_hash,
        "confirmation": confirmation.canonical_hash,
        "brief": brief.output_hash,
        "master": master.canonical_hash,
    }
    no_dispatch_counts = (
        db_session.query(ImageGenerationJobRecord).filter_by(project_id=lineage["run"].project_id).count(),
        db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count(),
        db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count(),
    )

    evaluation = evaluate_all_lg12_quality_domains(run=lineage["run"], page=page, db_session=db_session)
    report = evaluation["qa_report"]
    domains = evaluation["domain_results"]
    expected_domain_ids = {
        "factual_rights_policy", "image_identity_quality", "korean_copy_readability",
        "layout_typography_brand_flow", "channel_preview_export_parity",
    }

    assert db_session.get(QualityAssessmentReportVersion, report.id) is not None
    assert set(domains) == expected_domain_ids
    assert all(domain["status"] == "complete" for domain in domains.values())
    assert all(domain["critical_count"] == 0 for domain in domains.values())
    assert all(str(domain["evaluator_version"]).startswith("lg12-") for domain in domains.values())
    assert not report.report_json["critical_violations"]
    assert not any(domain["status"] in {"blocked", "needs_review", "not_evaluable"} for domain in domains.values())

    frozen_target = _frozen_detail_page_reference(page)
    manifest_hash = page.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["manifest_hash"]
    for domain in domains.values():
        assert domain["frozen_target_ref"] == frozen_target
        assert domain["approved_asset_manifest_hash"] == manifest_hash
        assert domain["workspace_id"] == lineage["run"].workspace_id
        assert domain["project_id"] == lineage["run"].project_id
        assert domain["creator_run_id"] == lineage["run"].id
        assert domain["report_ref"]["id"] == report.id
        assert domain["report_ref"]["version"] == report.version
        assert domain["report_ref"]["type"] == "QualityAssessmentReportVersion"
        assert domain["report_ref"]["hash"]
        assert domain["evaluation_hash"]
    assert report.report_json["input_lineage"] == {
        "source_snapshot_ref": _reference(source.id, source.version, source.canonical_hash),
        "truth_ref": _reference(truth.id, truth.version, truth.canonical_hash),
        "confirmation_ref": _reference(confirmation.id, confirmation.version, confirmation.canonical_hash),
        "master_ref": _master_reference(master),
    }
    assert quality_lineage["master_ref"] == _master_reference(master)
    assert report.report_json["threshold_profile_ref"]
    assert report.canonical_hash == report.report_json["canonical_hash"]
    profile = db_session.get(QualityThresholdProfileVersion, report.threshold_profile_id)
    assert profile is not None
    assert all(
        domain["score"] >= profile.thresholds_json["per_domain_minimum"][domain_id]
        for domain_id, domain in domains.items()
    )
    assert no_dispatch_counts == (
        db_session.query(ImageGenerationJobRecord).filter_by(project_id=lineage["run"].project_id).count(),
        db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count(),
        db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count(),
    )

    # QA report persistence must append only its own immutable rows; all
    # frozen input lineage remains exactly as it was before evaluation.
    assert page.sections_json["snapshot_hash"] == immutable_parent_hashes["page"]
    assert db_session.get(ProductSourceSnapshotVersion, source.id).canonical_hash == immutable_parent_hashes["source"]
    assert db_session.get(ProductTruthVersion, truth.id).canonical_hash == immutable_parent_hashes["truth"]
    assert db_session.get(SellerConfirmationVersion, confirmation.id).canonical_hash == immutable_parent_hashes["confirmation"]
    assert db_session.get(ProductCreativeBriefVersion, brief.id).output_hash == immutable_parent_hashes["brief"]
    assert db_session.get(CommerceCreativeMasterVersion, master.id).canonical_hash == immutable_parent_hashes["master"]
    assert layout_evidence["evidence_hash"]


def test_aggregates_persisted_lg12_quality_bar_pass(client, auth_headers, db_session, tmp_path):
    """A-1.5: a persisted complete report reaches real Quality Bar PASS."""

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=page)
    attach_valid_lg12_layout_evidence(page=page)
    attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)
    evaluation = evaluate_all_lg12_quality_domains(run=lineage["run"], page=page, db_session=db_session)
    report = evaluation["qa_report"]
    source = evidence_page["asset_lineage"]["source"]
    truth = evidence_page["asset_lineage"]["truth"]
    confirmation = evidence_page["asset_lineage"]["confirmation"]
    brief = evidence_page["asset_lineage"]["brief"]
    master = evidence_page["asset_lineage"]["master"]
    immutable_hashes = {
        "source": source.canonical_hash, "truth": truth.canonical_hash,
        "confirmation": confirmation.canonical_hash, "brief": brief.output_hash,
        "master": master.canonical_hash, "page": page.sections_json["snapshot_hash"],
        "report": report.canonical_hash,
    }

    aggregation = aggregate_valid_lg12_quality_bar(qa_report=report, db_session=db_session)
    profile = aggregation["threshold_profile"]
    quality_bar = aggregation["quality_bar"]
    repeated = aggregate_valid_lg12_quality_bar(qa_report=report, db_session=db_session)["quality_bar"]
    frozen_target = _frozen_detail_page_reference(page)
    expected_report_ref = {
        "id": report.id, "version": report.version, "hash": report.canonical_hash,
        "type": "QualityAssessmentReportVersion",
    }
    expected_profile_ref = {
        "id": profile.id, "version": profile.version, "hash": profile.canonical_hash,
        "type": "QualityThresholdProfileVersion",
    }

    assert quality_bar == repeated
    assert quality_bar["quality_bar_result_id"]
    assert quality_bar["canonical_hash"]
    assert quality_bar["frozen_target_ref"] == frozen_target
    assert quality_bar["quality_report_ref"] == expected_report_ref
    assert quality_bar["threshold_profile_ref"] == expected_profile_ref
    assert quality_bar["evaluator_bundle"]["bundle_id"] == report.evaluator_bundle_version
    assert {item["id"].split(":")[-1] for item in quality_bar["domain_result_refs"]} == set(evaluation["domain_results"])
    # These values are read from the persisted v1 profile by the production
    # service; the Quality Bar receives no separately supplied thresholds.
    assert profile.applicable_artifact_type == frozen_target["type"]
    assert set(report.target_channels_json).issubset(set(profile.applicable_channels_json))
    assert profile.thresholds_json["overall_minimum"] == 85
    assert set(profile.thresholds_json["per_domain_minimum"]) == set(evaluation["domain_results"])
    assert set(profile.thresholds_json["per_domain_minimum"].values()) == {70}
    assert profile.thresholds_json["max_critical_violations"] == 0
    assert quality_bar["critical_count"] == 0
    assert all(quality_bar["per_domain_threshold_result"].values())
    assert all(item["status"] == "complete" and item["meets_threshold"] for item in quality_bar["domain_scores"])
    assert quality_bar["overall_score"] >= profile.thresholds_json["overall_minimum"]
    assert quality_bar["overall_threshold_result"] is True
    assert quality_bar["verdict"] == "PASS"
    assert quality_bar["routing_code"] == "PASS"
    assert quality_bar["blocking_reasons"] == []
    assert quality_bar["rework_targets"] == []

    # Aggregation is read-only: it must neither modify its frozen parents nor
    # rewrite the immutable QA report/profile it reads.
    assert db_session.get(ProductSourceSnapshotVersion, source.id).canonical_hash == immutable_hashes["source"]
    assert db_session.get(ProductTruthVersion, truth.id).canonical_hash == immutable_hashes["truth"]
    assert db_session.get(SellerConfirmationVersion, confirmation.id).canonical_hash == immutable_hashes["confirmation"]
    assert db_session.get(ProductCreativeBriefVersion, brief.id).output_hash == immutable_hashes["brief"]
    assert db_session.get(CommerceCreativeMasterVersion, master.id).canonical_hash == immutable_hashes["master"]
    assert page.sections_json["snapshot_hash"] == immutable_hashes["page"]
    assert db_session.get(QualityAssessmentReportVersion, report.id).canonical_hash == immutable_hashes["report"]
    assert db_session.get(QualityThresholdProfileVersion, profile.id).canonical_hash == profile.canonical_hash


def test_compiled_graph_reaches_quality_promotion_ready_from_persisted_pass_fixture(
    client, auth_headers, db_session, tmp_path,
):
    """A-2: actual compiled LG-10 QA routing reaches the TASK-12.10 boundary."""

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=page)
    attach_valid_lg12_layout_evidence(page=page)
    attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)
    # A-1's real persisted PASS fixture is deliberately prepared before graph
    # entry. The real graph node still calls the idempotent production report
    # builder and Quality Bar; it must not skip them.
    existing = evaluate_all_lg12_quality_domains(run=lineage["run"], page=page, db_session=db_session)
    prior_report = existing["qa_report"]
    prior_bar = aggregate_valid_lg12_quality_bar(qa_report=prior_report, db_session=db_session)["quality_bar"]
    assert prior_bar["verdict"] == prior_bar["routing_code"] == "PASS"

    asset_lineage = evidence_page["asset_lineage"]
    immutable_hashes = {
        "source": asset_lineage["source"].canonical_hash,
        "truth": asset_lineage["truth"].canonical_hash,
        "confirmation": asset_lineage["confirmation"].canonical_hash,
        "brief": asset_lineage["brief"].output_hash,
        "master": asset_lineage["master"].canonical_hash,
        "page_plan": page_plan["page_plan_ref"]["hash"],
        "page": page.sections_json["snapshot_hash"],
    }
    initial_counts = {
        "source": db_session.query(ProductSourceSnapshotVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "truth": db_session.query(ProductTruthVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "confirmation": db_session.query(SellerConfirmationVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "brief": db_session.query(ProductCreativeBriefVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "master": db_session.query(CommerceCreativeMasterVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "page": db_session.query(DetailPageVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "report": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=lineage["run"].project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count(),
    }

    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=page, db_session=db_session,
    )
    graph = invocation["graph"]
    config = invocation["config"]
    checkpoint = invocation["checkpoint"]
    run = invocation["run"]
    quality = dict(checkpoint.values["quality"])
    expected_page_ref = _frozen_detail_page_reference(page)

    assert checkpoint.values["run_id"] == run.id
    assert checkpoint.values["thread_id"] == run.graph_thread_id == run.id
    assert checkpoint.values["current_stage"] == "quality_promotion_ready", {
        "bar_verdict": quality.get("quality_bar_verdict"),
        "routing_code": quality.get("routing_code"),
        "reasons": quality.get("last_blocking_reasons"),
        "targets": quality.get("rework_targets"),
        "next": checkpoint.next,
    }
    assert checkpoint.values["status"] == "completed"
    assert [event["stage"] for event in checkpoint.values["events"]][-2:] == [
        "quality_evaluation", "quality_promotion_ready",
    ]
    assert quality["current_detail_page_ref"] == expected_page_ref
    assert quality["quality_report_ref"] == {
        "id": prior_report.id,
        "version": prior_report.version,
        "hash": prior_report.canonical_hash,
        "type": "QualityAssessmentReportVersion",
    }
    assert quality["quality_bar_ref"]["hash"] == prior_bar["canonical_hash"]
    assert quality["quality_bar_verdict"] == quality["routing_code"] == "PASS"
    assert quality["attempt_ledger"] == []
    assert quality["rework_attempt_count"] == 0
    assert quality["seller_review_required"] is False

    db_session.refresh(run)
    projection = dict((run.outputs_json or {}).get("langgraph_quality") or {})
    assert run.status == "completed"
    assert run.current_stage == "quality_promotion_ready"
    assert projection == quality
    assert (run.outputs_json or {}).get("langgraph_review", {}).get("pending") is None
    assert "rework" not in run.current_stage

    # A completed checkpoint has no scheduled node. Reloading/replaying it is a
    # read-only idempotency operation: no duplicate report, provider work,
    # retry ledger, or child page may be created.
    replay = graph.invoke(None, config)
    assert replay["current_stage"] == "quality_promotion_ready"
    assert replay["quality"] == quality
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == initial_counts["report"]
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == initial_counts["jobs"]
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == initial_counts["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count() == initial_counts["cost"]
    assert db_session.query(ProductSourceSnapshotVersion).filter_by(project_id=run.project_id).count() == initial_counts["source"]
    assert db_session.query(ProductTruthVersion).filter_by(project_id=run.project_id).count() == initial_counts["truth"]
    assert db_session.query(SellerConfirmationVersion).filter_by(project_id=run.project_id).count() == initial_counts["confirmation"]
    assert db_session.query(ProductCreativeBriefVersion).filter_by(project_id=run.project_id).count() == initial_counts["brief"]
    assert db_session.query(CommerceCreativeMasterVersion).filter_by(project_id=run.project_id).count() == initial_counts["master"]
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == initial_counts["page"]

    assert db_session.get(ProductSourceSnapshotVersion, asset_lineage["source"].id).canonical_hash == immutable_hashes["source"]
    assert db_session.get(ProductTruthVersion, asset_lineage["truth"].id).canonical_hash == immutable_hashes["truth"]
    assert db_session.get(SellerConfirmationVersion, asset_lineage["confirmation"].id).canonical_hash == immutable_hashes["confirmation"]
    assert db_session.get(ProductCreativeBriefVersion, asset_lineage["brief"].id).output_hash == immutable_hashes["brief"]
    assert db_session.get(CommerceCreativeMasterVersion, asset_lineage["master"].id).canonical_hash == immutable_hashes["master"]
    assert page_plan["page_plan_ref"]["hash"] == immutable_hashes["page_plan"]
    assert db_session.get(DetailPageVersion, page.id).sections_json["snapshot_hash"] == immutable_hashes["page"]


def test_compiled_graph_executes_real_copy_rework_and_reqa(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """B-1: real COPY_REWORK creates one TASK-11.3 child then re-enters common QA."""

    from src.agents.langgraph_runtime import _lg12_quality_rework_action

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    original_page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=original_page)
    attach_valid_lg12_layout_evidence(page=original_page)
    attach_valid_lg12_channel_parity_evidence(
        page=original_page, db_session=db_session, tmp_path=tmp_path,
    )
    original_evaluation = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=original_page, db_session=db_session,
    )
    original_report = original_evaluation["qa_report"]
    original_bar = aggregate_valid_lg12_quality_bar(
        qa_report=original_report, db_session=db_session,
    )["quality_bar"]
    assert original_bar["verdict"] == original_bar["routing_code"] == "PASS"

    failure = build_copy_spacing_failure_fixture(
        run=lineage["run"], page=original_page, db_session=db_session,
    )
    failing_page = failure["page"]
    attach_valid_lg12_copy_evidence(page=failing_page)
    attach_valid_lg12_layout_evidence(page=failing_page)
    attach_valid_lg12_channel_parity_evidence(
        page=failing_page, db_session=db_session, tmp_path=tmp_path,
    )
    failing_evaluation = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )
    failing_report = failing_evaluation["qa_report"]
    failing_copy = failing_evaluation["domain_results"]["korean_copy_readability"]
    spacing_findings = [
        item for item in failing_copy["findings"]
        if item["rule_id"] == "copy.spacing_inconsistency"
    ]
    assert len(spacing_findings) == 1
    assert spacing_findings[0]["observed"] == {
        "value": 8,
        "unit": "repeated_whitespace_runs",
    }
    assert failing_copy["score"] == 68
    assert failing_copy["status"] == "complete"
    assert all(
        failing_evaluation["domain_results"][domain]["status"] == "complete"
        for domain in (
            "factual_rights_policy", "image_identity_quality",
            "layout_typography_brand_flow", "channel_preview_export_parity",
        )
    )
    failing_bar = aggregate_valid_lg12_quality_bar(
        qa_report=failing_report, db_session=db_session,
    )["quality_bar"]
    copy_target = next(
        target for target in failing_bar["rework_targets"]
        if target["domain"] == "korean_copy_readability"
    )
    assert failing_bar["verdict"] == "FAIL"
    assert failing_bar["routing_code"] == "COPY_REWORK"
    assert copy_target["recommended_action"] == "copy.spacing_inconsistency"
    assert copy_target["target_ref"]["type"] == "copy_field"
    assert _lg12_quality_rework_action(copy_target["recommended_action"]) == "spacing_inconsistency"

    asset_lineage = evidence_page["asset_lineage"]
    immutable_hashes = {
        "source": asset_lineage["source"].canonical_hash,
        "truth": asset_lineage["truth"].canonical_hash,
        "confirmation": asset_lineage["confirmation"].canonical_hash,
        "brief": asset_lineage["brief"].output_hash,
        "master": asset_lineage["master"].canonical_hash,
        "brand_kit": lineage["brand_kit"].content_hash,
        "page_plan": page_plan["page_plan_ref"]["hash"],
        "original_page": original_page.sections_json["snapshot_hash"],
        "failing_page": failing_page.sections_json["snapshot_hash"],
        "original_report": original_report.canonical_hash,
        "failing_report": failing_report.canonical_hash,
        "original_bar": original_bar["canonical_hash"],
        "failing_bar": failing_bar["canonical_hash"],
    }
    before_graph_counts = {
        "page": db_session.query(DetailPageVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "report": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=lineage["run"].project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count(),
    }

    # The production finalizer writes immutable standalone packages below its
    # process upload root. Point only this isolated test process at pytest's
    # temporary root; no executor, fork, evaluator, or Quality Bar seam is
    # replaced.
    monkeypatch.chdir(tmp_path)
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )
    graph = invocation["graph"]
    config = invocation["config"]
    checkpoint = invocation["checkpoint"]
    run = invocation["run"]
    quality = dict(checkpoint.values["quality"])
    child_ref = dict(quality["current_detail_page_ref"])
    child = db_session.get(DetailPageVersion, child_ref["id"])
    assert child is not None
    child_report = db_session.get(
        QualityAssessmentReportVersion, str(dict(quality["quality_report_ref"])["id"]),
    )
    assert child_report is not None
    child_domain_statuses = {
        str(domain["domain_id"]): (domain["status"], domain["score"])
        for domain in child_report.report_json["domain_scores"]
    }

    assert checkpoint.values["current_stage"] == "quality_promotion_ready", child_domain_statuses
    assert child_domain_statuses == {
        "factual_rights_policy": ("complete", 100),
        "image_identity_quality": ("complete", 100),
        "korean_copy_readability": ("complete", 100),
        "layout_typography_brand_flow": ("complete", 100),
        "channel_preview_export_parity": ("complete", 100),
    }
    assert checkpoint.values["status"] == "completed"
    assert [event["stage"] for event in checkpoint.values["events"]][-5:] == [
        "quality_evaluation", "quality_selective_rework", "quality_copy_rework",
        "quality_evaluation", "quality_promotion_ready",
    ]
    assert child.id != failing_page.id
    assert child.sections_json["snapshot_hash"] != failing_page.sections_json["snapshot_hash"]
    assert child.sections_json["lg11"]["parent_detail_page_version_id"] == failing_page.id
    assert child.sections_json["lg11"]["copy_changes"] == {
        failure["section_id"]: {failure["field"]: failure["source_text"] + " "},
    }
    assert child.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"] == (
        failing_page.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]
    )
    assert child.sections_json["lg10"]["canonical_page_assembly_input"]["brand_kit_ref"] == (
        failing_page.sections_json["lg10"]["canonical_page_assembly_input"]["brand_kit_ref"]
    )
    assert child.sections_json["lg12_quality_lineage"] == failing_page.sections_json["lg12_quality_lineage"]
    assert child.sections_json["lg10"]["canonical_page_assembly_input"]["planning_refs"]["page_plan"] == (
        failing_page.sections_json["lg10"]["canonical_page_assembly_input"]["planning_refs"]["page_plan"]
    )

    assert quality["quality_report_ref"]["id"] != failing_report.id
    assert quality["quality_bar_verdict"] == quality["routing_code"] == "PASS"
    assert quality["seller_review_required"] is False
    assert len(quality["attempt_ledger"]) == 1
    ledger = quality["attempt_ledger"][0]
    assert ledger["node_family"] == "copy_reassembly"
    assert ledger["attempt_count"] == 1
    assert ledger["status"] == "child_frozen"
    assert ledger["last_child_detail_page_ref"] == child_ref
    assert quality["rework_attempt_count"] == 1
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == before_graph_counts["page"] + 1
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == before_graph_counts["report"] + 1
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before_graph_counts["jobs"]
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before_graph_counts["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count() == before_graph_counts["cost"]

    replay = graph.invoke(None, config)
    assert replay["current_stage"] == "quality_promotion_ready"
    assert replay["quality"] == quality
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == before_graph_counts["page"] + 1
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == before_graph_counts["report"] + 1
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before_graph_counts["jobs"]
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before_graph_counts["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count() == before_graph_counts["cost"]

    assert db_session.get(ProductSourceSnapshotVersion, asset_lineage["source"].id).canonical_hash == immutable_hashes["source"]
    assert db_session.get(ProductTruthVersion, asset_lineage["truth"].id).canonical_hash == immutable_hashes["truth"]
    assert db_session.get(SellerConfirmationVersion, asset_lineage["confirmation"].id).canonical_hash == immutable_hashes["confirmation"]
    assert db_session.get(ProductCreativeBriefVersion, asset_lineage["brief"].id).output_hash == immutable_hashes["brief"]
    assert db_session.get(CommerceCreativeMasterVersion, asset_lineage["master"].id).canonical_hash == immutable_hashes["master"]
    assert lineage["brand_kit"].content_hash == immutable_hashes["brand_kit"]
    assert page_plan["page_plan_ref"]["hash"] == immutable_hashes["page_plan"]
    assert db_session.get(DetailPageVersion, original_page.id).sections_json["snapshot_hash"] == immutable_hashes["original_page"]
    assert db_session.get(DetailPageVersion, failing_page.id).sections_json["snapshot_hash"] == immutable_hashes["failing_page"]
    assert db_session.get(QualityAssessmentReportVersion, original_report.id).canonical_hash == immutable_hashes["original_report"]
    assert db_session.get(QualityAssessmentReportVersion, failing_report.id).canonical_hash == immutable_hashes["failing_report"]
    assert original_bar["canonical_hash"] == immutable_hashes["original_bar"]
    assert failing_bar["canonical_hash"] == immutable_hashes["failing_bar"]


def test_compiled_graph_executes_real_visual_rework_and_reqa(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """B-2: real Canvas findings route through VISUAL_REWORK and re-enter QA."""

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    original_page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=original_page)
    attach_valid_lg12_layout_evidence(page=original_page)
    attach_valid_lg12_channel_parity_evidence(
        page=original_page, db_session=db_session, tmp_path=tmp_path,
    )
    assert aggregate_valid_lg12_quality_bar(
        qa_report=evaluate_all_lg12_quality_domains(
            run=lineage["run"], page=original_page, db_session=db_session,
        )["qa_report"],
        db_session=db_session,
    )["quality_bar"]["verdict"] == "PASS"

    failure = build_visual_overflow_failure_fixture(
        run=lineage["run"], page=original_page, db_session=db_session,
    )
    failing_page = failure["page"]
    attach_valid_lg12_copy_evidence(page=failing_page)
    attach_valid_lg12_layout_evidence(page=failing_page)
    attach_valid_lg12_channel_parity_evidence(
        page=failing_page, db_session=db_session, tmp_path=tmp_path,
    )
    failing_evaluation = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )
    failing_layout = failing_evaluation["domain_results"]["layout_typography_brand_flow"]
    canvas_findings = [
        finding for finding in failing_layout["findings"]
        if finding["rule_id"] in {"layout.element_overflow", "layout.element_overlap"}
    ]
    assert failing_layout["status"] == "complete"
    assert failing_layout["score"] == 64, canvas_findings
    assert {finding["rule_id"] for finding in canvas_findings} == {
        "layout.element_overflow", "layout.element_overlap",
    }
    assert len(canvas_findings) == 3
    assert all(
        any(ref["type"] == "frozen_canvas_element" and ref["id"] == failure["element_id"]
            for ref in finding["target_refs"])
        for finding in canvas_findings
    )
    failing_report = failing_evaluation["qa_report"]
    failing_bar = aggregate_valid_lg12_quality_bar(
        qa_report=failing_report, db_session=db_session,
    )["quality_bar"]
    visual_target = next(
        target for target in failing_bar["rework_targets"]
        if target["domain"] == "layout_typography_brand_flow"
    )
    assert failing_bar["verdict"] == "FAIL"
    assert failing_bar["routing_code"] == "VISUAL_REWORK"
    assert visual_target["target_ref"]["type"] == "frozen_canvas_element"
    assert visual_target["target_ref"]["id"] == failure["element_id"]

    asset_lineage = evidence_page["asset_lineage"]
    immutable_hashes = {
        "source": asset_lineage["source"].canonical_hash,
        "truth": asset_lineage["truth"].canonical_hash,
        "confirmation": asset_lineage["confirmation"].canonical_hash,
        "brief": asset_lineage["brief"].output_hash,
        "master": asset_lineage["master"].canonical_hash,
        "brand_kit": lineage["brand_kit"].content_hash,
        "page_plan": page_plan["page_plan_ref"]["hash"],
        "original_page": original_page.sections_json["snapshot_hash"],
        "failing_page": failing_page.sections_json["snapshot_hash"],
        "failing_report": failing_report.canonical_hash,
        "failing_bar": failing_bar["canonical_hash"],
    }
    before_graph_counts = {
        "page": db_session.query(DetailPageVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "report": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=lineage["run"].project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count(),
    }

    monkeypatch.chdir(tmp_path)
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )
    graph, config, checkpoint, run = (
        invocation["graph"], invocation["config"], invocation["checkpoint"], invocation["run"],
    )
    quality = dict(checkpoint.values["quality"])
    child_ref = dict(quality["current_detail_page_ref"])
    child = db_session.get(DetailPageVersion, child_ref["id"])
    child_report = db_session.get(QualityAssessmentReportVersion, quality["quality_report_ref"]["id"])

    assert checkpoint.values["current_stage"] == "quality_promotion_ready", {
        "quality": quality, "events": checkpoint.values.get("events"),
    }
    assert checkpoint.values["status"] == "completed"
    assert child is not None and child_report is not None
    assert child.id != failing_page.id
    assert child.sections_json["lg11"]["parent_detail_page_version_id"] == failing_page.id
    child_asset = next(
        element
        for section in child.sections_json["lg10"]["canonical_page_assembly_input"]["sections"]
        for element in section["canvas_elements"]
        if element["element_id"] == failure["element_id"]
    )
    assert (child_asset["x"], child_asset["y"]) == (0, 144)
    assert child.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"] == (
        failing_page.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]
    )
    assert child.sections_json["lg10"]["canonical_page_assembly_input"]["brand_kit_ref"] == (
        failing_page.sections_json["lg10"]["canonical_page_assembly_input"]["brand_kit_ref"]
    )
    assert child.sections_json["lg12_quality_lineage"] == failing_page.sections_json["lg12_quality_lineage"]
    assert all(
        (domain["status"], domain["score"]) == ("complete", 100)
        for domain in child_report.report_json["domain_scores"]
    )
    assert quality["quality_bar_verdict"] == quality["routing_code"] == "PASS"
    assert len(quality["attempt_ledger"]) == quality["rework_attempt_count"] == 1
    assert quality["attempt_ledger"][0]["node_family"] == "layout_plan_reassembly"
    assert quality["attempt_ledger"][0]["attempt_count"] == 1
    assert quality["attempt_ledger"][0]["status"] == "child_frozen"
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == before_graph_counts["page"] + 1
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == before_graph_counts["report"] + 1
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before_graph_counts["jobs"]
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before_graph_counts["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count() == before_graph_counts["cost"]

    replay = graph.invoke(None, config)
    assert replay["current_stage"] == "quality_promotion_ready"
    assert replay["quality"] == quality
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == before_graph_counts["page"] + 1
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == before_graph_counts["report"] + 1

    assert db_session.get(ProductSourceSnapshotVersion, asset_lineage["source"].id).canonical_hash == immutable_hashes["source"]
    assert db_session.get(ProductTruthVersion, asset_lineage["truth"].id).canonical_hash == immutable_hashes["truth"]
    assert db_session.get(SellerConfirmationVersion, asset_lineage["confirmation"].id).canonical_hash == immutable_hashes["confirmation"]
    assert db_session.get(ProductCreativeBriefVersion, asset_lineage["brief"].id).output_hash == immutable_hashes["brief"]
    assert db_session.get(CommerceCreativeMasterVersion, asset_lineage["master"].id).canonical_hash == immutable_hashes["master"]
    assert lineage["brand_kit"].content_hash == immutable_hashes["brand_kit"]
    assert page_plan["page_plan_ref"]["hash"] == immutable_hashes["page_plan"]
    assert db_session.get(DetailPageVersion, original_page.id).sections_json["snapshot_hash"] == immutable_hashes["original_page"]
    assert db_session.get(DetailPageVersion, failing_page.id).sections_json["snapshot_hash"] == immutable_hashes["failing_page"]
    assert db_session.get(QualityAssessmentReportVersion, failing_report.id).canonical_hash == immutable_hashes["failing_report"]
    assert failing_bar["canonical_hash"] == immutable_hashes["failing_bar"]


def test_compiled_graph_executes_real_style_rework_and_reqa(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """B-2: an actual Master/Brand Kit mismatch uses TASK-11.6 reassembly."""

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    original_page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=original_page)
    attach_valid_lg12_layout_evidence(page=original_page)
    attach_valid_lg12_channel_parity_evidence(
        page=original_page, db_session=db_session, tmp_path=tmp_path,
    )
    assert aggregate_valid_lg12_quality_bar(
        qa_report=evaluate_all_lg12_quality_domains(
            run=lineage["run"], page=original_page, db_session=db_session,
        )["qa_report"],
        db_session=db_session,
    )["quality_bar"]["verdict"] == "PASS"

    failure = build_style_brand_mismatch_failure_fixture(
        run=lineage["run"], page=original_page, db_session=db_session,
    )
    failing_page = failure["page"]
    attach_valid_lg12_copy_evidence(page=failing_page)
    attach_valid_lg12_layout_evidence(page=failing_page)
    attach_valid_lg12_channel_parity_evidence(
        page=failing_page, db_session=db_session, tmp_path=tmp_path,
    )
    failing_evaluation = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )
    failing_layout = failing_evaluation["domain_results"]["layout_typography_brand_flow"]
    mismatch = next(
        finding for finding in failing_layout["findings"]
        if finding["rule_id"] == "layout.brand_kit_identity_mismatch"
    )
    assert failing_layout["status"] == "complete"
    assert mismatch["severity"] == "critical"
    assert any(
        ref["type"] == "BrandKitVersion"
        and ref["id"] == lineage["brand_kit"].id
        and ref["hash"] == lineage["brand_kit"].content_hash
        for ref in mismatch["target_refs"]
    )
    failing_report = failing_evaluation["qa_report"]
    failing_bar = aggregate_valid_lg12_quality_bar(
        qa_report=failing_report, db_session=db_session,
    )["quality_bar"]
    style_target = next(
        target for target in failing_bar["rework_targets"]
        if target["domain"] == "layout_typography_brand_flow"
        and target["recommended_action"] == "layout.brand_kit_identity_mismatch"
    )
    assert failing_bar["verdict"] == "FAIL"
    assert failing_bar["routing_code"] == "VISUAL_REWORK"
    assert style_target["target_ref"]["type"] == "BrandKitVersion"
    assert style_target["target_ref"]["id"] == lineage["brand_kit"].id

    before_counts = {
        "page": db_session.query(DetailPageVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "report": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=lineage["run"].project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count(),
    }
    parent_snapshot = deepcopy(failing_page.sections_json)
    alternate_hash = failure["alternate_brand_kit"].content_hash

    monkeypatch.chdir(tmp_path)
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )
    graph, config, checkpoint, run = (
        invocation["graph"], invocation["config"], invocation["checkpoint"], invocation["run"],
    )
    quality = dict(checkpoint.values["quality"])
    child_ref = dict(quality["current_detail_page_ref"])
    child = db_session.get(DetailPageVersion, child_ref["id"])
    child_report = db_session.get(QualityAssessmentReportVersion, quality["quality_report_ref"]["id"])

    assert checkpoint.values["current_stage"] == "quality_promotion_ready", {
        "quality": quality, "events": checkpoint.values.get("events"),
    }
    assert checkpoint.values["status"] == "completed"
    assert child is not None and child_report is not None
    assert child.id != failing_page.id
    assert child.sections_json["lg11"]["parent_detail_page_version_id"] == failing_page.id
    assert child.sections_json["lg10"]["canonical_page_assembly_input"]["brand_kit_ref"] == {
        "brand_kit_version_id": lineage["brand_kit"].id,
        "brand_kit_hash": lineage["brand_kit"].content_hash,
    }
    assert child.sections_json["lg12_quality_lineage"] == failing_page.sections_json["lg12_quality_lineage"]
    assert all(
        (domain["status"], domain["score"]) == ("complete", 100)
        for domain in child_report.report_json["domain_scores"]
    )
    assert quality["quality_bar_verdict"] == quality["routing_code"] == "PASS"
    assert len(quality["attempt_ledger"]) == quality["rework_attempt_count"] == 1
    assert quality["attempt_ledger"][0]["node_family"] == "style_reassembly"
    assert quality["attempt_ledger"][0]["attempt_count"] == 1
    assert quality["attempt_ledger"][0]["status"] == "child_frozen"
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == before_counts["page"] + 1
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == before_counts["report"] + 1
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before_counts["jobs"]
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before_counts["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count() == before_counts["cost"]

    replay = graph.invoke(None, config)
    assert replay["current_stage"] == "quality_promotion_ready"
    assert replay["quality"] == quality
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == before_counts["page"] + 1
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == before_counts["report"] + 1
    assert db_session.get(DetailPageVersion, failing_page.id).sections_json == parent_snapshot
    assert failure["alternate_brand_kit"].content_hash == alternate_hash
    assert lineage["brand_kit"].content_hash != alternate_hash


def test_compiled_graph_executes_real_plan_rework_and_reqa(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """B-3: frozen renderer/scene order drift uses the PagePlan/Canvas executor."""

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    original_page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=original_page)
    attach_valid_lg12_layout_evidence(page=original_page)
    attach_valid_lg12_channel_parity_evidence(
        page=original_page, db_session=db_session, tmp_path=tmp_path,
    )
    assert aggregate_valid_lg12_quality_bar(
        qa_report=evaluate_all_lg12_quality_domains(
            run=lineage["run"], page=original_page, db_session=db_session,
        )["qa_report"], db_session=db_session,
    )["quality_bar"]["verdict"] == "PASS"

    failure = build_plan_order_failure_fixture(
        run=lineage["run"], page=original_page, db_session=db_session,
    )
    failing_page = failure["page"]
    attach_valid_lg12_copy_evidence(page=failing_page)
    attach_valid_lg12_layout_evidence(page=failing_page)
    attach_valid_lg12_channel_parity_evidence(
        page=failing_page, db_session=db_session, tmp_path=tmp_path,
    )
    failing_evaluation = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )
    failing_layout = failing_evaluation["domain_results"]["layout_typography_brand_flow"]
    plan_finding = next(
        finding for finding in failing_layout["findings"]
        if finding["rule_id"] == "layout.section_order_mismatch"
    )
    assert failing_layout["score"] == 64
    assert any(
        ref["type"] == "PagePlanVersion"
        and ref["id"] == page_plan["page_plan_ref"]["id"]
        and ref["hash"] == page_plan["page_plan_ref"]["hash"]
        for ref in plan_finding["target_refs"]
    )
    failing_report = failing_evaluation["qa_report"]
    failing_bar = aggregate_valid_lg12_quality_bar(
        qa_report=failing_report, db_session=db_session,
    )["quality_bar"]
    plan_target = next(
        target for target in failing_bar["rework_targets"]
        if target["domain"] == "layout_typography_brand_flow"
    )
    assert failing_bar["verdict"] == "FAIL"
    # This is the current real Quality Bar taxonomy.  ``plan_reorder`` is a
    # narrow action below VISUAL_REWORK, rather than a newly invented route.
    assert failing_bar["routing_code"] == "VISUAL_REWORK"
    assert plan_target["target_ref"]["type"] == "PagePlanVersion"
    assert plan_target["recommended_action"] in {
        "layout.section_order_mismatch", "layout.scene_order_mismatch", "layout.scene_identity_mismatch",
    }

    before_counts = {
        "page": db_session.query(DetailPageVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "master": db_session.query(CommerceCreativeMasterVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "report": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=lineage["run"].project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=lineage["run"].project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=lineage["run"].id).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=lineage["run"].id).count(),
    }
    parent_master = evidence_page["asset_lineage"]["master"]
    parent_page_plan = dict(page_plan["page_plan_ref"])
    parent_snapshot = deepcopy(failing_page.sections_json)

    monkeypatch.chdir(tmp_path)
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=failing_page, db_session=db_session,
    )
    graph, config, checkpoint, run = (
        invocation["graph"], invocation["config"], invocation["checkpoint"], invocation["run"],
    )
    quality = dict(checkpoint.values["quality"])
    child_ref = dict(quality["current_detail_page_ref"])
    child = db_session.get(DetailPageVersion, child_ref["id"])
    child_report = db_session.get(QualityAssessmentReportVersion, quality["quality_report_ref"]["id"])
    assert checkpoint.values["current_stage"] == "quality_promotion_ready", {
        "quality": quality, "events": checkpoint.values.get("events"),
    }
    assert checkpoint.values["status"] == "completed"
    assert child is not None and child_report is not None
    assert child.id != failing_page.id
    assert child.sections_json["lg11"]["parent_detail_page_version_id"] == failing_page.id
    child_plan = child.sections_json["lg10"]["canonical_page_assembly_input"]["planning_refs"]["page_plan"]
    assert child_plan["artifact_id"] != parent_page_plan["id"]
    assert child_plan["artifact_version"] == parent_page_plan["version"] + 1
    assert child_plan["artifact_hash"] != parent_page_plan["hash"]
    child_master_ref = child.sections_json["lg12_quality_lineage"]["master_ref"]
    child_master = db_session.get(CommerceCreativeMasterVersion, child_master_ref["id"])
    assert child_master is not None
    assert child_master.parent_version_id == parent_master.id
    assert child_master.page_plan_artifact_ref_json["id"] == child_plan["artifact_id"]
    assert child_master.page_plan_artifact_ref_json["hash"] == child_plan["artifact_hash"]
    assert (
        child_master.source_snapshot_version_id,
        child_master.truth_version_id,
        child_master.confirmation_version_id,
        child_master.creative_brief_version_id,
        child_master.brand_kit_version_id,
    ) == (
        parent_master.source_snapshot_version_id,
        parent_master.truth_version_id,
        parent_master.confirmation_version_id,
        parent_master.creative_brief_version_id,
        parent_master.brand_kit_version_id,
    )
    assert child_master.evidence_artifact_refs_json == parent_master.evidence_artifact_refs_json
    assert child_master.approved_fact_snapshot_ref_json == parent_master.approved_fact_snapshot_ref_json
    assert child_master.approved_asset_manifest_ref_json == parent_master.approved_asset_manifest_ref_json
    assert child_master.copy_artifact_ref_json == parent_master.copy_artifact_ref_json
    assert child_master.target_channels == parent_master.target_channels
    successor_plan = resolve_commerce_planning_artifact_version(
        run=run, stage="page_planning",
        reference={
            "id": child_plan["artifact_id"],
            "version": child_plan["artifact_version"],
            "hash": child_plan["artifact_hash"],
        },
    )
    assert successor_plan["metadata"]["parent_artifact_ref"] == {
        "id": parent_page_plan["id"],
        "version": parent_page_plan["version"],
        "hash": parent_page_plan["hash"],
        "type": "PagePlanVersion",
    }
    assert [section["section_id"] for section in child.sections_json["lg10"]["canonical_page_assembly_input"]["sections"]] == failure["desired_order"]
    parent_sections = {
        section["section_id"]: section
        for section in parent_snapshot["lg10"]["canonical_page_assembly_input"]["sections"]
    }
    for section in child.sections_json["lg10"]["canonical_page_assembly_input"]["sections"]:
        parent_section = parent_sections[section["section_id"]]
        assert section["copy_ref"] == parent_section["copy_ref"]
        assert section["approved_assets"] == parent_section["approved_assets"]
        assert section["seller_owned_fallback_assets"] == parent_section["seller_owned_fallback_assets"]
    assert all((domain["status"], domain["score"]) == ("complete", 100) for domain in child_report.report_json["domain_scores"])
    assert quality["quality_bar_verdict"] == quality["routing_code"] == "PASS"
    assert len(quality["attempt_ledger"]) == quality["rework_attempt_count"] == 1
    assert quality["attempt_ledger"][0]["node_family"] == "layout_plan_reassembly"
    assert quality["attempt_ledger"][0]["attempt_count"] == 1
    assert quality["attempt_ledger"][0]["status"] == "child_frozen"
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == before_counts["page"] + 1
    assert db_session.query(CommerceCreativeMasterVersion).filter_by(project_id=run.project_id).count() == before_counts["master"] + 1
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == before_counts["report"] + 1
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before_counts["jobs"]
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before_counts["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count() == before_counts["cost"]

    # A valid-looking foreign PagePlan cannot be resolved by its copied ID or
    # hash; the append-only run history is the only source of plan authority.
    with pytest.raises(ValueError):
        resolve_commerce_planning_artifact_version(
            run=run, stage="page_planning",
            reference={**parent_page_plan, "id": "page-plan:cross-plan-injection"},
        )

    replay = graph.invoke(None, config)
    assert replay["current_stage"] == "quality_promotion_ready"
    assert replay["quality"] == quality
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == before_counts["page"] + 1
    assert db_session.query(CommerceCreativeMasterVersion).filter_by(project_id=run.project_id).count() == before_counts["master"] + 1
    assert db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count() == before_counts["report"] + 1
    assert failing_page.sections_json == parent_snapshot


def test_compiled_graph_executes_real_image_rework_cost_outbox_worker_and_reqa(
    client, auth_headers, db_session, tmp_path, monkeypatch, golden_result: dict[str, Any] | None = None,
    checkpointer: Any | None = None,
):
    """B-4: the real LG-11 image path repairs one frozen IMAGE_REWORK target."""

    from contextlib import contextmanager
    from io import BytesIO

    from langgraph.checkpoint.memory import InMemorySaver
    from src.config import settings
    from src.services import image_generation_worker, langgraph_run_service
    from src.services.image_generation_provider import ImageGenerationResult
    from src.services.image_generation_worker import run_image_worker_batch

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    original_page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=original_page)
    attach_valid_lg12_layout_evidence(page=original_page)
    attach_valid_lg12_channel_parity_evidence(page=original_page, db_session=db_session, tmp_path=tmp_path)
    assert aggregate_valid_lg12_quality_bar(
        qa_report=evaluate_all_lg12_quality_domains(run=lineage["run"], page=original_page, db_session=db_session)["qa_report"],
        db_session=db_session,
    )["quality_bar"]["verdict"] == "PASS"

    failing_page = build_image_identity_failure_fixture(
        run=lineage["run"], asset=evidence_page["asset"], job=evidence_page["job"], db_session=db_session,
    )
    attach_valid_lg12_copy_evidence(page=failing_page)
    attach_valid_lg12_layout_evidence(page=failing_page)
    attach_valid_lg12_channel_parity_evidence(page=failing_page, db_session=db_session, tmp_path=tmp_path)
    failing_evaluation = evaluate_all_lg12_quality_domains(run=lineage["run"], page=failing_page, db_session=db_session)
    failing_report = failing_evaluation["qa_report"]
    image_domain = failing_evaluation["domain_results"]["image_identity_quality"]
    assert image_domain["status"] == "blocked"
    assert any(item["code"] == "product_model_identity_mismatch" for item in image_domain["findings"])
    failing_bar = aggregate_valid_lg12_quality_bar(qa_report=failing_report, db_session=db_session)["quality_bar"]
    assert failing_bar["verdict"] == "FAIL"
    assert failing_bar["routing_code"] == "IMAGE_REWORK"
    image_target = next(item for item in failing_bar["rework_targets"] if item["domain"] == "image_identity_quality")
    assert image_target["target_ref"] == {
        "id": evidence_page["asset"].id, "version": 1,
        "hash": evidence_page["asset"].content_hash, "type": "asset",
    }

    # Test infrastructure supplies only the durable checkpointer. Every
    # production node and service below remains the real implementation.
    saver = checkpointer if checkpointer is not None else InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "generated"))
    monkeypatch.chdir(tmp_path)

    provider_calls: list[str] = []

    class ExpectedIdentityFakeProvider:
        """The only seam is the external provider adapter boundary."""

        def generate(self, request):
            provider_calls.append(request.job_id)
            image = Image.new("RGB", (800, 800), color=(16, 24, 32))
            image.paste((48, 64, 80), (240, 240, 560, 560))
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            return ImageGenerationResult(
                content=buffer.getvalue(), mime_type="image/png",
                provider="deterministic-image-provider", model="lg12-b4-fake-v1",
                usage_metadata={"actual_cost": 0.0, "fake_provider": True},
                observed_identity={"model": "SF-100", "color": "black", "variant": "standard"},
            )

    monkeypatch.setattr(image_generation_worker, "DurableFakeImageProvider", ExpectedIdentityFakeProvider)

    run = lineage["run"]
    run.mode = "mock"
    db_session.add(run)
    db_session.commit()
    immutable_hashes = {
        "source": evidence_page["asset_lineage"]["source"].canonical_hash,
        "truth": evidence_page["asset_lineage"]["truth"].canonical_hash,
        "confirmation": evidence_page["asset_lineage"]["confirmation"].canonical_hash,
        "brief": evidence_page["asset_lineage"]["brief"].output_hash,
        "master": evidence_page["asset_lineage"]["master"].canonical_hash,
        "brand_kit": lineage["brand_kit"].content_hash,
        "page_plan": page_plan["page_plan_ref"]["hash"],
        "parent_page": failing_page.sections_json["snapshot_hash"],
        "parent_report": failing_report.canonical_hash,
        "parent_bar": failing_bar["canonical_hash"],
    }
    before = {
        "pages": db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count(),
        "reports": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count(),
    }

    invocation = _invoke_compiled_quality_pass_path(
        run=run, page=failing_page, db_session=db_session, checkpointer=saver,
    )
    graph, config = invocation["graph"], invocation["config"]
    initial = graph.get_state(config)
    assert initial.tasks and initial.tasks[0].interrupts
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).count() == before["cost"] + 1
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == before["outbox"] == 0
    assert provider_calls == []

    # Recovery rebuilds the projection only: no approval, outbox, provider,
    # ledger, source, or child mutation is allowed.
    recover = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert recover.status_code == 200, recover.text
    pending_cost = recover.json()
    assert pending_cost["current_stage"] == "generation_pending"
    assert pending_cost["values"]["review"]["pending"]["review_stage"] == "generation_pending"
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == 0
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before["jobs"]
    assert provider_calls == []

    assert client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers).status_code == 409
    assert client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond"},
    ).status_code == 422

    cost_hash = pending_cost["values"]["generation"]["cost_plan"]["cost_plan_hash"]
    approved = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond", "response": {
            "schema_version": "lg5-v1", "review_stage": "generation_pending",
            "decision": "approve", "cost_plan_hash": cost_hash,
        }},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["current_stage"] == "provider_wait"
    deliveries = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
    regenerated = [
        row for row in db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
        if row.usage_metadata.get("langgraph_run_id") == run.id
        and row.usage_metadata.get("lg11_source_version_id") == failing_page.id
    ]
    assert len(deliveries) == len(regenerated) == 1
    assert deliveries[0].provider_dispatch_count == 0
    assert regenerated[0].scene_id == "hero"
    assert regenerated[0].usage_metadata["cost_plan_hash"] == cost_hash

    from src.db.database import SessionLocal

    worker_db = SessionLocal()
    try:
        worker_result = run_image_worker_batch(worker_db, owner="lg12-b4-worker", batch_size=10)
    finally:
        worker_db.close()
    assert len(worker_result) == 1 and worker_result[0]["status"] == "completed"
    assert provider_calls == [regenerated[0].job_id]
    # The worker intentionally owns a separate durable DB transaction.
    db_session.expire_all()
    delivery = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).one()
    db_session.refresh(regenerated[0])
    assert delivery.status == "completed" and delivery.provider_dispatch_count == 1
    assert regenerated[0].status == "needs_review" and regenerated[0].output_asset_id
    assert regenerated[0].validation_result["details"]["identity"]["observed_identity"] == {
        "model": "SF-100", "color": "black", "variant": "standard",
    }

    review_state = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert review_state.status_code == 200
    review = review_state.json()
    assert review["current_stage"] == "image_review"
    assert review["values"]["review"]["pending"]["review_stage"] == "image_review"
    reviewed = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond", "response": {
            "schema_version": "lg5-v1", "review_stage": "image_review",
            "decision": "approve", "job_id": regenerated[0].job_id,
        }},
    )
    assert reviewed.status_code == 200, reviewed.text
    db_session.expire_all()
    reviewed_body = reviewed.json()
    reviewed_report_ref = dict(reviewed_body["values"]["quality"].get("quality_report_ref") or {})
    reviewed_report = db_session.get(QualityAssessmentReportVersion, reviewed_report_ref.get("id"))
    reviewed_image = next((item for item in ((reviewed_report.report_json or {}).get("domain_scores") if reviewed_report else []) if item.get("domain_id") == "image_identity_quality"), None)
    reviewed_page_ref = dict(reviewed_body["values"].get("rendering") or {}).get("detail_page_version") or {}
    reviewed_page = db_session.get(DetailPageVersion, reviewed_page_ref.get("id"))
    assert ((reviewed_report.report_json or {}).get("target_artifact") or {}).get("id") == reviewed_page_ref.get("id")
    assert reviewed_body["current_stage"] == "quality_promotion_ready"
    assert reviewed.json()["status"] == "completed"

    final_state = graph.get_state(config)
    quality = dict(final_state.values["quality"])
    child_ref = dict(quality["current_detail_page_ref"])
    child = db_session.get(DetailPageVersion, child_ref["id"])
    child_report = db_session.get(QualityAssessmentReportVersion, quality["quality_report_ref"]["id"])
    assert child is not None and child_report is not None
    assert child.id != failing_page.id
    assert child.sections_json["lg11"]["parent_detail_page_version_id"] == failing_page.id
    assert child.sections_json["lg12_quality_lineage"] == failing_page.sections_json["lg12_quality_lineage"]
    assert child.sections_json["lg10"]["canonical_page_assembly_input"]["planning_refs"] == failing_page.sections_json["lg10"]["canonical_page_assembly_input"]["planning_refs"]
    child_manifest = child.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]
    parent_manifest = failing_page.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]
    assert child_manifest["assets"][0]["asset_id"] == regenerated[0].output_asset_id
    assert parent_manifest["assets"][0]["asset_id"] == evidence_page["asset"].id
    assert child_manifest["assets"][0]["asset_id"] != parent_manifest["assets"][0]["asset_id"]
    assert all((item["status"], item["score"]) == ("complete", 100) for item in child_report.report_json["domain_scores"])
    assert quality["quality_bar_verdict"] == quality["routing_code"] == "PASS"
    assert quality["rework_attempt_count"] == 1
    assert len(quality["attempt_ledger"]) == 1
    ledger = quality["attempt_ledger"][0]
    assert ledger["node_family"] == "scene_reassembly"
    assert ledger["logical_target_ref"]["type"] == "scene"
    assert ledger["logical_target_ref"]["id"] == "hero"
    assert ledger["attempt_count"] == 1 and ledger["last_child_detail_page_ref"] == child_ref

    assert db_session.get(ProductSourceSnapshotVersion, evidence_page["asset_lineage"]["source"].id).canonical_hash == immutable_hashes["source"]
    assert db_session.get(ProductTruthVersion, evidence_page["asset_lineage"]["truth"].id).canonical_hash == immutable_hashes["truth"]
    assert db_session.get(SellerConfirmationVersion, evidence_page["asset_lineage"]["confirmation"].id).canonical_hash == immutable_hashes["confirmation"]
    assert db_session.get(ProductCreativeBriefVersion, evidence_page["asset_lineage"]["brief"].id).output_hash == immutable_hashes["brief"]
    assert db_session.get(CommerceCreativeMasterVersion, evidence_page["asset_lineage"]["master"].id).canonical_hash == immutable_hashes["master"]
    assert lineage["brand_kit"].content_hash == immutable_hashes["brand_kit"]
    assert page_plan["page_plan_ref"]["hash"] == immutable_hashes["page_plan"]
    assert db_session.get(DetailPageVersion, failing_page.id).sections_json["snapshot_hash"] == immutable_hashes["parent_page"]
    assert db_session.get(QualityAssessmentReportVersion, failing_report.id).canonical_hash == immutable_hashes["parent_report"]
    assert failing_bar["canonical_hash"] == immutable_hashes["parent_bar"]

    counts_after = {
        "pages": db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count(),
        "reports": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
    }
    replay = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond", "response": {
            "schema_version": "lg5-v1", "review_stage": "image_review",
            "decision": "approve", "job_id": regenerated[0].job_id,
        }},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["current_stage"] == "quality_promotion_ready"
    assert provider_calls == [regenerated[0].job_id]
    assert {
        "pages": db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count(),
        "reports": db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
    } == counts_after
    if golden_result is not None:
        golden_result.update({
            "run": run,
            "page": child,
            "report": child_report,
            "initial_report": failing_report,
            "initial_quality_bar": failing_bar,
        })


def test_compiled_graph_changes_rework_route_after_child_reqa(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """B-5: child QA, not retained state, chooses COPY then VISUAL then PASS."""

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    original = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=original)
    attach_valid_lg12_layout_evidence(page=original)
    attach_valid_lg12_channel_parity_evidence(page=original, db_session=db_session, tmp_path=tmp_path)

    # Compose two real immutable defects.  The copy fork preserves the wrong
    # frozen Brand Kit, so common child QA must select its newly persisted
    # VISUAL route rather than retaining the parent's COPY route.
    copy_failure = build_copy_spacing_failure_fixture(
        run=lineage["run"], page=original, db_session=db_session,
    )
    visual_failure = build_style_brand_mismatch_failure_fixture(
        run=lineage["run"], page=copy_failure["page"], db_session=db_session,
    )
    parent = visual_failure["page"]
    attach_valid_lg12_copy_evidence(page=parent)
    attach_valid_lg12_layout_evidence(page=parent)
    attach_valid_lg12_channel_parity_evidence(page=parent, db_session=db_session, tmp_path=tmp_path)

    parent_evaluation = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=parent, db_session=db_session,
    )
    parent_bar = aggregate_valid_lg12_quality_bar(
        qa_report=parent_evaluation["qa_report"], db_session=db_session,
    )["quality_bar"]
    assert parent_bar["routing_code"] == "COPY_REWORK"
    assert {item["domain"] for item in parent_bar["rework_targets"]} >= {
        "korean_copy_readability", "layout_typography_brand_flow",
    }

    parent_hash = parent.sections_json["snapshot_hash"]
    monkeypatch.chdir(tmp_path)
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=parent, db_session=db_session,
    )
    checkpoint = invocation["checkpoint"]
    quality = dict(checkpoint.values["quality"])
    final_ref = dict(quality["current_detail_page_ref"])
    final_page = db_session.get(DetailPageVersion, final_ref["id"])
    assert checkpoint.values["current_stage"] == "quality_promotion_ready"
    assert quality["routing_code"] == quality["quality_bar_verdict"] == "PASS"
    assert final_page is not None

    ledger = list(quality["attempt_ledger"])
    assert {
        (item["node_family"], item["attempt_count"], item["status"])
        for item in ledger
    } == {
        ("copy_reassembly", 1, "child_frozen"),
        ("style_reassembly", 1, "child_frozen"),
    }
    copy_child_ref = next(item["last_child_detail_page_ref"] for item in ledger if item["node_family"] == "copy_reassembly")
    copy_child = db_session.get(DetailPageVersion, copy_child_ref["id"])
    assert copy_child is not None
    assert final_page.sections_json["lg11"]["parent_detail_page_version_id"] == copy_child.id
    assert copy_child.sections_json["lg11"]["parent_detail_page_version_id"] == parent.id
    # The first correction remains in v3 while the second executor changes
    # only the selected Canvas element.
    assert copy_child.sections_json["lg11"]["copy_changes"] == {
        copy_failure["section_id"]: {copy_failure["field"]: copy_failure["source_text"] + " "},
    }
    copied_text = [
        item["text"]
        for section in final_page.sections_json["lg10"]["canonical_rendering"]["sections"]
        if section["section_id"] == copy_failure["section_id"]
        for item in section["text_layer"]
        if item["field"] == copy_failure["field"]
    ]
    assert copied_text == [copy_failure["source_text"] + " "]
    assert db_session.get(DetailPageVersion, parent.id).sections_json["snapshot_hash"] == parent_hash


def test_projection_rebuild_preserves_exhausted_retry_budget(
    client, auth_headers, db_session, tmp_path, monkeypatch, golden_result: dict[str, Any] | None = None,
    checkpointer: Any | None = None, verify_public_ledger: bool = True,
):
    """B-5: one hero scene has two real attempts, even as its asset ref changes."""

    from contextlib import contextmanager
    from io import BytesIO

    from langgraph.checkpoint.memory import InMemorySaver
    from src.config import settings
    from src.services import image_generation_worker, langgraph_run_service
    from src.services.image_generation_provider import ImageGenerationResult
    from src.services.image_generation_worker import run_image_worker_batch

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    failing_page = build_image_identity_failure_fixture(
        run=lineage["run"], asset=evidence_page["asset"], job=evidence_page["job"], db_session=db_session,
    )
    for page in (failing_page,):
        attach_valid_lg12_copy_evidence(page=page)
        attach_valid_lg12_layout_evidence(page=page)
        attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)
    initial = evaluate_all_lg12_quality_domains(run=lineage["run"], page=failing_page, db_session=db_session)
    initial_bar = aggregate_valid_lg12_quality_bar(qa_report=initial["qa_report"], db_session=db_session)["quality_bar"]
    assert initial_bar["routing_code"] == "IMAGE_REWORK"

    saver = checkpointer if checkpointer is not None else InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "generated"))
    monkeypatch.chdir(tmp_path)

    provider_calls: list[str] = []

    class MismatchedIdentityFakeProvider:
        """Only the external provider boundary is fake; all graph work is real."""

        def generate(self, request):
            provider_calls.append(request.job_id)
            image = Image.new("RGB", (800, 800), color=(16, 24, 32))
            image.paste((48, 64, 80), (240, 240, 560, 560))
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            return ImageGenerationResult(
                content=buffer.getvalue(), mime_type="image/png",
                provider="deterministic-image-provider", model="lg12-b5-fake-v1",
                usage_metadata={"actual_cost": 0.0, "fake_provider": True},
                observed_identity={"model": "SF-999", "color": "black", "variant": "standard"},
            )

    monkeypatch.setattr(image_generation_worker, "DurableFakeImageProvider", MismatchedIdentityFakeProvider)
    run = lineage["run"]
    run.mode = "mock"
    db_session.add(run)
    db_session.commit()

    invocation = _invoke_compiled_quality_pass_path(
        run=run, page=failing_page, db_session=db_session, checkpointer=saver,
    )
    graph, config = invocation["graph"], invocation["config"]
    first_attempt_target = dict(graph.get_state(config).values["quality"]["active_attempt"]["target_ref"])
    seen_jobs: set[str] = set()

    def approve_one_actual_image_attempt() -> dict[str, Any]:
        # Explicit recovery is the public projection boundary for an
        # interrupted cost node; it must not manufacture provider work.
        recovered = client.post(
            f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
            json={"thread_id": run.id, "mode": "recover"},
        )
        assert recovered.status_code == 200, recovered.text
        recovered_values = dict(recovered.json()["values"])
        pending = dict(recovered_values.get("generation") or {})
        source_page_id = str(dict(recovered_values.get("quality") or {}).get("current_detail_page_ref", {}).get("id") or "")
        cost_hash = str(dict(pending.get("cost_plan") or {}).get("cost_plan_hash") or "")
        assert cost_hash
        approved = client.post(
            f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
            json={"thread_id": run.id, "mode": "respond", "response": {
                "schema_version": "lg5-v1", "review_stage": "generation_pending",
                "decision": "approve", "cost_plan_hash": cost_hash,
            }},
        )
        assert approved.status_code == 200, approved.text
        jobs = [
            row for row in db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
            if row.usage_metadata.get("langgraph_run_id") == run.id and row.job_id not in seen_jobs
            and str(row.usage_metadata.get("lg11_source_version_id") or "") == source_page_id
        ]
        assert len(jobs) == 1
        job = jobs[0]
        seen_jobs.add(job.job_id)
        from src.db.database import SessionLocal
        worker_db = SessionLocal()
        try:
            result = run_image_worker_batch(worker_db, owner=f"lg12-b5-{len(seen_jobs)}", batch_size=10)
        finally:
            worker_db.close()
        assert len(result) == 1 and result[0]["status"] == "completed"
        db_session.expire_all()
        reviewed = client.post(
            f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
            json={"thread_id": run.id, "mode": "respond", "response": {
                "schema_version": "lg5-v1", "review_stage": "image_review",
                "decision": "approve", "job_id": job.job_id,
            }},
        )
        assert reviewed.status_code == 200, reviewed.text
        return reviewed.json()

    # First Quality Bar target is the parent asset.  The completed child has a
    # different asset reference, but its actual frozen manifest still maps it
    # to the same ``hero`` scene logical target.
    first = approve_one_actual_image_attempt()
    assert first["current_stage"] == "generation_pending"
    first_state = graph.get_state(config)
    first_quality = dict(first_state.values["quality"])
    first_ledger = list(first_quality["attempt_ledger"])
    assert len(first_ledger) == 1
    # The child QA has already started the second, still-pending attempt.  It
    # shares the same logical key rather than resetting it for the new asset.
    assert first_ledger[0]["attempt_count"] == 2
    assert first_ledger[0]["status"] == "started"
    assert first_ledger[0]["logical_target_ref"]["type"] == "scene"
    assert first_ledger[0]["logical_target_ref"]["id"] == "hero"
    second_attempt_target = dict(first_quality["active_attempt"]["target_ref"])
    assert first_attempt_target["type"] == second_attempt_target["type"] == "asset"
    assert first_attempt_target["id"] != second_attempt_target["id"]
    assert dict(first_quality["active_attempt"]["logical_target_ref"]) == first_ledger[0]["logical_target_ref"]
    first_child_ref = dict(first_quality["attempt_history"][0]["child_detail_page_ref"])
    first_child = db_session.get(DetailPageVersion, first_child_ref["id"])
    assert first_child is not None and first_child.id != failing_page.id

    second = approve_one_actual_image_attempt()
    # Attempt two creates v3, then real child QA reaches the shared max-2
    # ledger and interrupts seller review instead of creating an attempt three.
    assert second["current_stage"] in {"quality_bar", "quality_review"}
    exhausted = graph.get_state(config)
    assert exhausted.tasks and exhausted.tasks[0].interrupts
    interrupt_payload = dict(exhausted.tasks[0].interrupts[0].value)
    assert interrupt_payload["review_stage"] == "quality_review"
    quality = dict(exhausted.values["quality"])
    ledger = list(quality["attempt_ledger"])
    assert len(ledger) == 1
    assert ledger[0]["attempt_count"] == 2
    assert ledger[0]["logical_target_ref"] == first_ledger[0]["logical_target_ref"]
    assert ledger[0]["last_child_detail_page_ref"] != first_child_ref
    assert quality["rework_attempt_count"] == 2
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count() == 2

    # Simulate a process dying after the seller-review checkpoint but before
    # its SQL projection.  ``recover`` must rebuild this pending interrupt
    # from the checkpoint without executing a third image attempt.
    run.outputs_json = {}
    run.current_stage = "projection_stale"
    run.status = "failed"
    db_session.add(run)
    db_session.commit()

    # Checkpoint recovery and an exhausted replay are read-only: no third
    # cost plan, outbox delivery, provider call, or child can appear.
    counts = {
        "pages": db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count(),
    }
    recovered = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["values"]["review"]["pending"]["review_stage"] == "quality_review"
    recovered_quality = dict(recovered.json()["values"]["quality"])
    if verify_public_ledger:
        assert recovered_quality["attempt_ledger"] == ledger
    replay = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert replay.status_code == 200, replay.text
    assert set(provider_calls) == seen_jobs and len(provider_calls) == 2
    assert {
        "pages": db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count(),
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count(),
    } == counts
    retry_page = db_session.get(DetailPageVersion, ledger[0]["last_child_detail_page_ref"]["id"])
    assert retry_page is not None
    retry_report = next(
        report for report in db_session.query(QualityAssessmentReportVersion).filter_by(project_id=run.project_id).all()
        if str(dict(report.report_json or {}).get("target_artifact", {}).get("id") or "") == retry_page.id
    )
    if golden_result is not None:
        golden_result.update({
            "run": run,
            "page": retry_page,
            "report": retry_report,
            "initial_report": initial["qa_report"],
            "initial_quality_bar": initial_bar,
            "attempt_ledger": ledger,
        })


def test_different_logical_target_keeps_independent_retry_budget(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """B-5: an exhausted hero scene cannot consume a copy field's budget."""

    from src.agents.langgraph_runtime import (
        _lg12_quality_attempt_key,
        _lg12_quality_logical_target_ref,
    )

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    original = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=original)
    attach_valid_lg12_layout_evidence(page=original)
    attach_valid_lg12_channel_parity_evidence(page=original, db_session=db_session, tmp_path=tmp_path)
    failure = build_copy_spacing_failure_fixture(run=lineage["run"], page=original, db_session=db_session)
    copy_page = failure["page"]
    attach_valid_lg12_copy_evidence(page=copy_page)
    attach_valid_lg12_layout_evidence(page=copy_page)
    attach_valid_lg12_channel_parity_evidence(page=copy_page, db_session=db_session, tmp_path=tmp_path)
    copy_bar = aggregate_valid_lg12_quality_bar(
        qa_report=evaluate_all_lg12_quality_domains(run=lineage["run"], page=copy_page, db_session=db_session)["qa_report"],
        db_session=db_session,
    )["quality_bar"]
    assert copy_bar["routing_code"] == "COPY_REWORK"

    # This is a persisted-checkpoint representation of a *different*, already
    # exhausted scene.  The graph still gets its route from the real copy QA/QB
    # result and must create COPY attempt 1, not reject the whole run.
    hero_target = {
        "target_ref": {
            "id": "hero", "version": "frozen-scene-v1",
            "hash": canonical_hash({"fixture": "hero"}), "type": "scene",
        },
    }
    hero_logical = _lg12_quality_logical_target_ref(page=copy_page, target=hero_target)
    exhausted_hero = {
        "attempt_key": _lg12_quality_attempt_key(
            node_family="scene_reassembly", target_ref=hero_logical,
        ),
        "node_family": "scene_reassembly",
        "target_ref": dict(hero_target["target_ref"]),
        "logical_target_ref": hero_logical,
        "attempt_count": 2,
        "last_quality_bar_ref": {"id": "prior-quality-bar", "version": 1, "hash": canonical_hash({"prior": "bar"}), "type": "QualityBarResult"},
        "last_child_detail_page_ref": None,
        "status": "child_frozen",
    }
    monkeypatch.chdir(tmp_path)
    invocation = _invoke_compiled_quality_pass_path(
        run=lineage["run"], page=copy_page, db_session=db_session,
        attempt_ledger=[exhausted_hero],
    )
    quality = dict(invocation["checkpoint"].values["quality"])
    assert invocation["checkpoint"].values["current_stage"] == "quality_promotion_ready"
    rows = {item["node_family"]: item for item in quality["attempt_ledger"]}
    assert rows["scene_reassembly"]["attempt_count"] == 2
    assert rows["copy_reassembly"]["attempt_count"] == 1
    assert quality["rework_attempt_count"] == 3


def test_recovery_after_attempt_persist_is_exactly_once(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """C-A: recover the persisted COPY attempt before its executor can run."""

    from src.services import langgraph_run_service
    from src.services.langgraph_run_service import GraphRunExecutionFailed, LangGraphRunService

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    parent = evidence["page"]
    attach_valid_lg12_copy_evidence(page=parent)
    attach_valid_lg12_layout_evidence(page=parent)
    attach_valid_lg12_channel_parity_evidence(page=parent, db_session=db_session, tmp_path=tmp_path)
    failing = build_copy_spacing_failure_fixture(run=lineage["run"], page=parent, db_session=db_session)["page"]
    attach_valid_lg12_copy_evidence(page=failing)
    attach_valid_lg12_layout_evidence(page=failing)
    attach_valid_lg12_channel_parity_evidence(page=failing, db_session=db_session, tmp_path=tmp_path)
    assert aggregate_valid_lg12_quality_bar(
        qa_report=evaluate_all_lg12_quality_domains(run=lineage["run"], page=failing, db_session=db_session)["qa_report"],
        db_session=db_session,
    )["quality_bar"]["routing_code"] == "COPY_REWORK"

    run = lineage["run"]
    run.mode = "mock"
    db_session.add(run)
    db_session.commit()
    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    monkeypatch.chdir(tmp_path)
    _seed_compiled_quality_graph(run=run, page=failing, db_session=db_session, checkpointer=saver)

    before = _quality_crash_counts(db_session=db_session, run=run)
    monkeypatch.setenv("LG12_TEST_FAILPOINT_AFTER_ATTEMPT_PERSIST", "1")
    with pytest.raises(GraphRunExecutionFailed):
        LangGraphRunService._execute(run, db_session, initial_state=None, rebuild_projection=False)
    monkeypatch.delenv("LG12_TEST_FAILPOINT_AFTER_ATTEMPT_PERSIST")
    db_session.refresh(run)
    assert run.status == "failed"
    assert _quality_crash_counts(db_session=db_session, run=run) == before

    recovered = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert recovered.status_code == 200, recovered.text
    recovered_quality = dict(recovered.json()["values"]["quality"])
    assert recovered_quality["attempt_ledger"][0]["attempt_count"] == 1
    assert recovered_quality["attempt_ledger"][0]["status"] == "started"
    assert _quality_crash_counts(db_session=db_session, run=run) == before

    # Recovery is projection-only even when repeated.  A new service/session
    # then continues the already-checkpointed business node exactly once.
    replay = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert replay.status_code == 200, replay.text
    assert dict(replay.json()["values"]["quality"])["attempt_ledger"] == recovered_quality["attempt_ledger"]
    assert _quality_crash_counts(db_session=db_session, run=run) == before

    from src.db.database import SessionLocal

    resumed_db = SessionLocal()
    try:
        resumed_run = resumed_db.get(AgentRun, run.id)
        assert resumed_run is not None
        LangGraphRunService._execute(resumed_run, resumed_db, initial_state=None, rebuild_projection=True)
    finally:
        resumed_db.close()
    db_session.expire_all()
    final = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert final.status_code == 200
    assert final.json()["current_stage"] == "quality_promotion_ready"
    final_quality = dict(final.json()["values"]["quality"])
    assert final_quality["attempt_ledger"][0]["attempt_count"] == 1
    assert final_quality["attempt_ledger"][0]["status"] == "child_frozen"
    assert _quality_crash_counts(db_session=db_session, run=run)["children"] == before["children"] + 1
    assert _quality_crash_counts(db_session=db_session, run=run)["reports"] == before["reports"] + 1


def test_recovery_after_provider_result_is_exactly_once(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """C-B: reuse one durable IMAGE result and freeze exactly one child."""

    from io import BytesIO

    from src.config import settings
    from src.services import image_generation_worker, langgraph_run_service
    from src.services.image_generation_provider import ImageGenerationResult
    from src.services.image_generation_worker import run_image_worker_batch
    from src.services.langgraph_run_service import LangGraphRunService

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    failing = build_image_identity_failure_fixture(
        run=lineage["run"], asset=evidence["asset"], job=evidence["job"], db_session=db_session,
    )
    attach_valid_lg12_copy_evidence(page=failing)
    attach_valid_lg12_layout_evidence(page=failing)
    attach_valid_lg12_channel_parity_evidence(page=failing, db_session=db_session, tmp_path=tmp_path)
    assert aggregate_valid_lg12_quality_bar(
        qa_report=evaluate_all_lg12_quality_domains(run=lineage["run"], page=failing, db_session=db_session)["qa_report"],
        db_session=db_session,
    )["quality_bar"]["routing_code"] == "IMAGE_REWORK"

    run = lineage["run"]
    run.mode = "mock"
    db_session.add(run)
    db_session.commit()
    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "generated"))
    monkeypatch.chdir(tmp_path)
    provider_calls: list[str] = []

    class ExpectedIdentityFakeProvider:
        def generate(self, request):
            provider_calls.append(request.job_id)
            image = Image.new("RGB", (800, 800), color=(16, 24, 32))
            image.paste((48, 64, 80), (240, 240, 560, 560))
            body = BytesIO()
            image.save(body, format="PNG")
            return ImageGenerationResult(
                content=body.getvalue(), mime_type="image/png",
                provider="deterministic-image-provider", model="lg12-c-crash-b",
                usage_metadata={"actual_cost": 0.0, "fake_provider": True},
                observed_identity={"model": "SF-100", "color": "black", "variant": "standard"},
            )

    monkeypatch.setattr(image_generation_worker, "DurableFakeImageProvider", ExpectedIdentityFakeProvider)
    invocation = _invoke_compiled_quality_pass_path(
        run=run, page=failing, db_session=db_session, checkpointer=saver,
    )
    assert invocation["graph"].get_state(invocation["config"]).tasks
    initial_recover = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert initial_recover.status_code == 200, initial_recover.text
    cost_hash = str(initial_recover.json()["values"]["generation"]["cost_plan"]["cost_plan_hash"])
    approved = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond", "response": {
            "schema_version": "lg5-v1", "review_stage": "generation_pending",
            "decision": "approve", "cost_plan_hash": cost_hash,
        }},
    )
    assert approved.status_code == 200, approved.text
    job = next(
        row for row in db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
        if row.usage_metadata.get("langgraph_run_id") == run.id
        and str(row.usage_metadata.get("lg11_source_version_id") or "") == failing.id
    )
    rework_job_ids = lambda: {
        row.job_id
        for row in db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
        if row.usage_metadata.get("langgraph_run_id") == run.id
        and str(row.usage_metadata.get("lg11_source_version_id") or "") == failing.id
    }
    before_worker = _quality_crash_counts(db_session=db_session, run=run)
    assert rework_job_ids() == {job.job_id}

    # The worker persists the outbox result/job first. The explicit image
    # review below then reaches the child-fork boundary and crashes.
    from src.db.database import SessionLocal

    worker_db = SessionLocal()
    try:
        worker_result = run_image_worker_batch(worker_db, owner="lg12-c-crash-b", batch_size=10)
    finally:
        worker_db.close()
    assert len(worker_result) == 1 and worker_result[0]["status"] == "completed"
    db_session.expire_all()
    assert provider_calls == [job.job_id]
    assert _quality_crash_counts(db_session=db_session, run=run) == before_worker

    pending_review = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert pending_review.status_code == 200
    assert pending_review.json()["values"]["review"]["pending"]["review_stage"] == "image_review"
    monkeypatch.setenv("LG12_TEST_FAILPOINT_AFTER_PROVIDER_RESULT", "1")
    crashed_review = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond", "response": {
            "schema_version": "lg5-v1", "review_stage": "image_review",
            "decision": "approve", "job_id": job.job_id,
        }},
    )
    monkeypatch.delenv("LG12_TEST_FAILPOINT_AFTER_PROVIDER_RESULT")
    assert crashed_review.status_code == 500, crashed_review.text
    db_session.refresh(run)
    assert run.status == "failed"
    assert _quality_crash_counts(db_session=db_session, run=run) == before_worker

    recovered = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert recovered.status_code == 200, recovered.text
    assert _quality_crash_counts(db_session=db_session, run=run) == before_worker

    # A new DB session re-enters the existing image-review interrupt; it does
    # not redispatch the persisted job/outbox/provider result.
    resumed_db = SessionLocal()
    try:
        resumed_run = resumed_db.get(AgentRun, run.id)
        assert resumed_run is not None
        LangGraphRunService._execute(resumed_run, resumed_db, initial_state=None, rebuild_projection=True)
    finally:
        resumed_db.close()
    db_session.expire_all()
    review = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert review.status_code == 200
    assert review.json()["values"]["review"]["pending"]["review_stage"] == "image_review"
    reviewed = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond", "response": {
            "schema_version": "lg5-v1", "review_stage": "image_review",
            "decision": "approve", "job_id": job.job_id,
        }},
    )
    assert reviewed.status_code == 200, reviewed.text
    final_counts = _quality_crash_counts(db_session=db_session, run=run)
    assert final_counts["outbox"] == before_worker["outbox"] == 1
    assert rework_job_ids() == {job.job_id}
    assert final_counts["children"] == before_worker["children"] + 1
    assert provider_calls == [job.job_id]

    replay = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "respond", "response": {
            "schema_version": "lg5-v1", "review_stage": "image_review",
            "decision": "approve", "job_id": job.job_id,
        }},
    )
    assert replay.status_code == 200, replay.text
    assert _quality_crash_counts(db_session=db_session, run=run) == final_counts


def test_recovery_after_child_persist_reuses_child_and_runs_qa_once(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """C-C: child checkpoint survives a crash before its first re-QA node."""

    from src.services import langgraph_run_service
    from src.services.langgraph_run_service import GraphRunExecutionFailed, LangGraphRunService

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    parent = evidence["page"]
    attach_valid_lg12_copy_evidence(page=parent)
    attach_valid_lg12_layout_evidence(page=parent)
    attach_valid_lg12_channel_parity_evidence(page=parent, db_session=db_session, tmp_path=tmp_path)
    failing = build_copy_spacing_failure_fixture(run=lineage["run"], page=parent, db_session=db_session)["page"]
    attach_valid_lg12_copy_evidence(page=failing)
    attach_valid_lg12_layout_evidence(page=failing)
    attach_valid_lg12_channel_parity_evidence(page=failing, db_session=db_session, tmp_path=tmp_path)

    run = lineage["run"]
    run.mode = "mock"
    db_session.add(run)
    db_session.commit()
    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    monkeypatch.chdir(tmp_path)
    _seed_compiled_quality_graph(run=run, page=failing, db_session=db_session, checkpointer=saver)
    before = _quality_crash_counts(db_session=db_session, run=run)
    monkeypatch.setenv("LG12_TEST_FAILPOINT_AFTER_CHILD_PERSIST", "1")
    with pytest.raises(GraphRunExecutionFailed):
        LangGraphRunService._execute(run, db_session, initial_state=None, rebuild_projection=False)
    monkeypatch.delenv("LG12_TEST_FAILPOINT_AFTER_CHILD_PERSIST")
    db_session.refresh(run)
    assert run.status == "failed"
    crashed = _quality_crash_counts(db_session=db_session, run=run)
    assert crashed["children"] == before["children"] + 1
    assert crashed["reports"] == before["reports"] + 1  # parent QA only

    recovered = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert recovered.status_code == 200, recovered.text
    recovered_quality = dict(recovered.json()["values"]["quality"])
    child_ref = dict(recovered_quality["current_detail_page_ref"])
    assert _quality_crash_counts(db_session=db_session, run=run) == crashed
    assert client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    ).status_code == 200
    assert _quality_crash_counts(db_session=db_session, run=run) == crashed

    from src.db.database import SessionLocal

    resumed_db = SessionLocal()
    try:
        resumed_run = resumed_db.get(AgentRun, run.id)
        assert resumed_run is not None
        LangGraphRunService._execute(resumed_run, resumed_db, initial_state=None, rebuild_projection=True)
    finally:
        resumed_db.close()
    db_session.expire_all()
    final = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert final.status_code == 200
    assert final.json()["current_stage"] == "quality_promotion_ready"
    final_quality = dict(final.json()["values"]["quality"])
    assert final_quality["current_detail_page_ref"] == child_ref
    assert final_quality["attempt_ledger"][0]["status"] == "child_frozen"
    final_counts = _quality_crash_counts(db_session=db_session, run=run)
    assert final_counts["children"] == crashed["children"]
    assert final_counts["reports"] == crashed["reports"] + 1


def test_recovery_after_quality_bar_persist_reuses_route_once(
    client, auth_headers, db_session, tmp_path, monkeypatch,
):
    """C-D: child COPY QA/QB persists VISUAL route before its executor starts."""

    from src.services import langgraph_run_service
    from src.services.langgraph_run_service import GraphRunExecutionFailed, LangGraphRunService

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    evidence = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    original = evidence["page"]
    attach_valid_lg12_copy_evidence(page=original)
    attach_valid_lg12_layout_evidence(page=original)
    attach_valid_lg12_channel_parity_evidence(page=original, db_session=db_session, tmp_path=tmp_path)
    copy_failure = build_copy_spacing_failure_fixture(run=lineage["run"], page=original, db_session=db_session)
    visual_failure = build_style_brand_mismatch_failure_fixture(
        run=lineage["run"], page=copy_failure["page"], db_session=db_session,
    )
    parent = visual_failure["page"]
    attach_valid_lg12_copy_evidence(page=parent)
    attach_valid_lg12_layout_evidence(page=parent)
    attach_valid_lg12_channel_parity_evidence(page=parent, db_session=db_session, tmp_path=tmp_path)
    assert aggregate_valid_lg12_quality_bar(
        qa_report=evaluate_all_lg12_quality_domains(run=lineage["run"], page=parent, db_session=db_session)["qa_report"],
        db_session=db_session,
    )["quality_bar"]["routing_code"] == "COPY_REWORK"
    parent_hash = parent.sections_json["snapshot_hash"]

    run = lineage["run"]
    run.mode = "mock"
    db_session.add(run)
    db_session.commit()
    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    monkeypatch.chdir(tmp_path)
    _seed_compiled_quality_graph(run=run, page=parent, db_session=db_session, checkpointer=saver)
    before = _quality_crash_counts(db_session=db_session, run=run)
    monkeypatch.setenv("LG12_TEST_FAILPOINT_AFTER_QB_PERSIST", "1")
    with pytest.raises(GraphRunExecutionFailed):
        LangGraphRunService._execute(run, db_session, initial_state=None, rebuild_projection=False)
    monkeypatch.delenv("LG12_TEST_FAILPOINT_AFTER_QB_PERSIST")
    db_session.refresh(run)
    assert run.status == "failed"
    crashed = _quality_crash_counts(db_session=db_session, run=run)
    assert crashed["children"] == before["children"] + 1

    recovered = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert recovered.status_code == 200, recovered.text
    recovered_quality = dict(recovered.json()["values"]["quality"])
    assert recovered_quality["routing_code"] == "VISUAL_REWORK"
    assert _quality_crash_counts(db_session=db_session, run=run) == crashed
    assert client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    ).status_code == 200
    assert _quality_crash_counts(db_session=db_session, run=run) == crashed

    from src.db.database import SessionLocal

    resumed_db = SessionLocal()
    try:
        resumed_run = resumed_db.get(AgentRun, run.id)
        assert resumed_run is not None
        LangGraphRunService._execute(resumed_run, resumed_db, initial_state=None, rebuild_projection=True)
    finally:
        resumed_db.close()
    db_session.expire_all()
    final = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert final.status_code == 200
    assert final.json()["current_stage"] == "quality_promotion_ready"
    quality = dict(final.json()["values"]["quality"])
    assert quality["routing_code"] == "PASS"
    assert {
        (item["node_family"], item["attempt_count"], item["status"])
        for item in quality["attempt_ledger"]
    } == {
        ("copy_reassembly", 1, "child_frozen"),
        ("style_reassembly", 1, "child_frozen"),
    }
    assert _quality_crash_counts(db_session=db_session, run=run)["children"] == crashed["children"] + 1
    assert db_session.get(DetailPageVersion, parent.id).sections_json["snapshot_hash"] == parent_hash


def test_pending_seller_review_recovery_is_idempotent(
    client, auth_headers, db_session, monkeypatch,
):
    """C: rebuild one ordinary QA seller-review interrupt without side effects."""

    from src.services import langgraph_run_service
    from src.services.langgraph_run_service import LangGraphRunService

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    # This frozen page deliberately has no new TASK-12 QA evidence.  The
    # compiled evaluator must fail closed to its normal seller-review
    # interrupt, rather than inventing a score or auto-rework target.
    page = build_valid_lg12_frozen_detail_page(lineage, page_plan, db_session)
    run = lineage["run"]
    run.mode = "mock"
    db_session.add(run)
    db_session.commit()
    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    _seed_compiled_quality_graph(run=run, page=page, db_session=db_session, checkpointer=saver)
    LangGraphRunService._execute(run, db_session, initial_state=None, rebuild_projection=False)
    state = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert state.status_code == 200
    pending = dict(state.json()["values"]["review"]["pending"])
    assert pending["review_stage"] == "quality_review"
    before = _quality_crash_counts(db_session=db_session, run=run)

    # The durable interrupt remains, but all derived SQL/public state is lost.
    run.outputs_json = {}
    run.current_stage = "projection_stale"
    run.status = "failed"
    db_session.add(run)
    db_session.commit()

    first = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    second = client.post(
        f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers,
        json={"thread_id": run.id, "mode": "recover"},
    )
    assert first.status_code == second.status_code == 200
    assert dict(first.json()["values"]["review"]["pending"]) == pending
    assert dict(second.json()["values"]["review"]["pending"]) == pending
    assert _quality_crash_counts(db_session=db_session, run=run) == before
