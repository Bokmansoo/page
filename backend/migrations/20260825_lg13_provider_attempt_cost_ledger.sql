-- LG-13.3: immutable provider-attempt usage and cost accounting.

CREATE TABLE IF NOT EXISTS image_generation_provider_attempts (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  thread_id VARCHAR(36) NOT NULL,
  image_job_id VARCHAR(36) NOT NULL REFERENCES image_generation_jobs(id) ON DELETE CASCADE,
  outbox_id VARCHAR(36) REFERENCES image_generation_outbox(id) ON DELETE SET NULL,
  job_id VARCHAR(100) NOT NULL,
  scene_id VARCHAR(100),
  seller_generation_attempt INTEGER NOT NULL,
  delivery_attempt INTEGER NOT NULL DEFAULT 0,
  provider_adapter_attempt INTEGER NOT NULL,
  provider VARCHAR(50) NOT NULL,
  model VARCHAR(100) NOT NULL,
  semantic_idempotency_key VARCHAR(64) NOT NULL,
  dispatch_state VARCHAR(30) NOT NULL,
  cost_state VARCHAR(40) NOT NULL,
  estimated_cost_at_dispatch FLOAT,
  actual_cost FLOAT,
  currency VARCHAR(20) NOT NULL DEFAULT 'credit',
  usage_json JSON NOT NULL DEFAULT '{}',
  outcome_code VARCHAR(100) NOT NULL DEFAULT 'SUCCESS',
  latency_ms INTEGER,
  started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,
  CONSTRAINT uq_image_provider_attempt_semantic UNIQUE (semantic_idempotency_key),
  CONSTRAINT uq_image_provider_attempt_job_adapter UNIQUE (image_job_id, provider_adapter_attempt),
  CONSTRAINT ck_image_provider_attempt_seller_positive CHECK (seller_generation_attempt > 0),
  CONSTRAINT ck_image_provider_attempt_adapter_positive CHECK (provider_adapter_attempt > 0),
  CONSTRAINT ck_image_provider_attempt_delivery_nonnegative CHECK (delivery_attempt >= 0),
  CONSTRAINT ck_image_provider_attempt_dispatch_state CHECK (dispatch_state IN ('NOT_DISPATCHED', 'DISPATCHED')),
  CONSTRAINT ck_image_provider_attempt_cost_state CHECK (cost_state IN ('NOT_DISPATCHED', 'EXPLICIT_ZERO', 'KNOWN', 'UNKNOWN_AFTER_DISPATCH')),
  CONSTRAINT ck_image_provider_attempt_actual_cost CHECK (
    (cost_state = 'UNKNOWN_AFTER_DISPATCH' AND actual_cost IS NULL) OR
    (cost_state <> 'UNKNOWN_AFTER_DISPATCH' AND actual_cost IS NOT NULL AND actual_cost >= 0)
  )
);

CREATE INDEX IF NOT EXISTS ix_image_provider_attempt_run_id ON image_generation_provider_attempts (run_id);
CREATE INDEX IF NOT EXISTS ix_image_provider_attempt_job_id ON image_generation_provider_attempts (image_job_id);

CREATE OR REPLACE FUNCTION sellform_reject_image_provider_attempt_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'IMAGE_PROVIDER_ATTEMPT_IMMUTABLE: % rows cannot be %', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_image_provider_attempts_immutable ON image_generation_provider_attempts;
CREATE TRIGGER trg_image_provider_attempts_immutable
  BEFORE UPDATE OR DELETE ON image_generation_provider_attempts
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_image_provider_attempt_mutation();
