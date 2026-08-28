-- LG-5R durable image generation schema.
-- Safe for an existing PostgreSQL development database; fresh databases use
-- SQLAlchemy metadata with the same columns and constraints.

ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS scene_id VARCHAR(100);
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(100);
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS prompt_hash VARCHAR(64);
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS reference_hash VARCHAR(64);
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS planning_hash VARCHAR(64);
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS input_hash VARCHAR(64);
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS generation_attempt INTEGER NOT NULL DEFAULT 1;
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64);
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS required_for_completion BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS supersedes_job_id VARCHAR(100);
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP;
ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP;

CREATE UNIQUE INDEX IF NOT EXISTS ix_image_generation_jobs_idempotency_key
  ON image_generation_jobs (idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_image_generation_jobs_scene_id
  ON image_generation_jobs (scene_id);

CREATE TABLE IF NOT EXISTS image_generation_cost_approvals (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  thread_id VARCHAR(36) NOT NULL,
  planning_hash VARCHAR(64) NOT NULL,
  cost_plan_hash VARCHAR(64) NOT NULL,
  provider VARCHAR(50) NOT NULL,
  model VARCHAR(100) NOT NULL,
  scene_count INTEGER NOT NULL,
  scene_costs JSON NOT NULL DEFAULT '[]',
  total_estimated_cost FLOAT NOT NULL DEFAULT 0,
  currency VARCHAR(20) NOT NULL DEFAULT 'credit',
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  approved_by VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
  approved_at TIMESTAMP,
  deferred_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_image_cost_run_plan UNIQUE (run_id, cost_plan_hash)
);

CREATE TABLE IF NOT EXISTS image_generation_outbox (
  id VARCHAR(36) PRIMARY KEY,
  workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
  run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  thread_id VARCHAR(36) NOT NULL,
  image_job_id VARCHAR(36) NOT NULL UNIQUE REFERENCES image_generation_jobs(id) ON DELETE CASCADE,
  job_id VARCHAR(100) NOT NULL,
  idempotency_key VARCHAR(64) NOT NULL UNIQUE,
  provider_mode VARCHAR(20) NOT NULL DEFAULT 'mock',
  status VARCHAR(30) NOT NULL DEFAULT 'queued',
  lease_owner VARCHAR(100),
  lease_expires_at TIMESTAMP,
  available_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  delivery_attempts INTEGER NOT NULL DEFAULT 0,
  max_delivery_attempts INTEGER NOT NULL DEFAULT 3,
  provider_dispatch_count INTEGER NOT NULL DEFAULT 0,
  completion_resume_count INTEGER NOT NULL DEFAULT 0,
  last_error_code VARCHAR(100),
  last_error_message TEXT,
  completed_at TIMESTAMP,
  dead_lettered_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_image_generation_outbox_status
  ON image_generation_outbox (status);
CREATE INDEX IF NOT EXISTS ix_image_generation_outbox_available_at
  ON image_generation_outbox (available_at);
CREATE INDEX IF NOT EXISTS ix_image_generation_outbox_lease_expires_at
  ON image_generation_outbox (lease_expires_at);
