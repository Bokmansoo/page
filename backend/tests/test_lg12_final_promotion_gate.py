"""TASK-12.10 persisted final-promotion/export authority."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

import pytest
from fastapi import HTTPException

from src.db.models import Asset, DetailPageVersion, ExportArtifact, ExportJob, QualityPromotionVersion
from src.services.quality_promotion_service import (
    QualityPromotionGateError,
    promote_current_quality_page,
    quality_status_projection,
    require_current_quality_promotion,
)


pytestmark = pytest.mark.lg12_fake_quality_gate

# The TASK-12.9 integration module owns the production-only frozen page
# builder.  Reusing its persisted fixture keeps this gate test on real
# Source→Truth→Confirmation→Brief→Master and five-domain QA contracts.
from test_lg12_quality_graph_integration import (  # type: ignore[import-not-found]
    _build_quality_evidence_page,
    attach_valid_lg12_channel_parity_evidence,
    attach_valid_lg12_copy_evidence,
    attach_valid_lg12_layout_evidence,
    aggregate_valid_lg12_quality_bar,
    build_copy_spacing_failure_fixture,
    build_valid_lg12_master_lineage,
    build_valid_lg12_page_plan,
    evaluate_all_lg12_quality_domains,
)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def _pass_fixture(client, auth_headers, db_session, tmp_path, *, product_name: str = "LG-12 quality integration product"):
    lineage = build_valid_lg12_master_lineage(
        client,
        auth_headers,
        db_session,
        product_name=product_name,
    )
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=page)
    attach_valid_lg12_layout_evidence(page=page)
    attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)
    report = evaluate_all_lg12_quality_domains(run=lineage["run"], page=page, db_session=db_session)["qa_report"]
    lineage["run"].current_stage = "quality_promotion_ready"
    lineage["run"].status = "completed"
    db_session.flush()
    return lineage, page, report


def _quality_fixture(client, auth_headers, db_session, tmp_path, *, verdict: str):
    """Build one real frozen QA result without changing production routing."""

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db_session)
    page_plan = build_valid_lg12_page_plan(lineage, db_session)
    evidence_page = _build_quality_evidence_page(
        lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db_session,
    )
    page = evidence_page["page"]
    attach_valid_lg12_copy_evidence(page=page)
    attach_valid_lg12_layout_evidence(page=page)
    if verdict == "FAIL":
        attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)
        page = build_copy_spacing_failure_fixture(
            run=lineage["run"], page=page, db_session=db_session,
        )["page"]
        attach_valid_lg12_copy_evidence(page=page)
        attach_valid_lg12_layout_evidence(page=page)
        attach_valid_lg12_channel_parity_evidence(page=page, db_session=db_session, tmp_path=tmp_path)
    report = evaluate_all_lg12_quality_domains(
        run=lineage["run"], page=page, db_session=db_session,
    )["qa_report"]
    bar = aggregate_valid_lg12_quality_bar(qa_report=report, db_session=db_session)["quality_bar"]
    assert bar["verdict"] == verdict
    return lineage, page, report, bar


def _current_stale_successor(*, historical_page: DetailPageVersion, db_session) -> DetailPageVersion:
    """Create a later frozen page without mutating a historical PASS page.

    E2E-3 needs both rows to remain persisted: the historical page keeps its
    valid immutable PASS/promotion lineage, while the newer page is the only
    current page selected by the production gate.
    """

    snapshot = deepcopy(historical_page.sections_json)
    snapshot.pop("snapshot_hash", None)
    snapshot["lg12_e2e_stale_successor"] = {
        "parent_detail_page_version_id": historical_page.id,
        "reason": "new-current-page",
    }
    import hashlib
    import json

    snapshot["snapshot_hash"] = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    successor = DetailPageVersion(
        project_id=historical_page.project_id,
        name="LG-12 E2E current successor",
        style_key=historical_page.style_key,
        sections_json=snapshot,
        # The historical page stays final and immutable. `_current_page()`
        # deterministically selects this later frozen final version.
        is_final=True,
        created_at=historical_page.created_at + timedelta(seconds=1),
    )
    db_session.add(successor)
    db_session.flush()
    return successor


def test_pass_promotion_is_immutable_idempotent_and_unlocks_only_current_channel(client, auth_headers, db_session, tmp_path):
    lineage, page, report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    run = lineage["run"]

    with pytest.raises(QualityPromotionGateError):
        require_current_quality_promotion(
            db_session, workspace_id=run.workspace_id, project_id=run.project_id,
            page_id=page.id, channel="smartstore",
        )

    first = promote_current_quality_page(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=page.id,
    )
    second = promote_current_quality_page(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=page.id,
    )
    assert first.id == second.id
    assert db_session.query(QualityPromotionVersion).filter_by(project_id=run.project_id).count() == 1
    allowed = require_current_quality_promotion(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        page_id=page.id, channel="smartstore",
    )
    assert allowed.quality_report_id == report.id
    with pytest.raises(QualityPromotionGateError):
        require_current_quality_promotion(
            db_session, workspace_id=run.workspace_id, project_id=run.project_id,
            page_id=page.id, channel="coupang",
        )
    assert quality_status_projection(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
    )["promotion_status"] == "promoted"


def test_stale_pass_and_direct_api_export_are_blocked(client, auth_headers, db_session, tmp_path):
    lineage, page, _report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    run = lineage["run"]
    promotion = promote_current_quality_page(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=page.id,
    )
    assert promotion.detail_page_version_id == page.id

    child_snapshot = deepcopy(page.sections_json)
    child_snapshot.pop("snapshot_hash")
    import hashlib, json
    child_snapshot["snapshot_hash"] = hashlib.sha256(
        json.dumps(child_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    page.is_final = False
    child = DetailPageVersion(
        project_id=run.project_id, name="new immutable child", style_key=page.style_key,
        sections_json=child_snapshot, is_final=True,
    )
    db_session.add(child); db_session.flush()

    with pytest.raises(QualityPromotionGateError):
        require_current_quality_promotion(
            db_session, workspace_id=run.workspace_id, project_id=run.project_id,
            page_id=page.id, channel="smartstore",
        )
    response = client.post(
        f"/api/v1/projects/{run.project_id}/page/export",
        headers=auth_headers,
        json={"preset_name": "smartstore", "final_version_id": page.id, "output_format": "png"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "quality_gate_blocked"


def test_stale_historical_pass_blocks_promotion_standalone_and_download(client, auth_headers, db_session, tmp_path):
    """A later current page cannot inherit v1's PASS, promotion, or files."""

    lineage, historical, _report = _pass_fixture(
        client, auth_headers, db_session, tmp_path, product_name="LG-12 stale historical pass",
    )
    run = lineage["run"]
    promotion = promote_current_quality_page(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=historical.id,
    )
    initial_export = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=auth_headers,
        json={"final_version_id": historical.id, "channel": "smartstore"},
    )
    assert initial_export.status_code == 200, initial_export.text
    historical_html_asset_id = initial_export.json()["html_download_url"].rsplit("/", 1)[-1]
    historical_zip_asset_id = initial_export.json()["zip_download_url"].rsplit("/", 1)[-1]
    artifact_count = db_session.query(ExportArtifact).filter_by(project_id=run.project_id).count()

    current = _current_stale_successor(historical_page=historical, db_session=db_session)
    assert current.id != historical.id
    assert historical.is_final is True

    stale_promotion = client.post(
        f"/api/v1/projects/{run.project_id}/page/promotion",
        headers=auth_headers,
        json={"detail_page_version_id": historical.id},
    )
    stale_standalone = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=auth_headers,
        json={"final_version_id": historical.id, "channel": "smartstore"},
    )
    stale_download = client.get(
        f"/api/v1/projects/{run.project_id}/page/export/download/{historical_html_asset_id}",
        headers=auth_headers,
    )
    stale_generic_html = client.get(
        f"/api/v1/files/assets/{historical_html_asset_id}",
        headers=auth_headers,
    )
    stale_generic_zip = client.get(
        f"/api/v1/files/assets/{historical_zip_asset_id}",
        headers=auth_headers,
    )
    for response in (stale_promotion, stale_standalone, stale_download, stale_generic_html, stale_generic_zip):
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "quality_gate_blocked"
    assert db_session.query(QualityPromotionVersion).filter_by(project_id=run.project_id).count() == 1
    assert db_session.query(ExportArtifact).filter_by(project_id=run.project_id).count() == artifact_count
    assert promotion.detail_page_version_id == historical.id

    status = client.get(f"/api/v1/projects/{run.project_id}/quality-status", headers=auth_headers)
    assert status.status_code == 200, status.text
    assert status.json()["current_page_ref"]["id"] == current.id
    assert status.json()["promotion_status"] == "blocked"


