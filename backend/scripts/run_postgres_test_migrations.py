"""Create a disposable legacy baseline then apply every checked-in SQL migration.

The repository has no baseline SQL migration or Alembic history.  ``create_all``
therefore supplies only the historical base tables; every additive LG migration
is read as raw SQL and executed against PostgreSQL afterwards.  The guard makes
this command unusable against Supabase or a normal development database.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, text

from scripts.postgres_test_environment import require_local_postgres_test_url
from src.db.database import Base
# Register every mapped legacy table before creating the unavoidable baseline.
# The raw LG migrations below remain the authority for their own additions.
import src.db.models  # noqa: F401


def main() -> None:
    url = require_local_postgres_test_url(
        os.environ.get("TEST_DATABASE_URL"),
        allow=os.environ.get("SELLFORM_ALLOW_TEST_DATABASE") == "1",
    )
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
        migrations = sorted((Path(__file__).resolve().parents[1] / "migrations").glob("*.sql"))
        with engine.begin() as connection:
            # Supabase provisions these API roles.  The isolated local
            # PostgreSQL image does not, so establish no-login equivalents
            # before applying the exact checked-in RLS/grant migrations.
            connection.execute(text("""
                DO $$
                BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN CREATE ROLE service_role NOLOGIN; END IF;
                END $$;
            """))
            for migration in migrations:
                sql = migration.read_text(encoding="utf-8")
                if not sql.lstrip().upper().startswith(("--", "CREATE", "ALTER", "DROP")):
                    raise RuntimeError(f"Migration is not SQL: {migration.name}")
                connection.connection.driver_connection.execute(sql)
                print(f"applied {migration.name}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
