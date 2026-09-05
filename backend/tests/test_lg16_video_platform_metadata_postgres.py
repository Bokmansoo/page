"""LG-16-A7 PostgreSQL acceptance for platform metadata adaptation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.models import AgentRun, AgentRunEvent, Asset, VideoPlatformMetadataVersion, VideoProjectVersion
from src.services.langgraph_run_service import LangGraphRunService
from src.services.video_assembly_service import assemble_common_video
from src.services.video_platform_metadata_service import (
    VideoPlatformMetadataContractError,
    create_video_platform_metadata_version,
    public_video_platform_metadata_projection,
)
from test_lg16_video_assembly_postgres import _completed

pytestmark = [pytest.mark.postgres, pytest.mark.integration]
_A1 = Path(__file__).parents[1] / "migrations" / "20260831_lg16_video_project_version.sql"
_A6 = Path(__file__).parents[1] / "migrations" / "20260905_lg16_video_text_version.sql"
_A7 = Path(__file__).parents[1] / "migrations" / "20260905_lg16_video_platform_metadata.sql"


@pytest.fixture(scope="module")
def metadata_engine():
    import os
    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"), allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1"
    )
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    with engine.begin() as connection:
        assert connection.execute(text("SELECT 1")).scalar_one() == 1
        for migration in (_A1, _A6, _A7):
            connection.exec_driver_sql(migration.read_text(encoding="utf-8"))
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def metadata_db(metadata_engine):
    connection = metadata_engine.connect()
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
def metadata_tmp_path():
    path = Path(__file__).resolve().parents[2] / ".tmp-lg16-a7" / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _setup(db, tmp_path):
    run, _video, _prepared = _completed(db, tmp_path)
    manifest = assemble_common_video(run_id=run.id, project_id=run.project_id, db=db)
    db.commit()
    video = db.query(VideoProjectVersion).filter_by(project_id=run.project_id).order_by(VideoProjectVersion.version.desc()).first()
    asset = db.query(Asset).filter_by(project_id=run.project_id, asset_role="video_final").one()
    storyboard = dict((video.video_manifest_json or {}).get("storyboard") or {})
    scene = list(storyboard.get("scenes") or [])[0]
    return run, video, asset, scene, manifest


def _request(run, video, asset, scene, platform="reels", **values):
    request = dict(
        workspace_id=run.workspace_id, project_id=run.project_id,
        video_project_version_id=video.id,
        final_asset_reference={"id": asset.id, "version": 1, "hash": asset.content_hash},
        platform=platform, author_id=run.created_by,
        fact_refs=list(scene["fact_refs"]), provenance_refs=list(scene["provenance_refs"]),
        text_refs=[],
    )
    request.update(values)
    return request


def test_postgres_platforms_share_common_mp4_and_replay_without_raw_event_body(metadata_db, metadata_tmp_path):
    run, video, asset, scene, manifest = _setup(metadata_db, metadata_tmp_path)
    reels = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, caption="제품의 핵심 장점을 확인하세요.", hashtags=["#제품", "#사용법"], cta="자세히 확인해 보세요")
    )
    tiktok = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, platform="tiktok", caption="사용 장면을 확인하세요.", hashtags=["#제품"])
    )
    youtube = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, platform="youtube_shorts", title="제품 사용 장면", description="승인된 사실에 기반한 제품 소개입니다.", hashtags=["#제품"])
    )
    metadata_db.commit()
    rows = [reels["artifact"], tiktok["artifact"], youtube["artifact"]]
    assert all(row.validation_status == "PASS" for row in rows)
    assert {row.final_asset_hash for row in rows} == {asset.content_hash}
    assert {row.video_project_version_id for row in rows} == {video.id}
    assert manifest["output_hash"] == asset.content_hash
    assert metadata_db.query(VideoPlatformMetadataVersion).filter_by(project_id=run.project_id).count() == 3
    persisted = str([event.payload_json for event in metadata_db.query(AgentRunEvent).filter_by(run_id=run.id).all()])
    assert "제품의 핵심 장점을 확인하세요." not in persisted
    assert "자세히 확인해 보세요" not in persisted
    assert public_video_platform_metadata_projection(reels["artifact"])["caption"] == reels["artifact"].caption_text
    replay = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, caption="제품의 핵심 장점을 확인하세요.", hashtags=["#제품", "#사용법"], cta="자세히 확인해 보세요")
    )
    assert replay["replayed"] is True and replay["artifact"].id == reels["artifact"].id
    assert metadata_db.query(AgentRunEvent).filter_by(run_id=run.id, event_type="video_platform_metadata_created").count() == 3
    metadata_db.commit()
    metadata_db.query(AgentRun).filter_by(id=run.id).update({"outputs_json": {}, "last_applied_event_sequence": 0})
    metadata_db.commit()
    rebuilt = LangGraphRunService.rebuild_event_projection(run.id, run.workspace_id, metadata_db)
    assert rebuilt.outputs_json["langgraph_video_platform_metadata"]["platform"] == "youtube_shorts"
    assert "제품의 핵심 장점을 확인하세요." not in str(rebuilt.outputs_json)


def test_postgres_metadata_claim_safety_target_isolation_and_stale_rejection(metadata_db, metadata_tmp_path):
    run, video, asset, scene, _manifest = _setup(metadata_db, metadata_tmp_path)
    with pytest.raises(VideoPlatformMetadataContractError, match="scope"):
        create_video_platform_metadata_version(
            metadata_db, **_request(run, video, asset, scene, workspace_id=str(uuid4()))
        )
    with pytest.raises(VideoPlatformMetadataContractError, match="Unsupported platform"):
        create_video_platform_metadata_version(
            metadata_db, **_request(run, video, asset, scene, platform="facebook")
        )
    review = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, caption="국내 유일 최고의 효과를 보장합니다.", hashtags=["#제품"])
    )
    assert review["artifact"].validation_status == "REVIEW_REQUIRED"
    unsafe_cta = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, caption="제품을 확인하세요.", hashtags=["#제품"], cta="지금 안 사면 손해를 봅니다", parent_metadata_version_id=review["artifact"].id)
    )
    assert unsafe_cta["artifact"].validation_status == "FAIL"
    with pytest.raises(VideoPlatformMetadataContractError, match="required"):
        create_video_platform_metadata_version(metadata_db, **_request(run, video, asset, scene, platform="youtube_shorts", description="설명만 있음"))
    reels = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, caption="초기 릴스 문구", hashtags=["#제품"], parent_metadata_version_id=unsafe_cta["artifact"].id)
    )
    with pytest.raises(VideoPlatformMetadataContractError, match="stale"):
        create_video_platform_metadata_version(
            metadata_db, **_request(run, video, asset, scene, caption="두 번째 릴스 문구", hashtags=["#제품"])
        )
    tiktok = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, platform="tiktok", caption="틱톡 문구", hashtags=["#제품"])
    )
    edited = create_video_platform_metadata_version(
        metadata_db, **_request(run, video, asset, scene, caption="수정된 릴스 문구", hashtags=["#제품"], parent_metadata_version_id=reels["artifact"].id)
    )
    assert edited["artifact"].version == 4
    assert tiktok["artifact"].caption_text == "틱톡 문구"
    with pytest.raises(VideoPlatformMetadataContractError):
        create_video_platform_metadata_version(
            metadata_db, **_request(run, video, asset, scene, platform="reels", caption="wrong", hashtags=["#제품"], parent_metadata_version_id=edited["artifact"].id, final_asset_reference={"id": asset.id, "version": 1, "hash": "0" * 64})
        )


def test_postgres_platform_metadata_concurrent_same_request_is_idempotent(metadata_engine, metadata_tmp_path):
    setup = sessionmaker(bind=metadata_engine, autoflush=False, expire_on_commit=False)()
    run, video, asset, scene, _manifest = _setup(setup, metadata_tmp_path)
    setup.commit()
    setup.close()
    request = _request(run, video, asset, scene, caption="동일한 문구", hashtags=["#제품"])

    def create_one():
        connection = metadata_engine.connect()
        session = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)()
        try:
            result = create_video_platform_metadata_version(session, **request)
            session.commit()
            return result["artifact"].id
        finally:
            session.close()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: create_one(), range(2)))
    assert ids[0] == ids[1]
    check = sessionmaker(bind=metadata_engine, autoflush=False, expire_on_commit=False)()
    try:
        assert check.query(VideoPlatformMetadataVersion).filter_by(project_id=run.project_id, platform="reels").count() == 1
    finally:
        check.close()


def test_postgres_platform_metadata_is_immutable(metadata_engine, metadata_tmp_path):
    setup = sessionmaker(bind=metadata_engine, autoflush=False, expire_on_commit=False)()
    run, video, asset, scene, _manifest = _setup(setup, metadata_tmp_path)
    row = create_video_platform_metadata_version(setup, **_request(run, video, asset, scene, caption="불변 메타데이터", hashtags=["#제품"]))["artifact"]
    setup.commit()
    connection = metadata_engine.connect()
    try:
        for statement in (
            text("UPDATE video_platform_metadata_versions SET caption_text = 'tampered' WHERE id = :id"),
            text("DELETE FROM video_platform_metadata_versions WHERE id = :id"),
        ):
            with pytest.raises(DBAPIError):
                with connection.begin():
                    connection.execute(statement, {"id": row.id})
    finally:
        connection.close()
        setup.close()
