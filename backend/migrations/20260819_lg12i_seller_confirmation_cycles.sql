-- LG-12I TASK-12I.7: durable, immutable seller-confirmation cycles.
-- The version row stays an immutable reference record; questions and answers
-- are bounded JSON identities and never include raw source bodies.
ALTER TABLE seller_confirmation_versions
  ADD COLUMN IF NOT EXISTS confirmation_cycle INTEGER NOT NULL DEFAULT 1;

ALTER TABLE seller_confirmation_versions
  ADD COLUMN IF NOT EXISTS clarification_refs_json JSON NOT NULL DEFAULT '[]';

ALTER TABLE seller_confirmation_versions
  ADD COLUMN IF NOT EXISTS unresolved_refs_json JSON NOT NULL DEFAULT '[]';

ALTER TABLE seller_confirmation_versions
  ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- A confirmation resume is identified by the frozen question set and the
-- normalized submitted answer bundle.  These nullable additions preserve
-- validation of already-persisted v1-v3 immutable rows; v4 rows require both.
ALTER TABLE seller_confirmation_versions
  ADD COLUMN IF NOT EXISTS resume_request_hash VARCHAR(64);

ALTER TABLE seller_confirmation_versions
  ADD COLUMN IF NOT EXISTS resume_answer_bundle_hash VARCHAR(64);

CREATE INDEX IF NOT EXISTS ix_seller_confirmation_resume_replay
  ON seller_confirmation_versions (creator_run_id, created_by, resume_request_hash);

-- PostgreSQL enforces that a run can persist a given Truth confirmation cycle
-- once.  The application verifies the immediate parent under row locks; this
-- constraint is the durable concurrent-write backstop.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'uq_seller_confirmation_run_truth_cycle'
      AND conrelid = 'seller_confirmation_versions'::regclass
  ) THEN
    ALTER TABLE seller_confirmation_versions
      ADD CONSTRAINT uq_seller_confirmation_run_truth_cycle
      UNIQUE (creator_run_id, truth_version_id, confirmation_cycle);
  END IF;
END $$;

-- Seller confirmation is a server-managed immutable lineage record.  It is
-- not a Data API resource: browser roles cannot read or mutate confirmation
-- decisions, while the backend service role can only read or insert a new
-- immutable successor.  The existing immutable trigger remains the final
-- UPDATE/DELETE backstop for every database role.
ALTER TABLE seller_confirmation_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE seller_confirmation_versions FORCE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE seller_confirmation_versions
  FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON TABLE seller_confirmation_versions TO service_role;
