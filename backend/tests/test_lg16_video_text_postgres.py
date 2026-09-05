"""LG-16-A6 PostgreSQL acceptance for immutable exact video text."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.models import AgentRun, AgentRunEvent, Asset, ImageGenerationJobRecord, VideoProjectVersion, VideoTextVersion
from src.services.langgraph_run_service import LangGraphRunService
from src.services.video_project_version_service import create_video_project_version
from src.services.video_text_service import (
    VideoTextContractError,
    create_video_text_version,
    public_video_text_projection,
    validate_video_text_version,
)
from test_lg16_video_project_version_postgres import _request, _setup
from test_lg16_video_storyboard_postgres import _scenes


pytestmark = [pytest.mark.postgres, pytest.mark.integration]
_PROJECT_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260831_lg16_video_project_version.sql"
_TEXT_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260905_lg16_video_text_version.sql"


@pytest.fixture(scope="module")
def text_engine():
    import os

    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"), allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1"
    )
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        connection.exec_driver_sql(_PROJECT_MIGRATION.read_text(encoding="utf-8"))
        connection.exec_driver_sql(_TEXT_MIGRATION.read_text(encoding="utf-8"))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def text_db(text_engine):
    connection = text_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def text_tmp_path():
    path = Path(__file__).resolve().parents[2] / ".tmp-lg16-a6" / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _base(db, tmp_path):
    run, master = _setup(db, tmp_path)
    video = create_video_project_version(db, **_request(run, master))
    db.commit()
    result = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request={
            "source_video_project_ref": {"id": video.id, "version": video.version, "hash": video.canonical_hash},
            "scenes": _scenes(video), "creative_intent": "product_demo",
        }, db=db,
    )
    current = db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    return run, current, list((current.video_manifest_json or {}).get("storyboard", {}).get("scenes") or [])


def _text_request(run, video, scene, body="제품의 핵심 기능을 간편하게 확인하세요."):
    return dict(
        workspace_id=run.workspace_id, project_id=run.project_id,
        parent_video_project_version_id=video.id, scene_id=scene["scene_id"],
        text_role="overlay_text", placement_role="body", visibility_status="visible",
        body_text=body, author_id=run.created_by,
        fact_refs=scene["fact_refs"], provenance_refs=scene["provenance_refs"],
    )


def test_postgres_video_text_is_exact_immutable_and_binds_only_target_scene(text_db, text_tmp_path):
    run, video, scenes = _base(text_db, text_tmp_path)
    jobs_before = text_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count()
    assets_before = text_db.query(Asset).filter_by(project_id=run.project_id).count()
    first = create_video_text_version(text_db, **_text_request(run, video, scenes[0]))
    text_db.commit()
    artifact = first["artifact"]
    successor = first["successor"]
    assert first["replayed"] is False and successor is not None
    assert artifact.body_text == "제품의 핵심 기능을 간편하게 확인하세요."
    assert artifact.validation_status == "PASS"
    validate_video_text_version(text_db, artifact)
    refs = list((successor.video_manifest_json or {}).get("text_layer_refs") or [])
    assert [ref["id"] for ref in refs] == [artifact.id]
    assert artifact.scene_id == scenes[0]["scene_id"] and scenes[1]["scene_id"] not in str(refs)
    assert public_video_text_projection(artifact)["text"] == artifact.body_text
    assert text_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == jobs_before
    assert text_db.query(Asset).filter_by(project_id=run.project_id).count() == assets_before
    reloaded = text_db.query(VideoTextVersion).filter_by(id=artifact.id).one()
    assert reloaded.body_text == "제품의 핵심 기능을 간편하게 확인하세요."

    replay = create_video_text_version(text_db, **_text_request(run, video, scenes[0]))
    assert replay["replayed"] is True
    assert replay["artifact"].id == artifact.id
    assert text_db.query(VideoTextVersion).filter_by(project_id=run.project_id).count() == 1
    assert text_db.query(AgentRunEvent).filter_by(
        run_id=video.creator_run_id, event_type="video_text_version_created",
    ).count() == 1
    projected_run = text_db.query(AgentRun).filter_by(id=video.creator_run_id).one()
    projected_run.outputs_json = {}
    projected_run.last_applied_event_sequence = 0
    text_db.commit()
    rebuilt = LangGraphRunService.rebuild_event_projection(projected_run.id, projected_run.workspace_id, text_db)
    assert dict(rebuilt.outputs_json.get("langgraph_video") or {}).get("video_project_ref", {}).get("id") == successor.id
    assert artifact.body_text not in str(rebuilt.outputs_json)


def test_postgres_video_text_successor_preserves_sibling_and_rejects_stale_or_cross_scope(text_db, text_tmp_path):
    run, video, scenes = _base(text_db, text_tmp_path)
    first = create_video_text_version(text_db, **_text_request(run, video, scenes[0]))
    text_db.commit()
    second = create_video_text_version(text_db, **_text_request(run, first["successor"], scenes[1], "사용 장면에서도 제품을 확인하세요."))
    text_db.commit()
    refs = list((second["successor"].video_manifest_json or {}).get("text_layer_refs") or [])
    assert {ref["id"] for ref in refs} == {first["artifact"].id, second["artifact"].id}
    with pytest.raises(VideoTextContractError, match="stale"):
        create_video_text_version(text_db, **_text_request(run, video, scenes[1], "다른 문구"))
    other_run, other_video, other_scenes = _base(text_db, text_tmp_path)
    with pytest.raises(VideoTextContractError, match="scope"):
        create_video_text_version(text_db, **_text_request(other_run, video, other_scenes[0]))


def test_postgres_video_text_fact_safety_and_privacy_boundaries(text_db, text_tmp_path):
    run, video, scenes = _base(text_db, text_tmp_path)
    review = create_video_text_version(
        text_db, **_text_request(run, video, scenes[0], "국내 유일 최고의 효과를 보장합니다."),
    )
    assert review["artifact"].validation_status == "REVIEW_REQUIRED"
    assert review["successor"] is None
    assert review["artifact"].body_text == "국내 유일 최고의 효과를 보장합니다."
    assert text_db.query(VideoProjectVersion).filter_by(
        project_id=run.project_id, parent_video_project_version_id=video.id,
    ).count() == 0
    persisted = " ".join(str(event.payload_json) for event in text_db.query(AgentRunEvent).filter_by(run_id=video.creator_run_id).all())
    assert review["artifact"].body_text not in persisted
    assert "prompt" not in persisted.lower()
    assert review["artifact"].body_text not in str(run.input_snapshot)
    assert review["artifact"].body_text not in str(run.outputs_json)
    assert text_db.query(Asset).filter_by(project_id=run.project_id).count() >= 1


def test_postgres_video_text_replay_and_concurrency_are_idempotent(text_engine, text_tmp_path):
    setup = sessionmaker(bind=text_engine, autoflush=False, expire_on_commit=False)()
    try:
        run, video, scenes = _base(setup, text_tmp_path)
        setup.commit()
        request = _text_request(run, video, scenes[0])
    finally:
        setup.close()

    def create_one(_):
        session = sessionmaker(bind=text_engine, autoflush=False, expire_on_commit=False)()
        try:
            result = create_video_text_version(session, **request)
            session.commit()
            return result["artifact"].id, result["successor"].id if result["successor"] else None
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create_one, range(2)))
    assert results[0] == results[1]
    check = sessionmaker(bind=text_engine, autoflush=False, expire_on_commit=False)()
    try:
        assert check.query(VideoTextVersion).filter_by(project_id=run.project_id).count() == 1
        assert check.query(VideoProjectVersion).filter_by(project_id=run.project_id).count() == 3
    finally:
        check.close()


def test_postgres_video_text_immutable_sql_trigger(text_engine, text_tmp_path):
    setup = sessionmaker(bind=text_engine, autoflush=False, expire_on_commit=False)()
    run, video, scenes = _base(setup, text_tmp_path)
    result = create_video_text_version(setup, **_text_request(run, video, scenes[0]))
    setup.commit()
    setup.close()
    connection = text_engine.connect()
    try:
        with pytest.raises(DBAPIError):
            with connection.begin():
                connection.execute(text("UPDATE video_text_versions SET visibility_status='hidden' WHERE id=:id"), {"id": result["artifact"].id})
        with pytest.raises(DBAPIError):
            with connection.begin():
                connection.execute(text("DELETE FROM video_text_versions WHERE id=:id"), {"id": result["artifact"].id})
    finally:
        connection.close()
