"""TASK-12.5 deterministic frozen Korean-copy/readability evaluator."""

from __future__ import annotations

import pytest

from src.db.models import AgentRun, DetailPageVersion, ImageGenerationCostApprovalRecord, ImageGenerationJobRecord, ImageGenerationOutboxRecord
from src.services.product_intake_version_service import create_seller_confirmation_version
from src.services.prompt_intelligence_service import canonical_hash
from src.services.quality_assessment_service import (
    KOREAN_COPY_READABILITY_EVALUATOR_VERSION,
    QualityAssessmentContractError,
    create_quality_threshold_profile,
    evaluate_korean_copy_readability_domain,
)
from test_lg12_quality_report_contract import _profile_payload, _report_payload
from test_lg12i_version_contract import _create_master, _ref, _run, _source_truth_confirmation, auth_headers as _headers


@pytest.fixture
def auth_headers():
    return _headers.__wrapped__()


def _copy_ref():
    return {
        "artifact_key": "copywriting", "schema_version": "lg10-copywriting-v1",
        "artifact_hash": canonical_hash({"fixture": "copywriting"}),
    }


def _frozen_copy_page(db, run, master, sections, *, renderer_sections=None):
    copy_ref = _copy_ref()
    canonical_sections = [
        {
            "section_id": section["section_id"],
            "copy_ref": {**copy_ref, "fields": [item["field"] for item in section["text_layer"]]},
            "approved_assets": [],
        }
        for section in sections
    ]
    manifest_body = {"schema_version": "lg10-approved-asset-manifest-v1", "assets": []}
    manifest = {**manifest_body, "manifest_hash": canonical_hash(manifest_body)}
    snapshot_body = {
        "schema_version": "lg10-detail-page-version-v1",
        "lg10": {
            "canonical_page_assembly_input": {
                "planning_refs": {"copy": copy_ref}, "approved_asset_manifest": manifest,
                "sections": canonical_sections,
            },
            "canonical_rendering": {
                "schema_version": "lg10-canonical-render-v1",
                "sections": sections if renderer_sections is None else renderer_sections,
            },
        },
        "lg12_quality_lineage": {
            "schema_version": "lg12-detail-page-quality-lineage-v1", "creator_run_id": run.id,
            "source_snapshot_ref": _ref(master.source_snapshot_version_id, master.source_snapshot_version, master.source_snapshot_hash),
            "truth_ref": _ref(master.truth_version_id, master.truth_version, master.truth_version_hash),
            "confirmation_ref": _ref(master.confirmation_version_id, master.confirmation_version, master.confirmation_version_hash),
            "master_ref": _ref(master.id, master.version, master.canonical_hash),
            "approved_asset_manifest_ref": dict(master.approved_asset_manifest_ref_json or {}),
        },
        "commerce_renderer": {"sections": []}, "sections": canonical_sections,
    }
    page = DetailPageVersion(
        project_id=run.project_id, name="LG12 frozen copy fixture", style_key="balanced_sale", is_final=True,
        sections_json={**snapshot_body, "snapshot_hash": canonical_hash(snapshot_body)},
    )
    db.add(page); db.flush()
    return page, manifest["manifest_hash"]


def _setup(db, client, headers, tmp_path, *, sections=None, renderer_sections=None):
    run = _run(client, headers, db, tmp_path)
    source, truth, initial = _source_truth_confirmation(db, run)
    confirmation = create_seller_confirmation_version(
        db, workspace_id=run.workspace_id, project_id=run.project_id, creator_run_id=run.id,
        created_by=run.created_by, truth_reference=_ref(truth.id, truth.version, truth.canonical_hash),
        answers=[], confirmed_fact_refs=[], rejected_fact_refs=[], unknown_fact_refs=[], rights_confirmations=[],
        parent_confirmation_reference=_ref(initial.id, initial.version, initial.canonical_hash), confirmation_cycle=2,
    )
    master = _create_master(db, run, chain=(source, truth, confirmation))
    sections = sections or [
        {"section_id": "hero", "canvas": {"is_visible": True}, "text_layer": [
            {"field": "hero_title", "text": "매일 쓰기 좋은 보온 텀블러"},
            {"field": "hero_body", "text": "필요한 정보를 간결하게 확인해 보세요."},
            {"field": "hero_cta", "text": "제품 자세히 보기"},
        ]},
    ]
    page, manifest_hash = _frozen_copy_page(db, run, master, sections, renderer_sections=renderer_sections)
    profile = create_quality_threshold_profile(
        db, workspace_id=run.workspace_id, project_id=run.project_id,
        payload=_profile_payload("profile:korean-copy"),
    )
    db.commit()
    return run, master, page, manifest_hash, profile


