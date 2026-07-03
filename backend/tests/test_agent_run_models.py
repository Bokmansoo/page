from src.db.models import AgentRun, AgentRunStep, ProductProject, Brand


def test_agent_run_persists_generation_execution(db_session):
    brand = Brand(id="brand-agent-run", workspace_id="workspace-agent-run", name="Agent Brand")
    project = ProductProject(
        id="project-agent-run",
        workspace_id="workspace-agent-run",
        brand_id=brand.id,
        name="유아 자전거",
    )
    run = AgentRun(
        id="run-agent-1",
        workspace_id="workspace-agent-run",
        project_id=project.id,
        mode="mock",
        status="created",
        current_stage="intake",
        input_snapshot={"product_name": "유아 자전거"},
        outputs_json={},
        cost_approval_status="not_required",
        created_by="user-agent-run",
    )
    db_session.add_all([brand, project, run])
    db_session.commit()

    saved = db_session.query(AgentRun).filter_by(id="run-agent-1").one()
    assert saved.project_id == "project-agent-run"
    assert saved.workspace_id == "workspace-agent-run"
    assert saved.mode == "mock"
    assert saved.cost_approval_status == "not_required"


def test_agent_run_step_tracks_stage_output_and_cost(db_session):
    brand = Brand(id="brand-agent-step", workspace_id="workspace-agent-step", name="Agent Step Brand")
    project = ProductProject(
        id="project-agent-step",
        workspace_id="workspace-agent-step",
        brand_id=brand.id,
        name="유아 자전거",
    )
    run = AgentRun(
        id="run-agent-step",
        workspace_id="workspace-agent-step",
        project_id=project.id,
        mode="mock",
        status="running",
        current_stage="product_understanding",
        input_snapshot={"product_name": "유아 자전거"},
        outputs_json={},
        cost_approval_status="not_required",
        created_by="user-agent-step",
    )
    step = AgentRunStep(
        id="step-agent-1",
        run_id=run.id,
        stage="product_understanding",
        status="completed",
        input_json={"product_name": "유아 자전거"},
        output_json={"product_type": "kids_bicycle"},
        provider="mock",
        model="deterministic",
        prompt_version="sprint-48",
        token_usage={"input": 0, "output": 0},
        estimated_cost=0.0,
    )
    db_session.add_all([brand, project, run, step])
    db_session.commit()

    saved = db_session.query(AgentRunStep).filter_by(id="step-agent-1").one()
    assert saved.run_id == "run-agent-step"
    assert saved.output_json["product_type"] == "kids_bicycle"
    assert saved.estimated_cost == 0.0
