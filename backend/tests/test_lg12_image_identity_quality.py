"""TASK-12.4 frozen image and product-identity quality evaluator tests."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from src.db.models import Asset, ImageGenerationCostApprovalRecord, ImageGenerationJobRecord, ImageGenerationOutboxRecord
from src.schemas.lg12_quality_report import QualityAssessmentContractError
from src.services.product_intake_version_service import (
    MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION,
    IntakeVersionContractError,
    create_manual_input_artifact,
    create_product_source_snapshot_version,
    create_product_truth_version,
    normalize_product_truth_from_source_snapshot,
)
from src.services.quality_assessment_service import (
    IMAGE_IDENTITY_QUALITY_EVALUATOR_VERSION,
    _expected_product_identity,
    create_quality_threshold_profile,
    evaluate_image_identity_quality_domain,
)
from src.services.product_identity_validator import build_frozen_image_quality_evidence
from src.services.prompt_intelligence_service import canonical_hash
from test_lg12_fact_rights_quality import _confirmed_ref, _frozen_page, _master_with_approved_asset
from test_lg12_quality_report_contract import _profile_payload, _report_payload
from test_lg12i_version_contract import _create_master, _ref, _run, _source_truth_confirmation, auth_headers as _headers
from src.services.product_intake_version_service import create_seller_confirmation_version


@pytest.fixture
def auth_headers():
    return _headers.__wrapped__()


def _write_image(asset: Asset, path: Path, *, size: tuple[int, int] = (800, 800)) -> None:
    Image.new("RGB", size, color=(35, 76, 125)).save(path, format="JPEG")
    asset.file_path = str(path)
    asset.filename = path.name
    asset.file_size = path.stat().st_size
    asset.mime_type = "image/jpeg"


def _freeze_image_evidence(page, asset: Asset, *, job=None, identity_metadata=None) -> str:
    """Fixture-only equivalent of the manifest evidence frozen by LG-9."""

    snapshot = deepcopy(dict(page.sections_json or {})); snapshot.pop("snapshot_hash", None)
    canonical = dict(dict(snapshot["lg10"])["canonical_page_assembly_input"])
    manifest = deepcopy(dict(canonical["approved_asset_manifest"]))
    entry = next(item for item in manifest["assets"] if str(item["asset_id"]) == str(asset.id))
    evidence = build_frozen_image_quality_evidence(asset=asset, job=job)
    if identity_metadata is not None:
        evidence["metadata"]["identity_metadata"] = dict(identity_metadata)
        body = deepcopy(evidence); body.pop("evidence_hash", None)
        evidence["evidence_hash"] = canonical_hash(body)
    entry["lg12_frozen_image_evidence"] = evidence
    manifest_body = deepcopy(manifest); manifest_body.pop("manifest_hash", None)
    manifest["manifest_hash"] = canonical_hash(manifest_body)
    canonical["approved_asset_manifest"] = manifest
    snapshot["lg10"]["canonical_page_assembly_input"] = canonical
    page.sections_json = {**snapshot, "snapshot_hash": canonical_hash(snapshot)}
    return manifest["manifest_hash"]


def _setup(db, client, headers, tmp_path, *, size=(800, 800), warnings=(), identity_status="confirmed", preserved=True):
    run = _run(client, headers, db, tmp_path)
    asset = db.query(Asset).filter_by(project_id=run.project_id, usage_status="seller_owned").first()
    assert asset is not None
    _write_image(asset, tmp_path / "frozen-approved.jpg", size=size)
    asset.identity_status = identity_status
    asset.product_identity_preserved = preserved
    asset.quality_warnings = list(warnings)
    db.flush()
    master, manifest_asset = _master_with_approved_asset(db, run)
    page, manifest_hash = _frozen_page(
        db, run, master,
        sections=[{"section_id": "hero", "assets": [manifest_asset]}], assets=[manifest_asset],
    )
    manifest_hash = _freeze_image_evidence(page, asset)
    profile = create_quality_threshold_profile(
        db, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:image-quality"),
    )
    db.commit()
    return run, master, page, manifest_hash, profile, asset


def _evaluate(db, run, master, page, manifest_hash, profile):
    # Domain hashes are report-bound; repeated evaluator reads must therefore
    # use one deterministic report identity for the same frozen fixture.
    report_id = "image-quality-eval:" + canonical_hash({
        "run_id": run.id,
        "page_id": page.id,
        "page_hash": page.sections_json["snapshot_hash"],
        "profile_hash": profile.canonical_hash,
    })[:24]
    return evaluate_image_identity_quality_domain(
        db, report_payload=_report_payload(
            run, page, manifest_hash, master, profile, report_id=report_id,
        ),
    )


def _identity_target(db, client, headers, tmp_path, *, expected_color: str, observed_color: str):
    """Build a frozen target with seller-confirmed color and frozen page evidence."""

    run = _run(client, headers, db, tmp_path)
    asset = db.query(Asset).filter_by(project_id=run.project_id, usage_status="seller_owned").first()
    assert asset is not None
    _write_image(asset, tmp_path / "identity-approved.jpg")
    db.flush()
    asset_hash = hashlib.sha256(Path(asset.file_path).read_bytes()).hexdigest()
    asset.content_hash = asset_hash
    source_ref = _ref(asset.id, 1, asset_hash, schema_version="lg12i-photo-asset-ref-v1", artifact_key="photo_asset")
    source, truth, initial = _source_truth_confirmation(
        db, run, confirmed_fact_ids=("color",), source_refs=[source_ref],
        provenance={"source": "seller", "source_asset_refs": [{**source_ref, "rights_status": "seller_owned"}]},
        rights={"status": "confirmed"},
    )
    confirmation = create_seller_confirmation_version(
        db, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id, created_by=run.created_by,
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash), answers=[{"question_id": "color", "answer": expected_color}],
        confirmed_fact_refs=[_confirmed_ref("color", value=expected_color, actor=run.created_by)],
        rejected_fact_refs=[], unknown_fact_refs=[], rights_confirmations=[],
        parent_confirmation_reference=_ref(initial.id, initial.version, initial.canonical_hash), confirmation_cycle=2,
    )
    master = _create_master(db, run, chain=(source, truth, confirmation), usable_asset_refs=[
        {"id": asset.id, "version": 1, "hash": asset_hash, "schema_version": "asset-sha256-v1"},
    ])
    manifest_asset = {"asset_id": asset.id, "asset_content_hash": asset_hash, "rights_status": "seller_owned"}
    page, _ = _frozen_page(db, run, master, sections=[{"section_id": "hero", "assets": [manifest_asset]}], assets=[manifest_asset])
    digest = _freeze_image_evidence(page, asset, identity_metadata={"color": observed_color})
    profile = create_quality_threshold_profile(db, workspace_id=run.workspace_id, project_id=run.project_id, payload=_profile_payload("profile:direct-identity"))
    db.commit()
    return run, master, page, digest, profile


def _source_backed_identity_target(
    db, client, headers, tmp_path, *, field_id: str, truth_value: str,
    observed_identity: dict[str, str], include_provenance: bool = True,
    confirmed_value: str | None = None,
    candidate_mutation=None,
):
    """Freeze a page whose identity baseline is a Truth observation, not a claim approval."""

    run = _run(client, headers, db, tmp_path)
    asset = db.query(Asset).filter_by(project_id=run.project_id, usage_status="seller_owned").first()
    assert asset is not None
    _write_image(asset, tmp_path / f"source-backed-{field_id}.jpg")
    db.flush()
    asset_hash = hashlib.sha256(Path(asset.file_path).read_bytes()).hexdigest()
    asset.content_hash = asset_hash
    fields = [{
        "field_id": field_id, "classification": "fact_candidate",
        "label": field_id, "value": truth_value,
    }]
    if field_id not in {"product_identity", "product_name", "model_name", "title"}:
        fields.append({
            "field_id": "product_identity", "classification": "fact_candidate",
            "label": "product identity", "value": "fixture-product",
        })
        observed_identity = {"product_identity": "fixture-product", **observed_identity}
    metadata = {
        "manual_payload_schema_version": MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION,
        "seller_entered_fields": fields,
        "unknown_fact_field_ids": [], "rights_confirmation_state": "confirmed",
    }
    artifact = create_manual_input_artifact(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        created_by=run.created_by, raw_body="bounded manual identity fixture", source_metadata=metadata,
    )
    artifact_ref = {
        "id": artifact.id, "version": artifact.version, "hash": artifact.content_hash,
        "schema_version": MANUAL_INPUT_ARTIFACT_SCHEMA_VERSION, "artifact_key": "manual_product_input",
    }
    source_asset_ref = _ref(
        asset.id, 1, asset_hash, schema_version="lg12i-photo-asset-ref-v1", artifact_key="photo_asset",
    )
    source = create_product_source_snapshot_version(
        db, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        created_by=run.created_by, input_mode="manual", source_refs=[artifact_ref],
        provenance={
            "source": "seller_entered", "manual_artifact_ref": artifact_ref,
            "source_asset_refs": [{**source_asset_ref, "rights_status": "seller_owned"}],
        }, rights={"confirmation_state": "confirmed", "final_use_status": "not_approved"},
        source_fidelity={"source_kind": "manual_artifact"},
    )
    source_ref = _ref(source.id, source.version, source.canonical_hash)
    normalized = normalize_product_truth_from_source_snapshot(db, run=run, source_reference=source_ref)
    from src.db.models import ProductTruthVersion
    truth = db.query(ProductTruthVersion).filter_by(id=normalized["truth_version"]["id"]).one()
    if not include_provenance or candidate_mutation is not None:
        normalization = deepcopy(dict(truth.normalization_json))
        candidate = dict(next(item for item in normalization["fact_candidates"] if item["field_id"] == field_id))
        if not include_provenance:
            candidate["observation_refs"] = []
        if candidate_mutation is not None:
            candidate_mutation(candidate)
        normalization["fact_candidates"] = [
            candidate if item["field_id"] == field_id else item
            for item in normalization["fact_candidates"]
        ]
        truth = create_product_truth_version(
            db, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
            created_by=run.created_by, source_reference=_ref(source.id, source.version, source.canonical_hash),
            fact_refs=[candidate["reference"]], evidence_refs=list(truth.evidence_refs_json), normalization=normalization,
        )
    confirmation = create_seller_confirmation_version(
        db, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        created_by=run.created_by, truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        answers=[],
        confirmed_fact_refs=(
            [_confirmed_ref(field_id, value=confirmed_value, actor=run.created_by)]
            if confirmed_value is not None else []
        ),
        rejected_fact_refs=[], unknown_fact_refs=[], rights_confirmations=[],
    )
    master = _create_master(db, run, chain=(source, truth, confirmation), usable_asset_refs=[
        {"id": asset.id, "version": 1, "hash": asset_hash, "schema_version": "asset-sha256-v1"},
    ])
    manifest_asset = {"asset_id": asset.id, "asset_content_hash": asset_hash, "rights_status": "seller_owned"}
    page, _ = _frozen_page(db, run, master, sections=[{"section_id": "hero", "assets": [manifest_asset]}], assets=[manifest_asset])
    digest = _freeze_image_evidence(page, asset, identity_metadata=observed_identity)
    profile = create_quality_threshold_profile(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        payload=_profile_payload(f"profile:source-backed-{field_id}"),
    )
    db.commit()
    return run, master, page, digest, profile


def test_valid_frozen_asset_is_deterministic_and_reference_only(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile, _asset = _setup(db_session, client, auth_headers, tmp_path)
    before = (
        db_session.query(ImageGenerationJobRecord).count(),
        db_session.query(ImageGenerationOutboxRecord).count(),
        db_session.query(ImageGenerationCostApprovalRecord).count(),
    )
    first = _evaluate(db_session, run, master, page, digest, profile)
    second = _evaluate(db_session, run, master, page, digest, profile)
    assert first == second
    assert first["domain"]["evaluator_version"] == IMAGE_IDENTITY_QUALITY_EVALUATOR_VERSION
    assert first["domain"]["findings"] == []
    assert {metric["metric_id"] for metric in first["domain"]["submetrics"]} == {
        "asset_integrity", "identity_consistency", "visibility_crop", "resolution",
    }
    assert "image_bytes" not in repr(first) and "base64" not in repr(first)
    assert (
        db_session.query(ImageGenerationJobRecord).count(),
        db_session.query(ImageGenerationOutboxRecord).count(),
        db_session.query(ImageGenerationCostApprovalRecord).count(),
    ) == before


def test_frozen_image_evidence_ignores_later_mutable_asset_and_job_metadata(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile, asset = _setup(db_session, client, auth_headers, tmp_path)
    frozen_result = _evaluate(db_session, run, master, page, digest, profile)
    # These fields belong to later mutable classification/review state.  They
    # must not rewrite the interpretation of the already frozen page.
    asset.identity_status = "blocked"
    asset.product_identity_preserved = False
    asset.quality_warnings = ["COLOR_MISMATCH", "WATERMARK"]
    db_session.add(ImageGenerationJobRecord(
        project_id=run.project_id, job_id="later-unbound-lg9-job", section_id="hero", role="product",
        prompt="later job", status="approved", output_asset_id=asset.id,
        validation_result={"status": "needs_review", "risk_codes": ["watermark"]},
    ))
    db_session.commit()
    assert _evaluate(db_session, run, master, page, digest, profile) == frozen_result


def test_no_expected_identity_does_not_trigger_a_pixel_guess(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile, asset = _setup(db_session, client, auth_headers, tmp_path)
    # Freeze an exact LG-9 job without observed visual identity metadata.  A
    # direct expected identity is deliberately not invented from pixels.
    job = ImageGenerationJobRecord(
        project_id=run.project_id, job_id="frozen-metadata-empty", section_id="hero", role="product",
        prompt="frozen", status="approved", output_asset_id=asset.id,
        validation_result={"status": "approved", "details": {"identity": {"status": "approved", "checks": []}}},
    )
    db_session.add(job); db_session.flush()
    digest = _freeze_image_evidence(page, asset, job=job)
    db_session.commit()
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["findings"] == []


def test_direct_seller_confirmed_color_identity_comparison_uses_frozen_page_evidence(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _identity_target(
        db_session, client, auth_headers, tmp_path, expected_color="black", observed_color="white",
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    color_findings = [item for item in result["domain"]["findings"] if item["code"] == "product_color_mismatch"]
    assert len(color_findings) == 1
    assert color_findings[0]["expected"] == "black"
    assert color_findings[0]["observed"] == "white"


def test_matching_seller_corrected_color_identity_passes_without_warning_duplicate(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _identity_target(
        db_session, client, auth_headers, tmp_path, expected_color="white", observed_color="white",
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "product_color_mismatch" not in {item["code"] for item in result["domain"]["findings"]}


def test_missing_frozen_identity_metadata_is_needs_review_when_truth_has_identity(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _identity_target(
        db_session, client, auth_headers, tmp_path, expected_color="black", observed_color="",
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "identity_metadata_not_evaluable" in {item["code"] for item in result["domain"]["findings"]}
    assert result["domain"]["status"] == "needs_review"
    identity_metric = next(item for item in result["domain"]["submetrics"] if item["metric_id"] == "identity_consistency")
    assert identity_metric["status"] == "needs_review"


@pytest.mark.parametrize(
    ("field_id", "truth_value", "observed_identity", "expected_code"),
    [
        ("color", "black", {"color": "white"}, "product_color_mismatch"),
        ("variant", "A", {"variant": "B"}, "product_variant_mismatch"),
        ("model_name", "A100", {"model": "B200"}, "product_model_identity_mismatch"),
    ],
)
def test_source_backed_truth_candidate_is_direct_identity_evidence(
    client, db_session, auth_headers, tmp_path, field_id, truth_value, observed_identity, expected_code,
):
    run, master, page, digest, profile = _source_backed_identity_target(
        db_session, client, auth_headers, tmp_path, field_id=field_id,
        truth_value=truth_value, observed_identity=observed_identity,
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    finding = next(item for item in result["domain"]["findings"] if item["code"] == expected_code)
    assert finding["expected"] == " ".join(truth_value.lower().split())
    assert finding["observed"] == " ".join(next(iter(observed_identity.values())).lower().split())


def test_source_backed_truth_candidate_matching_frozen_identity_is_complete(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _source_backed_identity_target(
        db_session, client, auth_headers, tmp_path, field_id="color",
        truth_value="black", observed_identity={"color": "black"},
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "complete", result["domain"]["findings"]
    assert "product_color_mismatch" not in {item["code"] for item in result["domain"]["findings"]}


@pytest.mark.parametrize("field_id", ["variant", "model_name"])
def test_missing_required_variant_or_model_metadata_needs_review(client, db_session, auth_headers, tmp_path, field_id):
    run, master, page, digest, profile = _source_backed_identity_target(
        db_session, client, auth_headers, tmp_path, field_id=field_id,
        truth_value="A" if field_id == "variant" else "A100", observed_identity={},
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "identity_metadata_not_evaluable" in {item["code"] for item in result["domain"]["findings"]}
    assert result["domain"]["status"] == "needs_review"


def test_seller_confirmed_identity_overrides_source_backed_candidate(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _identity_target(
        db_session, client, auth_headers, tmp_path, expected_color="white", observed_color="white",
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "complete"
    assert "product_color_mismatch" not in {item["code"] for item in result["domain"]["findings"]}


def test_unprovenanced_truth_identity_candidate_is_not_evaluable(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _source_backed_identity_target(
        db_session, client, auth_headers, tmp_path, field_id="color",
        truth_value="black", observed_identity={"color": "white"}, include_provenance=False,
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    codes = {item["code"] for item in result["domain"]["findings"]}
    assert "identity_source_provenance_not_evaluable" in codes
    assert "product_color_mismatch" not in codes
    assert result["domain"]["status"] == "needs_review"


@pytest.mark.parametrize(
    ("case", "mutate"),
    [
        ("source_hash", lambda item: item["source_refs"][0].update(hash="0" * 64)),
        ("source_version", lambda item: item["source_refs"][0].update(version=2)),
        ("other_source_observation", lambda item: item["observation_refs"][0].update(id="observation:other-source", hash="1" * 64)),
        ("other_project_evidence", lambda item: item["evidence_refs"][0].update(id="artifact:other-project", hash="2" * 64)),
        ("wrong_reference_type", lambda item: item["source_refs"][0].update(schema_version="unrelated-artifact-v1")),
    ],
)
def test_candidate_identity_requires_exact_persisted_source_observation_and_evidence(
    client, db_session, auth_headers, tmp_path, case, mutate,
):
    run, master, page, digest, profile = _source_backed_identity_target(
        db_session, client, auth_headers, tmp_path, field_id="color", truth_value="black",
        observed_identity={"color": "white"}, candidate_mutation=mutate,
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    codes = {item["code"] for item in result["domain"]["findings"]}
    assert "identity_source_provenance_not_evaluable" in codes, case
    assert "product_color_mismatch" not in codes, case
    assert result["domain"]["status"] == "needs_review"


def _identity_state_target(
    db, client, headers, tmp_path, *, field_id: str, state: str,
    confirmed_value: str | None = None, rejected: bool = False, build_master: bool = True,
):
    """Build a frozen page with an explicit non-commercial Truth state."""

    run = _run(client, headers, db, tmp_path)
    source, _old_truth, _old_confirmation = _source_truth_confirmation(
        db, run, confirmed_fact_ids=(), source_refs=[_ref("seller-source:manual:identity")],
    )
    truth_item = {
        "fact_id": field_id, "field_id": field_id, "field_type": "source_observation",
        "value": None, "state": state, "approval_status": "not_approved",
        "reference": _ref(field_id), "source_refs": [_ref("seller-source:manual:identity")],
        "observation_refs": [_ref(f"observation:{field_id}")], "evidence_refs": [_ref("seller-source:manual:identity")],
    }
    if state == "conflict":
        truth_item.update({"resolution_status": "unresolved", "conflicting_observations": [{"value": "A"}, {"value": "B"}]})
    if state == "prohibited_inference":
        truth_item.update({"inference_type": "price_advantage", "status": "prohibited_not_approved"})
    normalization = {
        "schema_version": "lg12i-product-truth-normalization-v1", "fact_candidates": [],
        "unknown_facts": [truth_item] if state == "unknown" else [],
        "conflict_facts": [truth_item] if state == "conflict" else [],
        "prohibited_inferences": [truth_item] if state == "prohibited_inference" else [],
        "observation_risks": [],
    }
    truth = create_product_truth_version(
        db, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        created_by=run.created_by, source_reference=_ref(source.id, source.version, source.canonical_hash),
        fact_refs=[], evidence_refs=[_ref("evidence:source")],
        unknown_refs=[truth_item["reference"]] if state == "unknown" else [],
        conflict_refs=[truth_item["reference"]] if state == "conflict" else [],
        prohibited_inference_refs=[truth_item["reference"]] if state == "prohibited_inference" else [],
        normalization=normalization,
    )
    confirmation = create_seller_confirmation_version(
        db, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        created_by=run.created_by, truth_reference=_ref(truth.id, truth.version, truth.canonical_hash), answers=[],
        confirmed_fact_refs=[_confirmed_ref(field_id, value=confirmed_value, actor=run.created_by)] if confirmed_value else [],
        rejected_fact_refs=[
            {**_ref(field_id), "provenance_ref": _ref(f"evidence:{field_id}")}
        ] if rejected else [],
        unknown_fact_refs=[], rights_confirmations=[],
    )
    if not build_master:
        db.commit()
        return run, source, truth, confirmation
    master = _create_master(db, run, chain=(source, truth, confirmation))
    page, digest = _frozen_page(db, run, master, sections=[{"section_id": "hero", "assets": []}], assets=[])
    profile = create_quality_threshold_profile(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        payload=_profile_payload(f"profile:identity-state-{field_id}-{state}"),
    )
    db.commit()
    return run, master, page, digest, profile


@pytest.mark.parametrize(("field_id", "state"), [("color", "unknown"), ("variant", "conflict")])
def test_unresolved_identity_truth_state_never_completes_domain(
    client, db_session, auth_headers, tmp_path, field_id, state,
):
    run, master, page, digest, profile = _identity_state_target(
        db_session, client, auth_headers, tmp_path, field_id=field_id, state=state,
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "identity_state_not_evaluable" in {item["code"] for item in result["domain"]["findings"]}
    assert result["domain"]["status"] == "needs_review"
    metric = next(item for item in result["domain"]["submetrics"] if item["metric_id"] == "identity_consistency")
    assert metric["status"] == "needs_review"


@pytest.mark.parametrize(("field_id", "state", "confirmed_value"), [
    ("color", "unknown", "white"),
    ("variant", "conflict", "B"),
])
def test_seller_confirmation_resolves_identity_state(
    client, db_session, auth_headers, tmp_path, field_id, state, confirmed_value,
):
    run, master, page, digest, profile = _identity_state_target(
        db_session, client, auth_headers, tmp_path,
        field_id=field_id, state=state, confirmed_value=confirmed_value,
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "identity_state_not_evaluable" not in {item["code"] for item in result["domain"]["findings"]}
    assert result["domain"]["status"] == "complete"


def test_rejected_identity_remains_not_evaluable(client, db_session, auth_headers, tmp_path):
    run, source, truth, confirmation = _identity_state_target(
        db_session, client, auth_headers, tmp_path,
        field_id="color", state="unknown", rejected=True, build_master=False,
    )
    expected, gaps, states = _expected_product_identity(
        db_session, run=run, source=source, truth=truth, confirmation=confirmation,
    )
    assert expected == {}
    assert not gaps
    assert states == {"color": {"unknown", "rejected"}}


def test_prohibited_identity_state_is_not_an_expected_identity(client, db_session, auth_headers, tmp_path):
    run, source, truth, confirmation = _identity_state_target(
        db_session, client, auth_headers, tmp_path,
        field_id="color", state="prohibited_inference", build_master=False,
    )
    expected, gaps, states = _expected_product_identity(
        db_session, run=run, source=source, truth=truth, confirmation=confirmation,
    )
    assert expected == {}
    assert not gaps
    assert states == {"color": {"prohibited"}}


def test_nonidentity_unknown_does_not_make_visual_identity_unevaluable(client, db_session, auth_headers, tmp_path):
    run, source, truth, confirmation = _identity_state_target(
        db_session, client, auth_headers, tmp_path,
        field_id="battery_capacity", state="unknown", build_master=False,
    )
    expected, gaps, states = _expected_product_identity(
        db_session, run=run, source=source, truth=truth, confirmation=confirmation,
    )
    assert expected == {}
    assert not gaps
    assert states == {}


@pytest.mark.parametrize(
    ("warnings", "expected_code", "severity"),
    [
        (("LOW_VISIBILITY",), "low_product_visibility", "major"),
        (("PRODUCT_CLIPPED",), "product_crop_or_clipping", "major"),
        (("SAFE_CROP_REVIEW_REQUIRED",), "product_crop_needs_review", "major"),
        (("COLOR_MISMATCH",), "product_color_mismatch", "major"),
        (("VARIANT_MISMATCH",), "product_variant_mismatch", "critical"),
        (("WATERMARK",), "visible_watermark", "major"),
        (("THIRD_PARTY_LOGO",), "third_party_logo", "major"),
        (("FOREIGN_BRAND_CONTAMINATION",), "foreign_brand_contamination", "major"),
        (("DUPLICATE_FILE",), "duplicate_scene_image", "minor"),
    ],
)
def test_persisted_lg9_metadata_stays_tied_to_frozen_asset(client, db_session, auth_headers, tmp_path, warnings, expected_code, severity):
    run, master, page, digest, profile, _asset = _setup(
        db_session, client, auth_headers, tmp_path, warnings=warnings,
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    finding = next(item for item in result["domain"]["findings"] if item["code"] == expected_code)
    assert finding["severity"] == severity
    assert {ref["type"] for ref in finding["target_refs"]} >= {"DetailPageVersion", "section", "asset"}
    assert "raw" not in repr(finding).lower()


def test_identity_evidence_needs_review_never_auto_passes(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile, _asset = _setup(
        db_session, client, auth_headers, tmp_path, identity_status="needs_review",
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "needs_review"
    assert "product_identity_needs_review" in {item["code"] for item in result["domain"]["findings"]}


def test_lg9_review_identity_is_recorded_but_never_overrides_needs_review(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile, asset = _setup(db_session, client, auth_headers, tmp_path)
    job = ImageGenerationJobRecord(
        project_id=run.project_id, job_id="lg12-image-quality-review", section_id="hero", role="product",
        prompt="existing frozen image", status="approved", output_asset_id=asset.id,
        validation_result={
            "status": "needs_review", "risk_codes": ["watermark"],
            "details": {"identity": {"status": "needs_review", "checks": []}},
        },
    )
    db_session.add(job); db_session.commit()
    digest = _freeze_image_evidence(page, asset, job=job)
    db_session.commit()
    result = _evaluate(db_session, run, master, page, digest, profile)
    finding = next(item for item in result["domain"]["findings"] if item["code"] == "identity_evidence_needs_review")
    assert finding["severity"] == "major"
    assert any(ref["type"] == "lg9_image_validation" for ref in finding["evidence_refs"])
    assert "lg9_watermark" in {item["code"] for item in result["domain"]["findings"]}


def test_identity_drift_and_low_resolution_are_distinct(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile, _asset = _setup(
        db_session, client, auth_headers, tmp_path, size=(512, 512), preserved=False,
    )
    codes = {item["code"] for item in _evaluate(db_session, run, master, page, digest, profile)["domain"]["findings"]}
    assert {"low_resolution", "product_identity_drift"}.issubset(codes)


def test_corrupt_frozen_image_is_critical_finding(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile, asset = _setup(db_session, client, auth_headers, tmp_path)
    # The immutable Master check is the first fail-closed target-integrity
    # barrier.  A corrupt file must never reach a passing image evaluator.
    Path(asset.file_path).write_bytes(b"not a jpeg")
    with pytest.raises(IntakeVersionContractError, match="final-use integrity validation"):
        _evaluate(db_session, run, master, page, digest, profile)


def test_actual_bytes_or_manifest_substitution_fails_closed(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile, asset = _setup(db_session, client, auth_headers, tmp_path)
    Path(asset.file_path).write_bytes(b"tampered after freeze")
    with pytest.raises(IntakeVersionContractError, match="final-use integrity validation"):
        _evaluate(db_session, run, master, page, digest, profile)


def test_page_asset_outside_master_manifest_fails_closed(client, db_session, auth_headers, tmp_path):
    run, master, _page, _digest, profile, asset = _setup(db_session, client, auth_headers, tmp_path)
    other_path = tmp_path / "substitution.jpg"
    _write_image(asset, other_path)
    other_hash = hashlib.sha256(other_path.read_bytes()).hexdigest()
    other = Asset(
        project_id=run.project_id, source_type="uploaded", usage_status="seller_owned",
        filename=other_path.name, file_path=str(other_path), mime_type="image/jpeg", file_size=other_path.stat().st_size,
        content_hash=other_hash, asset_role="product_detail", quality_status="usable", identity_status="confirmed",
    )
    db_session.add(other); db_session.flush()
    page, digest = _frozen_page(
        db_session, run, master,
        sections=[{"section_id": "hero", "assets": [{"asset_id": other.id, "asset_content_hash": other_hash}]}],
        assets=[{"asset_id": other.id, "asset_content_hash": other_hash}],
    )
    db_session.commit()
    with pytest.raises(QualityAssessmentContractError, match="bound Commerce Creative Master"):
        _evaluate(db_session, run, master, page, digest, profile)
