"""TASK-12I.6 deterministic Product Truth normalization contracts."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy

import pytest
from sqlalchemy import text, update

from src.db.models import (
    ImageGenerationCostApprovalRecord,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    AgentRun,
    ProductSourceSnapshotVersion,
    ProductTruthVersion,
    ReferenceInputVersion,
)
from src.services.product_intake_version_service import (
    PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION,
    PRODUCT_TRUTH_NORMALIZATION_SCHEMA_VERSION,
    IntakeVersionContractError,
    canonical_manual_input_artifact_hash,
    canonical_hash,
    create_manual_input_artifact,
    create_product_source_snapshot_version,
    normalize_product_truth_from_source_snapshot,
)
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _headers


pytestmark = pytest.mark.lg12i_fake_e2e


@pytest.fixture
def auth_headers():
    return _headers.__wrapped__()


@pytest.fixture
def lg12i_runtime(monkeypatch):
    from langgraph.checkpoint.memory import InMemorySaver
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _artifact(db, run, *, kind: str, metadata: dict, raw_body: str = "") -> ReferenceInputVersion:
    latest = db.query(ReferenceInputVersion).filter_by(project_id=run.project_id).order_by(ReferenceInputVersion.version.desc()).first()
    digest = (
        canonical_manual_input_artifact_hash(raw_body=raw_body, source_metadata=metadata)
        if kind == "text"
        else canonical_hash(metadata)
    )
    row = ReferenceInputVersion(
        workspace_id=run.workspace_id, project_id=run.project_id,
        version=(latest.version + 1 if latest else 1), input_kind=kind,
        content_text=raw_body or None, source_metadata=metadata, rights_status="unverified",
        usage_scope="analysis_only", content_hash=digest, created_by=run.created_by,
    )
    db.add(row); db.flush()
    return row


def _artifact_ref(row: ReferenceInputVersion, *, schema: str, key: str) -> dict:
    return {"id": row.id, "version": row.version, "hash": row.content_hash, "schema_version": schema, "artifact_key": key}


def _source(db, run, *, mode: str, artifact: ReferenceInputVersion, artifact_schema: str, artifact_key: str, rights: str = "seller_owned"):
    reference = _artifact_ref(artifact, schema=artifact_schema, key=artifact_key)
    source = create_product_source_snapshot_version(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        creator_run_id=run.id, created_by=run.created_by, input_mode=mode,
        source_refs=[reference], provenance={"source": "test", "artifact_ref": reference},
        rights={"confirmation_state": rights, "final_use_status": "not_approved"},
        source_fidelity={"source_kind": mode},
    )
    db.commit(); db.refresh(source)
    return source


def _source_ref(source) -> dict:
    return {"id": source.id, "version": source.version, "hash": source.canonical_hash}


def _manual_metadata(*, value="3200", conflict=False, rights="unconfirmed") -> dict:
    fields = [{"field_id": "battery_capacity", "classification": "fact_candidate", "label": "battery", "value": value, "unit": "mAh"}]
    return {
        "manual_payload_schema_version": "lg12i-manual-input-artifact-v1",
        "seller_entered_fields": fields,
        "unknown_fact_field_ids": ["certification"],
        "rights_confirmation_state": rights,
        "conflict_fact_candidates": ([
            {"field_id": "material", "label": "material", "observations": [
                {"value": "stainless", "unit": None}, {"value": "aluminum", "unit": None},
            ]}
        ] if conflict else []),
    }


def test_manual_truth_is_unapproved_and_preserves_unknown_conflict_rights(db_session, client, auth_headers, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _artifact(db_session, run, kind="text", metadata=_manual_metadata(conflict=True))
    source = _source(db_session, run, mode="manual", artifact=artifact, artifact_schema="lg12i-manual-input-artifact-v1", artifact_key="manual_product_input", rights="unconfirmed")

    result = normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(source))

    assert result["truth_version"]
    assert result["schema_version"] == PRODUCT_TRUTH_NORMALIZATION_SCHEMA_VERSION
    assert all(item["approval_status"] == "candidate_not_approved" for item in result["fact_candidates"])
    assert {item["field_id"] for item in result["unknown_facts"]} >= {"certification", "product_identity"}
    assert result["conflict_facts"][0]["state"] == "conflict"
    assert result["conflict_facts"][0]["resolution_status"] == "unresolved"
    assert {item["value"] for item in result["conflict_facts"][0]["observations"]} == {"stainless", "aluminum"}
    assert result["conflict_facts"][0]["conflicting_observations"] == result["conflict_facts"][0]["observations"]
    assert result["rights_uncertainty"]["state"] == "rights_uncertain"
    assert result["requires_review"] is True
    persisted = db_session.query(ProductTruthVersion).filter_by(id=result["truth_version"]["id"]).one()
    assert "content_text" not in repr(persisted.normalization_json)


@pytest.mark.parametrize("mode", ["owned_product_url", "photo_only"])
def test_url_and_photo_sources_normalize_to_the_same_truth_contract(db_session, client, auth_headers, tmp_path, mode):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    if mode == "owned_product_url":
        metadata = {
            "kind": "owned_product_url_capture_artifact", "observations": {
                "title": "Portable Fan", "description": "bounded", "image_urls": [],
                "specs": [{"label": "capacity", "value": "3200mAh"}],
            },
            "source_content_hash": "d" * 64,
        }
        artifact = _artifact(db_session, run, kind="url", metadata=metadata)
        source = _source(db_session, run, mode=mode, artifact=artifact, artifact_schema="lg12i-owned-product-url-capture-artifact-v1", artifact_key="owned_product_url_capture_artifact")
    else:
        asset_ref = {"id": "photo-asset-1", "version": 1, "hash": "a" * 64, "schema_version": "asset-ref-v1", "artifact_key": "photo_asset"}
        observation = {"observation_id": "obs-1", "observation_hash": "b" * 64, "normalized_field": "visible_product_role", "observed_value": "product_main", "observation_type": "visible_visual", "source_asset_refs": [asset_ref], "extractor_type": "VLM", "extractor_version": "fake", "region": {}}
        metadata = {
            "schema_version": PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION,
            "observations": [observation], "unknown_candidates": [{"field_id": "exact_weight", "state": "prohibited_inference", "source_observation_refs": [{"id": "obs-1", "version": 1, "hash": "b" * 64, "schema_version": "photo-v1", "artifact_key": "observation"}]}],
            "conflict_candidates": [], "risk_signals": [{"risk_type": "watermark", "observed_value": "sample", "region": {}, "source_asset_refs": [asset_ref], "extractor_type": "OCR", "extractor_version": "fake", "observation_hash": "c" * 64}],
        }
        artifact = _artifact(db_session, run, kind="image", metadata=metadata)
        source = _source(db_session, run, mode=mode, artifact=artifact, artifact_schema=PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION, artifact_key="photo_observation_artifact")

    result = normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(source))
    assert set(result) >= {"truth_version", "fact_candidates", "unknown_facts", "conflict_facts", "prohibited_inferences", "evidence_refs", "rights_uncertainty", "observation_risks"}
    assert all(item["approval_status"] == "candidate_not_approved" for item in result["fact_candidates"])
    if mode == "photo_only":
        assert result["prohibited_inferences"][0]["field_id"] == "exact_weight"
        assert result["observation_risks"][0]["risk_type"] == "watermark"
        assert result["observation_risks"][0]["source_refs"] == result["evidence_refs"]
        assert result["observation_risks"][0]["observation_ref"]["hash"]


def test_truth_is_deterministic_and_source_tamper_is_rejected(db_session, client, auth_headers, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _artifact(db_session, run, kind="text", metadata=_manual_metadata())
    source = _source(db_session, run, mode="manual", artifact=artifact, artifact_schema="lg12i-manual-input-artifact-v1", artifact_key="manual_product_input", rights="seller_owned")
    first = normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(source))
    second = normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(source))
    assert first["truth_version"] == second["truth_version"]

    # Simulate a privileged persisted-row tamper outside both application and
    # SQLite immutable guards; normalizer must still reject the source hash
    # mismatch before it can reuse the persisted Truth version.
    db_session.execute(text("DROP TRIGGER trg_product_source_snapshot_versions_update_immutable"))
    db_session.execute(
        update(ProductSourceSnapshotVersion)
        .where(ProductSourceSnapshotVersion.id == source.id)
        .values(provenance_json={"tampered": True})
    )
    db_session.commit()
    db_session.expire_all()
    with pytest.raises(IntakeVersionContractError):
        normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(source))


def test_normalization_rule_version_creates_a_new_immutable_truth_version(
    db_session, client, auth_headers, tmp_path, monkeypatch
):
    import src.services.product_intake_version_service as intake_versions

    run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _artifact(db_session, run, kind="text", metadata=_manual_metadata())
    source = _source(
        db_session, run, mode="manual", artifact=artifact,
        artifact_schema="lg12i-manual-input-artifact-v1", artifact_key="manual_product_input",
        rights="seller_owned",
    )
    first = normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(source))
    monkeypatch.setattr(
        intake_versions,
        "PRODUCT_TRUTH_NORMALIZATION_SCHEMA_VERSION",
        "lg12i-product-truth-normalization-v2-test",
    )
    second = intake_versions.normalize_product_truth_from_source_snapshot(
        db_session, run=run, source_reference=_source_ref(source)
    )

    assert second["truth_version"]["id"] != first["truth_version"]["id"]
    assert second["truth_version"]["hash"] != first["truth_version"]["hash"]
    assert db_session.query(ProductTruthVersion).filter_by(
        source_snapshot_version_id=source.id
    ).count() == 2


@pytest.mark.parametrize("generation_mode", ["quick", "expert"])
def test_truth_conflicts_stay_unresolved_across_graph_rebuild(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, generation_mode
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = create_manual_input_artifact(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        created_by=run.created_by, raw_body="bounded seller source", source_metadata=_manual_metadata(conflict=True),
    )
    db_session.commit(); db_session.refresh(artifact)
    response = client.post(
        f"/api/v1/graph-runs/projects/{run.project_id}/unified-intake", headers=auth_headers,
        json={"input_mode": "manual", "source_payload_refs": [{"id": artifact.id, "kind": "manual_payload_artifact", "version": artifact.version, "hash": artifact.content_hash}], "requested_generation_mode": generation_mode, "target_channels": ["smartstore"]},
    )
    assert response.status_code == 201, response.text
    state = response.json()
    assert state["current_stage"] == "seller_confirmation"
    assert state["values"]["intake"]["next_action"] == "seller_confirmation"
    conflict = state["values"]["intake"]["product_truth"]["conflict_facts"][0]
    assert conflict["resolution_status"] == "unresolved"
    assert "resolved" not in conflict

    persisted_run = db_session.query(AgentRun).filter_by(id=state["run_id"]).one()
    expected = deepcopy(persisted_run.outputs_json["langgraph_intake"])
    persisted_run.outputs_json = {
        key: value for key, value in persisted_run.outputs_json.items()
        if key != "langgraph_intake"
    }
    persisted_run.status = "running"
    db_session.commit()
    recovered = client.post(f"/api/v1/graph-runs/{persisted_run.id}/resume", headers=auth_headers)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["values"]["intake"] == expected
    assert recovered.json()["values"]["intake"]["product_truth"]["conflict_facts"][0]["resolution_status"] == "unresolved"
    assert db_session.query(ImageGenerationJobRecord).count() == 0
    assert db_session.query(ImageGenerationOutboxRecord).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).count() == 0


@pytest.mark.parametrize(
    ("mode", "kind", "schema", "key", "metadata", "mutated_metadata"),
    [
        (
            "manual", "text", "lg12i-manual-input-artifact-v1", "manual_product_input",
            _manual_metadata(), {**_manual_metadata(), "seller_entered_fields": [{
                "field_id": "battery_capacity", "classification": "fact_candidate",
                "label": "battery", "value": "6400", "unit": "mAh",
            }]},
        ),
        (
            "owned_product_url", "url", "lg12i-owned-product-url-capture-artifact-v1", "owned_product_url_capture_artifact",
            {"kind": "owned_product_url_capture_artifact", "source_content_hash": "a" * 64, "observations": {"title": "Fan", "specs": []}},
            {"kind": "owned_product_url_capture_artifact", "source_content_hash": "a" * 64, "observations": {"title": "Tampered Fan", "specs": []}},
        ),
        (
            "photo_only", "image", PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION, "photo_observation_artifact",
            {"schema_version": PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION, "observations": [], "unknown_candidates": [], "conflict_candidates": [], "risk_signals": []},
            {"schema_version": PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION, "observations": [{"normalized_field": "visible_role", "observed_value": "tampered"}], "unknown_candidates": [], "conflict_candidates": [], "risk_signals": []},
        ),
    ],
)
def test_truth_rechecks_each_persisted_source_artifact_content_hash(
    db_session, client, auth_headers, tmp_path, mode, kind, schema, key, metadata, mutated_metadata
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _artifact(db_session, run, kind=kind, metadata=metadata)
    source = _source(db_session, run, mode=mode, artifact=artifact, artifact_schema=schema, artifact_key=key)

    db_session.execute(
        update(ReferenceInputVersion)
        .where(ReferenceInputVersion.id == artifact.id)
        .values(source_metadata=mutated_metadata)
    )
    db_session.commit()
    db_session.expire_all()

    with pytest.raises(IntakeVersionContractError, match="source artifact ID/version/hash"):
        normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(source))
    assert db_session.query(ProductTruthVersion).filter_by(source_snapshot_version_id=source.id).count() == 0


def test_truth_rejects_stored_artifact_hash_or_pinned_reference_hash_mismatch(
    db_session, client, auth_headers, tmp_path
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = _artifact(db_session, run, kind="text", metadata=_manual_metadata())
    source = _source(
        db_session, run, mode="manual", artifact=artifact,
        artifact_schema="lg12i-manual-input-artifact-v1", artifact_key="manual_product_input",
    )
    db_session.execute(
        update(ReferenceInputVersion).where(ReferenceInputVersion.id == artifact.id).values(content_hash="f" * 64)
    )
    db_session.commit()
    with pytest.raises(IntakeVersionContractError, match="source artifact ID/version/hash"):
        normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(source))
    assert db_session.query(ProductTruthVersion).filter_by(source_snapshot_version_id=source.id).count() == 0

    intact = _artifact(db_session, run, kind="text", metadata=_manual_metadata())
    incorrect_reference = {
        **_artifact_ref(intact, schema="lg12i-manual-input-artifact-v1", key="manual_product_input"),
        "hash": "e" * 64,
    }
    stale_source = create_product_source_snapshot_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        creator_run_id=run.id, created_by=run.created_by, input_mode="manual",
        source_refs=[incorrect_reference], provenance={"source": "test", "artifact_ref": incorrect_reference},
        rights={"confirmation_state": "seller_owned", "final_use_status": "not_approved"},
        source_fidelity={"source_kind": "manual"},
    )
    db_session.commit(); db_session.refresh(stale_source)
    with pytest.raises(IntakeVersionContractError, match="source artifact ID/version/hash"):
        normalize_product_truth_from_source_snapshot(db_session, run=run, source_reference=_source_ref(stale_source))
    assert db_session.query(ProductTruthVersion).filter_by(source_snapshot_version_id=stale_source.id).count() == 0


def test_price_advantage_is_prohibited_while_observed_price_remains_unapproved_candidate(
    db_session, client, auth_headers, tmp_path
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    comparative_claims = [
        "동급 대비 저렴",
        "동급 대비 더 저렴",
        "동급 대비 싸다",
        "동급 제품 대비 저렴",
        "동급 제품보다 저렴",
        "타사보다 저렴",
        "타사보다 싸다",
        "경쟁사보다 저렴",
        "경쟁사보다 싸다",
        "가장 저렴",
        "제일 저렴",
        "최저가",
        "가격 대비 최고",
        "가성비 최고",
        "가성비 1위",
    ]
    for claim in comparative_claims:
        manual_metadata = _manual_metadata(value=claim, rights="confirmed")
        manual_metadata["seller_entered_fields"][0]["field_id"] = "marketing_price_claim"
        artifact = _artifact(db_session, run, kind="text", metadata=manual_metadata)
        source = _source(
            db_session, run, mode="manual", artifact=artifact,
            artifact_schema="lg12i-manual-input-artifact-v1", artifact_key="manual_product_input",
        )
        result = normalize_product_truth_from_source_snapshot(
            db_session, run=run, source_reference=_source_ref(source)
        )
        prohibited = next(
            item for item in result["prohibited_inferences"]
            if item.get("inference_type") == "price_advantage"
        )
        assert prohibited["field_id"] == "price_advantage"
        assert prohibited["attempted_claim"] == claim
        assert prohibited["status"] == "prohibited_not_approved"
        assert prohibited["approval_status"] == "not_approved"
        assert prohibited["policy_rule_id"]
        assert prohibited["provenance_hash"]
        assert all(item["field_id"] != "price_advantage" for item in result["fact_candidates"])

    for observed_price_or_promotion in ("19,900원", "10% 할인", "행사가 29,900원", "오늘만 할인"):
        manual_metadata = _manual_metadata(value=observed_price_or_promotion, rights="confirmed")
        manual_metadata["seller_entered_fields"][0]["field_id"] = "marketing_price_claim"
        artifact = _artifact(db_session, run, kind="text", metadata=manual_metadata)
        source = _source(
            db_session, run, mode="manual", artifact=artifact,
            artifact_schema="lg12i-manual-input-artifact-v1", artifact_key="manual_product_input",
        )
        result = normalize_product_truth_from_source_snapshot(
            db_session, run=run, source_reference=_source_ref(source)
        )
        assert not any(
            item.get("inference_type") == "price_advantage"
            for item in result["prohibited_inferences"]
        )
        assert any(
            item["field_id"] == "marketing_price_claim"
            for item in result["fact_candidates"]
        )

    photo_metadata = {
        "schema_version": PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION,
        "observations": [{
            "normalized_field": "listed_price", "observed_value": "19,900원",
            "observation_type": "ocr_text", "source_asset_refs": [],
            "extractor_type": "OCR", "extractor_version": "fake", "region": {},
        }],
        "unknown_candidates": [], "conflict_candidates": [],
        "risk_signals": [{
            "risk_type": "price_or_promotion", "observed_value": "19,900원", "region": {},
            "source_asset_refs": [], "extractor_type": "OCR", "extractor_version": "fake",
            "observation_hash": "a" * 64,
        }],
    }
    photo_artifact = _artifact(db_session, run, kind="image", metadata=photo_metadata)
    photo_source = _source(
        db_session, run, mode="photo_only", artifact=photo_artifact,
        artifact_schema=PHOTO_ONLY_OBSERVATION_ARTIFACT_SCHEMA_VERSION,
        artifact_key="photo_observation_artifact",
    )
    photo_result = normalize_product_truth_from_source_snapshot(
        db_session, run=run, source_reference=_source_ref(photo_source)
    )
    assert any(item["field_id"] == "listed_price" for item in photo_result["fact_candidates"])
    assert not any(item.get("inference_type") == "price_advantage" for item in photo_result["prohibited_inferences"])
    assert photo_result["observation_risks"][0]["risk_type"] == "price_or_promotion"


def test_truth_source_integrity_block_is_projected_and_rebuilt(
    client, auth_headers, db_session, tmp_path, lg12i_runtime, monkeypatch
):
    """A post-snapshot artifact tamper must stop the compiled graph before Truth.

    The adapter wrapper deliberately simulates an out-of-band database write
    after it has pinned the source reference.  The graph still uses the real
    adapter and normalizer nodes; only the hostile write is injected between
    them so the test exercises the production integrity boundary and durable
    projection recovery.
    """

    import src.services.product_intake_version_service as intake_versions

    run = _create_run(client, auth_headers, db_session, tmp_path)
    artifact = create_manual_input_artifact(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        created_by=run.created_by,
        raw_body="bounded seller source",
        source_metadata=_manual_metadata(),
    )
    db_session.commit()
    db_session.refresh(artifact)
    real_adapter = intake_versions.adapt_manual_input_to_source_snapshot

    def tampered_adapter(*args, **kwargs):
        result = real_adapter(*args, **kwargs)
        db_session.execute(
            update(ReferenceInputVersion)
            .where(ReferenceInputVersion.id == artifact.id)
            .values(source_metadata=_manual_metadata(value="6400"))
        )
        db_session.commit()
        return result

    monkeypatch.setattr(intake_versions, "adapt_manual_input_to_source_snapshot", tampered_adapter)
    response = client.post(
        f"/api/v1/graph-runs/projects/{run.project_id}/unified-intake",
        headers=auth_headers,
        json={
            "input_mode": "manual",
            "source_payload_refs": [{
                "id": artifact.id,
                "kind": "manual_payload_artifact",
                "version": artifact.version,
                "hash": artifact.content_hash,
            }],
            "requested_generation_mode": "quick",
            "target_channels": ["smartstore"],
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["current_stage"] == "truth_blocked_source_integrity"
    assert payload["values"]["intake"]["truth"]["status"] == "blocked_source_integrity"
    assert "source artifact ID/version/hash" in payload["values"]["intake"]["truth"]["reason"]
    assert db_session.query(ProductTruthVersion).count() == 0

    persisted_run = db_session.query(AgentRun).filter_by(id=payload["run_id"]).one()
    persisted_run.outputs_json = {
        key: value for key, value in persisted_run.outputs_json.items()
        if key != "langgraph_intake"
    }
    persisted_run.status = "running"
    db_session.commit()
    rebuilt = client.post(f"/api/v1/graph-runs/{persisted_run.id}/resume", headers=auth_headers)
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["current_stage"] == "truth_blocked_source_integrity"
    assert rebuilt.json()["values"]["intake"]["truth"] == payload["values"]["intake"]["truth"]