def _evaluate(db, run, master, page, manifest_hash, profile):
    return evaluate_korean_copy_readability_domain(
        db, report_payload=_report_payload(
            run, page, manifest_hash, master, profile,
            report_id=f"test-report:{run.id}:{page.id}",
        ),
    )


def _codes(result):
    return {item["code"] for item in result["domain"]["findings"]}


def test_valid_frozen_korean_copy_is_deterministic_reference_only_and_provider_free(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path)
    before = (
        db_session.query(ImageGenerationJobRecord).count(), db_session.query(ImageGenerationOutboxRecord).count(),
        db_session.query(ImageGenerationCostApprovalRecord).count(),
    )
    first = _evaluate(db_session, run, master, page, digest, profile)
    second = _evaluate(db_session, run, master, page, digest, profile)
    assert first == second
    assert first["domain"]["status"] == "complete"
    assert first["domain"]["evaluator_version"] == KOREAN_COPY_READABILITY_EVALUATOR_VERSION
    assert first["domain"]["human_rubric"] == {"status": "not_requested"}
    assert "매일 쓰기 좋은" not in repr(first)
    finding_ids = [item["finding_id"] for item in first["domain"]["findings"]]
    assert len(finding_ids) == len(set(finding_ids))
    assert before == (
        db_session.query(ImageGenerationJobRecord).count(), db_session.query(ImageGenerationOutboxRecord).count(),
        db_session.query(ImageGenerationCostApprovalRecord).count(),
    )


