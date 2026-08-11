-- LG-7R: provenance link for review material selected from collected assets.
-- Re-runnable on PostgreSQL.
ALTER TABLE review_input_versions
    ADD COLUMN IF NOT EXISTS source_asset_id VARCHAR(36)
    REFERENCES assets(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS ix_review_input_versions_source_asset_id
    ON review_input_versions (source_asset_id);
