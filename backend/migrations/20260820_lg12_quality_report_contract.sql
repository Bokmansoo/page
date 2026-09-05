-- LG-12 TASK-12.2: immutable, reference-only QualityAssessmentReport and
-- QualityThresholdProfile contracts.  Evaluators and final gate routing are
-- intentionally not part of this migration.

CREATE TABLE IF NOT EXISTS quality_threshold_profile_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  parent_profile_id VARCHAR(36) REFERENCES quality_threshold_profile_versions(id) ON DELETE RESTRICT,
  parent_profile_version INTEGER,
  parent_profile_hash VARCHAR(64),
  applicable_artifact_type VARCHAR(80) NOT NULL,
  applicable_channels_json JSON NOT NULL DEFAULT '[]',
  thresholds_json JSON NOT NULL DEFAULT '{}',
  status VARCHAR(40) NOT NULL,
  effective_from VARCHAR(80) NOT NULL,
  canonical_hash VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_quality_threshold_profile_project_hash UNIQUE (project_id, canonical_hash)
);
CREATE INDEX IF NOT EXISTS ix_quality_threshold_profile_project ON quality_threshold_profile_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_quality_threshold_profile_hash ON quality_threshold_profile_versions(canonical_hash);

CREATE TABLE IF NOT EXISTS quality_assessment_report_versions (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  creator_run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL,
  schema_version VARCHAR(80) NOT NULL,
  evaluator_bundle_version VARCHAR(100) NOT NULL,
  target_detail_page_version_id VARCHAR(36) NOT NULL REFERENCES detail_page_versions(id) ON DELETE RESTRICT,
  target_artifact_version VARCHAR(80) NOT NULL,
  target_artifact_hash VARCHAR(64) NOT NULL,
  approved_asset_manifest_hash VARCHAR(64) NOT NULL,
  target_channels_json JSON NOT NULL DEFAULT '[]',
  threshold_profile_id VARCHAR(36) NOT NULL REFERENCES quality_threshold_profile_versions(id) ON DELETE RESTRICT,
  threshold_profile_version INTEGER NOT NULL,
  threshold_profile_hash VARCHAR(64) NOT NULL,
  report_json JSON NOT NULL DEFAULT '{}',
  canonical_hash VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_quality_assessment_report_project_hash UNIQUE (project_id, canonical_hash)
);
CREATE INDEX IF NOT EXISTS ix_quality_assessment_report_project ON quality_assessment_report_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_quality_assessment_report_hash ON quality_assessment_report_versions(canonical_hash);
CREATE INDEX IF NOT EXISTS ix_quality_assessment_report_target ON quality_assessment_report_versions(target_detail_page_version_id);

-- Reuse the production immutable-version trigger function created by the
-- LG-12I migration; no update/delete path is allowed for either contract.
DROP TRIGGER IF EXISTS trg_quality_threshold_profile_versions_immutable ON quality_threshold_profile_versions;
CREATE TRIGGER trg_quality_threshold_profile_versions_immutable
  BEFORE UPDATE OR DELETE ON quality_threshold_profile_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();

DROP TRIGGER IF EXISTS trg_quality_assessment_report_versions_immutable ON quality_assessment_report_versions;
CREATE TRIGGER trg_quality_assessment_report_versions_immutable
  BEFORE UPDATE OR DELETE ON quality_assessment_report_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();
