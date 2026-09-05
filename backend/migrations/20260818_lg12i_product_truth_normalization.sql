-- LG-12I TASK-12I.6: bounded, immutable Product Truth normalization payload.
-- Source artifacts remain the owners of their bodies; this column stores only
-- normalized values and immutable ID/version/hash provenance references.
ALTER TABLE product_truth_versions
  ADD COLUMN IF NOT EXISTS normalization_json JSON NOT NULL DEFAULT '{}';
