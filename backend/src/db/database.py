from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from src.config import settings

engine = create_engine(settings.DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_runtime_schema_compatibility() -> None:
    """Add lightweight Sprint columns to existing local PostgreSQL databases.

    `Base.metadata.create_all()` creates tables but does not alter existing
    tables. This helper keeps local dev databases usable after sprint
    model additions without introducing a full migration framework yet.
    """
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Could not connect to database for runtime schema check: {e}")
        return

    if "product_facts" in table_names:
        existing_columns = {column["name"] for column in inspector.get_columns("product_facts")}
        column_ddls = {
            "extraction_source": "ALTER TABLE product_facts ADD COLUMN extraction_source VARCHAR(50)",
            "provider": "ALTER TABLE product_facts ADD COLUMN provider VARCHAR(50)",
            "model_name": "ALTER TABLE product_facts ADD COLUMN model_name VARCHAR(100)",
            "confidence": "ALTER TABLE product_facts ADD COLUMN confidence FLOAT",
            "needs_review": "ALTER TABLE product_facts ADD COLUMN needs_review BOOLEAN NOT NULL DEFAULT TRUE",
            "risk_flags": "ALTER TABLE product_facts ADD COLUMN risk_flags JSON",
        }

        with engine.begin() as connection:
            for column_name, ddl in column_ddls.items():
                if column_name not in existing_columns:
                    connection.execute(text(ddl))

    if "product_projects" in table_names:
        existing_project_columns = {column["name"] for column in inspector.get_columns("product_projects")}
        with engine.begin() as connection:
            if "selected_style" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN selected_style VARCHAR(50)"))
            if "selected_background" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN selected_background VARCHAR(100)"))
            if "intake_snapshot" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN intake_snapshot JSON"))
            if "style_candidates_snapshot" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN style_candidates_snapshot JSON"))
            if "style_generation" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN style_generation INTEGER NOT NULL DEFAULT 0"))
            if "visual_package_jobs" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN visual_package_jobs JSON"))

    if "figma_export_jobs" in table_names:
        existing_figma_columns = {
            column["name"] for column in inspector.get_columns("figma_export_jobs")
        }
        if "auth_url" not in existing_figma_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE figma_export_jobs ADD COLUMN auth_url TEXT")
                )

    if "page_sections" in table_names:
        existing_section_columns = {column["name"] for column in inspector.get_columns("page_sections")}
        with engine.begin() as connection:
            if "visual_kind" not in existing_section_columns:
                connection.execute(text("ALTER TABLE page_sections ADD COLUMN visual_kind VARCHAR(30)"))
            if "visual_payload" not in existing_section_columns:
                connection.execute(text("ALTER TABLE page_sections ADD COLUMN visual_payload JSON"))

    if "agent_runs" not in table_names or "agent_run_steps" not in table_names:
        Base.metadata.create_all(bind=engine)

