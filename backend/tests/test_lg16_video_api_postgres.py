"""LG-16-A8 seller video studio API acceptance."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.api.auth import get_current_user_and_workspace
from src.app import app
from src.db.database import get_db
from src.db.models import AgentRun, AgentRunEvent, Asset, ImageGenerationJobRecord, ProductProject, User, VideoPlatformMetadataVersion, VideoProjectVersion
from src.services.video_assembly_service import assemble_common_video
from src.services.langgraph_run_service import AgentRunEventJournal
from test_lg16_video_assembly_postgres import _completed

pytestmark = [pytest.mark.postgres, pytest.mark.integration]
_MIGRATIONS = (
    Path(__file__).parents[1] / "migrations" / "20260831_lg16_video_project_version.sql",
    Path(__file__).parents[1] / "migrations" / "20260905_lg16_video_text_version.sql",
    Path(__file__).parents[1] / "migrations" / "20260905_lg16_video_platform_metadata.sql",
)


@pytest.fixture(scope="module")
def api_engine():
    import os

    url = require_local_postgres_test_url(os.environ.get("TEST_DATABASE_URL"), allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1")
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        for migration in _MIGRATIONS:
            connection.exec_driver_sql(migration.read_text(encoding="utf-8"))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def api_db(api_engine):
    session = sessionmaker(bind=api_engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api_client(api_db):
    tmp_path = Path(__file__).resolve().parents[2] / ".tmp-lg16-a8" / uuid4().hex
    tmp_path.mkdir(parents=True, exist_ok=False)
    run, _video, _prepared = _completed(api_db, tmp_path)
    assemble_common_video(run_id=run.id, project_id=run.project_id, db=api_db)
    api_db.commit()
    user = api_db.query(User).filter_by(id=run.created_by).one()
    project = api_db.query(ProductProject).filter_by(id=run.project_id).one()

    def override_db():
        yield api_db

    app.dependency_overrides[get_db] = override_db
    auth = {"user": user, "workspace": project.workspace, "role": "owner"}
    app.dependency_overrides[get_current_user_and_workspace] = lambda: auth
    try:
        with TestClient(app) as client:
            yield client, run, auth
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user_and_workspace, None)


def test_video_get_is_bounded_and_downloads_current_mp4(api_client):
    client, run, _auth = api_client
    response = client.get(f"/api/v1/projects/{run.project_id}/video")
    assert response.status_code == 200
    body = response.json()
    assert body["video"]["download_available"] is True
    assert body["video"]["status"]["status"] == "ready"
    assert body["video"]["progress"]["percent"] == 100
    assert body["video"]["final_output"] == {"ready": True, "media_type": "video/mp4", "version": body["video"]["version"]}
    assert body["video"]["audio"]["mode"] == "silent"
    assert body["video"]["thumbnail"] == {"ready": True, "media_type": "image/png"}
    assert "canonical_hash" not in str(body)
    assert "file_path" not in str(body)
    download = client.get(f"/api/v1/projects/{run.project_id}/video/download")
    assert download.status_code == 200
    assert download.headers["content-type"].startswith("video/mp4")
    assert len(download.content) > 0


def test_video_actions_are_scoped_and_text_edit_is_replay_safe(api_client, api_db):
    client, run, _auth = api_client
    current = api_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    scenes = list(((current.video_manifest_json or {}).get("storyboard") or {}).get("scenes") or [])
    scene_id = str(scenes[0]["scene_id"])
    payload = {"run_id": run.id, "action": "text_edit", "parent_video_project_ref": {"id": current.id, "version": current.version}, "scene_id": scene_id, "body_text": "상품의 핵심 장점을 확인해 보세요."}
    first = client.post(f"/api/v1/projects/{run.project_id}/video/actions", json=payload)
    assert first.status_code == 200
    successor = first.json()["video"]
    assert successor["version"] == current.version + 1
    assert any(item["scene_id"] == scene_id and item["text"] == payload["body_text"] for item in successor["texts"])
    stale = client.post(f"/api/v1/projects/{run.project_id}/video/actions", json=payload)
    assert stale.status_code == 409


def test_video_reorder_preserves_scene_identity_and_assets(api_client, api_db):
    client, run, _auth = api_client
    current = api_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    scenes = list(((current.video_manifest_json or {}).get("storyboard") or {}).get("scenes") or [])
    before_jobs = api_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count()
    before_assets = api_db.query(Asset).filter_by(project_id=run.project_id, asset_role="video_final").count()
    ordered = [str(item["scene_id"]) for item in reversed(scenes)]
    response = client.post(
        f"/api/v1/projects/{run.project_id}/video/actions",
        json={
            "run_id": run.id, "action": "reorder",
            "parent_video_project_ref": {"id": current.id, "version": current.version},
            "ordered_scene_ids": ordered,
        },
    )
    assert response.status_code == 200
    assert [item["scene_id"] for item in response.json()["video"]["scenes"]] == ordered
    assert response.json()["video"]["final_output"]["ready"] is False
    assert response.json()["video"]["download_available"] is False
    assert client.get(f"/api/v1/projects/{run.project_id}/video/download").status_code == 409
    assert api_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before_jobs
    assert api_db.query(Asset).filter_by(project_id=run.project_id, asset_role="video_final").count() == before_assets
    successor = api_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    assert successor.output_hash is None
    assert (successor.video_manifest_json or {}).get("final_output_ref") is None
    assert (successor.video_manifest_json or {}).get("thumbnail_ref") is None
    metadata = client.post(
        f"/api/v1/projects/{run.project_id}/video/actions",
        json={
            "run_id": run.id, "action": "metadata_edit",
            "parent_video_project_ref": {"id": successor.id, "version": successor.version},
            "platform": "reels", "caption": "재조립 전 게시 정보",
        },
    )
    assert metadata.status_code == 409
    assert api_db.query(AgentRunEvent).filter_by(run_id=run.id, event_type="video_storyboard_planned").count() >= 1
    projected = AgentRunEventJournal.rebuild_projection(run, api_db)
    assert projected.outputs_json["langgraph_video"]["video_project_ref"]["id"] == str(successor.id)
    regenerated = client.post(
        f"/api/v1/projects/{run.project_id}/video/actions",
        json={
            "run_id": run.id, "action": "regenerate",
            "parent_video_project_ref": {"id": successor.id, "version": successor.version},
            "scene_id": ordered[0],
        },
    )
    assert regenerated.status_code == 200
    assert api_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before_jobs + 1


def test_video_metadata_edit_keeps_common_mp4_and_regeneration_is_target_only(api_client, api_db):
    client, run, auth = api_client
    current = api_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    scenes = list(((current.video_manifest_json or {}).get("storyboard") or {}).get("scenes") or [])
    scene_id = str(scenes[0]["scene_id"])
    before_jobs = api_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count()
    regenerated = client.post(f"/api/v1/projects/{run.project_id}/video/actions", json={"run_id": run.id, "action": "regenerate", "parent_video_project_ref": {"id": current.id, "version": current.version}, "scene_id": scene_id})
    assert regenerated.status_code == 200
    assert api_db.query(ImageGenerationJobRecord).filter_by(project_id=run.project_id).count() == before_jobs + 1
    current = api_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    metadata = client.post(f"/api/v1/projects/{run.project_id}/video/actions", json={"run_id": run.id, "action": "metadata_edit", "parent_video_project_ref": {"id": current.id, "version": current.version}, "platform": "reels", "caption": "제품의 핵심 장점을 확인해 보세요.", "hashtags": ["#제품"]})
    assert metadata.status_code == 200
    assert api_db.query(VideoPlatformMetadataVersion).filter_by(project_id=run.project_id, platform="reels").count() == 1
    assert metadata.json()["video"]["assembly"]["ready"] is True


def test_video_api_fail_closed_for_scope_and_viewer_actions(api_client):
    client, run, auth = api_client
    assert client.get(f"/api/v1/projects/{uuid4()}/video").status_code == 404
    auth["role"] = "viewer"
    response = client.post(f"/api/v1/projects/{run.project_id}/video/actions", json={"run_id": run.id, "action": "regenerate", "parent_video_project_ref": {"id": "missing", "version": 1}, "scene_id": "missing"})
    assert response.status_code == 403
