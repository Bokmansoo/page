"""TASK-12I.1 immutable intake/master version contract coverage."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from src.db.models import (
    BrandKit,
    BrandKitVersion,
    CommerceCreativeMasterVersion,
    FactSnapshot,
    ImageGenerationCostApprovalRecord,
    ImageGenerationOutboxRecord,
    ProductCreativeBriefVersion,
    ProductSourceSnapshotVersion,
)
from src.schemas.lg12_golden_dataset import GOLDEN_DATASET_V1_CONTENT_HASH, load_golden_dataset
from src.services.product_intake_version_service import (
    IntakeVersionContractError,
    canonical_version_hash,
    create_commerce_creative_master_version,
    create_product_source_snapshot_version,
    create_product_truth_version,
    create_seller_confirmation_version,
    master_reference_index,
    validate_immutable_version,
)
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers


def _ref(identifier: str, version: int = 1, digest: str | None = None, **extra: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": identifier,
        "version": version,
        "hash": digest or canonical_version_hash({"id": identifier, "version": version}),
    }
    payload.update(extra)
    return payload


def _fact_state_ref(identifier: str, version: int = 1, digest: str | None = None) -> dict[str, object]:
    return {
        **_ref(identifier, version, digest),
        "provenance_ref": _ref(f"evidence:{identifier}", version),
    }


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


def _run(client, headers, db_session, tmp_path):
    return _create_run(client, headers, db_session, tmp_path)


def _source_truth_confirmation(
    db_session,
    run,
    *,
    confirmed_fact_ids=("fact:fan:capacity",),
    rejected_fact_ids=(),
    unknown_fact_ids=(),
    answers=None,
):
    source = create_product_source_snapshot_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        input_mode="manual",
        source_refs=[_ref("seller-source:manual:fan")],
        provenance={"source": "seller"},
        rights={"status": "confirmed"},
        source_fidelity={"status": "complete"},
    )
    fact_ids = sorted(set(confirmed_fact_ids) | set(rejected_fact_ids) | set(unknown_fact_ids))
    truth = create_product_truth_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_reference=_ref(source.id, source.version, source.canonical_hash),
        fact_refs=[_ref(identifier) for identifier in fact_ids],
        evidence_refs=[_ref(f"evidence:{identifier}") for identifier in fact_ids],
    )
    confirmation = create_seller_confirmation_version(
        db_session,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        answers=answers if answers is not None else [{"question_id": "confirm-capacity", "answer": "confirmed"}],
        confirmed_fact_refs=[_fact_state_ref(identifier) for identifier in confirmed_fact_ids],
        rejected_fact_refs=[_fact_state_ref(identifier) for identifier in rejected_fact_ids],
        unknown_fact_refs=[_fact_state_ref(identifier) for identifier in unknown_fact_ids],
        rights_confirmations=[{"asset_id": "seller-source:manual:fan", "status": "confirmed"}],
    )
    return source, truth, confirmation


def _master_dependencies(db_session, run):
    fact_snapshot = FactSnapshot(
        project_id=run.project_id,
        purpose="lg12i-contract",
        snapshot_hash=canonical_version_hash({"facts": ["fan capacity"]}),
        facts_json=[{"id": "fact:fan:capacity"}],
        created_by=run.created_by,
    )
    sequence = db_session.query(BrandKit).filter_by(workspace_id=run.workspace_id).count() + 1
    kit = BrandKit(workspace_id=run.workspace_id, name=f"LG12I kit {run.id}-{sequence}", created_by=run.created_by)
    db_session.add_all([fact_snapshot, kit]); db_session.flush()
    kit_version = BrandKitVersion(
        brand_kit_id=kit.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        version=sequence,
        status="active",
        scope="project",
        color_tokens={"accent": "#0f766e"},
        typography={"body_font": "system-ui"},
        content_hash=canonical_version_hash({"brand": kit.id, "version": sequence}),
        created_by=run.created_by,
    )
    db_session.add(kit_version); db_session.flush()
    brief = ProductCreativeBriefVersion(
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        run_id=run.id,
        version=db_session.query(ProductCreativeBriefVersion).filter_by(project_id=run.project_id).count() + 1,
        fact_snapshot_id=fact_snapshot.id,
        fact_snapshot_hash=fact_snapshot.snapshot_hash,
        compiled_prompt_artifact_id="compiled-prompt-lg12i",
        category_pack_version_id="category-pack-lg12i",
        channel_pack_version_id="channel-pack-lg12i",
        brand_kit_version_id=kit_version.id,
        brand_kit_hash=kit_version.content_hash,
        review_insight_version_ids=[],
        reference_insight_version_ids=[],
        approved_fact_ids=["fact:fan:capacity"],
        input_hash=canonical_version_hash({"brief": "input", "sequence": sequence}),
        output_hash=canonical_version_hash({"brief": "output", "sequence": sequence}),
        brief_json={"sections": ["hero"]},
        created_by=run.created_by,
    )
    db_session.add(brief); db_session.flush()
    return fact_snapshot, kit_version, brief


def _create_master(db_session, run, *, chain=None, parent_version_id=None, downstream_output_refs=(), **overrides):
    source, truth, confirmation = chain or _source_truth_confirmation(db_session, run)
    fact_snapshot, kit, brief = _master_dependencies(db_session, run)
    payload = {
        "workspace_id": run.workspace_id,
        "project_id": run.project_id,
        "creator_run_id": run.id,
        "created_by": run.created_by,
        "source_reference": _ref(source.id, source.version, source.canonical_hash),
        "truth_reference": _ref(truth.id, truth.version, truth.canonical_hash),
        "confirmation_reference": _ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
        "creative_brief_reference": _ref(brief.id, brief.version, brief.output_hash),
        "brand_kit_reference": _ref(kit.id, kit.version, kit.content_hash),
        "evidence_artifact_refs": [_ref("evidence-artifact:fan")],
        "approved_fact_snapshot_ref": _ref(fact_snapshot.id, 1, fact_snapshot.snapshot_hash),
        "approved_asset_manifest_ref": _ref("manifest:fan"),
        "copy_artifact_ref": _ref("copywriting:fan", artifact_key="copywriting", schema_version="lg10-copy-v1"),
        "page_plan_artifact_ref": _ref("page-planning:fan", artifact_key="page_planning", schema_version="lg10-page-plan-v1"),
        "target_channels": ["smartstore", "coupang"],
        "parent_version_id": parent_version_id,
        "downstream_output_refs": downstream_output_refs,
    }
    payload.update(overrides)
    return create_commerce_creative_master_version(db_session, **payload)


def test_lg12i_canonical_hash_is_deterministic_excludes_self_hash_and_changes_with_content():
    payload = {"schema_version": "lg12i-test-v1", "body": {"b": 2, "a": 1}, "canonical_hash": "x" * 64}
    first = canonical_version_hash(payload)
    reordered = {"canonical_hash": "y" * 64, "body": {"a": 1, "b": 2}, "schema_version": "lg12i-test-v1"}
    assert first == canonical_version_hash(reordered)
    changed = deepcopy(payload); changed["body"]["a"] = 3
    assert first != canonical_version_hash(changed)

    unordered_a = {
        "source_refs": [_ref("source-b"), _ref("source-a")],
        "answers": [{"question_id": "first"}, {"question_id": "second"}],
    }
    unordered_b = {
        "source_refs": [_ref("source-a"), _ref("source-b")],
        "answers": [{"question_id": "first"}, {"question_id": "second"}],
    }
    assert canonical_version_hash(unordered_a) == canonical_version_hash(unordered_b)
    unordered_b["source_refs"][0] = _ref("source-c")
    assert canonical_version_hash(unordered_a) != canonical_version_hash(unordered_b)

    ordered_a = {"answers": [{"question_id": "first"}, {"question_id": "second"}]}
    ordered_b = {"answers": list(reversed(ordered_a["answers"]))}
    assert canonical_version_hash(ordered_a) != canonical_version_hash(ordered_b)


def test_lg12i_database_immutable_guards_block_orm_core_and_direct_sql_but_allow_successor_insert(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _source_truth_confirmation(db_session, run)
    db_session.commit()
    db_session.refresh(source)
    original_provenance = dict(source.provenance_json)

    # Mapper hook is a helpful early error, while the database trigger is the
    # durable guard exercised by the Core and direct-SQL paths below.
    source.provenance_json = {"source": "attacker"}
    with pytest.raises(ValueError, match="immutable"):
        db_session.flush()
    db_session.rollback()

    with pytest.raises(IntegrityError, match="LG12I_IMMUTABLE_VERSION"):
        db_session.execute(
            update(ProductSourceSnapshotVersion)
            .where(ProductSourceSnapshotVersion.id == source.id)
            .values(provenance_json={"source": "core-attacker"})
        )
    db_session.rollback()

    with pytest.raises(IntegrityError, match="LG12I_IMMUTABLE_VERSION"):
        db_session.execute(
            text("UPDATE product_source_snapshot_versions SET provenance_json = :body WHERE id = :id"),
            {"body": json.dumps({"source": "sql-attacker"}), "id": source.id},
        )
    db_session.rollback()

    with pytest.raises(IntegrityError, match="LG12I_IMMUTABLE_VERSION"):
        db_session.execute(text("DELETE FROM product_source_snapshot_versions WHERE id = :id"), {"id": source.id})
    db_session.rollback()

    persisted = db_session.get(ProductSourceSnapshotVersion, source.id)
    assert persisted.provenance_json == original_provenance
    successor = create_product_source_snapshot_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        created_by=run.created_by, input_mode="manual", source_refs=[_ref("seller-source:successor")],
        provenance=original_provenance, rights={"status": "confirmed"}, source_fidelity={"status": "complete"},
        parent_version_id=source.id,
    )
    assert successor.parent_version_id == source.id


def test_lg12i_database_unique_project_version_constraint_rejects_duplicate_insert(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _source_truth_confirmation(db_session, run)
    duplicate = ProductSourceSnapshotVersion(
        id=str(uuid4()), workspace_id=source.workspace_id, project_id=source.project_id,
        creator_run_id=source.creator_run_id, version=source.version, schema_version=source.schema_version,
        input_mode=source.input_mode, source_refs_json=source.source_refs_json,
        provenance_json=source.provenance_json, rights_json=source.rights_json,
        source_fidelity_json=source.source_fidelity_json, canonical_hash="f" * 64,
        created_by=source.created_by,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_lg12i_successor_parent_tamper_and_mismatched_parent_hash_are_blocked(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _source_truth_confirmation(db_session, run)
    successor = create_product_source_snapshot_version(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        created_by=run.created_by, input_mode="manual", source_refs=[_ref("seller-source:manual:fan-v2")],
        provenance={"source": "seller"}, rights={"status": "confirmed"}, source_fidelity={"status": "complete"},
        parent_version_id=source.id,
    )
    assert successor.parent_version == source.version
    assert successor.parent_version_hash == source.canonical_hash

    tampered_provenance = {"source": "tampered"}
    tampered_payload = {
        "kind": "ProductSourceSnapshotVersion",
        "schema_version": source.schema_version,
        "workspace_id": source.workspace_id,
        "project_id": source.project_id,
        "creator_run_id": source.creator_run_id,
        "version": source.version,
        "input_mode": source.input_mode,
        "parent": None,
        "source_refs": source.source_refs_json,
        "provenance": tampered_provenance,
        "rights": source.rights_json,
        "source_fidelity": source.source_fidelity_json,
    }
    # Simulate a privileged database breach after deliberately removing the
    # SQLite test mirror trigger.  Production PostgreSQL rejects this UPDATE
    # in the migration trigger; the lineage validator must still fail closed
    # if a persisted parent has somehow been changed and rehashed.
    db_session.execute(text("DROP TRIGGER trg_product_source_snapshot_versions_update_immutable"))
    db_session.execute(text("UPDATE product_source_snapshot_versions SET provenance_json = :body, canonical_hash = :digest WHERE id = :id"), {
        "body": json.dumps(tampered_provenance),
        "digest": canonical_version_hash(tampered_payload),
        "id": source.id,
    })
    db_session.commit()
    with pytest.raises(IntakeVersionContractError, match="parent hash"):
        validate_immutable_version(db_session, successor)


def test_lg12i_master_is_one_way_reference_index_and_successor_only_adds_downstream_outputs(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    chain = _source_truth_confirmation(db_session, run)
    master = _create_master(db_session, run, chain=chain)
    index = master_reference_index(master)
    assert index["source"]["hash"] and index["truth"]["hash"] and index["confirmation"]["hash"]
    assert index["creative_brief"]["hash"] and index["brand_kit"]["hash"]
    assert index["copy_artifact"]["artifact_key"] == "copywriting"
    assert index["page_plan_artifact"]["artifact_key"] == "page_planning"
    assert "brief_json" not in index and "raw_payload" not in index
    assert master.downstream_output_refs_json == []

    with pytest.raises(IntakeVersionContractError, match="initial Commerce Creative Master"):
        _create_master(db_session, run, chain=chain, downstream_output_refs=[{
            "kind": "DetailPageVersion", **_ref("detail-page:fan"),
        }])

    successor = _create_master(
        db_session, run, chain=chain, parent_version_id=master.id,
        downstream_output_refs=[{"kind": "DetailPageVersion", **_ref("detail-page:fan")}],
    )
    assert successor.parent_version_id == master.id
    assert successor.downstream_output_refs_json[0]["kind"] == "DetailPageVersion"


def test_lg12i_confirmation_pins_confirmed_rejected_unknown_fact_states_and_rejects_overlap(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    source, truth, confirmation = _source_truth_confirmation(
        db_session,
        run,
        confirmed_fact_ids=("fact:confirmed",),
        rejected_fact_ids=("fact:rejected",),
        unknown_fact_ids=("fact:unknown",),
    )
    assert confirmation.confirmed_fact_refs_json[0]["provenance_ref"]["id"] == "evidence:fact:confirmed"
    assert confirmation.rejected_fact_refs_json[0]["id"] == "fact:rejected"
    assert confirmation.unknown_fact_refs_json[0]["id"] == "fact:unknown"
    assert confirmation.answers_json == [{"question_id": "confirm-capacity", "answer": "confirmed"}]

    with pytest.raises(IntakeVersionContractError, match="more than one state"):
        create_seller_confirmation_version(
            db_session, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
            created_by=run.created_by, truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
            answers=[{"question_id": "same", "answer": "ambiguous"}],
            confirmed_fact_refs=[_fact_state_ref("fact:confirmed")],
            rejected_fact_refs=[_fact_state_ref("fact:confirmed")], unknown_fact_refs=[], rights_confirmations=[],
        )


@pytest.mark.parametrize("state", ["rejected", "unknown"])
def test_lg12i_master_rejects_non_confirmed_fact_promotion(client, auth_headers, db_session, tmp_path, state):
    run = _run(client, auth_headers, db_session, tmp_path)
    kwargs = {"confirmed_fact_ids": (), "rejected_fact_ids": (), "unknown_fact_ids": ()}
    kwargs[f"{state}_fact_ids"] = ("fact:fan:capacity",)
    chain = _source_truth_confirmation(db_session, run, **kwargs)
    with pytest.raises(IntakeVersionContractError, match="Rejected or unknown facts"):
        _create_master(db_session, run, chain=chain)


def test_lg12i_answers_do_not_implicitly_promote_facts_or_allow_raw_master_artifact_bodies(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    no_state_chain = _source_truth_confirmation(
        db_session,
        run,
        confirmed_fact_ids=(),
        answers=[{"question_id": "confirm-capacity", "answer": "confirmed"}],
    )
    with pytest.raises(IntakeVersionContractError, match="Only seller-confirmed facts"):
        _create_master(db_session, run, chain=no_state_chain)

    chain = _source_truth_confirmation(db_session, run)
    with pytest.raises(IntakeVersionContractError, match="not a copied artifact body"):
        _create_master(
            db_session,
            run,
            chain=chain,
            copy_artifact_ref={**_ref("copywriting:fan"), "raw_body": "must never be copied"},
        )


def test_lg12i_postgresql_immutable_migration_contract_is_present():
    migration = (Path(__file__).resolve().parents[1] / "migrations" / "20260818_lg12i_intake_version_contract.sql").read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION sellform_reject_lg12i_immutable_mutation()" in migration
    assert "LG12I_IMMUTABLE_VERSION" in migration
    for table in (
        "product_source_snapshot_versions",
        "product_truth_versions",
        "seller_confirmation_versions",
        "commerce_creative_master_versions",
    ):
        assert f"BEFORE UPDATE OR DELETE ON {table}" in migration
        assert f"trg_{table}_immutable" in migration


def test_lg12i_master_requires_every_reference_and_never_touches_provider_cost_or_golden_v1(client, auth_headers, db_session, tmp_path):
    run = _run(client, auth_headers, db_session, tmp_path)
    before = {
        "outbox": db_session.query(ImageGenerationOutboxRecord).count(),
        "cost": db_session.query(ImageGenerationCostApprovalRecord).count(),
        "golden": load_golden_dataset()["content_hash"],
    }
    with pytest.raises(IntakeVersionContractError, match="evidence artifact"):
        # Directly exercise the missing required reference contract while all
        # upstream versions remain valid and immutable.
        source, truth, confirmation = _source_truth_confirmation(db_session, run)
        fact_snapshot, kit, brief = _master_dependencies(db_session, run)
        create_commerce_creative_master_version(
            db_session, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
            created_by=run.created_by,
            source_reference=_ref(source.id, source.version, source.canonical_hash),
            truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
            confirmation_reference=_ref(confirmation.id, confirmation.version, confirmation.canonical_hash),
            creative_brief_reference=_ref(brief.id, brief.version, brief.output_hash),
            brand_kit_reference=_ref(kit.id, kit.version, kit.content_hash), evidence_artifact_refs=[],
            approved_fact_snapshot_ref=_ref(fact_snapshot.id, 1, fact_snapshot.snapshot_hash),
            approved_asset_manifest_ref=_ref("manifest:fan"), copy_artifact_ref=_ref("copywriting:fan"),
            page_plan_artifact_ref=_ref("page-planning:fan"), target_channels=["smartstore"],
        )
    assert db_session.query(ImageGenerationOutboxRecord).count() == before["outbox"]
    assert db_session.query(ImageGenerationCostApprovalRecord).count() == before["cost"]
    assert load_golden_dataset()["content_hash"] == GOLDEN_DATASET_V1_CONTENT_HASH == before["golden"]
