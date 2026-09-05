"""LG-11.1 frozen-version EditIntent and deterministic impact preview tests."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from src.db.models import Asset, DetailPageVersion, FactEvidence, ImageGenerationJobRecord, ProductFact
from src.services.page_finalization_service import build_page_assembly_structure
from src.services.renderer import render_lg10_canonical_page_html
from test_lg5_image_generation_subgraph import _create_run, auth_headers as _lg5_auth_headers

pytestmark = pytest.mark.lg11_fake_e2e


def _canonical_hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@pytest.fixture
def auth_headers():
    return _lg5_auth_headers.__wrapped__()


def _frozen_lg10_version(db_session, run) -> tuple[DetailPageVersion, ProductFact, str]:
    """Build only the immutable LG-10 snapshot consumed by the preview endpoint."""

    fact = (
        db_session.query(ProductFact)
        .filter_by(project_id=run.project_id, field_key="rated_input")
        .one()
    )
    evidence = db_session.query(FactEvidence).filter_by(fact_id=fact.id).first()
    asset = next(iter(run.input_snapshot["asset_ids"]))
    asset_row = db_session.query(Asset).filter_by(id=asset).one()
    asset_hash = hashlib.sha256(open(asset_row.file_path, "rb").read()).hexdigest()
    asset_row.content_hash = asset_hash
    job = ImageGenerationJobRecord(
        project_id=run.project_id,
        job_id=f"lg11-approved-{run.id}",
        section_id="hero",
        scene_id="hero-scene",
        role="hero",
        prompt="frozen fake scene",
        status="approved",
        output_asset_id=asset_row.id,
        provider="mock",
        model="durable-fake-image-v1",
        source_asset_ids=list(run.input_snapshot["asset_ids"]),
        estimated_cost=2.0,
        actual_cost=0.0,
    )
    manifest_payload = {
        "run_id": run.id,
        "project_id": run.project_id,
        "assets": [{
            "scene_id": "hero-scene",
            "section_id": "hero",
            "job_id": job.job_id,
            "asset_id": asset_row.id,
            "asset_content_hash": asset_hash,
            "generation_attempt": 1,
        }],
    }
    manifest = {**manifest_payload, "manifest_hash": _canonical_hash(manifest_payload)}
    canonical_input = {
        "schema_version": "lg10-canonical-page-assembly-input-v1",
        "planning_refs": {
            "copy": {
                "artifact_key": "copywriting",
                "schema_version": "lg3-copy-v1",
                "artifact_hash": "a" * 64,
            },
        },
        "run_id": run.id,
        "project_id": run.project_id,
        "design_direction": "balanced_sale",
        "brand_kit_ref": {"brand_kit_version_id": "brand-kit-v1", "brand_kit_hash": "b" * 64},
        "image_generation_contract": {
            "required_scene_count": 1,
            "completion_basis": "approved_required_scenes",
        },
        "approved_asset_manifest": manifest,
        "page_asset_manifest": manifest,
        "sections": [
            {
                "section_id": "hero",
                "sort_order": 0,
                "copy_ref": {
                    "artifact_key": "copywriting",
                    "schema_version": "lg3-copy-v1",
                    "artifact_hash": "a" * 64,
                    "fields": ["hero_title", "hero_subtitle"],
                    "fact_ids": [fact.id],
                    "evidence_ids_by_fact": {fact.id: [evidence.id] if evidence else []},
                },
                "layout_token_ref": {"artifact_key": "page_planning", "artifact_hash": "c" * 64},
                "approved_assets": [{
                    "scene_id": "hero-scene",
                    "section_id": "hero",
                    "asset_id": asset_row.id,
                    "asset_content_hash": asset_hash,
                }],
                "seller_owned_fallback_assets": [],
                "image_required": True,
                "rendering_mode": "approved_asset",
            },
            {
                "section_id": "specs",
                "sort_order": 1,
                "copy_ref": {
                    "artifact_key": "copywriting",
                    "schema_version": "lg3-copy-v1",
                    "artifact_hash": "a" * 64,
                    "fields": ["details_body"],
                    "fact_ids": [fact.id],
                    "evidence_ids_by_fact": {fact.id: [evidence.id] if evidence else []},
                },
                "layout_token_ref": {"artifact_key": "page_planning", "artifact_hash": "c" * 64},
                "approved_assets": [],
                "seller_owned_fallback_assets": [],
                "image_required": False,
                "rendering_mode": "information_only",
            },
        ],
    }
    canonical_input["input_hash"] = _canonical_hash(canonical_input)
    page_assembly = build_page_assembly_structure(canonical_page_assembly_input=canonical_input)
    brand_tokens = {
        "brand_kit_version_id": "brand-kit-v1",
        "color_tokens": {
            "accent": "#0f766e",
            "text": "#172033",
            "surface": "#ffffff",
            "muted_surface": "#eef2f7",
        },
        "typography": {"body_font": "system-ui, sans-serif"},
        "asset_layer": {
            "logo": {"asset_id": asset_row.id, "asset_content_hash": asset_hash},
            "watermark": None,
            "font_assets": [],
        },
        "fallback": False,
    }
    rendering_payload = {
        **render_lg10_canonical_page_html(
            canonical_page_assembly_input=canonical_input,
            page_assembly=page_assembly,
            copy_set={
                "hero_title": "저소음 모터 선풍기",
                "hero_subtitle": "제품을 간단히 소개합니다",
                "details_body": "기존 사양 안내",
            },
            brand_tokens=brand_tokens,
        ),
        "canonical_input_ref": {
            "schema_version": "lg10-canonical-page-assembly-input-v1",
            "input_hash": canonical_input["input_hash"],
        },
        "page_assembly_ref": {
            "schema_version": "lg10-page-assembly-v1",
            "assembly_hash": page_assembly["assembly_hash"],
        },
    }
    rendering = {**rendering_payload, "render_hash": _canonical_hash(rendering_payload)}
    snapshot_payload = {
        "schema_version": "lg10-detail-page-version-v1",
        "lg10": {
            "run_id": run.id,
            "canonical_page_assembly_input": canonical_input,
            "page_assembly": page_assembly,
            "canonical_rendering": rendering,
        },
        "sections": [],
    }
    version = DetailPageVersion(
        project_id=run.project_id,
        name="LG-11 frozen fixture",
        style_key="balanced_sale",
        sections_json={**snapshot_payload, "snapshot_hash": _canonical_hash(snapshot_payload)},
        is_final=True,
    )
    db_session.add_all([job, version])
    db_session.commit()
    return version, fact, asset_row.id


@pytest.mark.parametrize(
    ("scope", "operation", "target_key", "instruction", "expected_artifact"),
    [
        ("copy", "rewrite", "section", "제목을 간결하게 수정해 주세요", "copy_artifact"),
        ("scene", "regenerate", "scene", "대표 장면의 조명을 밝게 바꿔 주세요", "approved_asset_manifest"),
        ("style", "restyle", "version", "강조색을 브랜드 톤으로 변경해 주세요", "brand_kit_tokens"),
        ("fact", "rewrite", "fact", "정격 입력을 DC 5V 2A로 정정해 주세요", "fact_evidence_review"),
    ],
)
def test_lg11_preview_uses_only_frozen_targets_and_has_no_side_effects(
    client, auth_headers, db_session, tmp_path, scope, operation, target_key, instruction, expected_artifact
):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    version, fact, asset_id = _frozen_lg10_version(db_session, run)
    target_ids = {
        "section": ["hero"],
        "scene": ["hero-scene"],
        "version": [version.id],
        "fact": [fact.id],
    }[target_key]
    before_snapshot = deepcopy(version.sections_json)
    before_run_outputs = deepcopy(run.outputs_json)
    before_asset_hash = db_session.query(Asset).filter_by(id=asset_id).one().content_hash
    before_counts = {
        "versions": db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count(),
    }

    response = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview",
        headers=auth_headers,
        json={
            "scope": scope,
            "target_ids": target_ids,
            "operation": operation,
            "instruction": instruction,
            "preserve_constraints": {"retain_approved_assets": True},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    intent = payload["edit_intent"]
    impact = payload["impact_preview"]
    assert intent["schema_version"] == "lg11-edit-intent-v1"
    assert intent["base_detail_page_version_id"] == version.id
    assert intent["target_ids"] == target_ids
    assert intent["intent_hash"] == _canonical_hash({key: value for key, value in intent.items() if key != "intent_hash"})
    assert impact["targets"][0]["target_id"] == target_ids[0]
    assert expected_artifact in impact["stale_artifacts"]
    assert impact["retained_approvals"]["approved_asset_manifest_hash"]
    if scope == "scene":
        assert intent["requires_cost_approval"] is True
        assert impact["expected_provider_cost"]["status"] == "not_available"
        assert impact["expected_provider_cost"]["total"] is None
        assert impact["invalidated_approvals"] == [{"approval_type": "scene", "target_id": "hero-scene"}]
    if scope == "fact":
        assert impact["requires_evidence_review"] is True
        assert impact["requires_explicit_confirmation"] is True
        assert impact["execution_blocked"] is True

    db_session.expire_all()
    assert db_session.query(DetailPageVersion).filter_by(id=version.id).one().sections_json == before_snapshot
    assert db_session.query(type(run)).filter_by(id=run.id).one().outputs_json == before_run_outputs
    assert db_session.query(Asset).filter_by(id=asset_id).one().content_hash == before_asset_hash
    assert {
        "versions": db_session.query(DetailPageVersion).filter_by(project_id=run.project_id).count(),
        "jobs": db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count(),
    } == before_counts


def test_lg11_preview_blocks_unknown_cross_version_and_invalid_operations(client, auth_headers, db_session, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, run)
    other_version = DetailPageVersion(
        project_id=run.project_id,
        name="Other frozen version",
        style_key="balanced_sale",
        sections_json=deepcopy(version.sections_json),
        is_final=False,
    )
    db_session.add(other_version)
    db_session.commit()

    invalid_cases = [
        {"scope": "copy", "target_ids": ["not-in-snapshot"], "operation": "rewrite", "instruction": "문구 수정"},
        {"scope": "scene", "target_ids": ["hero-scene"], "operation": "restyle", "instruction": "장면 수정"},
        {"scope": "page", "target_ids": [other_version.id], "operation": "reorder", "instruction": "순서 변경"},
    ]
    for request in invalid_cases:
        response = client.post(
            f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview",
            headers=auth_headers,
            json=request,
        )
        assert response.status_code == 422, response.text


def test_lg11_preview_requires_confirmation_for_ambiguous_natural_language(client, auth_headers, db_session, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, run)

    response = client.post(
        f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview",
        headers=auth_headers,
        json={
            "scope": "copy",
            "target_ids": ["hero"],
            "operation": "rewrite",
            "instruction": "이거 전체적으로 알아서 좋게 바꿔 주세요",
        },
    )

    assert response.status_code == 200, response.text
    impact = response.json()["impact_preview"]
    assert impact["requires_explicit_confirmation"] is True
    assert impact["execution_blocked"] is True
    assert "ambiguous_instruction" in impact["confirmation_reasons"]


def test_lg11_preview_cost_and_structured_identities_are_frozen(client, auth_headers, db_session, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    version, fact, asset_id = _frozen_lg10_version(db_session, run)
    endpoint = f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview"
    request = {
        "scope": "scene",
        "target_ids": ["hero-scene"],
        "operation": "regenerate",
        "instruction": "대표 장면의 조명을 밝게 바꿔 주세요",
    }
    first = client.post(endpoint, headers=auth_headers, json=request)
    assert first.status_code == 200, first.text

    # A later mutable job-cost change must not change the preview of this frozen version.
    db_session.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).one().estimated_cost = 999.0
    db_session.commit()
    second = client.post(endpoint, headers=auth_headers, json=request)
    assert second.status_code == 200, second.text
    assert second.json()["impact_preview"]["expected_provider_cost"] == first.json()["impact_preview"]["expected_provider_cost"]

    impact = first.json()["impact_preview"]
    affected = impact["affected_artifacts"]
    assert affected["section_ids"] == ["hero"]
    assert affected["scene_ids"] == ["hero-scene"]
    assert affected["assets"] == [{
        "asset_id": asset_id,
        "asset_content_hash": db_session.query(Asset).filter_by(id=asset_id).one().content_hash,
        "scene_id": "hero-scene",
        "section_id": "hero",
    }]
    assert affected["copy_artifacts"][0]["artifact_hash"] == "a" * 64
    assert affected["brand_kit"]["brand_kit_hash"] == "b" * 64
    assert affected["brand_kit"]["assets"]["logo"]["asset_id"] == asset_id
    assert affected["style_layout_tokens"][0]["layout_token_ref"]["artifact_hash"] == "c" * 64

    fact_response = client.post(
        endpoint,
        headers=auth_headers,
        json={
            "scope": "copy",
            "target_ids": ["hero"],
            "operation": "rewrite",
            "instruction": "무게를 150g으로 바꿔줘",
        },
    )
    assert fact_response.status_code == 200, fact_response.text
    fact_impact = fact_response.json()["impact_preview"]
    assert fact_impact["requires_evidence_review"] is True
    assert fact_impact["requires_explicit_confirmation"] is True
    assert fact_impact["affected_artifacts"]["facts"][0]["fact_id"] == fact.id
    assert fact_impact["affected_artifacts"]["facts"][0]["evidence_ids"]


def test_lg11_preview_copy_rewrite_and_snapshot_hash_guard(client, auth_headers, db_session, tmp_path):
    run = _create_run(client, auth_headers, db_session, tmp_path)
    version, _, _ = _frozen_lg10_version(db_session, run)
    endpoint = f"/api/v1/projects/{run.project_id}/page/versions/{version.id}/edit-intents/preview"
    request = {
        "scope": "copy",
        "target_ids": ["hero"],
        "operation": "rewrite",
        "instruction": "제목을 간결하게 다듬어 주세요",
    }
    valid = client.post(endpoint, headers=auth_headers, json=request)
    assert valid.status_code == 200, valid.text
    assert valid.json()["impact_preview"]["requires_evidence_review"] is False

    tampered = deepcopy(version.sections_json)
    tampered["lg10"]["canonical_page_assembly_input"]["sections"][0]["section_id"] = "altered-hero"
    version.sections_json = tampered
    db_session.commit()
    blocked = client.post(endpoint, headers=auth_headers, json=request)
    assert blocked.status_code == 422
    assert "frozen LG-10 DetailPageVersion" in blocked.json()["detail"]
