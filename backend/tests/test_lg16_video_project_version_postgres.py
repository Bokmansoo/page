"""LG-16-A1 PostgreSQL acceptance for immutable VideoProjectVersion identity."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.models import AgentRun, Brand, ProductProject, User, VideoProjectVersion, Workspace
from src.services.video_project_version_service import (
    VideoProjectContractError,
    create_video_project_version,
    public_video_project_projection,
    validate_video_project_version,
)
from test_lg12i_commerce_creative_master import _source_chain_with_asset
from test_lg12i_version_contract import _create_master
from test_lg12i_version_contract import _ref


pytestmark = [pytest.mark.postgres, pytest.mark.integration]
_MIGRATION = Path(__file__).parents[1] / "migrations" / "20260831_lg16_video_project_version.sql"


@pytest.fixture(scope="module")
def video_engine():
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
def video_db(video_engine):
    connection = video_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _run(db):
    suffix = uuid4().hex
    user = User(id=str(uuid4()), email=f"lg16-{suffix}@test.invalid", name="LG16 test")
    workspace = Workspace(id=str(uuid4()), name="LG16 workspace", owner_id=user.id)
    brand = Brand(id=str(uuid4()), workspace_id=workspace.id, name="LG16 brand")
    project = ProductProject(id=str(uuid4()), workspace_id=workspace.id, brand_id=brand.id, name="LG16 project")
    run = AgentRun(
        id=str(uuid4()), workspace_id=workspace.id, project_id=project.id,
        mode="mock", status="created", current_stage="intake", created_by=user.id,
        graph_thread_id=str(uuid4()),
    )
    db.add_all([user, workspace, brand, project, run])
    db.flush()
    return run


def _setup(db, tmp_path):
    run = _run(db)
    chain, asset, _asset_path = _source_chain_with_asset(db, run, tmp_path)
    asset_ref = {
        "id": asset.id, "version": 1, "hash": asset.content_hash,
        "schema_version": "asset-sha256-v1",
    }
    master = _create_master(db, run, chain=chain, usable_asset_refs=[asset_ref])
    db.flush()
    return run, master


def _request(run, master):
    return dict(
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        creator_run_id=run.id,
        created_by=run.created_by,
        source_master_reference=_ref(master.id, master.version, master.canonical_hash),
        planning_contract_reference={},
        publishing_targets=["reels", "tiktok", "youtube_shorts"],
    )


def _recovery_run(db, run):
    recovery = AgentRun(
        id=str(uuid4()), workspace_id=run.workspace_id, project_id=run.project_id,
        mode="mock", status="created", current_stage="video", created_by=run.created_by,
        graph_thread_id=str(uuid4()),
    )
    db.add(recovery)
    db.flush()
    return recovery


def test_postgres_video_project_version_freezes_master_refs_and_replays(video_db, tmp_path):
    run, master = _setup(video_db, tmp_path)
    first = create_video_project_version(video_db, **_request(run, master))
    second = create_video_project_version(video_db, **_request(run, master))
    recovery = _recovery_run(video_db, run)
    replayed_from_recovery = create_video_project_version(
        video_db, **{**_request(recovery, master), "created_by": recovery.created_by}
    )

    assert first.id == second.id
    assert replayed_from_recovery.id == first.id
    assert first.version == 1
    assert first.source_master_id == master.id
    assert first.approved_fact_snapshot_ref_json == master.approved_fact_snapshot_ref_json
    assert first.creative_brief_ref_json["id"] == master.creative_brief_version_id
    assert first.brand_kit_ref_json["id"] == master.brand_kit_version_id
    assert first.rights_asset_refs_json
    assert first.output_hash is None
    assert public_video_project_projection(video_db, first)["source_master"]["hash"] == master.canonical_hash
    assert video_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).count() == 1


def test_postgres_video_project_version_rejects_scope_stale_parent_and_raw_reference(video_db, tmp_path):
    run, master = _setup(video_db, tmp_path)
    with pytest.raises(VideoProjectContractError):
        create_video_project_version(video_db, **{**_request(run, master), "source_master_reference": {"id": "https://private.example/prompt", "version": 1, "hash": "0" * 64}})
    with pytest.raises(VideoProjectContractError):
        create_video_project_version(
            video_db,
            **{
                **_request(run, master),
                "source_master_reference": {"id": master.id, "version": master.version, "hash": "0" * 64},
            },
        )
    with pytest.raises(VideoProjectContractError):
        create_video_project_version(video_db, **{**_request(run, master), "planning_contract_reference": {"id": "PROMPT SECRET", "version": 1, "hash": "1" * 64}})
    assert video_db.query(VideoProjectVersion).filter_by(project_id=run.project_id).count() == 0

    first = create_video_project_version(video_db, **_request(run, master))
    with pytest.raises(VideoProjectContractError):
        create_video_project_version(video_db, **{**_request(run, master), "parent_version_id": str(uuid4())})
    other_run = _run(video_db)
    with pytest.raises(VideoProjectContractError):
        create_video_project_version(video_db, **{**_request(other_run, master), "parent_version_id": first.id})


def test_postgres_video_project_version_successor_is_immutable(video_db, tmp_path):
    run, master = _setup(video_db, tmp_path)
    first = create_video_project_version(video_db, **_request(run, master))
    second = create_video_project_version(
        video_db, **{**_request(run, master), "parent_version_id": first.id, "planning_contract_reference": {}}
    )
    assert second.id != first.id
    assert second.version == 2
    assert second.parent_video_project_version_id == first.id
    validate_video_project_version(video_db, second, require_current_master=False)
    with pytest.raises(ValueError):
        first.version = 99
        video_db.flush()


def test_postgres_video_project_version_direct_sql_triggers(video_engine, tmp_path):
    connection = video_engine.connect()
    setup_session = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)()
    run, master = _setup(setup_session, tmp_path)
    first = create_video_project_version(setup_session, **_request(run, master))
    first_id = first.id
    setup_session.commit()
    setup_session.close()
    connection.close()

    for statement, params in (
        (
            text("UPDATE video_project_versions SET output_hash = :hash WHERE id = :id"),
            {"hash": "f" * 64, "id": first_id},
        ),
        (text("DELETE FROM video_project_versions WHERE id = :id"), {"id": first_id}),
    ):
        check_connection = video_engine.connect()
        try:
            with pytest.raises(DBAPIError):
                with check_connection.begin():
                    check_connection.execute(statement, params)
        finally:
            check_connection.close()


def test_postgres_concurrent_same_video_project_request_creates_one_row(video_engine, tmp_path):
    setup_connection = video_engine.connect()
    setup_session = sessionmaker(bind=setup_connection, autoflush=False, expire_on_commit=False)()
    run, master = _setup(setup_session, tmp_path)
    setup_session.commit()
    setup_session.close()
    setup_connection.close()
    request = _request(run, master)

    def create_one():
        connection = video_engine.connect()
        session = sessionmaker(bind=connection, autoflush=False)()
        try:
            row = create_video_project_version(session, **request)
            session.commit()
            return row.id
        finally:
            session.close()
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _index: create_one(), range(2)))
    assert ids[0] == ids[1]
    check = sessionmaker(bind=video_engine, autoflush=False)()
    try:
        assert check.query(VideoProjectVersion).filter_by(project_id=run.project_id).count() == 1
    finally:
        check.close()