@pytest.mark.parametrize(
    ("field", "text", "code"),
    [
        ("hero_title", "가" * 37, "overlong_headline"),
        ("hero_subtitle", "가" * 91, "overlong_subheadline"),
    ],
)
def test_role_aware_length_findings(client, db_session, auth_headers, tmp_path, field, text, code):
    sections = [{"section_id": "hero", "text_layer": [{"field": field, "text": text}]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert code in _codes(result)
    finding = next(item for item in result["domain"]["findings"] if item["code"] == code)
    references = {item["id"]: item for item in finding["target_refs"]}
    assert "hero" in references
    assert f"copy-field:hero:{field}" in references
    artifact_ref = references["copy-artifact:copywriting:hero"]
    assert artifact_ref["version"] == "lg10-copywriting-v1"
    assert artifact_ref["hash"] == _copy_ref()["artifact_hash"]


def test_only_source_backed_headline_and_subcopy_length_limits_apply(client, db_session, auth_headers, tmp_path):
    sections = [{"section_id": "hero", "text_layer": [
        {"field": "hero_title", "text": "가" * 36},
        {"field": "hero_subtitle", "text": "나" * 90},
        {"field": "hero_body", "text": "다" * 91},
        {"field": "hero_bullet", "text": "라" * 91},
        {"field": "hero_cta", "text": "상품의 상세 구성과 사용 방법 및 보관 안내를 확인한 뒤 필요한 옵션을 선택하고 구매하기"},
        {"field": "hero_badge", "text": "한정 구성과 제공 혜택 및 제품 선택 전 확인 사항을 자세히 안내합니다"},
    ]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    codes = _codes(_evaluate(db_session, run, master, page, digest, profile))
    assert not {
        "overlong_headline", "overlong_subheadline", "overlong_body", "overlong_bullet", "overlong_cta", "overlong_badge",
    } & codes


@pytest.mark.parametrize(
    ("field", "text"),
    [
        ("hero_cta", "상품의 상세 구성과 사용 방법 및 보관 안내를 확인한 뒤 필요한 옵션을 선택하고 구매하기"),
        ("hero_badge", "한정 구성과 제공 혜택 및 제품 선택 전 확인 사항을 자세히 안내합니다"),
    ],
)
def test_cta_and_badge_have_no_unsourced_numeric_length_gate(client, db_session, auth_headers, tmp_path, field, text):
    sections = [{"section_id": "hero", "text_layer": [{"field": field, "text": text}]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    assert not any(code.startswith("overlong_") for code in _codes(_evaluate(db_session, run, master, page, digest, profile)))


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "missing_copy_role"),
        ("<broken> \ufffd", "broken_korean_text"),
        ("상품 你好", "foreign_language_mix"),
        ("좋아요   정말 좋아요", "spacing_inconsistency"),
        ("지금 구매하세요!!!", "punctuation_overuse"),
        ("😀😀😀 제품 보기", "emphasis_overuse"),
    ],
)
def test_language_and_spacing_findings(client, db_session, auth_headers, tmp_path, text, code):
    sections = [{"section_id": "hero", "text_layer": [{"field": "hero_title", "text": text}]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert code in _codes(result)
    if code == "missing_copy_role":
        assert result["domain"]["status"] == "needs_review"


def test_permitted_english_brand_model_does_not_trip_language_mixing(client, db_session, auth_headers, tmp_path):
    sections = [{"section_id": "hero", "text_layer": [
        {"field": "hero_title", "text": "FAN PRO JET 무선 선풍기"},
        {"field": "hero_cta", "text": "제품 보기"},
    ]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    assert "foreign_language_mix" not in _codes(_evaluate(db_session, run, master, page, digest, profile))


def test_excessive_promotional_tone_is_a_noncritical_copy_finding(client, db_session, auth_headers, tmp_path):
    sections = [{"section_id": "hero", "text_layer": [
        {"field": "hero_title", "text": "무조건 사야 하는 최고의 선택"},
        {"field": "hero_cta", "text": "상품 보기"},
    ]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "excessive_promotional_tone" in _codes(result)
    assert result["critical_violations"] == []


def test_normal_promotional_cta_does_not_trigger_excessive_tone(client, db_session, auth_headers, tmp_path):
    sections = [{"section_id": "hero", "text_layer": [
        {"field": "hero_title", "text": "오늘의 상품 구성 안내"},
        {"field": "hero_cta", "text": "지금 상품 자세히 보기"},
    ]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    assert "excessive_promotional_tone" not in _codes(_evaluate(db_session, run, master, page, digest, profile))


def test_repetition_headline_cta_and_sentence_are_structured(client, db_session, auth_headers, tmp_path):
    sections = [
        {"section_id": "hero", "text_layer": [
            {"field": "hero_title", "text": "강력한 바람"}, {"field": "hero_cta", "text": "제품 보기"},
        ]},
        {"section_id": "feature", "text_layer": [
            {"field": "feature_title", "text": "강력한 바람"}, {"field": "feature_body", "text": "매일 편하게 사용하세요. 매일 편하게 사용하세요."},
            {"field": "feature_cta", "text": "제품 보기"},
        ]},
    ]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    codes = _codes(_evaluate(db_session, run, master, page, digest, profile))
    assert {"duplicate_headline", "duplicate_cta", "repeated_sentence"} <= codes


@pytest.mark.parametrize(
    ("cta", "code"), [("", "missing_copy_role"), ("좋은 선택입니다", "cta_action_unclear")],
)
def test_cta_requires_nonempty_action_intent(client, db_session, auth_headers, tmp_path, cta, code):
    sections = [{"section_id": "cta", "text_layer": [{"field": "cta", "text": cta}]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    assert code in _codes(_evaluate(db_session, run, master, page, digest, profile))


def test_numeric_unit_style_checks_readability_not_factual_validity(client, db_session, auth_headers, tmp_path):
    sections = [{"section_id": "spec", "text_layer": [
        {"field": "spec_body", "text": "용량은 600ml이며 무게는 1 kg입니다."},
        {"field": "spec_bullet", "text": "추가 표기는 600 ml입니다."},
    ]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert "numeric_unit_spacing_inconsistency" in _codes(result)
    assert result["critical_violations"] == []


def test_missing_required_body_is_sparse_and_needs_review(client, db_session, auth_headers, tmp_path):
    sections = [{"section_id": "feature", "text_layer": [
        {"field": "feature_title", "text": "매일 편하게 사용하는 방법"},
        {"field": "feature_body", "text": ""},
    ]}]
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path, sections=sections)
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "needs_review"
    assert "missing_copy_role" in _codes(result)
    body_density = next(item for item in result["domain"]["submetrics"] if item["metric_id"] == "body_density")
    assert body_density["status"] == "failed"


def test_changed_frozen_copy_has_a_new_deterministic_result(client, db_session, auth_headers, tmp_path):
    run, master, first_page, digest, profile = _setup(db_session, client, auth_headers, tmp_path)
    changed_sections = [{"section_id": "hero", "text_layer": [
        {"field": "hero_title", "text": "가" * 37},
        {"field": "hero_body", "text": "간결한 안내 문구입니다."},
        {"field": "hero_cta", "text": "제품 보기"},
    ]}]
    changed_page, changed_digest = _frozen_copy_page(db_session, run, master, changed_sections)
    db_session.commit()
    before = _evaluate(db_session, run, master, first_page, digest, profile)
    changed = _evaluate(db_session, run, master, changed_page, changed_digest, profile)
    assert before != changed
    assert "overlong_headline" in _codes(changed)
    assert changed == _evaluate(db_session, run, master, changed_page, changed_digest, profile)


def test_cross_run_master_injection_is_rejected(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path)
    response = client.post("/api/agent-runs", headers=auth_headers, json={
        "product_name": "LG12 foreign copy lineage fixture",
        "description": "Isolated lineage fixture.",
    })
    assert response.status_code == 201, response.text
    foreign_run = db_session.query(AgentRun).filter_by(id=response.json()["id"]).one()
    source, truth, initial = _source_truth_confirmation(db_session, foreign_run)
    confirmation = create_seller_confirmation_version(
        db_session, workspace_id=foreign_run.workspace_id, project_id=foreign_run.project_id,
        creator_run_id=foreign_run.id, created_by=foreign_run.created_by,
        truth_reference=_ref(truth.id, truth.version, truth.canonical_hash), answers=[],
        confirmed_fact_refs=[], rejected_fact_refs=[], unknown_fact_refs=[], rights_confirmations=[],
        parent_confirmation_reference=_ref(initial.id, initial.version, initial.canonical_hash), confirmation_cycle=2,
    )
    foreign_master = _create_master(db_session, foreign_run, chain=(source, truth, confirmation))
    db_session.commit()
    assert foreign_run.id != run.id
    payload = _report_payload(run, page, digest, master, profile)
    payload["input_lineage"]["master_ref"] = _ref(foreign_master.id, foreign_master.version, foreign_master.canonical_hash)
    with pytest.raises(QualityAssessmentContractError):
        evaluate_korean_copy_readability_domain(db_session, report_payload=payload)


def test_mutable_run_copy_output_does_not_change_frozen_result(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _setup(db_session, client, auth_headers, tmp_path)
    before = _evaluate(db_session, run, master, page, digest, profile)
    run.outputs_json = {"commerce": {"copywriting": {"output": {"hero_title": "MUTATED"}, "metadata": {"artifact_hash": "0" * 64}}}}
    db_session.commit()
    assert _evaluate(db_session, run, master, page, digest, profile) == before


def test_missing_frozen_renderer_copy_cannot_complete(client, db_session, auth_headers, tmp_path):
    run, master, page, digest, profile = _setup(
        db_session, client, auth_headers, tmp_path,
        renderer_sections=[],
    )
    result = _evaluate(db_session, run, master, page, digest, profile)
    assert result["domain"]["status"] == "needs_review"
    assert "missing_renderer_copy" in _codes(result)
