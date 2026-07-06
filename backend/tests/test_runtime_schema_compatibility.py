from types import SimpleNamespace

from src.db import database


class _FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(str(statement))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self):
        self.connection = _FakeConnection()

    def begin(self):
        return self.connection


def test_runtime_schema_compatibility_adds_style_candidate_columns(monkeypatch):
    fake_engine = _FakeEngine()

    fake_inspector = SimpleNamespace(
        get_table_names=lambda: ["product_projects", "agent_runs", "agent_run_steps"],
        get_columns=lambda table_name: [
            {"name": "id"},
            {"name": "selected_style"},
            {"name": "selected_background"},
        ],
    )

    monkeypatch.setattr(database, "engine", fake_engine)
    monkeypatch.setattr(database, "inspect", lambda _engine: fake_inspector)

    database.ensure_runtime_schema_compatibility()

    executed_sql = "\n".join(fake_engine.connection.statements)
    assert "ADD COLUMN style_candidates_snapshot" in executed_sql
    assert "ADD COLUMN style_generation" in executed_sql