def test_duplicate_export_reuses_current_artifacts_and_rejects_wrong_channel(client, auth_headers, db_session, tmp_path):
    lineage, page, _report = _pass_fixture(
        client, auth_headers, db_session, tmp_path, product_name="LG-12 duplicate export",
    )
    run = lineage["run"]
    promote_current_quality_page(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=page.id,
    )
    first = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=auth_headers,
        json={"final_version_id": page.id, "channel": "smartstore"},
    )
    assert first.status_code == 200, first.text
    artifact_count = db_session.query(ExportArtifact).filter_by(project_id=run.project_id).count()
    second = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=auth_headers,
        json={"final_version_id": page.id, "channel": "smartstore"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["html_download_url"] == first.json()["html_download_url"]
    assert second.json()["zip_download_url"] == first.json()["zip_download_url"]
    current_html = client.get(first.json()["html_download_url"], headers=auth_headers)
    current_zip = client.get(first.json()["zip_download_url"], headers=auth_headers)
    assert current_html.status_code == 200, current_html.text
    assert current_zip.status_code == 200, current_zip.text
    assert db_session.query(ExportArtifact).filter_by(project_id=run.project_id).count() == artifact_count
    # Export request history is intentionally append-only, but frozen output
    # artifacts and promotion authority are not duplicated.
    assert db_session.query(ExportJob).filter_by(project_id=run.project_id).count() == 2
    assert db_session.query(QualityPromotionVersion).filter_by(project_id=run.project_id).count() == 1

    wrong_channel = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=auth_headers,
        json={"final_version_id": page.id, "channel": "coupang"},
    )
    assert wrong_channel.status_code == 409, wrong_channel.text
    assert wrong_channel.json()["detail"]["code"] == "quality_gate_blocked"
    assert db_session.query(ExportArtifact).filter_by(project_id=run.project_id).count() == artifact_count


