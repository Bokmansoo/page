-- LG-13.1: immutable, run-local graph event journal.

ALTER TABLE agent_runs
  ADD COLUMN IF NOT EXISTS last_applied_event_sequence INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS event_projection_version INTEGER NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS agent_run_events (
  id VARCHAR(36) PRIMARY KEY,
  run_id VARCHAR(36) NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL,
  event_type VARCHAR(80) NOT NULL,
  idempotency_key VARCHAR(64) NOT NULL,
  payload_json JSON NOT NULL DEFAULT '{}',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_agent_run_event_idempotency UNIQUE (run_id, idempotency_key),
  CONSTRAINT uq_agent_run_event_sequence UNIQUE (run_id, sequence),
  CONSTRAINT ck_agent_run_event_sequence_positive CHECK (sequence > 0)
);
CREATE INDEX IF NOT EXISTS ix_agent_run_events_run_id ON agent_run_events(run_id);

CREATE OR REPLACE FUNCTION sellform_reject_agent_run_event_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'AGENT_RUN_EVENT_IMMUTABLE: % rows cannot be %', TG_TABLE_NAME, TG_OP
    USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_agent_run_events_immutable ON agent_run_events;
CREATE TRIGGER trg_agent_run_events_immutable
  BEFORE UPDATE OR DELETE ON agent_run_events
  FOR EACH ROW EXECUTE FUNCTION sellform_reject_agent_run_event_mutation();
