"""PostgreSQL-only smoke for LG-12 persistence and LangGraph checkpoints."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.agents.langgraph_runtime import build_lg0_compiled_graph, open_postgres_checkpointer


pytestmark = [pytest.mark.postgres, pytest.mark.integration]


def _test_url() -> str:
    return require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )


def test_postgres_lg12_migrations_and_checkpointer_are_available():
    url = _test_url()
    engine = create_engine(url)
    try:
        assert engine.dialect.name == "postgresql"
        with engine.connect() as connection:
            tables = set(connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars())
            assert {"quality_promotion_versions", "quality_assessment_report_versions", "seller_confirmation_versions"} <= tables
            columns = set(connection.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'quality_promotion_versions'")).scalars())
            assert {"quality_bar_hash", "detail_page_hash", "canonical_hash"} <= columns
            triggers = set(connection.execute(text("SELECT tgname FROM pg_trigger WHERE tgrelid = 'quality_promotion_versions'::regclass AND NOT tgisinternal")).scalars())
            assert "trg_quality_promotion_versions_immutable" in triggers
            constraints = set(connection.execute(text("SELECT conname FROM pg_constraint WHERE conrelid = 'seller_confirmation_versions'::regclass")).scalars())
            assert "uq_seller_confirmation_run_truth_cycle" in constraints
        thread_id = f"postgres-quality-smoke-{uuid4()}"
        config = {"configurable": {"thread_id": thread_id}}
        with open_postgres_checkpointer(url) as checkpointer:
            graph = build_lg0_compiled_graph(checkpointer=checkpointer)
            graph.invoke(
                {
                    "run_id": thread_id,
                    "project_id": "postgres-quality-smoke",
                    "input_snapshot": {"product_name": "PostgreSQL smoke"},
                    "events": [],
                },
                config=config,
            )
            assert graph.get_state(config).values["events"] == ["bootstrap_run", "finalize_run"]

        # A fresh saver connection proves state is in PostgreSQL rather than
        # process memory, which is the failure mode that caused the prior 422.
        with open_postgres_checkpointer(url) as recovered_checkpointer:
            recovered = build_lg0_compiled_graph(checkpointer=recovered_checkpointer).get_state(config)
            assert recovered.values["run_id"] == thread_id
            assert recovered.values["events"] == ["bootstrap_run", "finalize_run"]
    finally:
        engine.dispose()
