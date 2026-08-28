"""TASK-11.3 production LangGraph copy-only version fork tests."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.db.models import AgentRun, DetailPageVersion, ImageGenerationJobRecord, ImageGenerationOutboxRecord
from src.services.export_service import build_lg10_copyable_html, build_lg10_standalone_export_bundle
from test_lg11_edit_intent_preview import _frozen_lg10_version
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers

pytestmark = pytest.mark.lg11_fake_e2e


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


@pytest.fixture
def lg11_runtime(monkeypatch):
    """Run the production LG-11 graph with a deterministic in-memory saver."""

    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _copy_edit_request(*, copy_changes: dict[str, dict[str, str]]) -> dict[str, object]:
    return {
        "scope": "copy",
        "target_ids": ["hero"],
        "operation": "rewrite",
        "instruction": "첫 화면의 소개 문구를 더 간결하게 바꿉니다.",
        "preserve_constraints": {"retain_approved_assets": True},
        "copy_changes": copy_changes,
    }


def _start_and_approve_copy_edit(client, headers, run, version, *, copy_changes):
    started = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-runs",
        headers=headers,
        json=_copy_edit_request(copy_changes=copy_changes),
    )
    assert started.status_code == 201, started.text
    response = client.post(
        f"/api/v1/graph-runs/{started.json()['run_id']}/resume",
        headers=headers,
        json={
            "thread_id": started.json()["run_id"],
            "response": {
                "schema_version": "lg11-v1",
                "review_stage": "edit_confirmation",
                "decision": "approve",
            },
        },
    )
    assert response.status_code == 200, response.text
    return started.json(), response.json()


def test_lg11_copy_edit_forks_frozen_version_without_provider_or_asset_changes(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, asset_id = _frozen_lg10_version(db_session, source_run)
    source_snapshot = deepcopy(source.sections_json)
    before_jobs = db_session.query(ImageGenerationJobRecord).filter_by(project_id=source_run.project_id).count()
    before_outbox = db_session.query(ImageGenerationOutboxRecord).filter_by(project_id=source_run.project_id).count()

    started, state = _start_and_approve_copy_edit(
        client,
        auth_headers,
        source_run,
        source,
        copy_changes={"hero": {"hero_subtitle": "제품을 더 간결하게 소개합니다"}},
    )
    # Every immutable LG-11 child now passes through the shared LG-12 QA
    # gate.  This legacy fixture has no LG-12 Master lineage, so it safely
    # stops at the bounded review gate rather than bypassing QA.
    assert state["status"] == "awaiting_review"
    assert state["current_stage"] == "quality_review"
    fork = state["values"]["edit"]["copy_version_fork"]
    assert fork["source_detail_page_version_id"] == source.id
    assert fork["parent_detail_page_version_id"] == source.id
    assert fork["edit_run_id"] == started["run_id"]

    db_session.expire_all()
    edited = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    source = db_session.query(DetailPageVersion).filter_by(id=source.id).one()
    assert edited.id != source.id
    assert edited.is_final is True
    assert source.is_final is False
    assert source.sections_json == source_snapshot
    assert edited.sections_json["snapshot_hash"] == fork["snapshot_hash"]
    assert edited.sections_json["lg11"]["source_detail_page_version_id"] == source.id
    assert edited.sections_json["lg11"]["parent_detail_page_version_id"] == source.id

    source_lg10 = source_snapshot["lg10"]
    edited_lg10 = edited.sections_json["lg10"]
    source_hero_ref = source_lg10["canonical_page_assembly_input"]["sections"][0]["copy_ref"]
    edited_hero_ref = edited_lg10["canonical_page_assembly_input"]["sections"][0]["copy_ref"]
    assert edited_hero_ref["artifact_hash"] == source_hero_ref["artifact_hash"]
    assert edited_hero_ref["lg11_copy_overlay"]["source_copy_ref"] == source_hero_ref
    assert edited_hero_ref["lg11_copy_overlay"]["field_provenance"]["hero_subtitle"] == {
        "classification": "narrative_only",
        "reason": "no_factual_claim_retained",
        "source_text_hash": edited.sections_json["lg11"]["copy_provenance"]["hero"]["hero_subtitle"]["source_text_hash"],
        "source_factual_cues": [],
        "new_factual_cues": [],
        "fact_ids": [],
        "evidence_ids_by_fact": {},
    }
    assert edited_hero_ref["fact_ids"] == source_hero_ref["fact_ids"]
    assert edited_lg10["page_assembly"]["sections"] == source_lg10["page_assembly"]["sections"]
    assert [section["asset_layer"] for section in edited_lg10["canonical_rendering"]["sections"]] == [
        section["asset_layer"] for section in source_lg10["canonical_rendering"]["sections"]
    ]
    assert edited_lg10["canonical_rendering"]["sections"][0]["text_layer"] == [
        {"field": "hero_title", "text": "저소음 모터 선풍기"},
        {"field": "hero_subtitle", "text": "제품을 더 간결하게 소개합니다"},
    ]
    assert edited_lg10["canonical_rendering"]["sections"][1] == source_lg10["canonical_rendering"]["sections"][1]
    assert asset_id in edited_lg10["canonical_rendering"]["html"]
    assert "제품을 더 간결하게 소개합니다" in edited_lg10["canonical_rendering"]["html"]
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=source_run.project_id).count() == before_jobs
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(project_id=source_run.project_id).count() == before_outbox

    copyable = build_lg10_copyable_html(db=db_session, project_id=source_run.project_id, version=edited)
    assert copyable["detail_page_version_id"] == edited.id
    assert "제품을 더 간결하게 소개합니다" in copyable["html"]
    assert asset_id in copyable["html"]
    standalone = build_lg10_standalone_export_bundle(
        db=db_session,
        project_id=source_run.project_id,
        version=edited,
        output_dir=str(tmp_path / "lg11-copy-export"),
    )
    assert standalone["detail_page_version_id"] == edited.id
    assert "제품을 더 간결하게 소개합니다" in Path(standalone["html_path"]).read_text(encoding="utf-8")


def test_lg11_copy_fork_rebuilds_checkpointed_result_without_duplicate_version(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    started, completed = _start_and_approve_copy_edit(
        client,
        auth_headers,
        source_run,
        source,
        copy_changes={"hero": {"hero_subtitle": "제품을 더 간결하게 소개합니다"}},
    )
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    expected_fork = deepcopy(completed["values"]["edit"]["copy_version_fork"])
    version_count = db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count()

    # Simulate a process stopping after the final checkpoint but before the
    # edit projection is durable.  Public resume must replay the same fork.
    edit_run.outputs_json = {key: value for key, value in (edit_run.outputs_json or {}).items() if key != "langgraph_edit"}
    edit_run.status = "running"
    db_session.add(edit_run)
    db_session.commit()
    recovered = client.post(
        f"/api/v1/graph-runs/{edit_run.id}/resume", headers=auth_headers,
        json={"mode": "recover", "thread_id": edit_run.id},
    )
    assert recovered.status_code == 200, recovered.text
    db_session.refresh(edit_run)
    assert edit_run.status == "awaiting_review"
    assert edit_run.outputs_json["langgraph_edit"]["copy_version_fork"] == expected_fork
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == version_count


def test_lg11_copy_fork_rejects_invalid_field_and_rejected_confirmation_does_not_execute(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    invalid = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{source.id}/edit-runs",
        headers=auth_headers,
        json=_copy_edit_request(copy_changes={"hero": {"unknown_field": "변경"}}),
    )
    assert invalid.status_code == 422

    before_versions = db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count()
    started = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{source.id}/edit-runs",
        headers=auth_headers,
        json=_copy_edit_request(copy_changes={"hero": {"hero_title": "거절되면 반영되지 않음"}}),
    )
    assert started.status_code == 201, started.text
    rejected = client.post(
        f"/api/v1/graph-runs/{started.json()['run_id']}/resume",
        headers=auth_headers,
        json={
            "thread_id": started.json()["run_id"],
            "response": {"schema_version": "lg11-v1", "review_stage": "edit_confirmation", "decision": "reject"},
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["current_stage"] == "edit_rejected"
    assert rejected.json()["values"]["edit"]["next_action"] == "none"
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == before_versions


def test_lg11_fact_sensitive_direct_copy_is_not_forked_before_evidence_review(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    request = _copy_edit_request(copy_changes={"hero": {"hero_subtitle": "무게는 150g입니다."}})
    preview = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{source.id}/edit-intents/preview",
        headers=auth_headers,
        json=request,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["impact_preview"]["requires_evidence_review"] is True

    before_versions = db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count()
    started = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{source.id}/edit-runs",
        headers=auth_headers,
        json=request,
    )
    assert started.status_code == 201, started.text
    approved = client.post(
        f"/api/v1/graph-runs/{started.json()['run_id']}/resume",
        headers=auth_headers,
        json={
            "thread_id": started.json()["run_id"],
            "response": {"schema_version": "lg11-v1", "review_stage": "edit_confirmation", "decision": "approve"},
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["current_stage"] == "evidence_review"
    pending = approved.json()["values"]["review"]["pending"]
    assert pending["review_stage"] == "evidence_review"
    assert approved.json()["values"]["edit"]["next_action"] == "fact_evidence_review"
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == before_versions


def test_lg11_existing_fact_rewrite_keeps_only_verified_field_provenance(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, fact, _ = _frozen_lg10_version(db_session, source_run)
    _, state = _start_and_approve_copy_edit(
        client,
        auth_headers,
        source_run,
        source,
        copy_changes={"hero": {"hero_title": "저소음 모터를 강조한 선풍기"}},
    )
    assert state["current_stage"] == "quality_review"
    fork = state["values"]["edit"]["copy_version_fork"]
    edited = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    copy_ref = edited.sections_json["lg10"]["canonical_page_assembly_input"]["sections"][0]["copy_ref"]
    field_provenance = copy_ref["lg11_copy_overlay"]["field_provenance"]["hero_title"]
    assert field_provenance["classification"] == "fact_backed"
    assert field_provenance["fact_ids"] == [fact.id]
    assert copy_ref["fact_ids"] == [fact.id]


def test_lg11_new_nonnumeric_product_claim_requires_evidence_review_without_fork(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    request = _copy_edit_request(copy_changes={"hero": {"hero_title": "방수 기능을 지원하는 선풍기"}})
    preview = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{source.id}/edit-intents/preview",
        headers=auth_headers,
        json=request,
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["impact_preview"]["requires_evidence_review"] is True
    field_provenance = preview_body["edit_intent"]["copy_change_provenance"]["hero"]["hero_title"]
    assert field_provenance["classification"] == "needs_evidence_review"
    assert field_provenance["fact_ids"] == []

    before_versions = db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count()
    started = client.post(
        f"/api/v1/projects/{source_run.project_id}/page/versions/{source.id}/edit-runs",
        headers=auth_headers,
        json=request,
    )
    assert started.status_code == 201, started.text
    approved = client.post(
        f"/api/v1/graph-runs/{started.json()['run_id']}/resume",
        headers=auth_headers,
        json={
            "thread_id": started.json()["run_id"],
            "response": {"schema_version": "lg11-v1", "review_stage": "edit_confirmation", "decision": "approve"},
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["current_stage"] == "evidence_review"
    assert approved.json()["values"]["review"]["pending"]["review_stage"] == "evidence_review"
    assert approved.json()["values"]["edit"]["next_action"] == "fact_evidence_review"
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == before_versions
