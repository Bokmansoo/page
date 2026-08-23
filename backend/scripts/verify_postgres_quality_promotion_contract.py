"""Verify PostgreSQL-only LG-12 promotion constraints against a seeded row."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from scripts.postgres_test_environment import require_local_postgres_test_url


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)


def _must_reject(connection, statement, params, expected_state: str) -> None:
    try:
        connection.execute(statement, params)
    except DBAPIError as error:
        assert _sqlstate(error) == expected_state, error
        connection.rollback()
    else:
        raise AssertionError(f"expected PostgreSQL SQLSTATE {expected_state}")


def main() -> None:
    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            promotion_id = connection.execute(
                text("SELECT id FROM quality_promotion_versions ORDER BY created_at DESC LIMIT 1")
            ).scalar_one_or_none()
            if not promotion_id:
                raise RuntimeError("Seed a PASS promotion before verifying PostgreSQL promotion constraints.")

            _must_reject(
                connection,
                text("UPDATE quality_promotion_versions SET version = version WHERE id = :id"),
                {"id": promotion_id},
                "55000",
            )
            _must_reject(
                connection,
                text("DELETE FROM quality_promotion_versions WHERE id = :id"),
                {"id": promotion_id},
                "55000",
            )
            _must_reject(
                connection,
                text("""
                    INSERT INTO quality_promotion_versions (
                      id, workspace_id, project_id, creator_run_id, version, schema_version,
                      detail_page_version_id, detail_page_schema_version, detail_page_hash,
                      quality_report_id, quality_report_version, quality_report_hash,
                      quality_bar_result_id, quality_bar_hash, master_ref_json, page_plan_ref_json,
                      brand_kit_ref_json, target_channels_json, canonical_hash, created_by, created_at
                    )
                    SELECT
                      :copy_id, workspace_id, project_id, creator_run_id, version, schema_version,
                      detail_page_version_id, detail_page_schema_version, detail_page_hash,
                      quality_report_id, quality_report_version, quality_report_hash,
                      quality_bar_result_id, quality_bar_hash, master_ref_json, page_plan_ref_json,
                      brand_kit_ref_json, target_channels_json, canonical_hash, created_by, created_at
                    FROM quality_promotion_versions WHERE id = :id
                """),
                {"id": promotion_id, "copy_id": str(uuid4())},
                "23505",
            )
            # Two independent PostgreSQL connections race the same canonical
            # promotion insert.  The immutable table intentionally cannot be
            # cleaned up afterwards, so this creates one disposable row in the
            # tmpfs-backed test database only.
            race_token = uuid4().hex
            race_hash = sha256(f"promotion-race:{race_token}".encode()).hexdigest()
            barrier = Barrier(2)
            insert_sql = text("""
                INSERT INTO quality_promotion_versions (
                  id, workspace_id, project_id, creator_run_id, version, schema_version,
                  detail_page_version_id, detail_page_schema_version, detail_page_hash,
                  quality_report_id, quality_report_version, quality_report_hash,
                  quality_bar_result_id, quality_bar_hash, master_ref_json, page_plan_ref_json,
                  brand_kit_ref_json, target_channels_json, canonical_hash, created_by, created_at
                )
                SELECT
                  :copy_id, workspace_id, project_id, creator_run_id, version, schema_version,
                  detail_page_version_id, detail_page_schema_version, detail_page_hash,
                  quality_report_id, quality_report_version, quality_report_hash,
                  :bar_id, :bar_hash, master_ref_json, page_plan_ref_json,
                  brand_kit_ref_json, target_channels_json, :canonical_hash, created_by, CURRENT_TIMESTAMP
                FROM quality_promotion_versions WHERE id = :id
            """)

            def race_insert() -> str:
                with engine.connect() as race_connection:
                    transaction = race_connection.begin()
                    barrier.wait(timeout=10)
                    try:
                        race_connection.execute(insert_sql, {
                            "id": promotion_id,
                            "copy_id": str(uuid4()),
                            "bar_id": f"quality-bar-race:{race_token}",
                            "bar_hash": race_hash,
                            "canonical_hash": race_hash,
                        })
                        transaction.commit()
                        return "inserted"
                    except DBAPIError as error:
                        transaction.rollback()
                        return f"{_sqlstate(error) or 'unknown'}:{error.orig}"

            with ThreadPoolExecutor(max_workers=2) as executor:
                race_results = sorted(executor.map(lambda _: race_insert(), range(2)))
            assert any(result == "inserted" for result in race_results), race_results
            assert any(result.startswith("23505:") for result in race_results), race_results
            print("quality promotion UPDATE/DELETE=55000; duplicate=23505; two-connection race=one row")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
