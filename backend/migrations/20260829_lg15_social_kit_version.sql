-- LG-15-A1: immutable, reference-only Social Creative Kit persistence.
-- No captions, prompts, provider payloads, image bytes, or rendered page data
-- belong in this table; cards retain frozen artifact identities only.

CREATE TABLE IF NOT EXISTS social_kit_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  creator_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  parent_version_id VARCHAR(36) REFERENCES social_kit_versions(id) ON DELETE RESTRICT,
  parent_version INTEGER,
  parent_version_hash VARCHAR(64),
  source_master_id VARCHAR(36) NOT NULL REFERENCES commerce_creative_master_versions(id) ON DELETE RESTRICT,
  source_master_version INTEGER NOT NULL,
  source_master_hash VARCHAR(64) NOT NULL,
  approved_fact_snapshot_ref_json JSON NOT NULL DEFAULT '{}',
  creative_brief_ref_json JSON NOT NULL DEFAULT '{}',
  brand_kit_ref_json JSON NOT NULL DEFAULT '{}',
  rights_asset_refs_json JSON NOT NULL DEFAULT '[]',
  target_channel VARCHAR(80) NOT NULL,
  target_format VARCHAR(80) NOT NULL,
  channel_contract_ref_json JSON NOT NULL DEFAULT '{}',
  execution_mode VARCHAR(40) NOT NULL,
  template_version VARCHAR(100) NOT NULL,
  evaluator_version VARCHAR(100) NOT NULL,
  card_manifest_json JSON NOT NULL DEFAULT '[]',
  output_hash VARCHAR(64) NOT NULL,
  idempotency_key VARCHAR(64) NOT NULL,
  canonical_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_social_kit_project_version UNIQUE (project_id, version),
  CONSTRAINT uq_social_kit_project_hash UNIQUE (project_id, canonical_hash),
  CONSTRAINT uq_social_kit_project_idempotency UNIQUE (project_id, idempotency_key),
  CONSTRAINT ck_social_kit_version_positive CHECK (version > 0),
  CONSTRAINT ck_social_kit_source_master_version_positive CHECK (source_master_version > 0),
  CONSTRAINT ck_social_kit_output_hash CHECK (output_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_social_kit_idempotency_key CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_social_kit_canonical_hash CHECK (canonical_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_social_kit_target_channel CHECK (char_length(target_channel) BETWEEN 1 AND 80),
  CONSTRAINT ck_social_kit_target_format CHECK (char_length(target_format) BETWEEN 1 AND 80)
);

CREATE INDEX IF NOT EXISTS ix_social_kit_workspace ON social_kit_versions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_social_kit_project ON social_kit_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_social_kit_creator_run ON social_kit_versions(creator_run_id);
CREATE INDEX IF NOT EXISTS ix_social_kit_source_master ON social_kit_versions(source_master_id);
CREATE INDEX IF NOT EXISTS ix_social_kit_output_hash ON social_kit_versions(output_hash);
CREATE INDEX IF NOT EXISTS ix_social_kit_canonical_hash ON social_kit_versions(canonical_hash);

DROP TRIGGER IF EXISTS trg_social_kit_versions_immutable ON social_kit_versions;
CREATE TRIGGER trg_social_kit_versions_immutable
  BEFORE UPDATE OR DELETE ON social_kit_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();

-- LG-15-A10.1: copy bodies live only in immutable, scoped artifacts.  The
-- SocialKit manifest stores references to these rows, never the body itself.
CREATE TABLE IF NOT EXISTS social_card_copy_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  source_social_kit_id VARCHAR(36) NOT NULL REFERENCES social_kit_versions(id) ON DELETE CASCADE,
  source_social_kit_version INTEGER NOT NULL,
  card_id VARCHAR(100) NOT NULL,
  source_master_id VARCHAR(36) NOT NULL REFERENCES commerce_creative_master_versions(id) ON DELETE RESTRICT,
  source_master_version INTEGER NOT NULL,
  version INTEGER NOT NULL,
  parent_version_id VARCHAR(36) REFERENCES social_card_copy_versions(id) ON DELETE RESTRICT,
  parent_version INTEGER,
  parent_version_hash VARCHAR(64),
  body_text TEXT NOT NULL,
  body_hash VARCHAR(64) NOT NULL,
  validation_status VARCHAR(32) NOT NULL,
  validation_result_json JSON NOT NULL DEFAULT '{}',
  author_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  idempotency_key VARCHAR(64) NOT NULL,
  canonical_hash VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_social_copy_project_card_version UNIQUE (project_id, card_id, version),
  CONSTRAINT uq_social_copy_project_idempotency UNIQUE (project_id, idempotency_key),
  CONSTRAINT ck_social_copy_version_positive CHECK (version > 0),
  CONSTRAINT ck_social_copy_body_bounded CHECK (char_length(body_text) BETWEEN 1 AND 2000),
  CONSTRAINT ck_social_copy_body_hash CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_social_copy_canonical_hash CHECK (canonical_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_social_copy_idempotency_key CHECK (idempotency_key ~ '^[0-9a-f]{64}$'),
  CONSTRAINT ck_social_copy_validation_status CHECK (validation_status IN ('PASS','REVIEW_REQUIRED','FAIL'))
);

CREATE INDEX IF NOT EXISTS ix_social_copy_workspace ON social_card_copy_versions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_social_copy_project ON social_card_copy_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_social_copy_source_kit ON social_card_copy_versions(source_social_kit_id);
CREATE INDEX IF NOT EXISTS ix_social_copy_source_master ON social_card_copy_versions(source_master_id);
DROP TRIGGER IF EXISTS trg_social_card_copy_versions_immutable ON social_card_copy_versions;
CREATE TRIGGER trg_social_card_copy_versions_immutable
  BEFORE UPDATE OR DELETE ON social_card_copy_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();
