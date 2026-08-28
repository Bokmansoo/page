"""TASK-12.12 opt-in-only real-provider smoke through the existing LG-9 worker path."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from PIL import Image

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.config import settings
from src.db.models import Asset, DetailPageVersion, ImageGenerationCostApprovalRecord, ImageGenerationJobRecord, ImageGenerationOutboxRecord, QualityAssessmentReportVersion
from src.schemas.lg12_product_intake_golden_dataset import load_product_intake_golden_dataset
from src.services.image_generation_worker import run_image_worker_batch
from src.services.product_identity_validator import MIN_RECOMMENDED_EDGE
from test_lg12_fake_quality_gate_postgres import auth_headers, postgres_runtime  # noqa: F401
from test_lg12_quality_graph_integration import (
    _build_quality_evidence_page,
    _invoke_compiled_quality_pass_path,
    aggregate_valid_lg12_quality_bar,
    attach_valid_lg12_channel_parity_evidence,
    attach_valid_lg12_copy_evidence,
    attach_valid_lg12_layout_evidence,
    build_image_identity_failure_fixture,
    build_valid_lg12_frozen_detail_page,
    build_valid_lg12_master_lineage,
    build_valid_lg12_page_plan,
    evaluate_all_lg12_quality_domains,
    _write_deterministic_png,
)


pytestmark = [pytest.mark.postgres, pytest.mark.integration, pytest.mark.lg12_real_provider_smoke]


REAL_SMOKE_MODEL = "gpt-image-1-mini"
REAL_SMOKE_OUTPUT_SIZE = "1024x1024"
REAL_SMOKE_OUTPUT_QUALITY = "medium"
REAL_SMOKE_OUTPUT_COST_USD = 0.011
REAL_SMOKE_MAX_PROVIDER_DISPATCHES = 1
LOCAL_DATABASE_ENVIRONMENT_KEYS = (
    "DATABASE_URL",
    "TEST_DATABASE_URL",
    "E2E_DATABASE_URL",
    "SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL",
)


def _require_local_real_smoke_environment() -> str:
    """Fail closed unless every mutable integration endpoint is the local test DB."""

    test_url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    for key in LOCAL_DATABASE_ENVIRONMENT_KEYS:
        if os.environ.get(key) != test_url:
            raise RuntimeError(f"TASK-12.12 real smoke requires {key} to equal local TEST_DATABASE_URL.")
    return test_url


def _require_local_real_smoke_storage(path: Path, *, local_root: Path) -> Path:
    """Keep real-smoke artifacts in pytest's local temporary directory only."""

    raw_path = str(path).replace("\\", "/").lower()
    if "://" in raw_path or raw_path.startswith(("s3:", "gs:", "http:", "https:")):
        raise RuntimeError("TASK-12.12 real smoke refuses remote artifact storage.")
    resolved = path.resolve()
    try:
        resolved.relative_to(local_root.resolve())
    except ValueError as exc:
        raise RuntimeError("TASK-12.12 real smoke requires local pytest artifact storage.") from exc
    return resolved


def _real_smoke_cost_preflight(source_image: Path) -> dict[str, object]:
    """Describe the exact request without dispatching it or guessing edit-input token cost."""

    with Image.open(source_image) as image:
        image.load()
        source = {
            "count": 1,
            "dimensions": [image.width, image.height],
            "format": image.format,
            "bytes": source_image.stat().st_size,
            "preprocessing": "none",
        }
    return {
        "provider": "openai",
        "model": REAL_SMOKE_MODEL,
        "endpoint": "images.edit",
        "source": source,
        "scene_count": 1,
        "image_count": 1,
        "output_size": REAL_SMOKE_OUTPUT_SIZE,
        "quality": REAL_SMOKE_OUTPUT_QUALITY,
        "output_cost_usd": REAL_SMOKE_OUTPUT_COST_USD,
        "credential_configured": bool(os.getenv("OPENAI_API_KEY")),
        # OpenAI's published model pricing does not specify an upper bound for
        # image-edit input tokens, so a finite all-in spend ceiling is unknown.
        "max_estimated_cost_usd": None,
        "status": "BLOCKED_COST_UNBOUNDED",
        "max_provider_dispatches": REAL_SMOKE_MAX_PROVIDER_DISPATCHES,
    }

def _skip_reason() -> str | None:
    if os.getenv("SELLFORM_RUN_REAL_PROVIDER_SMOKE") != "1":
        return "Set SELLFORM_RUN_REAL_PROVIDER_SMOKE=1 to permit one billed LG-12 provider request."
    if not os.getenv("OPENAI_API_KEY"):
        return "OPENAI_API_KEY is required after explicit real-provider opt-in."
    return None


