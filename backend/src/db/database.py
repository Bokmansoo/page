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
            "field_key": "ALTER TABLE product_facts ADD COLUMN field_key VARCHAR(100)",
            "fact_category": "ALTER TABLE product_facts ADD COLUMN fact_category VARCHAR(50)",
            "original_text": "ALTER TABLE product_facts ADD COLUMN original_text TEXT",
            "translated_text": "ALTER TABLE product_facts ADD COLUMN translated_text TEXT",
            "normalized_value": "ALTER TABLE product_facts ADD COLUMN normalized_value VARCHAR(255)",
            "normalized_unit": "ALTER TABLE product_facts ADD COLUMN normalized_unit VARCHAR(50)",
            "scope": "ALTER TABLE product_facts ADD COLUMN scope VARCHAR(30) DEFAULT 'product'",
            "model_option": "ALTER TABLE product_facts ADD COLUMN model_option VARCHAR(255)",
            "extractor_version": "ALTER TABLE product_facts ADD COLUMN extractor_version VARCHAR(50)",
            "conflict_group_key": "ALTER TABLE product_facts ADD COLUMN conflict_group_key VARCHAR(255)",
            "seller_confirmed_at": "ALTER TABLE product_facts ADD COLUMN seller_confirmed_at TIMESTAMP",
            "seller_confirmed_by": "ALTER TABLE product_facts ADD COLUMN seller_confirmed_by VARCHAR(36)",
        }

        with engine.begin() as connection:
            for column_name, ddl in column_ddls.items():
                if column_name not in existing_columns:
                    connection.execute(text(ddl))

    if "users" in table_names:
        existing_user_columns = {column["name"] for column in inspector.get_columns("users")}
        user_column_ddls = {
            "is_active": "ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE",
            "deleted_at": "ALTER TABLE users ADD COLUMN deleted_at TIMESTAMP",
            "created_at": "ALTER TABLE users ADD COLUMN created_at TIMESTAMP",
        }
        with engine.begin() as connection:
            for column_name, ddl in user_column_ddls.items():
                if column_name not in existing_user_columns:
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
            if "planning_mode" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN planning_mode VARCHAR(20) NOT NULL DEFAULT 'quality'"))
            if "planning_draft" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN planning_draft JSON"))
            if "brand_kit_version_id" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN brand_kit_version_id VARCHAR(36)"))
            if "brand_kit_override_version_id" not in existing_project_columns:
                connection.execute(text("ALTER TABLE product_projects ADD COLUMN brand_kit_override_version_id VARCHAR(36)"))

    if "brand_kit_versions" in table_names:
        existing_brand_kit_columns = {
            column["name"] for column in inspector.get_columns("brand_kit_versions")
        }
        if "watermark_policy" not in existing_brand_kit_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE brand_kit_versions ADD COLUMN watermark_policy JSON NOT NULL DEFAULT '{}'")
                )

    if "product_creative_brief_versions" in table_names:
        existing_brief_columns = {
            column["name"] for column in inspector.get_columns("product_creative_brief_versions")
        }
        if "previous_version_id" not in existing_brief_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE product_creative_brief_versions "
                        "ADD COLUMN previous_version_id VARCHAR(36) "
                        "REFERENCES product_creative_brief_versions(id)"
                    )
                )

    if "review_input_versions" in table_names:
        existing_review_columns = {
            column["name"] for column in inspector.get_columns("review_input_versions")
        }
        if "source_asset_id" not in existing_review_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE review_input_versions ADD COLUMN source_asset_id VARCHAR(36) "
                        "REFERENCES assets(id) ON DELETE SET NULL"
                    )
                )
        # The column and index are independently idempotent: a previously
        # interrupted migration may have added only the column.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_review_input_versions_source_asset_id "
                    "ON review_input_versions (source_asset_id)"
                )
            )

    if "figma_export_jobs" in table_names:
        existing_figma_columns = {
            column["name"] for column in inspector.get_columns("figma_export_jobs")
        }
        if "auth_url" not in existing_figma_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE figma_export_jobs ADD COLUMN auth_url TEXT")
                )

    # The image-job FK added below requires the immutable LG-8 table first.
    if "scene_prompt_versions" not in table_names:
        Base.metadata.tables["scene_prompt_versions"].create(bind=engine, checkfirst=True)
    else:
        existing_scene_prompt_columns = {
            column["name"] for column in inspector.get_columns("scene_prompt_versions")
        }
        scene_prompt_column_ddls = {
            "rights_snapshot": (
                "ALTER TABLE scene_prompt_versions ADD COLUMN rights_snapshot JSON NOT NULL DEFAULT '[]'"
            ),
            "instruction_priority": (
                "ALTER TABLE scene_prompt_versions ADD COLUMN instruction_priority JSON NOT NULL DEFAULT '[]'"
            ),
        }
        with engine.begin() as connection:
            for column_name, ddl in scene_prompt_column_ddls.items():
                if column_name not in existing_scene_prompt_columns:
                    connection.execute(text(ddl))

    if "image_generation_jobs" in table_names:
        existing_generation_columns = {
            column["name"] for column in inspector.get_columns("image_generation_jobs")
        }
        generation_column_ddls = {
            "input_snapshot": "ALTER TABLE image_generation_jobs ADD COLUMN input_snapshot JSON NOT NULL DEFAULT '{}'",
            "validation_result": "ALTER TABLE image_generation_jobs ADD COLUMN validation_result JSON NOT NULL DEFAULT '{}'",
            "estimated_cost": "ALTER TABLE image_generation_jobs ADD COLUMN estimated_cost FLOAT",
            "actual_cost": "ALTER TABLE image_generation_jobs ADD COLUMN actual_cost FLOAT",
            "usage_metadata": "ALTER TABLE image_generation_jobs ADD COLUMN usage_metadata JSON NOT NULL DEFAULT '{}'",
            "seed": "ALTER TABLE image_generation_jobs ADD COLUMN seed VARCHAR(100)",
            "scene_id": "ALTER TABLE image_generation_jobs ADD COLUMN scene_id VARCHAR(100)",
            "prompt_version": "ALTER TABLE image_generation_jobs ADD COLUMN prompt_version VARCHAR(100)",
            "prompt_hash": "ALTER TABLE image_generation_jobs ADD COLUMN prompt_hash VARCHAR(64)",
            "reference_hash": "ALTER TABLE image_generation_jobs ADD COLUMN reference_hash VARCHAR(64)",
            "planning_hash": "ALTER TABLE image_generation_jobs ADD COLUMN planning_hash VARCHAR(64)",
            "input_hash": "ALTER TABLE image_generation_jobs ADD COLUMN input_hash VARCHAR(64)",
            "generation_attempt": "ALTER TABLE image_generation_jobs ADD COLUMN generation_attempt INTEGER NOT NULL DEFAULT 1",
            "idempotency_key": "ALTER TABLE image_generation_jobs ADD COLUMN idempotency_key VARCHAR(64)",
            "required_for_completion": "ALTER TABLE image_generation_jobs ADD COLUMN required_for_completion BOOLEAN NOT NULL DEFAULT TRUE",
            "supersedes_job_id": "ALTER TABLE image_generation_jobs ADD COLUMN supersedes_job_id VARCHAR(100)",
            "approved_at": "ALTER TABLE image_generation_jobs ADD COLUMN approved_at TIMESTAMP",
            "rejected_at": "ALTER TABLE image_generation_jobs ADD COLUMN rejected_at TIMESTAMP",
            "scene_prompt_version_id": "ALTER TABLE image_generation_jobs ADD COLUMN scene_prompt_version_id VARCHAR(36) REFERENCES scene_prompt_versions(id) ON DELETE SET NULL",
        }
        with engine.begin() as connection:
            for column_name, ddl in generation_column_ddls.items():
                if column_name not in existing_generation_columns:
                    connection.execute(text(ddl))
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_image_generation_jobs_idempotency_key "
                    "ON image_generation_jobs (idempotency_key) WHERE idempotency_key IS NOT NULL"
                )
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_image_generation_jobs_scene_id ON image_generation_jobs (scene_id)")
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_image_generation_jobs_scene_prompt_version_id ON image_generation_jobs (scene_prompt_version_id)")
            )

    if "page_sections" in table_names:
        existing_section_columns = {column["name"] for column in inspector.get_columns("page_sections")}
        with engine.begin() as connection:
            if "visual_kind" not in existing_section_columns:
                connection.execute(text("ALTER TABLE page_sections ADD COLUMN visual_kind VARCHAR(30)"))
            if "visual_payload" not in existing_section_columns:
                connection.execute(text("ALTER TABLE page_sections ADD COLUMN visual_payload JSON"))
            if "facts_stale" not in existing_section_columns:
                connection.execute(text("ALTER TABLE page_sections ADD COLUMN facts_stale BOOLEAN NOT NULL DEFAULT FALSE"))

    if "fact_histories" in table_names:
        existing_history_columns = {column["name"] for column in inspector.get_columns("fact_histories")}
        with engine.begin() as connection:
            if "event_type" not in existing_history_columns:
                connection.execute(text("ALTER TABLE fact_histories ADD COLUMN event_type VARCHAR(50) NOT NULL DEFAULT 'updated'"))
            if "previous_payload" not in existing_history_columns:
                connection.execute(text("ALTER TABLE fact_histories ADD COLUMN previous_payload JSON"))
            if "note" not in existing_history_columns:
                connection.execute(text("ALTER TABLE fact_histories ADD COLUMN note TEXT"))

    if "fact_evidences" in table_names:
        existing_evidence_columns = {column["name"] for column in inspector.get_columns("fact_evidences")}
        evidence_column_ddls = {
            "inspection_id": "ALTER TABLE fact_evidences ADD COLUMN inspection_id VARCHAR(36)",
            "ocr_language": "ALTER TABLE fact_evidences ADD COLUMN ocr_language VARCHAR(20)",
            "ocr_provider": "ALTER TABLE fact_evidences ADD COLUMN ocr_provider VARCHAR(50)",
            "ocr_model": "ALTER TABLE fact_evidences ADD COLUMN ocr_model VARCHAR(100)",
            "processed_at": "ALTER TABLE fact_evidences ADD COLUMN processed_at TIMESTAMP",
        }
        with engine.begin() as connection:
            for column_name, ddl in evidence_column_ddls.items():
                if column_name not in existing_evidence_columns:
                    connection.execute(text(ddl))

    # New tables are safe to create independently of the rest of the legacy
    # schema; create_all covers fresh installs and this covers upgraded ones.
    if "generation_jobs" not in table_names:
        Base.metadata.tables["generation_jobs"].create(bind=engine, checkfirst=True)

    if "assets" in table_names:
        existing_assets_columns = {column["name"] for column in inspector.get_columns("assets")}
        with engine.begin() as connection:
            if "source_asset_id" not in existing_assets_columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN source_asset_id VARCHAR(36)"))
            if "cutout_status" not in existing_assets_columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN cutout_status VARCHAR(50)"))
            if "background_removed" not in existing_assets_columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN background_removed BOOLEAN DEFAULT FALSE"))
            if "product_identity_preserved" not in existing_assets_columns:
                connection.execute(text("ALTER TABLE assets ADD COLUMN product_identity_preserved BOOLEAN DEFAULT TRUE"))
            asset_column_ddls = {
                "usage_status": "ALTER TABLE assets ADD COLUMN usage_status VARCHAR(30) NOT NULL DEFAULT 'blocked'",
                "asset_role": "ALTER TABLE assets ADD COLUMN asset_role VARCHAR(50) NOT NULL DEFAULT 'unknown'",
                "role_confidence": "ALTER TABLE assets ADD COLUMN role_confidence FLOAT NOT NULL DEFAULT 0",
                "role_source": "ALTER TABLE assets ADD COLUMN role_source VARCHAR(20) NOT NULL DEFAULT 'auto'",
                "quality_status": "ALTER TABLE assets ADD COLUMN quality_status VARCHAR(20) NOT NULL DEFAULT 'warning'",
                "identity_status": "ALTER TABLE assets ADD COLUMN identity_status VARCHAR(20) NOT NULL DEFAULT 'needs_review'",
                "width": "ALTER TABLE assets ADD COLUMN width INTEGER",
                "height": "ALTER TABLE assets ADD COLUMN height INTEGER",
                "image_format": "ALTER TABLE assets ADD COLUMN image_format VARCHAR(20)",
                "quality_warnings": "ALTER TABLE assets ADD COLUMN quality_warnings JSON",
                "content_hash": "ALTER TABLE assets ADD COLUMN content_hash VARCHAR(64)",
                "intake_order": "ALTER TABLE assets ADD COLUMN intake_order INTEGER",
                "ocr_text": "ALTER TABLE assets ADD COLUMN ocr_text TEXT",
                "safe_crop_status": "ALTER TABLE assets ADD COLUMN safe_crop_status VARCHAR(30) NOT NULL DEFAULT 'needs_review'",
                "is_representative": "ALTER TABLE assets ADD COLUMN is_representative BOOLEAN NOT NULL DEFAULT FALSE",
                "representative_source": "ALTER TABLE assets ADD COLUMN representative_source VARCHAR(20) NOT NULL DEFAULT 'auto'",
                "classification_version": "ALTER TABLE assets ADD COLUMN classification_version INTEGER NOT NULL DEFAULT 0",
            }
            for column_name, ddl in asset_column_ddls.items():
                if column_name not in existing_assets_columns:
                    connection.execute(text(ddl))
            connection.execute(
                text(
                    """
                    UPDATE assets
                    SET usage_status = CASE
                        WHEN source_type IN ('sourced', 'url-extracted', 'url-imported') THEN 'reference_only'
                        WHEN source_type IN ('ai_generated', 'ai-generated', 'generated_image', 'mock-generated', 'real-generated') THEN 'ai_generated'
                        WHEN source_type IN ('html-graphic', 'ai_corrected') THEN 'derived_graphic'
                        WHEN source_type IN ('uploaded', 'self_shot') THEN 'seller_owned'
                        ELSE 'blocked'
                    END
                    WHERE usage_status IS NULL OR usage_status = 'unknown'
                    """
                )
            )
    if "asset_inspections" in table_names:
        existing_inspection_columns = {
            column["name"] for column in inspector.get_columns("asset_inspections")
        }
        if "analysis_metadata" not in existing_inspection_columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE asset_inspections "
                        "ADD COLUMN analysis_metadata JSON NOT NULL DEFAULT '{}'"
                    )
                )
    if "source_captures" in table_names:
        existing_source_capture_columns = {
            column["name"] for column in inspector.get_columns("source_captures")
        }
        if "capture_metadata" not in existing_source_capture_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE source_captures ADD COLUMN capture_metadata JSON NOT NULL DEFAULT '{}'")
                )
    if "browser_extension_connections" in table_names:
        existing_extension_connection_columns = {
            column["name"] for column in inspector.get_columns("browser_extension_connections")
        }
        if "token_rotated_at" not in existing_extension_connection_columns:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE browser_extension_connections ADD COLUMN token_rotated_at TIMESTAMP")
                )
    if "browser_extension_captures" in table_names:
        existing_extension_capture_columns = {
            column["name"] for column in inspector.get_columns("browser_extension_captures")
        }
        extension_capture_ddls = {
            "selected_asset_ids": "ALTER TABLE browser_extension_captures ADD COLUMN selected_asset_ids JSON NOT NULL DEFAULT '[]'",
            "selection_scope": "ALTER TABLE browser_extension_captures ADD COLUMN selection_scope JSON NOT NULL DEFAULT '{}'",
        }
        with engine.begin() as connection:
            for column_name, ddl in extension_capture_ddls.items():
                if column_name not in existing_extension_capture_columns:
                    connection.execute(text(ddl))
    if "product_facts" in table_names:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE product_facts
                    SET verification_status = CASE
                        WHEN verification_status = 'confirmed'
                             AND (provider = 'seller_input' OR extraction_source = 'seller_input')
                            THEN 'seller_confirmed'
                        WHEN verification_status = 'confirmed' THEN 'source_confirmed'
                        WHEN verification_status = 'unknown' THEN 'extracted'
                        WHEN verification_status = 'needs_revision' THEN 'needs_review'
                        ELSE verification_status
                    END
                    WHERE verification_status IN ('confirmed', 'unknown', 'needs_revision')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE product_facts
                    SET needs_review = CASE
                        WHEN verification_status IN ('extracted', 'needs_review', 'conflicted') THEN TRUE
                        ELSE FALSE
                    END
                    """
                )
            )

    if "agent_runs" not in table_names or "agent_run_steps" not in table_names:
        Base.metadata.create_all(bind=engine)

    if "agent_runs" in table_names:
        existing_agent_run_columns = {
            column["name"] for column in inspector.get_columns("agent_runs")
        }
        agent_run_column_ddls = {
            "graph_thread_id": "ALTER TABLE agent_runs ADD COLUMN graph_thread_id VARCHAR(36)",
            "graph_checkpoint_id": "ALTER TABLE agent_runs ADD COLUMN graph_checkpoint_id VARCHAR(128)",
        }
        with engine.begin() as connection:
            for column_name, ddl in agent_run_column_ddls.items():
                if column_name not in existing_agent_run_columns:
                    connection.execute(text(ddl))
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_agent_runs_graph_thread_id "
                    "ON agent_runs (graph_thread_id)"
                )
            )

