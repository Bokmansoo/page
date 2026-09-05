"""LG-16-A5 common MP4 assembly acceptance."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.models import AgentRun, AgentRunEvent, Asset, ImageGenerationJobRecord, VideoProjectVersion
from src.services.image_generation_worker import claim_image_delivery, process_image_delivery, worker_identity
from src.services.langgraph_run_service import LangGraphRunService
from src.services.video_assembly_service import VideoAssemblyError, assemble_common_video
from src.services import video_assembly_service
from src.services.video_project_version_service import create_video_project_version
from src.services.video_scene_generation_service import prepare_video_scene_jobs
from test_lg16_video_storyboard_postgres import _scenes
from test_lg16_video_project_version_postgres import _request, _setup


pytestmark = [pytest.mark.postgres, pytest.mark.integration]
_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260831_lg16_video_project_version.sql"


@pytest.fixture(scope="module")
def assembly_engine():
    import os

    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"), allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1"
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
def assembly_db(assembly_engine):
    session = sessionmaker(bind=assembly_engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def assembly_tmp_path():
    path = Path(__file__).resolve().parents[2] / ".tmp-lg16-a5" / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _completed(assembly_db, assembly_tmp_path):
    run, master = _setup(assembly_db, assembly_tmp_path)
    video = create_video_project_version(assembly_db, **_request(run, master))
    assembly_db.commit()
    result = LangGraphRunService.start_video_project(
        project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
        request={
            "source_video_project_ref": {"id": video.id, "version": video.version, "hash": video.canonical_hash},
            "scenes": _scenes(video), "creative_intent": "product_demo",
        }, db=assembly_db,
    )
    prepared = prepare_video_scene_jobs(run_id=result.id, project_id=run.project_id, db=assembly_db)
    owner = worker_identity()
    while (delivery := claim_image_delivery(assembly_db, owner=owner, run_id=result.id)) is not None:
        process_image_delivery(delivery.id, owner, assembly_db)
    assembly_db.commit()
    return result, video, prepared


def test_postgres_common_mp4_is_ordered_probed_and_rebuildable(assembly_db, assembly_tmp_path):
    run, _video, _prepared = _completed(assembly_db, assembly_tmp_path)
    manifest = assemble_common_video(run_id=run.id, project_id=run.project_id, db=assembly_db)
    assert manifest["status"] == "completed"
    assert manifest["common_targets"] == ["reels", "tiktok", "youtube_shorts"]
    current_video = assembly_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    assert current_video.output_hash == manifest["output_hash"]
    assert manifest["ordered_scene_ids"] == [
        item["scene_id"] for item in sorted(
            ((current_video.video_manifest_json or {}).get("storyboard") or {}).get("scenes") or [], key=lambda item: int(item["order"])
        )
    ]
    final = assembly_db.query(Asset).filter_by(project_id=run.project_id, mime_type="video/mp4", asset_role="video_final").one()
    current_video = assembly_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    final_manifest = dict(current_video.video_manifest_json or {})
    assert final_manifest["final_output_ref"]["id"] == str(final.id)
    assert final_manifest["final_output_ref"]["hash"] == final.content_hash == current_video.output_hash
    assert final_manifest["audio_ref"]["id"] == "audio:silent"
    thumbnail_ref = dict(final_manifest["thumbnail_ref"])
    thumbnail = assembly_db.query(Asset).filter_by(id=thumbnail_ref["id"], project_id=run.project_id, asset_role="video_thumbnail").one()
    assert thumbnail.content_hash == thumbnail_ref["hash"]
    assert thumbnail.mime_type == "image/png"
    assert final.file_size > 0 and final.content_hash == manifest["output_hash"]
    assert final.width == manifest["geometry"]["width"] and final.height == manifest["geometry"]["height"]
    assert final.filename.startswith("ai_generated/video_final_")
    assert "ffmpeg" not in str(run.outputs_json).lower()
    events = assembly_db.query(AgentRunEvent).filter_by(run_id=run.id, event_type="video_assembly_completed").all()
    assert len(events) == 1
    persisted = str([event.payload_json for event in assembly_db.query(AgentRunEvent).filter_by(run_id=run.id).all()]).lower()
    assert "ffmpeg" not in persisted and ".video-tmp" not in persisted and "concat-" not in persisted
    before_assets = assembly_db.query(Asset).filter_by(project_id=run.project_id, asset_role="video_final").count()
    before_versions = assembly_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).count()
    replay = assemble_common_video(run_id=run.id, project_id=run.project_id, db=assembly_db)
    assert replay["assembly_hash"] == manifest["assembly_hash"]
    assert assembly_db.query(Asset).filter_by(project_id=run.project_id, asset_role="video_final").count() == before_assets
    assert assembly_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).count() == before_versions
    assert assembly_db.query(AgentRunEvent).filter_by(run_id=run.id, event_type="video_assembly_completed").count() == 1
    assembly_db.query(AgentRun).filter_by(id=run.id).update({"outputs_json": {}, "last_applied_event_sequence": 0})
    assembly_db.commit()
    rebuilt = LangGraphRunService.rebuild_event_projection(run.id, run.workspace_id, assembly_db)
    assert dict(rebuilt.outputs_json.get("langgraph_video_assembly") or {}).get("assembly_hash") == manifest["assembly_hash"]


def test_postgres_assembly_restarts_after_render_crash_without_duplicate_output(assembly_db, assembly_tmp_path, monkeypatch):
    run, _video, _prepared = _completed(assembly_db, assembly_tmp_path)
    original = video_assembly_service._render

    def crash_once(paths, output):
        monkeypatch.setattr(video_assembly_service, "_render", original)
        raise VideoAssemblyError("VIDEO_FFMPEG_FAILED")

    monkeypatch.setattr(video_assembly_service, "_render", crash_once)
    with pytest.raises(VideoAssemblyError, match="VIDEO_FFMPEG_FAILED"):
        assemble_common_video(run_id=run.id, project_id=run.project_id, db=assembly_db)
    assert assembly_db.query(Asset).filter_by(project_id=run.project_id, asset_role="video_final").count() == 0
    assert assembly_db.query(AgentRunEvent).filter_by(run_id=run.id, event_type="video_assembly_failed").count() == 1

    manifest = assemble_common_video(run_id=run.id, project_id=run.project_id, db=assembly_db)
    assert manifest["status"] == "completed"
    assert assembly_db.query(Asset).filter_by(project_id=run.project_id, asset_role="video_final").count() == 1
    assert assembly_db.query(AgentRunEvent).filter_by(run_id=run.id, event_type="video_assembly_started").count() == 1
    assert assembly_db.query(AgentRunEvent).filter_by(run_id=run.id, event_type="video_assembly_completed").count() == 1


def test_postgres_assembly_rejects_missing_or_stale_current_clip(assembly_db, assembly_tmp_path):
    run, _video, prepared = _completed(assembly_db, assembly_tmp_path)
    target = str(prepared["jobs"][0]["scene_id"])
    job = assembly_db.query(ImageGenerationJobRecord).filter_by(job_id=prepared["jobs"][0]["job_id"]).one()
    job.status = "queued"
    job.output_asset_id = None
    assembly_db.commit()
    with pytest.raises(VideoAssemblyError, match="VIDEO_CLIP_NOT_READY"):
        assemble_common_video(run_id=run.id, project_id=run.project_id, db=assembly_db)
    assert target


def test_postgres_selective_scene_regenerate_keeps_siblings_and_changes_final(assembly_db, assembly_tmp_path):
    run, _video, prepared = _completed(assembly_db, assembly_tmp_path)
    first = assemble_common_video(run_id=run.id, project_id=run.project_id, db=assembly_db)
    target = str(prepared["jobs"][0]["scene_id"])
    sibling = str(prepared["jobs"][1]["scene_id"])
    prior_sibling = next(item["asset_ref"] for item in first["selected_clip_refs"] if item["scene_id"] == sibling)
    regenerated = prepare_video_scene_jobs(run_id=run.id, project_id=run.project_id, db=assembly_db, regenerate_scene_ids=[target])
    owner = worker_identity()
    while (delivery := claim_image_delivery(assembly_db, owner=owner, run_id=run.id)) is not None:
        process_image_delivery(delivery.id, owner, assembly_db)
    assembly_db.commit()
    second = assemble_common_video(run_id=run.id, project_id=run.project_id, db=assembly_db)
    assert regenerated["jobs"][0]["generation_attempt"] == 2
    assert second["assembly_hash"] != first["assembly_hash"]
    assert next(item["asset_ref"] for item in second["selected_clip_refs"] if item["scene_id"] == sibling) == prior_sibling


def test_postgres_concurrent_same_assembly_has_one_final_asset(assembly_engine, assembly_tmp_path):
    setup = sessionmaker(bind=assembly_engine, autoflush=False, expire_on_commit=False)()
    try:
        run, master = _setup(setup, assembly_tmp_path)
        video = create_video_project_version(setup, **_request(run, master))
        setup.commit()
        result = LangGraphRunService.start_video_project(
            project_id=run.project_id, workspace_id=run.workspace_id, actor_id=run.created_by,
            request={
                "source_video_project_ref": {"id": video.id, "version": video.version, "hash": video.canonical_hash},
                "scenes": _scenes(video), "creative_intent": "product_demo",
            }, db=setup,
        )
        prepare_video_scene_jobs(run_id=result.id, project_id=run.project_id, db=setup)
        owner = worker_identity()
        while (delivery := claim_image_delivery(setup, owner=owner, run_id=result.id)) is not None:
            process_image_delivery(delivery.id, owner, setup)
        setup.commit()
        args = {"run_id": result.id, "project_id": run.project_id}
    finally:
        setup.close()

    def assemble_one(_index):
        session = sessionmaker(bind=assembly_engine, autoflush=False, expire_on_commit=False)()
        try:
            return assemble_common_video(db=session, **args)["final_asset_ref"]["id"]
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        asset_ids = list(pool.map(assemble_one, range(2)))
    check = sessionmaker(bind=assembly_engine, autoflush=False, expire_on_commit=False)()
    try:
        assert asset_ids[0] == asset_ids[1]
        assert check.query(Asset).filter_by(project_id=args["project_id"], asset_role="video_final").count() == 1
        assert check.query(AgentRunEvent).filter_by(run_id=args["run_id"], event_type="video_assembly_completed").count() == 1
    finally:
        check.close()