def test_lg12_real_provider_smoke_guard_is_safe_without_opt_in_or_credential(monkeypatch):
    monkeypatch.delenv("SELLFORM_RUN_REAL_PROVIDER_SMOKE", raising=False)
    assert _skip_reason() and "SELLFORM_RUN_REAL_PROVIDER_SMOKE" in _skip_reason()
    monkeypatch.setenv("SELLFORM_RUN_REAL_PROVIDER_SMOKE", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _skip_reason() and "OPENAI_API_KEY" in _skip_reason()


def test_lg12_real_provider_preflight_fails_closed_for_remote_targets_and_unbounded_edit_cost(tmp_path, monkeypatch):
    """No provider, outbox, database, or credential dispatch occurs in preflight."""

    local_url = "postgresql+psycopg://sellform_test:test-only-password@127.0.0.1:5433/sellform_test"
    monkeypatch.setenv("SELLFORM_ALLOW_TEST_DATABASE", "1")
    for key in LOCAL_DATABASE_ENVIRONMENT_KEYS:
        monkeypatch.setenv(key, local_url)
    assert _require_local_real_smoke_environment() == local_url
    monkeypatch.setenv("E2E_DATABASE_URL", "postgresql+psycopg://x:x@db.example.com:5432/sellform")
    with pytest.raises(RuntimeError, match="E2E_DATABASE_URL"):
        _require_local_real_smoke_environment()
    monkeypatch.setenv("E2E_DATABASE_URL", local_url)

    local_storage = _require_local_real_smoke_storage(tmp_path / "real-provider-output", local_root=tmp_path)
    assert local_storage.parent == tmp_path.resolve()
    with pytest.raises(RuntimeError, match="remote artifact storage"):
        _require_local_real_smoke_storage(Path("s3://bucket/object.png"), local_root=tmp_path)

    source_path, _ = _write_deterministic_png(tmp_path)
    preflight = _real_smoke_cost_preflight(source_path)
    assert preflight["source"] == {
        "count": 1,
        "dimensions": [800, 800],
        "format": "PNG",
        "bytes": source_path.stat().st_size,
        "preprocessing": "none",
    }
    assert preflight["provider"] == "openai"
    assert preflight["model"] == REAL_SMOKE_MODEL
    assert preflight["scene_count"] == preflight["image_count"] == REAL_SMOKE_MAX_PROVIDER_DISPATCHES
    assert preflight["output_size"] == REAL_SMOKE_OUTPUT_SIZE
    assert preflight["quality"] == REAL_SMOKE_OUTPUT_QUALITY
    assert preflight["output_cost_usd"] == REAL_SMOKE_OUTPUT_COST_USD
    assert isinstance(preflight["credential_configured"], bool)
    assert preflight["max_estimated_cost_usd"] is None
    assert preflight["status"] == "BLOCKED_COST_UNBOUNDED"
    print(
        "TASK-12.12 preflight "
        "database=127.0.0.1:5433/sellform_test "
        "checkpoint=127.0.0.1:5433/sellform_test storage=pytest-local-temp "
        f"credential_configured={preflight['credential_configured']} "
        f"source={preflight['source']} provider={preflight['provider']} "
        f"model={preflight['model']} output={preflight['output_size']}/{preflight['quality']} "
        f"output_cost_usd={preflight['output_cost_usd']} "
        f"max_estimated_cost_usd={preflight['max_estimated_cost_usd']} "
        f"provider_requests_before=0 provider_requests_after=0 status={preflight['status']}"
    )


def test_lg12_real_provider_one_scene_uses_cost_outbox_worker_and_quality_contract(request, tmp_path, monkeypatch):
    """Run only after explicit opt-in; default pytest exits before any provider setup."""

    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    pytest.skip("BLOCKED_COST_UNBOUNDED: no published upper bound for GPT Image edit-input token billing.")
    url, client, db = request.getfixturevalue("postgres_runtime")
    auth_headers = request.getfixturevalue("auth_headers")
    representative_case = next(case for case in load_product_intake_golden_dataset()["cases"] if case["input_mode"] == "manual")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", os.environ["OPENAI_API_KEY"])
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(_require_local_real_smoke_storage(tmp_path / "real-provider-output", local_root=tmp_path)))

    lineage = build_valid_lg12_master_lineage(client, auth_headers, db, product_name=f"LG-12 real smoke {representative_case['case_id']}")
    page_plan = build_valid_lg12_page_plan(lineage, db)
    build_valid_lg12_frozen_detail_page(lineage, page_plan, db)
    evidence = _build_quality_evidence_page(lineage=lineage, page_plan=page_plan, tmp_path=tmp_path, db_session=db)
    evidence["job"].provider = "openai"
    evidence["job"].model = REAL_SMOKE_MODEL
    evidence["job"].output_size = REAL_SMOKE_OUTPUT_SIZE
    db.add(evidence["job"])
    db.flush()
    source_page = evidence["page"]
    attach_valid_lg12_copy_evidence(page=source_page)
    attach_valid_lg12_layout_evidence(page=source_page)
    attach_valid_lg12_channel_parity_evidence(page=source_page, db_session=db, tmp_path=tmp_path)
    failing_page = build_image_identity_failure_fixture(run=lineage["run"], asset=evidence["asset"], job=evidence["job"], db_session=db)
    attach_valid_lg12_copy_evidence(page=failing_page)
    attach_valid_lg12_layout_evidence(page=failing_page)
    attach_valid_lg12_channel_parity_evidence(page=failing_page, db_session=db, tmp_path=tmp_path)
    failed_report = evaluate_all_lg12_quality_domains(run=lineage["run"], page=failing_page, db_session=db)["qa_report"]
    assert aggregate_valid_lg12_quality_bar(qa_report=failed_report, db_session=db)["quality_bar"]["routing_code"] == "IMAGE_REWORK"

    run = lineage["run"]
    run.mode = "real"
    db.add(run)
    db.commit()
    from src.agents.langgraph_runtime import open_postgres_checkpointer

    with open_postgres_checkpointer(url) as checkpointer:
        invocation = _invoke_compiled_quality_pass_path(run=run, page=failing_page, db_session=db, checkpointer=checkpointer)
        assert invocation["checkpoint"].values["current_stage"] == "generation_pending"
        approval = db.query(ImageGenerationCostApprovalRecord).filter_by(run_id=run.id).one()
        assert approval.provider == "openai" and approval.model == REAL_SMOKE_MODEL
        assert approval.scene_count == 1 and approval.scene_costs[0]["scene_id"] == "hero"
        assert approval.scene_costs[0]["output_size"] == REAL_SMOKE_OUTPUT_SIZE
        approved = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers, json={"thread_id": run.id, "mode": "respond", "response": {"schema_version": "lg5-v1", "review_stage": "generation_pending", "decision": "approve", "cost_plan_hash": approval.cost_plan_hash}})
        assert approved.status_code == 200, approved.text
        deliveries = db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
        jobs = db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
        assert len(deliveries) == len(jobs) == 1
        assert jobs[0].scene_id == "hero" and deliveries[0].provider_dispatch_count == 0

        worker_result = run_image_worker_batch(db, owner="lg12-real-provider-smoke", batch_size=1)
        assert len(worker_result) == 1 and worker_result[0]["status"] == "completed"
        db.expire_all()
        delivery = db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).one()
        job = db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).one()
        asset = db.get(Asset, job.output_asset_id)
        assert delivery.provider_dispatch_count == 1 and delivery.status == "completed"
        assert job.status == "needs_review" and asset is not None
        payload = Path(asset.file_path).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == asset.content_hash
        with Image.open(Path(asset.file_path)) as image:
            assert image.width >= MIN_RECOMMENDED_EDGE and image.height >= MIN_RECOMMENDED_EDGE
            assert image.format

        review = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers).json()
        assert review["current_stage"] == "image_review"
        completed = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers, json={"thread_id": run.id, "mode": "respond", "response": {"schema_version": "lg5-v1", "review_stage": "image_review", "decision": "approve", "job_id": job.job_id}})
        assert completed.status_code == 200, completed.text
        quality_ref = completed.json()["values"]["quality"]["quality_report_ref"]
        report = db.get(QualityAssessmentReportVersion, quality_ref["id"])
        assert report is not None and report.threshold_profile_id and report.report_json["threshold_profile_ref"]
        assert report.report_json["critical_violations"] == []
        assert all(domain["critical_count"] == 0 for domain in report.report_json["domains"])
        assert all(domain["human_rubric"]["status"] == "not_requested" for domain in report.report_json["domains"])
        assert completed.json()["values"]["quality"]["quality_bar_ref"]

        replay = client.post(f"/api/v1/graph-runs/{run.id}/resume", headers=auth_headers, json={"thread_id": run.id, "mode": "respond", "response": {"schema_version": "lg5-v1", "review_stage": "image_review", "decision": "approve", "job_id": job.job_id}})
        assert replay.status_code == 200, replay.text
        assert db.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).one().provider_dispatch_count == 1
        assert db.query(DetailPageVersion).filter_by(project_id=run.project_id).count() >= 2
