"""LG-16-A2 PostgreSQL acceptance for bounded deterministic storyboards."""

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
from src.db.models import Asset, VideoProjectVersion
from src.services.prompt_intelligence_service import canonical_hash
from src.services.video_project_version_service import create_video_project_version
from src.services.video_storyboard_service import (
    VideoStoryboardContractError,
    create_video_storyboard_version,
    plan_video_storyboard,
    public_video_storyboard_projection,
    validate_video_storyboard,
)
from test_lg16_video_project_version_postgres import _request, _run, _setup


pytestmark = [pytest.mark.postgres, pytest.mark.integration]
_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260831_lg16_video_project_version.sql"


@pytest.fixture(scope="module")
def storyboard_engine():
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
def storyboard_db(storyboard_engine):
    connection = storyboard_engine.connect()
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
def storyboard_tmp_path():
    path = Path(__file__).resolve().parents[2] / ".tmp-lg16-a2" / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def _approved_fact_ref(video_project, fact_id="fact:fan:capacity"):
    snapshot = video_project.approved_fact_snapshot_ref_json
    digest = canonical_hash({
        "schema_version": "lg16-approved-fact-ref-v1",
        "snapshot": snapshot,
        "fact_id": fact_id,
    })
    return {
        "id": fact_id, "version": 1, "hash": digest,
        "schema_version": "lg16-approved-fact-ref-v1", "artifact_key": "approved_fact",
    }


def _scenes(video_project, *, reorder=False):
    asset = deepcopy(video_project.rights_asset_refs_json[0])
    fact = _approved_fact_ref(video_project)
    provenance = deepcopy(video_project.rights_asset_refs_json[:0])
    # The Master evidence refs are the only approved provenance authority.
    from src.db.models import CommerceCreativeMasterVersion

    master = video_project.source_master_id
    db = video_project.__dict__.get("_sa_instance_state").session
    evidence = db.query(CommerceCreativeMasterVersion).filter_by(id=master).one().evidence_artifact_refs_json
    provenance = [deepcopy(evidence[0])]
    values = [
        {
            "logical_target": "opening",
            "role": "hook",
            "order": 1,
            "duration_intent": "short",
            "visual_intent": "opening_product",
            "product_asset_refs": [asset], "fact_refs": [fact], "provenance_refs": provenance,
            "usage_intent": "show_product",
        },
        {
            "logical_target": "demonstration",
            "role": "usage",
            "order": 2,
            "duration_intent": "medium",
            "visual_intent": "usage_in_context",
            "product_asset_refs": [asset], "fact_refs": [fact], "provenance_refs": provenance,
            "usage_intent": "demonstrate_usage",
        },
    ]
    if reorder:
        values[0]["order"], values[1]["order"] = 2, 1
    return values


def _base(storyboard_db, tmp_path):
    run, master = _setup(storyboard_db, tmp_path)
    video = create_video_project_version(storyboard_db, **_request(run, master))
    storyboard_db.flush()
    return run, master, video


def test_postgres_storyboard_is_deterministic_and_reorder_preserves_scene_identity(storyboard_db, storyboard_tmp_path):
    _run, _master, video = _base(storyboard_db, storyboard_tmp_path)
    first = plan_video_storyboard(storyboard_db, video, _scenes(video))
    second = plan_video_storyboard(storyboard_db, video, _scenes(video))
    reordered = plan_video_storyboard(storyboard_db, video, _scenes(video, reorder=True))
    assert first == second
    assert first["canonical_hash"] == second["canonical_hash"]
    assert {scene["scene_id"] for scene in first["scenes"]} == {scene["scene_id"] for scene in reordered["scenes"]}
    assert first["canonical_hash"] != reordered["canonical_hash"]


def test_postgres_storyboard_successor_replay_and_bounded_projection(storyboard_db, storyboard_tmp_path):
    _run, _master, video = _base(storyboard_db, storyboard_tmp_path)
    scenes = _scenes(video)
    first = create_video_storyboard_version(storyboard_db, video_project=video, scenes=scenes)
    replay = create_video_storyboard_version(storyboard_db, video_project=video, scenes=scenes)
    assert first.id == replay.id
    assert first.parent_video_project_version_id == video.id
    assert validate_video_storyboard(storyboard_db, first)["scene_count"] == 2
    projection = public_video_storyboard_projection(storyboard_db, first)
    assert projection["scene_count"] == 2
    assert [scene["order"] for scene in projection["scenes"]] == [1, 2]
    assert not any("prompt" in scene for scene in projection["scenes"])
    assert storyboard_db.query(VideoProjectVersion).filter_by(project_id=video.project_id).count() == 2