def _ordinary_project_asset(db_session, *, project_id: str, tmp_path) -> Asset:
    path = tmp_path / f"ordinary-{project_id}.png"
    path.write_bytes(b"ordinary seller-owned asset")
    asset = Asset(
        project_id=project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename=path.name,
        file_path=str(path),
        mime_type="image/png",
        file_size=path.stat().st_size,
    )
    db_session.add(asset)
    db_session.flush()
    return asset


def test_ordinary_asset_download_is_not_subject_to_quality_promotion_gate(client, auth_headers, db_session, tmp_path):
    lineage, _page, _report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    asset = _ordinary_project_asset(db_session, project_id=lineage["run"].project_id, tmp_path=tmp_path)

    response = client.get(f"/api/v1/files/assets/{asset.id}", headers=auth_headers)

    assert response.status_code == 200, response.text


def test_non_promoted_lg12_export_asset_is_blocked_from_generic_asset_endpoint(client, auth_headers, db_session, tmp_path):
    lineage, page, _report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    asset = _ordinary_project_asset(db_session, project_id=lineage["run"].project_id, tmp_path=tmp_path)
    db_session.add(ExportArtifact(
        project_id=lineage["run"].project_id,
        version_id=page.id,
        artifact_type="lg10_copyable_html:smartstore",
        file_path=asset.file_path,
    ))
    db_session.flush()

    response = client.get(f"/api/v1/files/assets/{asset.id}", headers=auth_headers)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "quality_gate_blocked"


def test_wrong_channel_lg12_export_asset_is_blocked_from_generic_asset_endpoint(client, auth_headers, db_session, tmp_path):
    lineage, page, _report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    run = lineage["run"]
    promote_current_quality_page(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=page.id,
    )
    asset = _ordinary_project_asset(db_session, project_id=run.project_id, tmp_path=tmp_path)
    db_session.add(ExportArtifact(
        project_id=run.project_id,
        version_id=page.id,
        artifact_type="lg10_copyable_html:coupang",
        file_path=asset.file_path,
    ))
    db_session.flush()

    response = client.get(f"/api/v1/files/assets/{asset.id}", headers=auth_headers)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "quality_gate_blocked"


