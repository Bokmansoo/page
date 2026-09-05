-- LG-16-A7: immutable platform publishing metadata bound to one common MP4.
-- Exact metadata bodies live only in this artifact; events/checkpoints keep refs and hashes.

CREATE TABLE IF NOT EXISTS video_platform_metadata_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  video_project_version_id VARCHAR(36) NOT NULL REFERENCES video_project_versions(id) ON DELETE RESTRICT,
  source_master_id VARCHAR(36) NOT NULL REFERENCES commerce_creative_master_versions(id) ON DELETE RESTRICT,
  final_asset_id VARCHAR(36) NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
  final_asset_hash VARCHAR(64) NOT NULL,
  schema_version VARCHAR(80) NOT NULL DEFAULT 'lg16-video-platform-metadata-v1',
  platform VARCHAR(32) NOT NULL,
  version INTEGER NOT NULL,
  parent_metadata_version_id VARCHAR(36) REFERENCES video_platform_metadata_versions(id) ON DELETE RESTRICT,
  parent_metadata_version INTEGER,
  parent_metadata_hash VARCHAR(64),
  title_text TEXT,
  caption_text TEXT,
  description_text TEXT,
  cta_text TEXT,
  hashtags_json JSON NOT NULL DEFAULT '[]',
  text_refs_json JSON NOT NULL DEFAULT '[]',
  source_fact_refs_json JSON NOT NULL DEFAULT '[]',
  provenance_refs_json JSON NOT NULL DEFAULT '[]',
  validation_status VARCHAR(32) NOT NULL,
  validation_result_json JSON NOT NULL DEFAULT '{}',
  author_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  idempotency_key VARCHAR(64) NOT NULL,
  canonical_hash VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_video_platform_metadata_idempotency UNIQUE (project_id, platform, idempotency_key),
  CONSTRAINT uq_video_platform_metadata_version UNIQUE (project_id, platform, version),
  CONSTRAINT ck_video_platform_metadata_version_positive CHECK (version > 0),
  CONSTRAINT ck_video_platform_metadata_platform CHECK (platform IN ('reels','tiktok','youtube_shorts')),
  CONSTRAINT ck_video_platform_metadata_asset_hash CHECK (length(final_asset_hash) = 64 AND final_asset_hash = lower(final_asset_hash)),
  CONSTRAINT ck_video_platform_metadata_canonical_hash CHECK (length(canonical_hash) = 64 AND canonical_hash = lower(canonical_hash)),
  CONSTRAINT ck_video_platform_metadata_idempotency_key CHECK (length(idempotency_key) = 64 AND idempotency_key = lower(idempotency_key)),
  CONSTRAINT ck_video_platform_metadata_validation_status CHECK (validation_status IN ('PASS','REVIEW_REQUIRED','FAIL'))
);

CREATE INDEX IF NOT EXISTS ix_video_platform_metadata_workspace ON video_platform_metadata_versions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_video_platform_metadata_project ON video_platform_metadata_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_video_platform_metadata_video ON video_platform_metadata_versions(video_project_version_id);
CREATE INDEX IF NOT EXISTS ix_video_platform_metadata_asset ON video_platform_metadata_versions(final_asset_id);
CREATE INDEX IF NOT EXISTS ix_video_platform_metadata_platform ON video_platform_metadata_versions(platform);
CREATE INDEX IF NOT EXISTS ix_video_platform_metadata_hash ON video_platform_metadata_versions(canonical_hash);

DROP TRIGGER IF EXISTS trg_video_platform_metadata_versions_immutable ON video_platform_metadata_versions;
CREATE TRIGGER trg_video_platform_metadata_versions_immutable
  BEFORE UPDATE OR DELETE ON video_platform_metadata_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();
