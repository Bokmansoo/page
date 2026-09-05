"""One explicitly opt-in paid LG-11 scene-edit smoke test."""

from __future__ import annotations

import os

import pytest

from test_lg11_edit_intent_preview import _frozen_lg10_version
from test_lg11_scene_edit_regeneration import (
    _make_source_dispatchable,
    _resume,
    _scene_request,
    _start_scene_edit,
    auth_headers,
    lg11_runtime,
)
from test_lg5_image_generation_subgraph import _create_run


@pytest.mark.lg11_real_provider_smoke
def test_lg11_real_provider_scene_edit_requires_explicit_opt_in(
    client, auth_headers, db_session, lg11_runtime, monkeypatch, tmp_path,
):
    """Use the production LG-11 cost/outbox/worker flow for exactly one scene."""

    if os.getenv("SELLFORM_RUN_REAL_PROVIDER_SMOKE") != "1":
        pytest.skip("Set SELLFORM_RUN_REAL_PROVIDER_SMOKE=1 to permit a billed provider request.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY is required for the real-provider smoke test.")

    from src.config import settings
    from src.db.database import SessionLocal
    from src.db.models import DetailPageVersion, ImageGenerationOutboxRecord
    from src.services.image_generation_worker import run_image_worker_batch

    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", api_key)
    run = _create_run(client, auth_headers, db_session, tmp_path, mode="real")
    source, _, _ = _frozen_lg10_version(db_session, run)
    _make_source_dispatchable(db_session, run)

    started, state = _start_scene_edit(
        client, auth_headers, run, source, _scene_request(operation="regenerate"),
    )
    cost_wait = _resume(client, auth_headers, state, "approve").json()
    provider_wait_response = _resume(
        client,
        auth_headers,
        cost_wait,
        "approve",
        cost_plan_hash=cost_wait["values"]["generation"]["cost_plan"]["cost_plan_hash"],
    )
    assert provider_wait_response.status_code == 200, provider_wait_response.text
    assert provider_wait_response.json()["current_stage"] == "provider_wait"
    delivery = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=started["run_id"]).one()
    assert delivery.provider_mode == "real"

    worker_db = SessionLocal()
    try:
        result = run_image_worker_batch(worker_db, owner="lg11-real-provider-smoke", batch_size=1)
    finally:
        worker_db.close()
    assert len(result) == 1 and result[0]["provider_dispatch_count"] == 1

    review = client.get(f"/api/v1/graph-runs/{started['run_id']}", headers=auth_headers).json()
    assert review["current_stage"] == "image_review"
    completed = _resume(
        client, auth_headers, review, "approve", job_id=review["values"]["generation"]["jobs"][0]["job_id"],
    )
    assert completed.status_code == 200, completed.text
    child_id = completed.json()["values"]["edit"]["scene_version_fork"]["detail_page_version_id"]
    child = db_session.query(DetailPageVersion).filter_by(id=child_id).one()
    assert child.sections_json["lg11"]["source_detail_page_version_id"] == source.id
