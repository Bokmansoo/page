-- LG-6 Prompt Intelligence + Brand Kit schema.

CREATE TABLE IF NOT EXISTS prompt_packs (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  pack_type VARCHAR(20) NOT NULL,
  pack_key VARCHAR(100) NOT NULL,
  locale VARCHAR(20) NOT NULL DEFAULT 'ko-KR',
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_prompt_pack_scope UNIQUE (workspace_id, pack_type, pack_key, locale)
);

CREATE TABLE IF NOT EXISTS prompt_pack_versions (
  id VARCHAR(36) PRIMARY KEY,
  pack_id VARCHAR(36) NOT NULL REFERENCES prompt_packs(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'draft_generated',
  content_json JSON NOT NULL DEFAULT '{}',
  content_hash VARCHAR(64) NOT NULL,
  evaluation_score FLOAT,
  evaluation_dataset_version VARCHAR(100),
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  validated_by VARCHAR(36) REFERENCES users(id),
  approved_by VARCHAR(36) REFERENCES users(id),
  activated_by VARCHAR(36) REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  validated_at TIMESTAMP,
  approved_at TIMESTAMP,
  activated_at TIMESTAMP,
  deprecated_at TIMESTAMP,
  CONSTRAINT uq_prompt_pack_version UNIQUE (pack_id, version)
);

CREATE INDEX IF NOT EXISTS ix_prompt_packs_workspace_id ON prompt_packs(workspace_id);
CREATE INDEX IF NOT EXISTS ix_prompt_pack_versions_pack_id ON prompt_pack_versions(pack_id);
CREATE INDEX IF NOT EXISTS ix_prompt_pack_versions_status ON prompt_pack_versions(status);
CREATE UNIQUE INDEX IF NOT EXISTS ix_prompt_pack_one_active
  ON prompt_pack_versions (pack_id)
  WHERE status = 'active';

CREATE TABLE IF NOT EXISTS category_evaluation_reports (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  dataset_version VARCHAR(100) NOT NULL,
  classifier_version VARCHAR(100) NOT NULL,
  input_hash VARCHAR(64) NOT NULL,
  output_hash VARCHAR(64) NOT NULL,
  accuracy FLOAT NOT NULL,
  safe_fallback_rate FLOAT NOT NULL DEFAULT 0,
  report_json JSON NOT NULL DEFAULT '{}',
  creator_run_id VARCHAR(36) REFERENCES agent_runs(id) ON DELETE SET NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS brand_kits (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_brand_kit_workspace_name UNIQUE (workspace_id, name)
);

CREATE TABLE IF NOT EXISTS brand_kit_versions (
  id VARCHAR(36) PRIMARY KEY,
  brand_kit_id VARCHAR(36) NOT NULL REFERENCES brand_kits(id) ON DELETE CASCADE,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  scope VARCHAR(20) NOT NULL DEFAULT 'workspace',
  project_id VARCHAR(36) REFERENCES product_projects(id) ON DELETE CASCADE,
  logo_asset_ids JSON NOT NULL DEFAULT '[]',
  font_asset_ids JSON NOT NULL DEFAULT '[]',
  color_tokens JSON NOT NULL DEFAULT '{}',
  typography JSON NOT NULL DEFAULT '{}',
  tone_of_voice JSON NOT NULL DEFAULT '{}',
  forbidden_terms JSON NOT NULL DEFAULT '[]',
  cta_rules JSON NOT NULL DEFAULT '{}',
  image_style JSON NOT NULL DEFAULT '{}',
  layout_rules JSON NOT NULL DEFAULT '{}',
  background_rules JSON NOT NULL DEFAULT '{}',
  watermark_policy JSON NOT NULL DEFAULT '{}',
  constraints JSON NOT NULL DEFAULT '{}',
  asset_rights JSON NOT NULL DEFAULT '{}',
  content_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  activated_by VARCHAR(36) REFERENCES users(id),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  activated_at TIMESTAMP,
  deprecated_at TIMESTAMP,
  CONSTRAINT uq_brand_kit_version UNIQUE (brand_kit_id, version)
);

CREATE INDEX IF NOT EXISTS ix_brand_kits_workspace_id ON brand_kits(workspace_id);
CREATE INDEX IF NOT EXISTS ix_brand_kit_versions_project_id ON brand_kit_versions(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_brand_kit_one_workspace_active
  ON brand_kit_versions (workspace_id)
  WHERE status = 'active' AND scope = 'workspace';

ALTER TABLE brand_kit_versions ADD COLUMN IF NOT EXISTS watermark_policy JSON NOT NULL DEFAULT '{}';

ALTER TABLE product_projects ADD COLUMN IF NOT EXISTS brand_kit_version_id VARCHAR(36) REFERENCES brand_kit_versions(id);
ALTER TABLE product_projects ADD COLUMN IF NOT EXISTS brand_kit_override_version_id VARCHAR(36) REFERENCES brand_kit_versions(id);

CREATE TABLE IF NOT EXISTS compiled_prompt_artifacts (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  category_pack_version_id VARCHAR(36) NOT NULL REFERENCES prompt_pack_versions(id),
  channel_pack_version_id VARCHAR(36) NOT NULL REFERENCES prompt_pack_versions(id),
  brand_kit_version_id VARCHAR(36) REFERENCES brand_kit_versions(id),
  category_pack_hash VARCHAR(64) NOT NULL,
  channel_pack_hash VARCHAR(64) NOT NULL,
  brand_kit_hash VARCHAR(64),
  compiler_version VARCHAR(100) NOT NULL,
  input_hash VARCHAR(64) NOT NULL,
  output_hash VARCHAR(64) NOT NULL,
  compiled_json JSON NOT NULL DEFAULT '{}',
  creator_run_id VARCHAR(36) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_compiled_prompt_run UNIQUE (run_id)
);
