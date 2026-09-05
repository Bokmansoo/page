-- LG-8: immutable per-scene visual prompt compiler contracts.
CREATE TABLE IF NOT EXISTS scene_prompt_versions (
    id VARCHAR(36) PRIMARY KEY,
    workspace_id VARCHAR(36) NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id VARCHAR(36) NOT NULL REFERENCES product_projects(id) ON DELETE CASCADE,
    run_id VARCHAR(36) REFERENCES agent_runs(id) ON DELETE SET NULL,
    section_id VARCHAR(100) NOT NULL,
    scene_id VARCHAR(100) NOT NULL,
    scene_type VARCHAR(80) NOT NULL,
    version INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    objective TEXT NOT NULL,
    approved_fact_ids JSON NOT NULL DEFAULT '[]',
    reference_asset_ids JSON NOT NULL DEFAULT '[]',
    reference_hash VARCHAR(64) NOT NULL,
    identity_constraints JSON NOT NULL DEFAULT '{}',
    composition JSON NOT NULL DEFAULT '{}',
    camera JSON NOT NULL DEFAULT '{}',
    lighting JSON NOT NULL DEFAULT '{}',
    background JSON NOT NULL DEFAULT '{}',
    palette JSON NOT NULL DEFAULT '{}',
    material JSON NOT NULL DEFAULT '{}',
    negative_constraints JSON NOT NULL DEFAULT '[]',
    text_policy JSON NOT NULL DEFAULT '{}',
    rights_snapshot JSON NOT NULL DEFAULT '[]',
    instruction_priority JSON NOT NULL DEFAULT '[]',
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    size VARCHAR(50) NOT NULL,
    quality VARCHAR(30) NOT NULL DEFAULT 'standard',
    expected_cost FLOAT NOT NULL DEFAULT 0,
    prompt_version VARCHAR(100) NOT NULL,
    prompt_hash VARCHAR(64) NOT NULL,
    input_hash VARCHAR(64) NOT NULL,
    brand_kit_version_id VARCHAR(36) REFERENCES brand_kit_versions(id) ON DELETE SET NULL,
    brand_kit_visual_hash VARCHAR(64),
    canonical_prompt JSON NOT NULL DEFAULT '{}',
    seller_adjustment TEXT,
    supersedes_version_id VARCHAR(36) REFERENCES scene_prompt_versions(id) ON DELETE SET NULL,
    stale_reason VARCHAR(100),
    stale_impact JSON NOT NULL DEFAULT '{}',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    stale_at TIMESTAMP,
    CONSTRAINT uq_scene_prompt_project_scene_version UNIQUE (project_id, scene_id, version)
);

CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_workspace_id ON scene_prompt_versions(workspace_id);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_project_id ON scene_prompt_versions(project_id);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_run_id ON scene_prompt_versions(run_id);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_section_id ON scene_prompt_versions(section_id);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_scene_id ON scene_prompt_versions(scene_id);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_status ON scene_prompt_versions(status);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_reference_hash ON scene_prompt_versions(reference_hash);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_prompt_hash ON scene_prompt_versions(prompt_hash);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_input_hash ON scene_prompt_versions(input_hash);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_versions_brand_visual_hash ON scene_prompt_versions(brand_kit_visual_hash);
CREATE INDEX IF NOT EXISTS ix_scene_prompt_project_scene_status ON scene_prompt_versions(project_id, scene_id, status);

ALTER TABLE scene_prompt_versions ADD COLUMN IF NOT EXISTS rights_snapshot JSON NOT NULL DEFAULT '[]';
ALTER TABLE scene_prompt_versions ADD COLUMN IF NOT EXISTS instruction_priority JSON NOT NULL DEFAULT '[]';

ALTER TABLE image_generation_jobs ADD COLUMN IF NOT EXISTS scene_prompt_version_id VARCHAR(36)
    REFERENCES scene_prompt_versions(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_image_generation_jobs_scene_prompt_version_id
    ON image_generation_jobs(scene_prompt_version_id);
