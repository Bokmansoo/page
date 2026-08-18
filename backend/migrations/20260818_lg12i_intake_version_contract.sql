-- LG-12I: immutable Product Intake and Commerce Creative Master references.
-- These tables intentionally store version references and small structured
-- provenance only; raw source/OCR/copy/page payloads remain with their owners.

CREATE TABLE IF NOT EXISTS product_source_snapshot_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  creator_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  input_mode VARCHAR(40) NOT NULL,
  parent_version_id VARCHAR(36) REFERENCES product_source_snapshot_versions(id) ON DELETE RESTRICT,
  parent_version INTEGER,
  parent_version_hash VARCHAR(64),
  source_refs_json JSON NOT NULL DEFAULT '[]',
  provenance_json JSON NOT NULL DEFAULT '{}',
  rights_json JSON NOT NULL DEFAULT '{}',
  source_fidelity_json JSON NOT NULL DEFAULT '{}',
  canonical_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_product_source_snapshot_project_version UNIQUE (project_id, version),
  CONSTRAINT uq_product_source_snapshot_project_hash UNIQUE (project_id, canonical_hash)
);
CREATE INDEX IF NOT EXISTS ix_product_source_snapshot_project ON product_source_snapshot_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_product_source_snapshot_hash ON product_source_snapshot_versions(canonical_hash);

CREATE TABLE IF NOT EXISTS product_truth_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  creator_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  source_snapshot_version_id VARCHAR(36) NOT NULL REFERENCES product_source_snapshot_versions(id) ON DELETE RESTRICT,
  source_snapshot_version INTEGER NOT NULL,
  source_snapshot_hash VARCHAR(64) NOT NULL,
  parent_version_id VARCHAR(36) REFERENCES product_truth_versions(id) ON DELETE RESTRICT,
  parent_version INTEGER,
  parent_version_hash VARCHAR(64),
  fact_refs_json JSON NOT NULL DEFAULT '[]',
  evidence_refs_json JSON NOT NULL DEFAULT '[]',
  unknown_refs_json JSON NOT NULL DEFAULT '[]',
  conflict_refs_json JSON NOT NULL DEFAULT '[]',
  prohibited_inference_refs_json JSON NOT NULL DEFAULT '[]',
  canonical_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_product_truth_project_version UNIQUE (project_id, version),
  CONSTRAINT uq_product_truth_project_hash UNIQUE (project_id, canonical_hash)
);
CREATE INDEX IF NOT EXISTS ix_product_truth_project ON product_truth_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_product_truth_hash ON product_truth_versions(canonical_hash);

CREATE TABLE IF NOT EXISTS seller_confirmation_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  creator_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  truth_version_id VARCHAR(36) NOT NULL REFERENCES product_truth_versions(id) ON DELETE RESTRICT,
  truth_version INTEGER NOT NULL,
  truth_version_hash VARCHAR(64) NOT NULL,
  parent_version_id VARCHAR(36) REFERENCES seller_confirmation_versions(id) ON DELETE RESTRICT,
  parent_version INTEGER,
  parent_version_hash VARCHAR(64),
  answers_json JSON NOT NULL DEFAULT '[]',
  confirmed_fact_refs_json JSON NOT NULL DEFAULT '[]',
  rejected_fact_refs_json JSON NOT NULL DEFAULT '[]',
  unknown_fact_refs_json JSON NOT NULL DEFAULT '[]',
  rights_confirmations_json JSON NOT NULL DEFAULT '[]',
  canonical_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_seller_confirmation_project_version UNIQUE (project_id, version),
  CONSTRAINT uq_seller_confirmation_project_hash UNIQUE (project_id, canonical_hash)
);
CREATE INDEX IF NOT EXISTS ix_seller_confirmation_project ON seller_confirmation_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_seller_confirmation_hash ON seller_confirmation_versions(canonical_hash);

