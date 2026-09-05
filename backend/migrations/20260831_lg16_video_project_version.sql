-- LG-16-A1: immutable VideoProjectVersion identity foundation.
-- This table stores only bounded references and hashes; storyboard bodies,
-- prompts, provider payloads, media bytes, and audio/caption bodies are deferred.

CREATE TABLE IF NOT EXISTS video_project_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  creator_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  parent_video_project_version_id VARCHAR(36) REFERENCES video_project_versions(id) ON DELETE RESTRICT,
  parent_version INTEGER,
  parent_version_hash VARCHAR(64),
  source_master_id VARCHAR(36) NOT NULL REFERENCES commerce_creative_master_versions(id) ON DELETE RESTRICT,
  source_master_version INTEGER NOT NULL,
  source_master_hash VARCHAR(64) NOT NULL,
  approved_fact_snapshot_ref_json JSON NOT NULL DEFAULT '{}',
  creative_brief_ref_json JSON NOT NULL DEFAULT '{}',
  brand_kit_ref_json JSON NOT NULL DEFAULT '{}',
  rights_asset_refs_json JSON NOT NULL DEFAULT '[]',
  planning_contract_ref_json JSON NOT NULL DEFAULT '{}',
  video_manifest_json JSON NOT NULL DEFAULT '{}',
  publishing_targets_json JSON NOT NULL DEFAULT '[]',
  execution_mode VARCHAR(40) NOT NULL,
  output_hash VARCHAR(64),
  idempotency_key VARCHAR(64) NOT NULL,
  canonical_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_video_project_project_version UNIQUE (project_id, version),
  CONSTRAINT uq_video_project_project_hash UNIQUE (project_id, canonical_hash),
  CONSTRAINT uq_video_project_project_idempotency UNIQUE (project_id, idempotency_key),
  CONSTRAINT ck_video_project_version_positive CHECK (version > 0),
  CONSTRAINT ck_video_project_source_master_version_positive CHECK (source_master_version > 0),
  CONSTRAINT ck_video_project_canonical_hash CHECK (canonical_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_video_project_idempotency_key CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_video_project_output_hash CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS ix_video_project_workspace ON video_project_versions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_video_project_project ON video_project_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_video_project_creator_run ON video_project_versions(creator_run_id);
CREATE INDEX IF NOT EXISTS ix_video_project_source_master ON video_project_versions(source_master_id);
CREATE INDEX IF NOT EXISTS ix_video_project_canonical_hash ON video_project_versions(canonical_hash);

DROP TRIGGER IF EXISTS trg_video_project_versions_immutable ON video_project_versions;
CREATE TRIGGER trg_video_project_versions_immutable
  BEFORE UPDATE OR DELETE ON video_project_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();
