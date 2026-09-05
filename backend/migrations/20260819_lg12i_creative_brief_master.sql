-- LG-12I TASK-12I.8: retain the existing Creative Brief artifact while
-- pinning the immutable intake lineage that produced new LG-12I briefs.
-- Old LG-7 rows intentionally remain readable; only additive nullable
-- reference fields are introduced here.

ALTER TABLE product_creative_brief_versions
  ADD COLUMN IF NOT EXISTS source_snapshot_version_id VARCHAR(36)
    REFERENCES product_source_snapshot_versions(id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS source_snapshot_version INTEGER,
  ADD COLUMN IF NOT EXISTS source_snapshot_hash VARCHAR(64),
  ADD COLUMN IF NOT EXISTS truth_version_id VARCHAR(36)
    REFERENCES product_truth_versions(id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS truth_version INTEGER,
  ADD COLUMN IF NOT EXISTS truth_version_hash VARCHAR(64),
  ADD COLUMN IF NOT EXISTS confirmation_version_id VARCHAR(36)
    REFERENCES seller_confirmation_versions(id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS confirmation_version INTEGER,
  ADD COLUMN IF NOT EXISTS confirmation_version_hash VARCHAR(64),
  ADD COLUMN IF NOT EXISTS target_channels JSON NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS review_reference_refs_json JSON NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS confirmed_fact_refs_json JSON NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS usable_asset_refs_json JSON NOT NULL DEFAULT '[]',
  ADD COLUMN IF NOT EXISTS prohibited_claim_refs_json JSON NOT NULL DEFAULT '[]';

-- LG-7 rows retain their original populated references.  LG-12I Briefs use
-- the intake lineage columns above instead of inventing synthetic legacy
-- prompt/fact artifacts, so those historical-only columns must be nullable.
ALTER TABLE product_creative_brief_versions
  ALTER COLUMN fact_snapshot_id DROP NOT NULL,
  ALTER COLUMN fact_snapshot_hash DROP NOT NULL,
  ALTER COLUMN compiled_prompt_artifact_id DROP NOT NULL,
  ALTER COLUMN category_pack_version_id DROP NOT NULL,
  ALTER COLUMN channel_pack_version_id DROP NOT NULL;

CREATE INDEX IF NOT EXISTS ix_product_creative_brief_truth
  ON product_creative_brief_versions(truth_version_id);
CREATE INDEX IF NOT EXISTS ix_product_creative_brief_confirmation
  ON product_creative_brief_versions(confirmation_version_id);

-- The shared LG-12I immutable trigger function is created by the intake
-- version-contract migration.  Reuse it rather than adding another mutation
-- policy or a compatibility execution path.
DROP TRIGGER IF EXISTS trg_product_creative_brief_versions_immutable
  ON product_creative_brief_versions;
CREATE TRIGGER trg_product_creative_brief_versions_immutable
  BEFORE UPDATE OR DELETE ON product_creative_brief_versions
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_lg12i_immutable_mutation();
