-- LG-7 review/reference intake, creative brief and gate audit schema.
CREATE TABLE IF NOT EXISTS review_input_versions (
  id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE, version INTEGER NOT NULL,
  input_format VARCHAR(20) NOT NULL, source_label VARCHAR(255), source_metadata JSON NOT NULL DEFAULT '{}',
  consent_status VARCHAR(30) NOT NULL DEFAULT 'unconfirmed', rights_status VARCHAR(30) NOT NULL DEFAULT 'unverified',
  content_text TEXT NOT NULL, content_hash VARCHAR(64) NOT NULL, created_by VARCHAR(36) NOT NULL REFERENCES users(id),
  collected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_review_input_project_version UNIQUE (project_id, version)
);
CREATE INDEX IF NOT EXISTS ix_review_input_project ON review_input_versions(project_id);

CREATE TABLE IF NOT EXISTS review_insight_versions (
  id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  review_input_version_id VARCHAR(36) NOT NULL REFERENCES review_input_versions(id) ON DELETE CASCADE,
  analyzer_version VARCHAR(100) NOT NULL DEFAULT 'lg7-review-v1', insights_json JSON NOT NULL DEFAULT '{}',
  content_hash VARCHAR(64) NOT NULL, fact_promotion_status VARCHAR(30) NOT NULL DEFAULT 'blocked',
  usage_status VARCHAR(30) NOT NULL DEFAULT 'available', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_review_insight_analysis UNIQUE (review_input_version_id, analyzer_version)
);

CREATE TABLE IF NOT EXISTS reference_input_versions (
  id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE, version INTEGER NOT NULL,
  input_kind VARCHAR(20) NOT NULL, source_url TEXT, asset_id VARCHAR(36) REFERENCES assets(id) ON DELETE SET NULL,
  content_text TEXT, source_metadata JSON NOT NULL DEFAULT '{}', rights_status VARCHAR(30) NOT NULL DEFAULT 'unverified',
  usage_scope VARCHAR(30) NOT NULL DEFAULT 'analysis_only', content_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id), collected_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_reference_input_project_version UNIQUE (project_id, version)
);
CREATE INDEX IF NOT EXISTS ix_reference_input_project ON reference_input_versions(project_id);

CREATE TABLE IF NOT EXISTS reference_insight_versions (
  id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  reference_input_version_id VARCHAR(36) NOT NULL REFERENCES reference_input_versions(id) ON DELETE CASCADE,
  analyzer_version VARCHAR(100) NOT NULL DEFAULT 'lg7-reference-v1', abstract_signals_json JSON NOT NULL DEFAULT '{}',
  content_hash VARCHAR(64) NOT NULL, usage_status VARCHAR(30) NOT NULL DEFAULT 'available',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_reference_insight_analysis UNIQUE (reference_input_version_id, analyzer_version)
);

CREATE TABLE IF NOT EXISTS seller_creative_direction_versions (
  id VARCHAR(36) PRIMARY KEY, project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  version INTEGER NOT NULL, desired_mood JSON NOT NULL DEFAULT '[]', target_audience TEXT,
  emphasis JSON NOT NULL DEFAULT '[]', forbidden_scenes JSON NOT NULL DEFAULT '[]', content_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id), created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_creative_direction_project_version UNIQUE (project_id, version)
);

CREATE TABLE IF NOT EXISTS product_creative_brief_versions (
  id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE, version INTEGER NOT NULL,
  previous_version_id VARCHAR(36) REFERENCES product_creative_brief_versions(id),
  fact_snapshot_id VARCHAR(36) NOT NULL REFERENCES fact_snapshots(id), fact_snapshot_hash VARCHAR(64) NOT NULL,
  compiled_prompt_artifact_id VARCHAR(36) NOT NULL REFERENCES compiled_prompt_artifacts(id),
  category_pack_version_id VARCHAR(36) NOT NULL REFERENCES prompt_pack_versions(id),
  channel_pack_version_id VARCHAR(36) NOT NULL REFERENCES prompt_pack_versions(id),
  brand_kit_version_id VARCHAR(36) REFERENCES brand_kit_versions(id), brand_kit_hash VARCHAR(64),
  creative_direction_version_id VARCHAR(36) REFERENCES seller_creative_direction_versions(id),
  review_insight_version_ids JSON NOT NULL DEFAULT '[]', reference_insight_version_ids JSON NOT NULL DEFAULT '[]',
  approved_fact_ids JSON NOT NULL DEFAULT '[]', compiler_version VARCHAR(100) NOT NULL DEFAULT 'lg7-creative-brief-v1',
  input_hash VARCHAR(64) NOT NULL, output_hash VARCHAR(64) NOT NULL, brief_json JSON NOT NULL DEFAULT '{}',
  created_by VARCHAR(36) NOT NULL REFERENCES users(id), created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_product_creative_brief_version UNIQUE (project_id, version),
  CONSTRAINT uq_product_creative_brief_run_input UNIQUE (run_id, input_hash)
);
ALTER TABLE product_creative_brief_versions
  ADD COLUMN IF NOT EXISTS previous_version_id VARCHAR(36) REFERENCES product_creative_brief_versions(id);

CREATE TABLE IF NOT EXISTS workflow_gate_events (
  id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE, gate_stage VARCHAR(80) NOT NULL,
  interaction_mode VARCHAR(20) NOT NULL, decision VARCHAR(30) NOT NULL, decision_source VARCHAR(20) NOT NULL,
  rationale TEXT NOT NULL, impact_json JSON NOT NULL DEFAULT '{}', checkpoint_id VARCHAR(128),
  created_by VARCHAR(36) REFERENCES users(id), created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_workflow_gate_run ON workflow_gate_events(run_id);
