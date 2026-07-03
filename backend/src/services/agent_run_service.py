import datetime
from sqlalchemy.orm import Session
from src.agents.graph import AgentGraph
from src.agents.state import AgentRunState, ProductInput
from src.db.models import AgentRun


class AgentRunService:
    @staticmethod
    def run_mock(run_id: str, workspace_id: str, db: Session) -> AgentRun:
        run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id, AgentRun.workspace_id == workspace_id)
            .first()
        )
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

    @staticmethod
    def run_real_text(run_id: str, workspace_id: str, db: Session) -> AgentRun:
        run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id, AgentRun.workspace_id == workspace_id)
            .first()
        )
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

        from src.services.llm_router import get_text_provider_by_settings
        text_provider = get_text_provider_by_settings()

        graph = AgentGraph.real_text(text_provider=text_provider)
        completed_state = graph.run_text_generation(state)

        # 이미지 생성 및 에셋 매핑이 이뤄지지 않은 상태이지만,
        # 프론트 미리보기 렌더링에 차질이 없도록 outputs["generated_assets"] 은 mock으로 보장
        from src.agents.mock_outputs import build_mock_generated_assets
        completed_state.outputs["generated_assets"] = build_mock_generated_assets(product_input.product_name)

        run.outputs_json = completed_state.outputs
        run.current_stage = completed_state.current_stage.value
        run.status = "completed"
        run.completed_at = datetime.datetime.utcnow()

        db.add(run)
        db.commit()
        db.refresh(run)

        return run

