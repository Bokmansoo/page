"""TASK-11.6 production LG-11 style/Brand Kit selective reassembly tests."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.db.models import (
    AgentRun,
    Asset,
    BrandKit,
    BrandKitVersion,
    DetailPageVersion,
    ImageGenerationCostApprovalRecord,
    ImageGenerationOutboxRecord,
)
from test_lg11_edit_intent_preview import _frozen_lg10_version
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


def _style_request(version_id: str, *, direction: str | None = None, brand_version_id: str | None = None):
    return {
        "scope": "style",
        "target_ids": [version_id],
        "operation": "restyle",
        "instruction": "Apply the approved visual brand direction without regenerating product images.",
        "preserve_constraints": {"retain_unaffected_approved_assets": True},
        "design_direction": direction,
        "brand_kit_version_id": brand_version_id,
    }


def _resume(client, headers, state):
    pending = state["values"]["review"]["pending"]
    return client.post(
        f"/api/v1/graph-runs/{state['run_id']}/resume",
        headers=headers,
        json={
            "thread_id": state["thread_id"],
            "response": {
                "schema_version": pending["schema_version"],
                "review_stage": pending["review_stage"],
                "decision": "approve",
            },
        },
    )


def _brand_version(db_session, run, asset: Asset, *, primary: str = "#2563EB") -> BrandKitVersion:
    kit = BrandKit(workspace_id=run.workspace_id, name=f"LG11 style kit {asset.id}", created_by=run.created_by)
    db_session.add(kit)
    db_session.flush()
    version = BrandKitVersion(
        brand_kit_id=kit.id,
        workspace_id=run.workspace_id,
        version=1,
        status="draft",
        scope="workspace",
        logo_asset_ids=[asset.id],
        color_tokens={"primary": primary, "secondary": "#EFF6FF"},
        typography={"font_family": "Arial"},
        watermark_policy={"mode": "logo_subtle"},
        content_hash=sha256(f"kit:{kit.id}:{primary}".encode()).hexdigest(),
        created_by=run.created_by,
    )
    db_session.add(version)
    db_session.commit()
    return version


def _start(client, headers, run, version, payload):
    response = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-runs",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json(), client.get(f"/api/v1/graph-runs/{response.json()['run_id']}", headers=headers).json()


def test_lg11_style_reassembly_reuses_frozen_product_contract_without_provider_work(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, product_asset_id = _frozen_lg10_version(db_session, source_run)
    source_snapshot = deepcopy(source.sections_json)
    before_versions = db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count()

    started, state = _start(
        client,
        auth_headers,
        source_run,
        source,
        _style_request(source.id, direction="safe_information"),
    )
    result = _resume(client, auth_headers, state)
    assert result.status_code == 200, result.text
    completed = result.json()
    assert completed["status"] == "awaiting_review"
    assert completed["current_stage"] == "quality_review"
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    db_session.refresh(edit_run)
    persisted_edit = edit_run.outputs_json["langgraph_edit"]
    assert persisted_edit["impact_preview"]["expected_provider_cost"] == {
        "status": "not_required",
        "source": "lg11_style_selective_reassembly",
        "currency": "credits",
        "total": 0,
        "scenes": [],
    }
    fork = persisted_edit["style_version_fork"]
    assert fork["source_detail_page_version_id"] == source.id
    assert fork["parent_detail_page_version_id"] == source.id
    assert fork["snapshot"]["lg11"]["retained"]["scene_ids"] == ["hero-scene"]
    child = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    canonical = child.sections_json["lg10"]["canonical_page_assembly_input"]
    assert canonical["design_direction"] == "safe_information"
    assert canonical["approved_asset_manifest"] == source_snapshot["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]
    assert canonical["sections"][0]["approved_assets"][0]["asset_id"] == product_asset_id
    assert child.sections_json["lg10"]["canonical_rendering"]["sections"] == source_snapshot["lg10"]["canonical_rendering"]["sections"]
    assert not (set(child.sections_json["lg10"]["canonical_rendering"]) - {"design_direction", "renderer_tokens", "brand_tokens", "brand_geometry", "css", "html", "sections", "schema_version", "canonical_input_ref", "page_assembly_ref", "render_hash", "lg12_layout_evidence"})
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == before_versions + 1
    db_session.refresh(source)
    assert source.sections_json == source_snapshot
    assert not db_session.query(AgentRun).filter_by(id=started["run_id"]).one().outputs_json.get("langgraph_generation")
    assert db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).count() == 0
    assert db_session.query(ImageGenerationCostApprovalRecord).filter_by(run_id=started["run_id"]).count() == 0

    duplicate = _resume(client, auth_headers, completed)
    assert duplicate.status_code == 200
    assert db_session.query(DetailPageVersion).filter_by(project_id=source_run.project_id).count() == before_versions + 1


def test_lg11_brand_kit_reassembly_pins_approved_brand_assets_and_rejects_unsafe_assets(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, product_asset_id = _frozen_lg10_version(db_session, source_run)
    product = db_session.query(Asset).filter_by(id=product_asset_id).one()
    product.usage_status = "seller_owned"
    product.source_type = "uploaded"
    product.content_hash = sha256(open(product.file_path, "rb").read()).hexdigest()
    db_session.commit()
    approved_kit = _brand_version(db_session, source_run, product)

    started, state = _start(
        client,
        auth_headers,
        source_run,
        source,
        _style_request(source.id, brand_version_id=approved_kit.id),
    )
    completed = _resume(client, auth_headers, state)
    assert completed.status_code == 200, completed.text
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    db_session.refresh(edit_run)
    fork = edit_run.outputs_json["langgraph_edit"]["style_version_fork"]
    child = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    rendering = child.sections_json["lg10"]["canonical_rendering"]
    assert rendering["brand_tokens"]["brand_kit_version_id"] == approved_kit.id
    assert rendering["brand_tokens"]["asset_layer"]["logo"] == {
        "asset_id": product.id, "asset_content_hash": product.content_hash,
    }
    assert rendering["brand_tokens"]["asset_layer"]["watermark"] == rendering["brand_tokens"]["asset_layer"]["logo"]
    assert rendering["brand_tokens"]["color_tokens"]["accent"] == "#2563eb"
    assert rendering["brand_tokens"]["typography"]["body_font"] == "Arial"
    assert child.sections_json["lg10"]["canonical_page_assembly_input"]["approved_asset_manifest"]["assets"][0]["asset_id"] == product_asset_id

    unsafe_source = child
    for usage_status, source_type in [
        ("blocked", "uploaded"),
        ("reference_only", "sourced"),
        ("seller_owned", "supplier"),
    ]:
        unsafe = Asset(
            project_id=source_run.project_id,
            source_type=source_type,
            usage_status=usage_status,
            filename=f"unsafe-{usage_status}-{source_type}.jpg",
            file_path=product.file_path,
            mime_type="image/jpeg",
            file_size=product.file_size,
            content_hash=product.content_hash,
            quality_status="usable",
        )
        db_session.add(unsafe)
        db_session.commit()
        unsafe_kit = _brand_version(db_session, source_run, unsafe, primary="#7C3AED")
        # The unsafe logo is excluded by the existing rights resolver.  Each
        # completed child remains the final immutable source for the next edit.
        unsafe_started, unsafe_state = _start(
            client,
            auth_headers,
            source_run,
            unsafe_source,
            _style_request(unsafe_source.id, brand_version_id=unsafe_kit.id),
        )
        unsafe_result = _resume(client, auth_headers, unsafe_state)
        assert unsafe_result.status_code == 200, unsafe_result.text
        unsafe_edit_run = db_session.query(AgentRun).filter_by(id=unsafe_started["run_id"]).one()
        db_session.refresh(unsafe_edit_run)
        unsafe_fork = unsafe_edit_run.outputs_json["langgraph_edit"]["style_version_fork"]
        unsafe_child = db_session.query(DetailPageVersion).filter_by(id=unsafe_fork["detail_page_version_id"]).one()
        layer = unsafe_child.sections_json["lg10"]["canonical_rendering"]["brand_tokens"]["asset_layer"]
        assert layer == {"logo": None, "watermark": None, "font_assets": []}
        assert unsafe.id not in repr(unsafe_child.sections_json)
        unsafe_source = unsafe_child


def test_lg11_style_reassembly_public_resume_rebuilds_checkpointed_child_lineage(
    client, auth_headers, db_session, tmp_path, lg11_runtime
):
    source_run = _create_run(client, auth_headers, db_session, tmp_path)
    source, _, _ = _frozen_lg10_version(db_session, source_run)
    started, state = _start(
        client,
        auth_headers,
        source_run,
        source,
        _style_request(source.id, direction="image_centric"),
    )
    completed = _resume(client, auth_headers, state)
    assert completed.status_code == 200, completed.text
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    db_session.refresh(edit_run)
    fork = edit_run.outputs_json["langgraph_edit"]["style_version_fork"]
    child = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()

    # Simulate a process crash after the immutable checkpoint committed but
    # before its SQL projection/version persistence became durable.
    db_session.delete(child)
    edit_run = db_session.query(AgentRun).filter_by(id=started["run_id"]).one()
    edit_run.outputs_json = {}
    edit_run.status = "running"
    db_session.commit()

    recovered = client.post(
        f"/api/v1/graph-runs/{started['run_id']}/resume", headers=auth_headers,
        json={"mode": "recover", "thread_id": started["run_id"]},
    )
    assert recovered.status_code == 200, recovered.text
    db_session.refresh(edit_run)
    restored_fork = edit_run.outputs_json["langgraph_edit"]["style_version_fork"]
    assert restored_fork == fork
    restored_child = db_session.query(DetailPageVersion).filter_by(id=fork["detail_page_version_id"]).one()
    assert restored_child.sections_json == fork["snapshot"]
    assert restored_child.sections_json["lg11"]["parent_detail_page_version_id"] == source.id
