"""TASK-12.3 deterministic factual/rights/policy domain evaluator."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from src.db.models import Asset, DetailPageVersion
from src.schemas.lg12_quality_report import QualityAssessmentContractError
from src.services.product_intake_version_service import IntakeVersionContractError, canonical_version_hash
from src.services.prompt_intelligence_service import canonical_hash
from src.services.quality_assessment_service import (
    FACTUAL_RIGHTS_POLICY_EVALUATOR_VERSION, _confirmed_fact_supports_claim,
    evaluate_factual_rights_policy_domain,
)
from test_lg12_quality_report_contract import _profile_payload, _report_payload
from test_lg12i_version_contract import (
    _create_master, _ref, _run, _source_truth_confirmation, auth_headers as _headers,
)
from src.services.quality_assessment_service import create_quality_threshold_profile


@pytest.fixture
def auth_headers():
    return _headers.__wrapped__()


def _confirmed_ref(identifier: str, *, value: str = "confirmed", unit: str | None = None, actor: str) -> dict:
    original = _ref(identifier)
    source_ref, evidence_ref = _ref("seller-source:manual:fan"), _ref(f"evidence:{identifier}")
    clarification_ref = _ref(f"clarification:{identifier}", schema_version="lg12i-seller-clarification-v1")
    answer_ref = _ref(f"seller-answer:{identifier}", schema_version="lg12i-seller-answer-v1")
    identity = {
        "original_truth_item_ref": original, "fact_id": identifier, "field_id": identifier,
        "normalized_value": value, "unit": unit, "source_kind": "product_truth_candidate",
        "clarification_ref": clarification_ref, "answer_ref": answer_ref, "seller_actor_id": actor,
        "confirmation_cycle": 1, "source_refs": [source_ref], "evidence_refs": [evidence_ref],
        "selected_observation_ref": None, "conflicting_observation_refs": [], "decision_status": "confirmed",
    }
    digest = canonical_version_hash(identity)
    return {
        **original, "provenance_ref": evidence_ref, "confirmed_fact_id": f"seller-confirmed-fact:{digest[:24]}",
        "fact_id": identifier, "field_id": identifier, "normalized_value": value, "unit": unit,
        "value_structure": {"value": value, "unit": unit}, "source_kind": "product_truth_candidate",
        "original_truth_item_ref": original, "clarification_ref": clarification_ref, "answer_ref": answer_ref,
        "seller_actor_id": actor, "confirmation_cycle": 1, "source_refs": [source_ref],
        "evidence_refs": [evidence_ref], "selected_observation_ref": None, "conflicting_observation_refs": [],
        "provenance_hash": digest, "decision_status": "confirmed",
    }


def _frozen_page(db, run, master, *, sections, assets=()):
    manifest_body = {"schema_version": "lg10-approved-asset-manifest-v1", "assets": list(assets)}
    manifest = {**manifest_body, "manifest_hash": canonical_hash(manifest_body)}
    snapshot_body = {
        "schema_version": "lg10-detail-page-version-v1",
        "lg10": {"canonical_page_assembly_input": {"approved_asset_manifest": manifest, "sections": sections}},
        "lg12_quality_lineage": {
            "schema_version": "lg12-detail-page-quality-lineage-v1",
            "creator_run_id": run.id,
            "source_snapshot_ref": _ref(master.source_snapshot_version_id, master.source_snapshot_version, master.source_snapshot_hash),
            "truth_ref": _ref(master.truth_version_id, master.truth_version, master.truth_version_hash),
            "confirmation_ref": _ref(master.confirmation_version_id, master.confirmation_version, master.confirmation_version_hash),
            "master_ref": _ref(master.id, master.version, master.canonical_hash),
            "approved_asset_manifest_ref": dict(master.approved_asset_manifest_ref_json or {}),
        },
        "commerce_renderer": {"sections": sections}, "sections": sections,
    }
    page = DetailPageVersion(
        project_id=run.project_id, name="LG12 factual frozen fixture", style_key="balanced_sale",
        sections_json={**snapshot_body, "snapshot_hash": canonical_hash(snapshot_body)}, is_final=True,
    )
    db.add(page); db.flush()
    return page, manifest["manifest_hash"]


def _setup(db, client, headers, tmp_path, *, confirmed=("fact:capacity",), rejected=(), unknown=(), sections=None, assets=()):
    run = _run(client, headers, db, tmp_path)
    chain = _source_truth_confirmation(
        db, run, confirmed_fact_ids=confirmed, rejected_fact_ids=rejected, unknown_fact_ids=unknown,
    )
    master = _create_master(db, run, chain=chain)
    sections = sections or [{"section_id": "hero", "title": "confirmed", "copy_ref": {"fact_ids": list(confirmed)}}]
    page, manifest_hash = _frozen_page(db, run, master, sections=sections, assets=assets)
    profile = create_quality_threshold_profile(
        db, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:factual"),
    )
    db.commit()
    return run, master, page, manifest_hash, profile


def _master_with_approved_asset(db, run):
    """Create the one valid final-use chain used by page parity tests."""

    asset = db.query(Asset).filter_by(project_id=run.project_id, usage_status="seller_owned").first()
    assert asset is not None and asset.file_path
    asset_hash = hashlib.sha256(Path(asset.file_path).read_bytes()).hexdigest()
    asset.content_hash = asset_hash
    db.flush()
    source_reference = _ref(
        asset.id, 1, asset_hash,
        schema_version="lg12i-photo-asset-ref-v1", artifact_key="photo_asset",
    )
    source_asset_ref = {**source_reference, "rights_status": "seller_owned"}
    chain = _source_truth_confirmation(
        db, run, source_refs=[source_reference],
        provenance={"source": "seller", "source_asset_refs": [source_asset_ref]},
        rights={"status": "confirmed"},
    )
    usable_asset_ref = {
        "id": asset.id, "version": 1, "hash": asset_hash, "schema_version": "asset-sha256-v1",
    }
    master = _create_master(db, run, chain=chain, usable_asset_refs=[usable_asset_ref])
    return master, {
        "asset_id": asset.id, "asset_content_hash": asset_hash, "rights_status": "seller_owned",
    }


def _replace_frozen_snapshot(page, mutate):
    body = deepcopy(dict(page.sections_json or {}))
    body.pop("snapshot_hash", None)
    mutate(body)
    page.sections_json = {**body, "snapshot_hash": canonical_hash(body)}


def _evaluate(db, run, master, page, manifest_hash, profile):
    return evaluate_factual_rights_policy_domain(
        db, report_payload=_report_payload(run, page, manifest_hash, master, profile),
    )


def test_valid_confirmed_fact_is_deterministic_and_reference_only(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    first = _evaluate(db_session, run, master, page, manifest_hash, profile)
    second = _evaluate(db_session, run, master, page, manifest_hash, profile)
    assert first == second
    assert first["domain"]["evaluator_version"] == FACTUAL_RIGHTS_POLICY_EVALUATOR_VERSION
    assert first["domain"]["findings"] == []
    assert "raw_html" not in repr(first) and "provider_response" not in repr(first)


def test_creative_narrative_without_a_factual_taxonomy_is_not_false_positive(client, db_session, auth_headers, tmp_path):
    # A seller-confirmed fact must not turn every unrelated creative sentence into a claim.
    sections = [{"section_id": "hero", "title": "different", "copy_ref": {"fact_ids": ["fact:capacity"]}}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    assert _evaluate(db_session, run, master, page, digest, profile)["domain"]["findings"] == []


@pytest.mark.parametrize(
    ("fact", "claim", "expected"),
    [
        ({"field_id": "material", "normalized_value": "SUS304"}, {"claim_type": "material", "text": "SUS304 소재"}, True),
        ({"field_id": "brand_name", "normalized_value": "SUS304"}, {"claim_type": "material", "text": "SUS304 소재"}, False),
        ({"field_id": "product_name", "normalized_value": "SUS304"}, {"claim_type": "material", "text": "SUS304 소재"}, False),
        ({"field_id": "color", "normalized_value": "600", "unit": "ml"}, {"claim_type": "numeric", "text": "600ml"}, False),
        ({"field_id": "fact:capacity", "normalized_value": "600", "unit": "ml"}, {"claim_type": "numeric", "text": "600ml"}, True),
        ({"field_id": "certification", "normalized_value": "KC"}, {"claim_type": "certification", "text": "KC 인증"}, True),
        ({"field_id": "brand_name", "normalized_value": "KC"}, {"claim_type": "certification", "text": "KC 인증"}, False),
        ({"field_id": "performance", "normalized_value": "12시간"}, {"claim_type": "performance", "text": "12시간 보온"}, True),
        ({"field_id": "battery_capacity", "normalized_value": "12시간"}, {"claim_type": "performance", "text": "12시간 보온"}, False),
        ({"field_id": "unclassified_source_field", "normalized_value": "SUS304"}, {"claim_type": "material", "text": "SUS304 소재"}, False),
        ({"field_id": "material", "normalized_value": "SUS304", "source_kind": "seller_confirmation"}, {"claim_type": "material", "text": "SUS304 소재"}, True),
        ({"field_id": "capacity", "normalized_value": "600", "unit": "ml", "source_kind": "seller_confirmation"}, {"claim_type": "material", "text": "600ml 소재"}, False),
    ],
)
def test_confirmed_fact_requires_exact_claim_type_compatibility(fact, claim, expected):
    assert _confirmed_fact_supports_claim(fact, claim) is expected


def test_numeric_unit_equivalence_and_mismatch(client, db_session, auth_headers, tmp_path):
    # Use a successor confirmation so the original immutable cycle remains intact.
    from src.services.product_intake_version_service import create_seller_confirmation_version
    run = _run(client, auth_headers, db_session, tmp_path)
    source, truth, initial = _source_truth_confirmation(db_session, run, confirmed_fact_ids=("fact:capacity",))
    confirmation = create_seller_confirmation_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id, created_by=run.created_by,
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash), answers=[{"question_id": "capacity", "answer": "600 ml"}],
        confirmed_fact_refs=[_confirmed_ref("fact:capacity", value="600", unit="ml", actor=run.created_by)],
        rejected_fact_refs=[], unknown_fact_refs=[], rights_confirmations=[],
        parent_confirmation_reference=_ref(initial.id, initial.version, initial.canonical_hash), confirmation_cycle=2,
    )
    # The master must reference this confirmation; create a complete chain with it.
    master = _create_master(db_session, run, chain=(source, truth, confirmation))
    page, digest = _frozen_page(db_session, run, master, sections=[{"section_id": "hero", "title": "0.6 L", "copy_ref": {"fact_ids": ["fact:capacity"]}}])
    profile = create_quality_threshold_profile(db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:numeric"))
    db_session.commit()
    assert _evaluate(db_session, run, master, page, digest, profile)["domain"]["findings"] == []
    changed_page, changed_digest = _frozen_page(db_session, run, master, sections=[{"section_id": "hero", "title": "500 ml", "copy_ref": {"fact_ids": ["fact:capacity"]}}])
    assert "numeric_unit_mismatch" in {item["code"] for item in _evaluate(db_session, run, master, changed_page, changed_digest, profile)["domain"]["findings"]}


def test_mixed_copy_requires_matching_provenance_per_factual_span(client, db_session, auth_headers, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    from src.services.product_intake_version_service import create_seller_confirmation_version
    source, truth, initial = _source_truth_confirmation(
        db_session, run, confirmed_fact_ids=("fact:capacity", "fact:brand_name"),
    )
    confirmation = create_seller_confirmation_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id, created_by=run.created_by,
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash), answers=[{"question_id": "capacity", "answer": "600 ml"}],
        confirmed_fact_refs=[
            _confirmed_ref("fact:capacity", value="600", unit="ml", actor=run.created_by),
            _confirmed_ref("fact:brand_name", value="SUS304", actor=run.created_by),
        ],
        rejected_fact_refs=[], unknown_fact_refs=[], rights_confirmations=[],
        parent_confirmation_reference=_ref(initial.id, initial.version, initial.canonical_hash), confirmation_cycle=2,
    )
    master = _create_master(db_session, run, chain=(source, truth, confirmation))
    profile = create_quality_threshold_profile(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:mixed-claims"),
    )
    cases = {
        "600 ml tumbler": set(),
        "600 ml SUS304 material tumbler": {"unapproved_material_claim"},
        "600 ml, 12시간 보온": {"unapproved_performance_claim"},
    }
    for ordinal, (text, expected) in enumerate(cases.items()):
        page, manifest_hash = _frozen_page(
            db_session, run, master,
            sections=[{
                "section_id": f"hero:{ordinal}", "title": text,
                "copy_ref": {"fact_ids": ["fact:capacity", "fact:brand_name"]},
            }],
        )
        codes = {item["code"] for item in _evaluate(db_session, run, master, page, manifest_hash, profile)["domain"]["findings"]}
        assert expected.issubset(codes)
        if not expected:
            assert not codes


def test_one_confirmed_material_claim_cannot_authorize_a_second_material_claim(client, db_session, auth_headers, tmp_path):
    from src.services.product_intake_version_service import create_seller_confirmation_version

    run = _run(client, auth_headers, db_session, tmp_path)
    source, truth, initial = _source_truth_confirmation(db_session, run, confirmed_fact_ids=("fact:material",))
    confirmation = create_seller_confirmation_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id, created_by=run.created_by,
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash), answers=[{"question_id": "material", "answer": "SUS304"}],
        confirmed_fact_refs=[_confirmed_ref("fact:material", value="SUS304", actor=run.created_by)],
        rejected_fact_refs=[], unknown_fact_refs=[], rights_confirmations=[],
        parent_confirmation_reference=_ref(initial.id, initial.version, initial.canonical_hash), confirmation_cycle=2,
    )
    master = _create_master(db_session, run, chain=(source, truth, confirmation))
    page, manifest_hash = _frozen_page(
        db_session, run, master,
        sections=[{"section_id": "hero", "title": "SUS304 material, BPA Free", "copy_ref": {"fact_ids": ["fact:material"]}}],
    )
    profile = create_quality_threshold_profile(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:material-span"),
    )
    codes = {item["code"] for item in _evaluate(db_session, run, master, page, manifest_hash, profile)["domain"]["findings"]}
    assert "unapproved_material_claim" in codes


@pytest.mark.parametrize("claim,code", [
    ("KC 인증 제품", "unsupported_certification"), ("통증 치료에 효과", "unsupported_medical_health_claim"),
    ("동급 대비 저렴", "unsupported_price_advantage"),
])
def test_unsupported_policy_claims_are_critical(client, db_session, auth_headers, tmp_path, claim, code):
    run, master, page, digest, profile = _setup(
        db_session, client, auth_headers, tmp_path, confirmed=(), sections=[{"section_id": "hero", "title": claim, "copy_ref": {"fact_ids": []}}],
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    finding = next(item for item in result["domain"]["findings"] if item["code"] == code)
    assert finding["severity"] == "critical" and finding["evidence_refs"]
    assert any(item["reason_code"] == code for item in result["critical_violations"])


@pytest.mark.parametrize("source_type,status,rights,expected", [
    ("self_shot", "seller_owned", "seller_owned", False),
    ("self_shot", "seller_owned", "rights_confirmed", False),
    ("self_shot", "seller_owned", "unconfirmed", True),
    ("supplier", "seller_owned", "rights_confirmed", True),
    ("url-imported", "reference_only", "rights_confirmed", True),
    ("competitor", "seller_owned", "rights_confirmed", True),
    ("blocked", "blocked", "rights_confirmed", True),
])
def test_final_asset_rights_and_manifest_parity(client, db_session, auth_headers, tmp_path, source_type, status, rights, expected):
    run = _run(client, auth_headers, db_session, tmp_path)
    path = Path(tmp_path) / f"{source_type}.png"; path.write_bytes(b"frozen-asset")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    asset = Asset(project_id=run.project_id, source_type=source_type, usage_status=status, filename=path.name,
                  file_path=str(path), mime_type="image/png", file_size=path.stat().st_size, content_hash=digest)
    db_session.add(asset); db_session.flush()
    manifest_asset = {"asset_id": asset.id, "asset_content_hash": digest, "rights_status": rights}
    sections = [{"section_id": "hero", "title": "confirmed", "copy_ref": {"fact_ids": ["fact:capacity"]}, "approved_assets": [manifest_asset]}]
    if not expected:
        # The frozen page's asset is anchored to the Master-derived usable
        # asset manifest, rather than merely self-declaring seller ownership.
        master, manifest_asset = _master_with_approved_asset(db_session, run)
    else:
        chain = _source_truth_confirmation(db_session, run)
        master = _create_master(db_session, run, chain=chain)
    sections = [{"section_id": "hero", "title": "confirmed", "copy_ref": {"fact_ids": ["fact:capacity"]}, "approved_assets": [manifest_asset]}]
    page, manifest_hash = _frozen_page(db_session, run, master, sections=sections, assets=[manifest_asset])
    profile = create_quality_threshold_profile(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:asset"),
    )
    db_session.commit()
    result = _evaluate(db_session, run, master, page, manifest_hash, profile)
    codes = {item["code"] for item in result["domain"]["findings"]}
    assert ("asset_missing_master_manifest" in codes) is expected


def test_manifest_missing_target_tamper_and_cross_project_fail_closed(client, db_session, auth_headers, tmp_path):
    sections = [{"section_id": "hero", "title": "confirmed", "copy_ref": {"fact_ids": ["fact:capacity"]}, "approved_assets": [{"asset_id": "missing", "asset_content_hash": "a" * 64}]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    assert "asset_missing_approved_manifest" in {item["code"] for item in _evaluate(db_session, run, master, page, digest, profile)["domain"]["findings"]}
    payload = _report_payload(run, page, digest, master, profile)
    payload["target_artifact"] = {**payload["target_artifact"], "hash": "b" * 64}
    with pytest.raises(QualityAssessmentContractError):
        evaluate_factual_rights_policy_domain(db_session, report_payload=payload)


def test_actual_asset_bytes_and_manifest_reference_mismatches_are_critical(client, db_session, auth_headers, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    master, entry = _master_with_approved_asset(db_session, run)
    asset = db_session.query(Asset).filter_by(id=entry["asset_id"]).one()
    page, manifest_hash = _frozen_page(
        db_session, run, master,
        sections=[{"section_id": "hero", "title": "confirmed", "copy_ref": {"fact_ids": ["fact:capacity"]}, "approved_assets": [entry]}],
        assets=[entry],
    )
    profile = create_quality_threshold_profile(db_session, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:bytes"))
    db_session.commit()
    Path(asset.file_path).write_bytes(b"tampered")
    with pytest.raises(IntakeVersionContractError, match="asset|manifest|hash"):
        _evaluate(db_session, run, master, page, manifest_hash, profile)


def test_page_master_run_and_manifest_injections_fail_closed(client, db_session, auth_headers, tmp_path):
    run, master, page, manifest_hash, profile = _setup(db_session, client, auth_headers, tmp_path)
    for mutate in (
        lambda body: body["lg12_quality_lineage"].update({"creator_run_id": "other-run"}),
        lambda body: body["lg12_quality_lineage"].update({"master_ref": _ref("other-master")}),
        lambda body: body["lg12_quality_lineage"].update({"approved_asset_manifest_ref": _ref("other-manifest")}),
    ):
        _replace_frozen_snapshot(page, mutate)
        with pytest.raises(QualityAssessmentContractError):
            _evaluate(db_session, run, master, page, manifest_hash, profile)
        # Recreate the valid frozen page before the next injection attempt.
        page, manifest_hash = _frozen_page(
            db_session, run, master, sections=[{"section_id": "hero", "title": "confirmed", "copy_ref": {"fact_ids": ["fact:capacity"]}}],
        )
