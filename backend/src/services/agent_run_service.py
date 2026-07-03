import datetime
from sqlalchemy.orm import Session
from src.agents.graph import AgentGraph
from src.agents.state import AgentRunState, ProductInput
from src.db.models import AgentRun


class AgentRunService:
    @staticmethod
    def run_mock(run_id: str, db: Session) -> AgentRun:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if not run:
            raise ValueError(f"AgentRun not found: {run_id}")

        product_input = ProductInput(
            product_name=run.input_snapshot.get("product_name") or "",
            description=run.input_snapshot.get("description"),
            product_url=run.input_snapshot.get("product_url"),
            asset_ids=run.input_snapshot.get("asset_ids") or [],
            reference_urls=run.input_snapshot.get("reference_urls") or [],
        )

        state = AgentRunState(
            id=run.id,
            project_id=run.project_id,
            product_input=product_input,
            current_stage=run.current_stage,
            outputs=run.outputs_json or {},
        )

        graph = AgentGraph.mock()
        completed_state = graph.run_all(state)

        run.outputs_json = completed_state.outputs
        run.current_stage = completed_state.current_stage.value
        run.status = "completed"
        run.completed_at = datetime.datetime.utcnow()

        db.add(run)
        db.commit()
        db.refresh(run)

        return run
