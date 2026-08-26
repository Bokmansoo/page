-- LG-13.5: PostgreSQL-authoritative timestamps for immutable SLO boundaries.

ALTER TABLE agent_run_events
  ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ;

ALTER TABLE agent_run_events
  ALTER COLUMN occurred_at SET DEFAULT clock_timestamp();

-- Historical immutable rows need a one-time schema backfill. This migration
-- runs transactionally and immediately restores the append-only trigger.
ALTER TABLE agent_run_events DISABLE TRIGGER trg_agent_run_events_immutable;
UPDATE agent_run_events
SET occurred_at = created_at AT TIME ZONE 'UTC'
WHERE occurred_at IS NULL;
ALTER TABLE agent_run_events ENABLE TRIGGER trg_agent_run_events_immutable;

ALTER TABLE agent_run_events
  ALTER COLUMN occurred_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_agent_run_events_slo_window
  ON agent_run_events (event_type, occurred_at);
