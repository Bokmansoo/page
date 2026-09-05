-- LG-16-A6: immutable, fact-bound editable video text.
-- The body is stored only in this canonical artifact; manifests/journals keep refs and hashes.

CREATE TABLE IF NOT EXISTS video_text_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  video_project_version_id VARCHAR(36) NOT NULL REFERENCES video_project_versions(id) ON DELETE RESTRICT,
  source_master_id VARCHAR(36) NOT NULL REFERENCES commerce_creative_master_versions(id) ON DELETE RESTRICT,
  schema_version VARCHAR(80) NOT NULL DEFAULT 'lg16-video-text-v1',
  scene_id VARCHAR(100) NOT NULL,
  text_role VARCHAR(40) NOT NULL,
  placement_role VARCHAR(40) NOT NULL,
  visibility_status VARCHAR(24) NOT NULL DEFAULT 'visible',
  version INTEGER NOT NULL,
  parent_text_version_id VARCHAR(36) REFERENCES video_text_versions(id) ON DELETE RESTRICT,
  parent_text_version INTEGER,
  parent_text_hash VARCHAR(64),
  body_text TEXT NOT NULL,
  body_hash VARCHAR(64) NOT NULL,
  source_fact_refs_json JSON NOT NULL DEFAULT '[]',
  provenance_refs_json JSON NOT NULL DEFAULT '[]',
  validation_status VARCHAR(32) NOT NULL,
  validation_result_json JSON NOT NULL DEFAULT '{}',
  author_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  idempotency_key VARCHAR(64) NOT NULL,
  canonical_hash VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_video_text_project_idempotency UNIQUE (project_id, idempotency_key),
  CONSTRAINT uq_video_text_scene_version UNIQUE (project_id, video_project_version_id, scene_id, text_role, version),
  CONSTRAINT ck_video_text_version_positive CHECK (version > 0),
  CONSTRAINT ck_video_text_body_hash CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_video_text_canonical_hash CHECK (canonical_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_video_text_idempotency_key CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_video_text_validation_status CHECK (validation_status IN ('PASS','REVIEW_REQUIRED','FAIL'))
);

ALTER TABLE video_text_versions
  ADD COLUMN IF NOT EXISTS schema_version VARCHAR(80) NOT NULL DEFAULT 'lg16-video-text-v1';

CREATE INDEX IF NOT EXISTS ix_video_text_workspace ON video_text_versions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_video_text_project ON video_text_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_video_text_project_version ON video_text_versions(video_project_version_id);
CREATE INDEX IF NOT EXISTS ix_video_text_scene ON video_text_versions(scene_id);
CREATE INDEX IF NOT EXISTS ix_video_text_canonical_hash ON video_text_versions(canonical_hash);

DROP TRIGGER IF EXISTS trg_video_text_versions_immutable ON video_text_versions;
CREATE TRIGGER trg_video_text_versions_immutable
  BEFORE UPDATE OR DELETE ON video_text_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();
