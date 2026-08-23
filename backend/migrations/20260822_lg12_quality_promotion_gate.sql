-- LG-12 TASK-12.10: immutable final-promotion authority.
-- The Quality Bar remains a deterministic projection of its immutable report;
-- this row pins the PASS projection before public final/export use.

CREATE TABLE IF NOT EXISTS quality_promotion_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  creator_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  detail_page_version_id VARCHAR(36) NOT NULL REFERENCES detail_page_versions(id) ON DELETE RESTRICT,
  detail_page_schema_version VARCHAR(80) NOT NULL,
  detail_page_hash VARCHAR(64) NOT NULL,
  quality_report_id VARCHAR(36) NOT NULL REFERENCES quality_assessment_report_versions(id) ON DELETE RESTRICT,
  quality_report_version INTEGER NOT NULL,
  quality_report_hash VARCHAR(64) NOT NULL,
  quality_bar_result_id VARCHAR(160) NOT NULL,
  quality_bar_hash VARCHAR(64) NOT NULL,
  master_ref_json JSON NOT NULL DEFAULT '{}',
  page_plan_ref_json JSON NOT NULL DEFAULT '{}',
  brand_kit_ref_json JSON NOT NULL DEFAULT '{}',
  target_channels_json JSON NOT NULL DEFAULT '[]',
  canonical_hash VARCHAR(64) NOT NULL,
  created_by VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_quality_promotion_project_hash UNIQUE (project_id, canonical_hash),
  CONSTRAINT uq_quality_promotion_page_bar UNIQUE (project_id, detail_page_version_id, quality_bar_hash)
);
CREATE INDEX IF NOT EXISTS ix_quality_promotion_project ON quality_promotion_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_quality_promotion_page ON quality_promotion_versions(detail_page_version_id);

DROP TRIGGER IF EXISTS trg_quality_promotion_versions_immutable ON quality_promotion_versions;
CREATE TRIGGER trg_quality_promotion_versions_immutable
  BEFORE UPDATE OR DELETE ON quality_promotion_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();
