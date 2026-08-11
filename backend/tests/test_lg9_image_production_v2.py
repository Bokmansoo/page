"""LG-9 real-provider smoke coverage, kept out of the default test run."""

from __future__ import annotations

import os

import pytest

from test_lg5_image_generation_subgraph import (
    _cost_hash,
    _create_run,
    _resume,
    auth_headers,
    lg5_runtime,
)


@pytest.mark.lg9_real_provider_smoke
def test_lg9_real_provider_smoke_requires_explicit_opt_in(
    client, auth_headers, db_session, lg5_runtime, monkeypatch, tmp_path
):
    """Send one explicitly approved production LangGraph scene to OpenAI."""

    if os.getenv("SELLFORM_RUN_REAL_PROVIDER_SMOKE") != "1":
        pytest.skip("Set SELLFORM_RUN_REAL_PROVIDER_SMOKE=1 to permit a billed provider request.")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        pytest.skip("OPENAI_API_KEY is required for the real-provider smoke test.")

    from src.config import settings
    from src.db.database import SessionLocal
    from src.db.models import ImageGenerationOutboxRecord, ProductProject
    from src.services.image_generation_worker import run_image_worker_batch

    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "real")
    monkeypatch.setattr(settings, "SELLFORM_IMAGE_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", api_key)
    run = _create_run(client, auth_headers, db_session, tmp_path, mode="real")
    state = client.post(f"/api/v1/graph-runs/{run.id}/start", headers=auth_headers).json()
    state = _resume(client, auth_headers, state, "approve").json()
    state = _resume(client, auth_headers, state, "approve").json()
    project = db_session.query(ProductProject).filter_by(id=run.project_id).one()
    draft = dict(project.planning_draft or {})
    cards = [dict(card) for card in draft.get("cards") or []]
    assert cards
    for index, card in enumerate(cards):
        card["image_requirement"] = "ai_redesign_required" if index == 0 else "seller_upload_required"
    draft["cards"] = cards
    project.planning_draft = draft
    db_session.commit()
    generation_wait = _resume(client, auth_headers, state, "approve").json()
    assert generation_wait["current_stage"] == "generation_pending"
    assert generation_wait["values"]["generation"]["cost_plan"]["scene_count"] == 1
    provider_wait = _resume(
        client,
        auth_headers,
        generation_wait,
        "approve",
        cost_plan_hash=_cost_hash(generation_wait),
    )
    assert provider_wait.status_code == 200, provider_wait.text
    assert provider_wait.json()["current_stage"] == "provider_wait"

    deliveries = db_session.query(ImageGenerationOutboxRecord).filter_by(run_id=run.id).all()
    assert len(deliveries) == 1
    assert deliveries[0].provider_mode == "real"

    worker_db = SessionLocal()
    try:
        results = run_image_worker_batch(worker_db, owner="lg9-real-provider-smoke", batch_size=1)
    finally:
        worker_db.close()
    assert len(results) == 1
    assert results[0]["status"] == "completed"
    assert results[0]["provider_dispatch_count"] == 1

    image_review = client.get(f"/api/v1/graph-runs/{run.id}", headers=auth_headers)
    assert image_review.status_code == 200, image_review.text
    state = image_review.json()
    assert state["current_stage"] == "image_review"
    assert state["values"]["generation"]["jobs"][0]["output_asset_id"]
