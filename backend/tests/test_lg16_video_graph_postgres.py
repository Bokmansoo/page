"""LG-16-A3 PostgreSQL acceptance for the canonical planning subgraph."""

from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.models import AgentRun, AgentRunEvent, VideoProjectVersion
from src.services.prompt_intelligence_service import canonical_hash
from src.services.langgraph_run_service import LangGraphRunService
from src.services import video_storyboard_service
from src.services.video_project_version_service import create_video_project_version
from test_lg16_video_project_version_postgres import _request, _setup
from test_lg16_video_storyboard_postgres import _scenes


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
    path = Path(__file__).resolve().parents[2] / ".tmp-lg16-a3" / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _video_request(video, scenes):
    return {
        "source_video_project_ref": {"id": video.id, "version": video.version, "hash": video.canonical_hash},
        "scenes": deepcopy(scenes),
        "creative_intent": "product_demo",
    }


def _base(graph_db, graph_tmp_path):
    run, master = _setup(graph_db, graph_tmp_path)
    video = create_video_project_version(graph_db, **_request(run, master))
    graph_db.commit()
    return run, master, video


def test_postgres_video_graph_plans_and_quality_is_bounded(graph_db, graph_tmp_path):
    run, _master, video = _base(graph_db, graph_tmp_path)
    request = _video_request(video, _scenes(video))
    result = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request=request, db=graph_db,
    )
    assert result.status == "completed"
    assert result.current_stage == "video_review_ready"
    rows = graph_db.query(AgentRunEvent).filter_by(run_id=result.id).order_by(AgentRunEvent.sequence).all()
    event_types = [row.event_type for row in rows]
    assert "video_requested" in event_types
    assert "video_storyboard_planned" in event_types
    assert "video_storyboard_quality_evaluated" in event_types
    assert "video_review_ready" in event_types
    quality = dict(result.outputs_json.get("langgraph_quality") or {})
    assert quality["verdict"] == "PASS"
    assert quality["quality_stage"] == "storyboard_content"
    assert all(value in {"PASS", "DEFERRED"} for value in quality["dimension_results"].values())
    assert graph_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).count() == 2
    state = LangGraphRunService.get_state(result.id, run.workspace_id, graph_db)
    assert "scenes" not in dict(state.values.get("video", {}))
    assert "prompt" not in str(state.values)


def test_postgres_video_graph_preserves_review_required_semantics(graph_db, graph_tmp_path, monkeypatch):
    run, _master, video = _base(graph_db, graph_tmp_path)
    request = _video_request(video, _scenes(video))
    original = video_storyboard_service.evaluate_video_storyboard_quality

    def review_required(db, project):
        quality = original(db, project)
        quality["verdict"] = "REVIEW_REQUIRED"
        quality["reason_codes"] = ["MANUAL_REVIEW"]
        quality["canonical_hash"] = canonical_hash({key: value for key, value in quality.items() if key != "canonical_hash"})
        return quality

    monkeypatch.setattr(video_storyboard_service, "evaluate_video_storyboard_quality", review_required)
    result = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request=request, db=graph_db,
    )
    assert result.status == "awaiting_review"
    assert result.current_stage == "video_storyboard_quality"
    assert dict(result.outputs_json.get("langgraph_quality") or {})["verdict"] == "REVIEW_REQUIRED"
    assert dict(result.outputs_json.get("langgraph_video") or {})["status"] == "quality_review_required"
    event_types = [row.event_type for row in graph_db.query(AgentRunEvent).filter_by(run_id=result.id).all()]
    assert "video_storyboard_quality_evaluated" in event_types
    assert "video_review_ready" not in event_types


def test_postgres_video_graph_rejects_raw_scene_before_run_persistence(graph_db, graph_tmp_path):
    run, _master, video = _base(graph_db, graph_tmp_path)
    request = _video_request(video, _scenes(video))
    request["scenes"][0]["prompt"] = "PROMPT_SECRET_A3"
    with pytest.raises(ValueError):
        LangGraphRunService.start_video_project(
            project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
            request=request, db=graph_db,
        )
    assert "PROMPT_SECRET_A3" not in str(run.input_snapshot)
    assert graph_db.query(AgentRun).filter_by(project_id=run.project_id, mode="lg16_video_project").count() == 0


def test_postgres_video_graph_replay_and_projection_rebuild_are_idempotent(graph_db, graph_tmp_path):
    run, _master, video = _base(graph_db, graph_tmp_path)
    request = _video_request(video, _scenes(video))
    first = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request=request, db=graph_db,
    )
    before_events = graph_db.query(AgentRunEvent).filter_by(run_id=first.id).count()
    replay = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request=request, db=graph_db,
    )
    assert replay.id == first.id
    assert graph_db.query(AgentRunEvent).filter_by(run_id=first.id).count() == before_events
    graph_db.query(AgentRun).filter_by(id=first.id).update({"outputs_json": {}, "last_applied_event_sequence": 0})
    graph_db.commit()
    rebuilt = LangGraphRunService.rebuild_event_projection(first.id, run.workspace_id, graph_db)
    assert dict(rebuilt.outputs_json.get("langgraph_video") or {}).get("status") == "review_ready"
    assert dict(rebuilt.outputs_json.get("langgraph_quality") or {}).get("verdict") == "PASS"
    assert graph_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).count() == 2


def test_postgres_video_graph_rejects_cross_scope_source(graph_db, graph_tmp_path):
    run, _master, video = _base(graph_db, graph_tmp_path)
    other_run, _other_master, _other_video = _base(graph_db, graph_tmp_path)
    request = _video_request(video, _scenes(video))
    with pytest.raises((ValueError, RuntimeError)):
        LangGraphRunService.start_video_project(
            project_id=other_run.project_id, workspace_id=other_run.workspace_id,
            actor_id=other_run.created_by, request=request, db=graph_db,
        )


def test_postgres_video_graph_concurrent_same_request_has_one_run_and_successor(graph_engine, graph_tmp_path):
    setup = sessionmaker(bind=graph_engine, autoflush=False, expire_on_commit=False)()
    try:
        run, _master, video = _base(setup, graph_tmp_path)
        request = _video_request(video, _scenes(video))
        setup.commit()
        args = {
            "project_id": run.project_id,
            "workspace_id": run.workspace_id,
            "actor_id": run.created_by,
            "request": request,
        }
    finally:
        setup.close()

    def start_one(_index):
        session = sessionmaker(bind=graph_engine, autoflush=False, expire_on_commit=False)()
        try:
            return LangGraphRunService.start_video_project(db=session, **args).id
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        run_ids = list(pool.map(start_one, range(2)))
    check = sessionmaker(bind=graph_engine, autoflush=False, expire_on_commit=False)()
    try:
        assert run_ids[0] == run_ids[1]
        assert check.query(AgentRun).filter_by(id=run_ids[0]).one().status == "completed"
        assert check.query(VideoProjectVersion).filter_by(project_id=args["project_id"]).count() == 2
    finally:
        check.close()
