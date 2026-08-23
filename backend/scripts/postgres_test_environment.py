"""Fail-closed helpers for PostgreSQL-only integration and E2E commands."""

from __future__ import annotations

from urllib.parse import urlparse


class PostgresTestEnvironmentError(RuntimeError):
    pass


def require_local_postgres_test_url(url: str | None, *, allow: bool) -> str:
    """Reject production/Supabase or SQLite URLs before a test can mutate them."""

    if not allow:
        raise PostgresTestEnvironmentError(
            "SELLFORM_ALLOW_TEST_DATABASE=1 is required for PostgreSQL integration/E2E commands."
        )
    if not url:
        raise PostgresTestEnvironmentError("TEST_DATABASE_URL is required; SQLite fallback is forbidden.")
    parsed = urlparse(url)
    if parsed.scheme.split("+", 1)[0] not in {"postgres", "postgresql"}:
        raise PostgresTestEnvironmentError("PostgreSQL integration/E2E requires a PostgreSQL URL.")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise PostgresTestEnvironmentError("Integration/E2E refuses non-local database hosts.")
    if parsed.port != 5433 or parsed.path.rstrip("/") != "/sellform_test":
        raise PostgresTestEnvironmentError("Integration/E2E requires local PostgreSQL test database localhost:5433/sellform_test.")
    return url