def test_postgres_storyboard_rejects_unsupported_claims_and_raw_fields(storyboard_db, storyboard_tmp_path):
    _run, _master, video = _base(storyboard_db, storyboard_tmp_path)
    unsupported = _scenes(video)
    unsupported[0]["fact_refs"] = [{"id": "fact:invented", "version": 1, "hash": "0" * 64}]
    with pytest.raises(VideoStoryboardContractError):
        plan_video_storyboard(storyboard_db, video, unsupported)
    raw = _scenes(video)
    raw[0]["prompt"] = "PROMPT_SECRET"
    with pytest.raises(VideoStoryboardContractError):
        plan_video_storyboard(storyboard_db, video, raw)
    assert storyboard_db.query(VideoProjectVersion).filter_by(project_id=video.project_id).count() == 1


def test_postgres_storyboard_rejects_unconfirmed_product_identity(storyboard_db, storyboard_tmp_path):
    _run, _master, video = _base(storyboard_db, storyboard_tmp_path)
    asset_id = video.rights_asset_refs_json[0]["id"]
    asset = storyboard_db.query(Asset).filter_by(id=asset_id).one()
    asset.identity_status = "needs_review"
    storyboard_db.flush()
    with pytest.raises(VideoStoryboardContractError, match="product-identity"):
        plan_video_storyboard(storyboard_db, video, _scenes(video))


def test_postgres_storyboard_rejects_cross_project_or_stale_asset_reference(storyboard_db, storyboard_tmp_path):
    _run, _master, video = _base(storyboard_db, storyboard_tmp_path)
    other_run, other_master = _setup(storyboard_db, storyboard_tmp_path)
    other_video = create_video_project_version(storyboard_db, **_request(other_run, other_master))
    scenes = _scenes(video)
    scenes[0]["product_asset_refs"] = list(other_video.rights_asset_refs_json)
    with pytest.raises(VideoStoryboardContractError):
        plan_video_storyboard(storyboard_db, video, scenes)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda scenes: scenes[0].update({"order": 2}),
        lambda scenes: scenes[0].update({"role": "unsupported"}),
        lambda scenes: scenes[1].update({"provenance_refs": []}),
    ],
)
def test_postgres_storyboard_rejects_invalid_order_role_or_usage_evidence(storyboard_db, storyboard_tmp_path, mutator):
    _run, _master, video = _base(storyboard_db, storyboard_tmp_path)
    scenes = _scenes(video)
    mutator(scenes)
    with pytest.raises(VideoStoryboardContractError):
        plan_video_storyboard(storyboard_db, video, scenes)


def test_postgres_storyboard_concurrent_same_plan_creates_one_successor(storyboard_engine, storyboard_tmp_path):
    setup_connection = storyboard_engine.connect()
    setup_session = sessionmaker(bind=setup_connection, autoflush=False, expire_on_commit=False)()
    run, master = _setup(setup_session, storyboard_tmp_path)
    video = create_video_project_version(setup_session, **_request(run, master))
    setup_session.commit()
    setup_session.close()
    setup_connection.close()
    request_scenes = [
        {
            "logical_target": "opening", "role": "hook", "order": 1,
            "duration_intent": "short", "visual_intent": "opening_product",
            "product_asset_refs": list(video.rights_asset_refs_json), "fact_refs": [_approved_fact_ref(video)],
            "provenance_refs": list(master.evidence_artifact_refs_json[:1]), "usage_intent": "show_product",
        },
    ]

    def create_one(_index):
        connection = storyboard_engine.connect()
        session = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)()
        try:
            parent = session.query(VideoProjectVersion).filter_by(id=video.id).one()
            row = create_video_storyboard_version(session, video_project=parent, scenes=request_scenes)
            session.commit()
            return row.id
        finally:
            session.close()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create_one, range(2)))
    assert ids[0] == ids[1]
    check = sessionmaker(bind=storyboard_engine, autoflush=False)()
    try:
        assert check.query(VideoProjectVersion).filter_by(project_id=run.project_id).count() == 2
    finally:
        check.close()
