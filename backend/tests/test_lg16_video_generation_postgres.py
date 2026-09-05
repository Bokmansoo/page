"""LG-16-A4 durable scene generation acceptance."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.models import AgentRun, AgentRunEvent, Asset, ImageGenerationJobRecord, ImageGenerationOutboxRecord, ImageGenerationProviderAttemptRecord
from src.services.image_generation_worker import claim_image_delivery, process_image_delivery, worker_identity
from src.services.langgraph_run_service import LangGraphRunService
from src.services.video_scene_generation_service import (
    VideoSceneGenerationError,
    evaluate_video_scene_quality,
    prepare_video_scene_jobs,
)
from src.services import video_scene_generation_service
from src.services.video_project_version_service import create_video_project_version
from test_lg16_video_graph_postgres import _request, _scenes, _setup


pytestmark = [pytest.mark.postgres, pytest.mark.integration]
_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260831_lg16_video_project_version.sql"


@pytest.fixture(scope="module")
def graph_engine():
    import os

    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        connection.exec_driver_sql(_MIGRATION.read_text(encoding="utf-8"))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def graph_db(graph_engine):
    session = sessionmaker(bind=graph_engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def graph_tmp_path():
    path = Path(__file__).resolve().parents[2] / ".tmp-lg16-a4" / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _video(graph_db, graph_tmp_path):
    run, master = _setup(graph_db, graph_tmp_path)
    video = create_video_project_version(graph_db, **_request(run, master))
    graph_db.commit()
    return run, video


def _request_graph(graph_db, run, video):
    return {
        "source_video_project_ref": {"id": video.id, "version": video.version, "hash": video.canonical_hash},
        "scenes": _scenes(video),
        "creative_intent": "product_demo",
    }


def test_postgres_video_scene_jobs_worker_asset_and_cost(graph_db, graph_tmp_path):
    run, video = _video(graph_db, graph_tmp_path)
    result = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request=_request_graph(graph_db, run, video), db=graph_db,
    )
    prepared = prepare_video_scene_jobs(run_id=result.id, project_id=run.project_id, db=graph_db)
    assert prepared["scene_count"] == len(_scenes(video))
    assert all(job["status"] == "queued" for job in prepared["jobs"])
    jobs = graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    assert len(jobs) == prepared["scene_count"]
    assert all("prompt" not in str(job.input_snapshot) for job in jobs)
    owner = worker_identity()
    while (delivery := claim_image_delivery(graph_db, owner=owner, run_id=result.id)) is not None:
        process_image_delivery(delivery.id, owner, graph_db)
    jobs = graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).all()
    assets = graph_db.query(Asset).filter_by(project_id=run.project_id, mime_type="video/mp4").all()
    attempts = graph_db.query(ImageGenerationProviderAttemptRecord).filter_by(run_id=result.id).all()
    assert len(assets) == len(jobs)
    assert len(attempts) == len(jobs)
    assert all(job.output_asset_id and job.status == "needs_review" for job in jobs)
    assert all(attempt.actual_cost == 0 and attempt.cost_state == "EXPLICIT_ZERO" for attempt in attempts)
    assert any(e.event_type == "video_scene_generation_requested" for e in graph_db.query(AgentRunEvent).filter_by(run_id=result.id).all())
    assert any(e.event_type == "video_scene_generation_completed" for e in graph_db.query(AgentRunEvent).filter_by(run_id=result.id).all())
    graph_db.query(AgentRun).filter_by(id=result.id).update({"outputs_json": {}, "last_applied_event_sequence": 0})
    graph_db.commit()
    rebuilt = LangGraphRunService.rebuild_event_projection(result.id, run.workspace_id, graph_db)
    rebuilt_generation = dict((rebuilt.outputs_json.get("langgraph_video_generation") or {}))
    assert rebuilt_generation.get("completed_count") == prepared["scene_count"]
    quality = evaluate_video_scene_quality(jobs[0], next(asset for asset in assets if asset.id == jobs[0].output_asset_id))
    assert quality["verdict"] == "PASS"


def test_postgres_video_scene_job_replay_and_selective_regenerate(graph_db, graph_tmp_path):
    run, video = _video(graph_db, graph_tmp_path)
    result = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request=_request_graph(graph_db, run, video), db=graph_db,
    )
    first = prepare_video_scene_jobs(run_id=result.id, project_id=run.project_id, db=graph_db)
    second = prepare_video_scene_jobs(run_id=result.id, project_id=run.project_id, db=graph_db)
    assert [item["job_id"] for item in first["jobs"]] == [item["job_id"] for item in second["jobs"]]
    count = graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count()
    target = str(first["jobs"][0]["scene_id"])
    regenerated = prepare_video_scene_jobs(run_id=result.id, project_id=run.project_id, db=graph_db, regenerate_scene_ids=[target])
    assert len(regenerated["jobs"]) == 1
    assert graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == count + 1
    assert regenerated["jobs"][0]["generation_attempt"] == 2


def test_postgres_video_scene_generation_requires_a3_pass(graph_db, graph_tmp_path):
    run, video = _video(graph_db, graph_tmp_path)
    result = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request=_request_graph(graph_db, run, video), db=graph_db,
    )
    result.outputs_json = {**result.outputs_json, "langgraph_quality": {"verdict": "REVIEW_REQUIRED"}}
    graph_db.commit()
    with pytest.raises(VideoSceneGenerationError, match="VIDEO_GENERATION_QUALITY_GATE"):
        prepare_video_scene_jobs(run_id=result.id, project_id=run.project_id, db=graph_db)
    assert graph_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == 0


def test_postgres_video_scene_retry_uses_attempt_ledger(graph_db, graph_tmp_path, monkeypatch):
    run, video = _video(graph_db, graph_tmp_path)
    result = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request=_request_graph(graph_db, run, video), db=graph_db,
    )
    prepared = prepare_video_scene_jobs(run_id=result.id, project_id=run.project_id, db=graph_db)
    calls = {"count": 0}
    original = video_scene_generation_service.DurableFakeVideoProvider.generate

    def flaky(self, *, semantic_hash):
        calls["count"] += 1
        if calls["count"] == 1:
            raise VideoSceneGenerationError("PROVIDER_TIMEOUT")
        return original(self, semantic_hash=semantic_hash)

    monkeypatch.setattr(video_scene_generation_service.DurableFakeVideoProvider, "generate", flaky)
    owner = worker_identity()
    delivery = claim_image_delivery(graph_db, owner=owner, run_id=result.id)
    assert delivery is not None
    process_image_delivery(delivery.id, owner, graph_db)
    delivery = claim_image_delivery(graph_db, owner=owner, run_id=result.id)
    assert delivery is not None
    process_image_delivery(delivery.id, owner, graph_db)
    attempts = graph_db.query(ImageGenerationProviderAttemptRecord).filter_by(run_id=result.id).all()
    assert len(attempts) == 2
    assert attempts[0].outcome_code == "PROVIDER_TIMEOUT"
    assert attempts[1].outcome_code == "SUCCESS"
    assert graph_db.query(ImageGenerationOutboxRecord).filter_by(run_id=result.id, status="completed").count() == 1