CREATE TABLE IF NOT EXISTS commerce_creative_master_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  creator_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  parent_version_id VARCHAR(36) REFERENCES commerce_creative_master_versions(id) ON DELETE RESTRICT,
  parent_version INTEGER,
  parent_version_hash VARCHAR(64),
  source_snapshot_version_id VARCHAR(36) NOT NULL REFERENCES product_source_snapshot_versions(id) ON DELETE RESTRICT,
  source_snapshot_version INTEGER NOT NULL,
  source_snapshot_hash VARCHAR(64) NOT NULL,
  truth_version_id VARCHAR(36) NOT NULL REFERENCES product_truth_versions(id) ON DELETE RESTRICT,
  truth_version INTEGER NOT NULL,
  truth_version_hash VARCHAR(64) NOT NULL,
  confirmation_version_id VARCHAR(36) NOT NULL REFERENCES seller_confirmation_versions(id) ON DELETE RESTRICT,
  confirmation_version INTEGER NOT NULL,
  confirmation_version_hash VARCHAR(64) NOT NULL,
  creative_brief_version_id VARCHAR(36) NOT NULL REFERENCES product_creative_brief_versions(id) ON DELETE RESTRICT,
  creative_brief_version INTEGER NOT NULL,
  creative_brief_hash VARCHAR(64) NOT NULL,
  brand_kit_version_id VARCHAR(36) NOT NULL REFERENCES brand_kit_versions(id) ON DELETE RESTRICT,
  brand_kit_version INTEGER NOT NULL,
  brand_kit_hash VARCHAR(64) NOT NULL,
  evidence_artifact_refs_json JSON NOT NULL DEFAULT '[]',
  approved_fact_snapshot_ref_json JSON NOT NULL DEFAULT '{}',
  approved_asset_manifest_ref_json JSON NOT NULL DEFAULT '{}',
  copy_artifact_ref_json JSON NOT NULL DEFAULT '{}',
  page_plan_artifact_ref_json JSON NOT NULL DEFAULT '{}',
  target_channels JSON NOT NULL DEFAULT '[]',
  downstream_output_refs_json JSON NOT NULL DEFAULT '[]',
  canonical_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_commerce_creative_master_project_version UNIQUE (project_id, version),
  CONSTRAINT uq_commerce_creative_master_project_hash UNIQUE (project_id, canonical_hash)
);
CREATE INDEX IF NOT EXISTS ix_commerce_creative_master_project ON commerce_creative_master_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_commerce_creative_master_hash ON commerce_creative_master_versions(canonical_hash);

-- PostgreSQL is the production source of truth for LG-12I immutability.
-- Each update/delete attempt, including Core SQL and direct SQL, is rejected;
-- successors must always be inserted as new rows.
CREATE OR REPLACE FUNCTION sellform_reject_lg12i_immutable_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'LG12I_IMMUTABLE_VERSION: % rows cannot be %', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_product_source_snapshot_versions_immutable ON product_source_snapshot_versions;
CREATE TRIGGER trg_product_source_snapshot_versions_immutable
  BEFORE UPDATE OR DELETE ON product_source_snapshot_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();

DROP TRIGGER IF EXISTS trg_product_truth_versions_immutable ON product_truth_versions;
CREATE TRIGGER trg_product_truth_versions_immutable
  BEFORE UPDATE OR DELETE ON product_truth_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();

DROP TRIGGER IF EXISTS trg_seller_confirmation_versions_immutable ON seller_confirmation_versions;
CREATE TRIGGER trg_seller_confirmation_versions_immutable
  BEFORE UPDATE OR DELETE ON seller_confirmation_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();

DROP TRIGGER IF EXISTS trg_commerce_creative_master_versions_immutable ON commerce_creative_master_versions;
CREATE TRIGGER trg_commerce_creative_master_versions_immutable
  BEFORE UPDATE OR DELETE ON commerce_creative_master_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();