def test_cross_project_export_artifact_download_cannot_be_injected(client, auth_headers, db_session, tmp_path):
    lineage, page, _report = _pass_fixture(
        client, auth_headers, db_session, tmp_path, product_name="LG-12 source export artifact",
    )
    run = lineage["run"]
    promote_current_quality_page(
        db_session, workspace_id=run.workspace_id, project_id=run.project_id,
        actor_id=run.created_by, requested_page_id=page.id,
    )
    exported = client.post(
        f"/api/v1/projects/{run.project_id}/page/export/standalone",
        headers=auth_headers,
        json={"final_version_id": page.id, "channel": "smartstore"},
    )
    assert exported.status_code == 200, exported.text
    asset_id = exported.json()["zip_download_url"].rsplit("/", 1)[-1]
    other = build_valid_lg12_master_lineage(
        client, auth_headers, db_session, product_name="LG-12 foreign artifact target",
    )
    cross_project = client.get(
        f"/api/v1/projects/{other['run'].project_id}/page/export/download/{asset_id}",
        headers=auth_headers,
    )
    assert cross_project.status_code == 404


def test_promotion_endpoint_rejects_forged_or_cross_scope_page(client, auth_headers, db_session, tmp_path):
    lineage, page, _report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    run = lineage["run"]
    forged = client.post(
        f"/api/v1/projects/{run.project_id}/page/promotion",
        headers=auth_headers,
        json={"detail_page_version_id": "not-a-persisted-page"},
    )
    assert forged.status_code == 409
    success = client.post(
        f"/api/v1/projects/{run.project_id}/page/promotion",
        headers=auth_headers,
        json={"detail_page_version_id": page.id},
    )
    assert success.status_code == 201, success.text
    replay = client.post(
        f"/api/v1/projects/{run.project_id}/page/promotion",
        headers=auth_headers,
        json={"detail_page_version_id": page.id},
    )
    assert replay.status_code == 201
    assert replay.json()["promotion_id"] == success.json()["promotion_id"]


def test_pending_rework_blocks_a_historical_pass_promotion(client, auth_headers, db_session, tmp_path):
    lineage, page, _report = _pass_fixture(client, auth_headers, db_session, tmp_path)
    run = lineage["run"]
    run.current_stage = "quality_selective_rework"
    run.status = "running"
    db_session.flush()
    response = client.post(
        f"/api/v1/projects/{run.project_id}/page/promotion",
        headers=auth_headers,
        json={"detail_page_version_id": page.id},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "quality_gate_blocked"


def test_fail_quality_status_is_preserved_when_run_projection_looks_failed(client, auth_headers, db_session, tmp_path):
    """A valid immutable FAIL must not become a generic NEEDS_REVIEW error."""

    lineage, page, _report, bar = _quality_fixture(
        client, auth_headers, db_session, tmp_path, verdict="FAIL",
    )
    assert bar["routing_code"] == "COPY_REWORK"
    run = lineage["run"]
    # Simulate only a stale infrastructure projection. The frozen QA result
    # remains the seller-facing source of truth while the run is repaired.
    run.current_stage = "seed_reset"
    run.status = "failed"
    db_session.flush()

    response = client.get(
        f"/api/v1/projects/{run.project_id}/quality-status", headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["quality_verdict"] == "FAIL"
    assert payload["status"] == "needs_attention"
    assert payload["promotion_status"] == "blocked"
    assert payload["review_required"] is False
    assert payload["export_readiness"] == {"smartstore": False}
    assert db_session.query(QualityPromotionVersion).filter_by(project_id=run.project_id).count() == 0
    assert page.is_final is True


def test_needs_review_quality_status_exposes_bounded_review_state(client, auth_headers, db_session, tmp_path):
    lineage, page, _report, bar = _quality_fixture(
        client, auth_headers, db_session, tmp_path, verdict="NEEDS_REVIEW",
    )
    run = lineage["run"]
    run.current_stage = "quality_review"
    run.status = "awaiting_review"
    db_session.flush()

    response = client.get(
        f"/api/v1/projects/{run.project_id}/quality-status", headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["quality_verdict"] == "NEEDS_REVIEW"
    assert payload["status"] == "needs_attention"
    assert payload["review_required"] is True
    assert payload["promotion_status"] == "blocked"
    assert payload["export_readiness"] == {"smartstore": False}
    assert page.is_final is True
