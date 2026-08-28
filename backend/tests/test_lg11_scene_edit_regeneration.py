"""TASK-11.4 production LG-11 scene edit integration tests."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.db.models import (
    AgentRun,
    Asset,
    DetailPageVersion,
    ImageGenerationCostApprovalRecord,
    ImageGenerationJobRecord,
    ImageGenerationOutboxRecord,
    ProductProject,
)
from test_lg11_edit_intent_preview import _canonical_hash, _frozen_lg10_version
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers

pytestmark = pytest.mark.lg11_fake_e2e


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


@pytest.fixture
def lg11_runtime(monkeypatch):
    from src.services import langgraph_run_service

    saver = InMemorySaver()

    @contextmanager
    def open_test_checkpointer():
        yield saver

    monkeypatch.setattr(langgraph_run_service, "open_postgres_checkpointer", open_test_checkpointer)
    monkeypatch.setattr(langgraph_run_service, "langgraph_runtime_enabled", lambda: True)
    return saver


def _scene_request(*, operation: str, replacement_asset_id: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "scope": "scene",
        "target_ids": ["hero-scene"],
        "operation": operation,
        "instruction": "대표 장면을 다시 검수 가능한 새 결과로 바꿔 주세요.",
        "preserve_constraints": {"retain_unaffected_approved_assets": True},
    }
    if replacement_asset_id:
        payload.update({"replacement_asset_id": replacement_asset_id, "seller_attested": True})
    return payload


def _make_source_dispatchable(db_session, run) -> None:
    """Give the frozen fixture the same current storyboard prerequisites LG-9 uses."""

    project = db_session.query(ProductProject).filter_by(id=run.project_id).one()
    project.planning_draft = {
        "revision": 1,
        "cards": [{
            "id": "hero",
            "type": "hero",
            "image_requirement": "ai_redesign_required",
            "candidate_asset_ids": list(run.input_snapshot["asset_ids"]),
        }],
    }
    db_session.commit()


def _add_frozen_sibling_scene(db_session, run, source: DetailPageVersion) -> tuple[str, str]:
    """Give the source manifest a second approved scene to verify isolation."""

    sibling_asset = db_session.query(Asset).filter(
        Asset.project_id == run.project_id, Asset.id != source.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["assets"][0]["asset_id"],
    ).first()
    from hashlib import sha256
    sibling_asset.content_hash = sha256(open(sibling_asset.file_path, "rb").read()).hexdigest()
    sibling_job = ImageGenerationJobRecord(
        project_id=run.project_id, job_id=f"lg11-sibling-{run.id}", section_id="specs", scene_id="specs-scene",
        role="detail", prompt="frozen sibling", status="approved", output_asset_id=sibling_asset.id,
        provider="mock", model="durable-fake-image-v1", source_asset_ids=list(run.input_snapshot["asset_ids"]),
    )
    db_session.add(sibling_job)
    db_session.flush()
    snapshot = deepcopy(source.sections_json)
    canonical = snapshot["lg10"]["canonical_page_assembly_input"]
    manifest = canonical["approved_asset_manifest"]
    manifest["assets"].append({
        "scene_id": "specs-scene", "section_id": "specs", "job_id": sibling_job.job_id,
        "generation_attempt": 1, "asset_id": sibling_asset.id, "asset_content_hash": sibling_asset.content_hash,
        "provider": "mock", "model": "durable-fake-image-v1",
    })
    for section in canonical["sections"]:
        if section["section_id"] == "specs":
            section["approved_assets"] = [{
                "scene_id": "specs-scene", "section_id": "specs", "job_id": sibling_job.job_id,
                "asset_id": sibling_asset.id, "asset_content_hash": sibling_asset.content_hash,
            }]
            section["rendering_mode"] = "approved_asset"
    manifest_payload = {key: manifest[key] for key in ("run_id", "project_id", "assets")}
    manifest["manifest_hash"] = _canonical_hash(manifest_payload)
    canonical["page_asset_manifest"] = deepcopy(manifest)
    canonical_payload = deepcopy(canonical)
    canonical_payload.pop("input_hash", None)
    canonical["input_hash"] = _canonical_hash(canonical_payload)
    snapshot.pop("snapshot_hash", None)
    snapshot["snapshot_hash"] = _canonical_hash(snapshot)
    source.sections_json = snapshot
    db_session.commit()
    return sibling_asset.id, sibling_asset.content_hash


def _resume(client, headers, state, decision: str, **extra):
    pending = state["values"]["review"]["pending"]
    return client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume",
        headers=headers,
        json={
            "thread_id": state["thread_id"],
            "response": {
                "schema_version": pending["schema_version"],
                "review_stage": pending["review_stage"],
                "decision": decision,
                **extra,
            },
        },
    )


def _start_scene_edit(client, headers, run, version, payload):
    result = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-runs",
        headers=headers,
        json=payload,
    )
    assert result.status_code == 201, result.text
    return result.json(), client.get(f"/api/v1/graph-runs/{result.json()['run_id']}", headers=headers).json()


def test_lg11_regenerates_only_target_after_new_cost_approval_and_forks_frozen_version(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, original_asset_id = _frozen_lg10_version(db_session, run)
    sibling_asset_id, sibling_hash = _add_frozen_sibling_scene(db_session, run, source)
    _make_source_dispatchable(db_session, run)
    source_snapshot = deepcopy(source.sections_json)

    started, state = _start_scene_edit(client, auth_headers, run, source, _scene_request(operation="regenerate"))
    confirmed = _resume(client, auth_headers, state, "approve")
    assert confirmed.status_code == 200, confirmed.text
    cost_wait = confirmed.json()
    # The LG-11 node intentionally reuses the LG-9 public cost-review stage.
    assert cost_wait["current_stage"] == "generation_pending"
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).count() == 0

    provider_wait_response = _resume(
        client, auth_headers, cost_wait, "approve",
        cost_plan_hash=cost_wait["values"]["generation"]["cost_plan"]["cost_plan_hash"],
    )
    assert provider_wait_response.status_code == 200, provider_wait_response.text
    provider_wait = provider_wait_response.json()
    assert provider_wait["current_stage"] == "provider_wait"
    jobs = db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    regenerated = [job for job in jobs if job.usage_metadata.get("langgraph_run_id") == started["run_id"]]
    assert len(regenerated) == 1
    assert regenerated[0].scene_id == "hero-scene"
    deliveries = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).all()
    assert len(deliveries) == 1 and deliveries[0].provider_dispatch_count == 0

    from src.db.database import SessionLocal
    from src.services.image_generation_worker import run_image_worker_batch

    worker_db = SessionLocal()
    try:
        worker = run_image_worker_batch(worker_db, owner="lg11-scene-worker", batch_size=10)
    finally:
        worker_db.close()
    assert len(worker) == 1 and worker[0]["provider_dispatch_count"] == 1

    review = client.get(f"/api/v1/graph-runs/{started['run_id']}", headers=auth_headers).json()
    assert review["current_stage"] == "image_review"
    target = review["values"]["generation"]["jobs"][0]
    completed = _resume(client, auth_headers, review, "approve", job_id=target["job_id"])
    assert completed.status_code == 200, completed.text
    final = completed.json()
    assert final["status"] == "awaiting_review"
    assert final["current_stage"] == "quality_review"
    fork = final["values"]["edit"]["scene_version_fork"]
    child = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    assert child.sections_json["lg11"]["source_detail_page_version_id"] == source.id
    assert child.sections_json["lg11"]["scene_change"]["replacement_asset_id"] != original_asset_id
    assert source.sections_json == source_snapshot
    replacement = child.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["assets"][0]
    assert replacement["asset_id"] == child.sections_json["lg11"]["scene_change"]["replacement_asset_id"]
    sibling = next(item for item in child.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["assets"] if item["scene_id"] == "specs-scene")
    assert (sibling["asset_id"], sibling["asset_content_hash"]) == (sibling_asset_id, sibling_hash)

    duplicate = client.post(
        f"/api/v1/graph-runs/{started['run_id']}/resume", headers=auth_headers,
        # The image decision already produced the immutable child.  Its new
        # common QA review is now the only resumable interrupt, and resolving
        # it must not create another scene child or provider delivery.
        json={"thread_id": started["run_id"], "response": {"schema_version": "lg12i-v1", "review_stage": "quality_review", "decision": "approve"}},
    )
    assert duplicate.status_code == 200
    assert db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).count() == 1
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).one().provider_dispatch_count == 1


def test_lg11_seller_owned_replacement_is_zero_provider_and_rejects_unapproved_assets(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, run)
    _make_source_dispatchable(db_session, run)
    seller_asset = db_session.query(Asset).filter_by(project_id=run.project_id, usage_status="seller_owned").first()
    blocked = Asset(
        project_id=run.project_id, source_type="supplier", usage_status="blocked", filename="blocked.jpg",
        file_path=seller_asset.file_path, mime_type="image/jpeg", file_size=seller_asset.file_size,
    )
    db_session.add(blocked)
    db_session.commit()

    denied = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{source.id}/edit-runs", headers=auth_headers,
        json=_scene_request(operation="replace", replacement_asset_id=blocked.id),
    )
    assert denied.status_code == 201
    denied_state = client.get(f"/api/v1/graph-runs/{denied.json()['run_id']}", headers=auth_headers).json()
    denied_resume = _resume(client, auth_headers, denied_state, "approve")
    assert denied_resume.status_code == 200
    assert denied_resume.json()["current_stage"] == "scene_generation_failed"
    assert denied_resume.json()["status"] == "completed"

    started, state = _start_scene_edit(client, auth_headers, run, source, _scene_request(operation="replace", replacement_asset_id=seller_asset.id))
    review_response = _resume(client, auth_headers, state, "approve")
    assert review_response.status_code == 200, review_response.text
    review = review_response.json()
    assert review["current_stage"] == "image_review"
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).count() == 0
    job = review["values"]["generation"]["jobs"][0]
    complete = _resume(client, auth_headers, review, "approve", job_id=job["job_id"])
    assert complete.status_code == 200
    assert complete.json()["status"] == "awaiting_review"
    assert complete.json()["current_stage"] == "quality_review"


def test_lg11_scene_provider_failure_does_not_touch_source_or_create_child(
    monkeypatch, client, auth_headers, db_session, tmp_path, lg11_runtime
):
    """LG-9 dead-letter policy fails only the one LG-11 target attempt."""

    from src.db.database import SessionLocal
    from src.services import image_generation_worker
    from src.services.image_generation_worker import run_image_worker_batch

    run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, source_asset_id = _frozen_lg10_version(db_session, run)
    _make_source_dispatchable(db_session, run)
    started, state = _start_scene_edit(client, auth_headers, run, source, _scene_request(operation="regenerate"))
    cost_wait = _resume(client, auth_headers, state, "approve").json()
    wait = _resume(
        client, auth_headers, cost_wait, "approve",
        cost_plan_hash=cost_wait["values"]["generation"]["cost_plan"]["cost_plan_hash"],
    ).json()
    target = wait["values"]["generation"]["jobs"][0]
    original_generate = image_generation_worker.DurableFakeImageProvider.generate

    def fail_target(self, request):
        if request.job_id == target["job_id"]:
            raise RuntimeError("MODERATION_REJECTED")
        return original_generate(self, request)

    monkeypatch.setattr(image_generation_worker.DurableFakeImageProvider, "generate", fail_target)
    worker_db = SessionLocal()
    try:
        result = run_image_worker_batch(worker_db, owner="lg11-failed-target", batch_size=10)
    finally:
        worker_db.close()
    assert result[0]["status"] == "dead_letter"
    restored = client.get(f"/api/v1/graph-runs/{started['run_id']}", headers=auth_headers).json()
    assert restored["status"] == "completed"
    assert restored["current_stage"] == "scene_generation_failed"
    assert restored["values"]["generation"]["jobs"][0]["status"] == "failed"
    assert db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count() == 1
    assert source.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["assets"][0]["asset_id"] == source_asset_id


def test_lg11_scene_pending_cost_checkpoint_rebuilds_before_public_resume(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    """A checkpoint committed before projection still restores cost + lineage."""

    run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, run)
    _make_source_dispatchable(db_session, run)
    started, state = _start_scene_edit(client, auth_headers, run, source, _scene_request(operation="regenerate"))
    pending = _resume(client, auth_headers, state, "approve").json()
    assert pending["current_stage"] == "generation_pending"
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    expected_lineage = deepcopy(edit_run.outputs_json["langgraph_edit"]["lineage"])
    edit_run.outputs_json = {}
    edit_run.status = "running"
    db_session.commit()

    recovered = client.post(f"/api/v1/graph-runs/{started['run_id']}/resume", headers=auth_headers)
    assert recovered.status_code == 409
    db_session.refresh(edit_run)
    assert edit_run.outputs_json["langgraph_edit"]["lineage"] == expected_lineage
    assert edit_run.outputs_json["langgraph_review"]["pending"]["review_stage"] == "generation_pending"
    assert edit_run.outputs_json["langgraph_generation"]["cost_plan"]["scene_count"] == 1


def test_lg11_explicit_recovery_rebuilds_pending_cost_without_side_effects(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    """Only an explicit recovery may return the restored pending cost state."""

    run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, run)
    _make_source_dispatchable(db_session, run)
    started, state = _start_scene_edit(client, auth_headers, run, source, _scene_request(operation="regenerate"))
    pending = _resume(client, auth_headers, state, "approve").json()
    assert pending["current_stage"] == "generation_pending"
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    expected_lineage = deepcopy(edit_run.outputs_json["langgraph_edit"]["lineage"])
    before = {
        "outbox": db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=edit_run.id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=edit_run.project_id).count(),
        "cost_status": edit_run.cost_approval_status,
        "cost_records": [
            (record.id, record.cost_plan_hash, record.status)
            for record in db_session.query(ImageGenerationCostApprovalRecord)
            .filter_by(run_id=edit_run.id)
            .order_by(ImageGenerationCostApprovalRecord.id)
            .all()
        ],
        "page_versions": db_session.query(DetailPageVersion).filter_by(project_id=edit_run.project_id).count(),
    }
    edit_run.outputs_json = {}
    edit_run.status = "running"
    db_session.commit()

    payload = {"thread_id": started["run_id"], "mode": "recover"}
    recovered = client.post(f"/api/v1/graph-runs/{started['run_id']}/resume", headers=auth_headers, json=payload)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["current_stage"] == "generation_pending"
    db_session.refresh(edit_run)
    assert edit_run.outputs_json["langgraph_edit"]["lineage"] == expected_lineage
    assert edit_run.outputs_json["langgraph_review"]["pending"]["review_stage"] == "generation_pending"
    assert edit_run.cost_approval_status == before["cost_status"]
    assert [
        (record.id, record.cost_plan_hash, record.status)
        for record in db_session.query(ImageGenerationCostApprovalRecord)
        .filter_by(run_id=edit_run.id)
        .order_by(ImageGenerationCostApprovalRecord.id)
        .all()
    ] == before["cost_records"]
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=edit_run.id).count() == before["outbox"] == 0
    assert db_session.query(ImageGenerationJobRecord).filter_by(project_id=edit_run.project_id).count() == before["jobs"]
    assert db_session.query(DetailPageVersion).filter_by(project_id=edit_run.project_id).count() == before["page_versions"]

    duplicate = client.post(f"/api/v1/graph-runs/{started['run_id']}/resume", headers=auth_headers, json=payload)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["values"]["review"]["pending"]["review_stage"] == "generation_pending"
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=edit_run.id).count() == 0
    assert db_session.query(DetailPageVersion).filter_by(project_id=edit_run.project_id).count() == before["page_versions"]

    missing_respond = client.post(
        f"/api/v1/graph-runs/{started['run_id']}/resume",
        headers=auth_headers,
        json={"thread_id": started["run_id"], "mode": "respond"},
    )
    assert missing_respond.status_code == 422
    invalid_recovery = client.post(
        f"/api/v1/graph-runs/{started['run_id']}/resume",
        headers=auth_headers,
        json={"thread_id": started["run_id"], "mode": "recover", "response": {"decision": "approve"}},
    )
    assert invalid_recovery.status_code == 422

    approved = _resume(
        client,
        auth_headers,
        recovered.json(),
        "approve",
        cost_plan_hash=recovered.json()["values"]["generation"]["cost_plan"]["cost_plan_hash"],
    )
    assert approved.status_code == 200, approved.text
    deliveries = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=edit_run.id).all()
    assert len(deliveries) == 1 and deliveries[0].provider_dispatch_count == 0
    duplicate_approval = _resume(
        client,
        auth_headers,
        recovered.json(),
        "approve",
        cost_plan_hash=recovered.json()["values"]["generation"]["cost_plan"]["cost_plan_hash"],
    )
    assert duplicate_approval.status_code == 409
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=edit_run.id).count() == 1

    # ``recover`` is a deliberately closed recovery surface: an arbitrary
    # graph mode cannot turn the public endpoint into a generic graph retry.
    edit_run.mode = "unsupported_checkpoint_mode"
    db_session.commit()
    unsupported = client.post(
        f"/api/v1/graph-runs/{started['run_id']}/resume",
        headers=auth_headers,
        json={"thread_id": started["run_id"], "mode": "recover"},
    )
    assert unsupported.status_code == 409
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=edit_run.id).count() == 1
