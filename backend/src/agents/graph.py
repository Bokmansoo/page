import json
import os
from typing import Any, Callable

from src.agents.state import AgentRunState, AgentStage
from src.agents.schemas import (
    ProductUnderstandingOutput,
    SalesStrategyOutput,
    DetailPagePlanOutput,
    CopySetOutput,
    VisualPlanOutput,
    QAReportOutput,
)
from src.services.provider_adapters import ProviderRequest, TextProviderProtocol

# Import 11 agents
from src.agents.nodes.input_router.agent import InputRouterAgent
from src.agents.nodes.source_collection.agent import SourceCollectionAgent
from src.agents.nodes.product_understanding.agent import ProductUnderstandingAgent
from src.agents.nodes.reference_analysis.agent import ReferenceAnalysisAgent
from src.agents.nodes.sales_strategy.agent import SalesStrategyAgent
from src.agents.nodes.page_planning.agent import PagePlanningAgent
from src.agents.nodes.copywriting.agent import CopywritingAgent
from src.agents.nodes.visual_planning.agent import VisualPlanningAgent
from src.agents.nodes.image_generation.agent import ImageGenerationAgent
from src.agents.nodes.page_assembly.agent import PageAssemblyAgent
from src.agents.nodes.qa_review.agent import QAReviewAgent


class AgentGraph:
    def __init__(self, is_mock: bool = True):
        self.is_mock = is_mock
        self.text_provider: TextProviderProtocol | None = None

        # Instantiate 11 agents
        self.agents = [
            InputRouterAgent(),
            SourceCollectionAgent(),
            ProductUnderstandingAgent(),
            ReferenceAnalysisAgent(),
            SalesStrategyAgent(),
            PagePlanningAgent(),
            CopywritingAgent(),
            VisualPlanningAgent(),
            ImageGenerationAgent(),
            PageAssemblyAgent(),
            QAReviewAgent(),
        ]

    @classmethod
    def mock(cls) -> "AgentGraph":
        return cls(is_mock=True)

    @classmethod
    def real_text(cls, text_provider: TextProviderProtocol) -> "AgentGraph":
        instance = cls(is_mock=False)
        instance.text_provider = text_provider
        return instance

    def run(self, state: AgentRunState) -> AgentRunState:
        # Run all 11 agents in order
        for agent in self.agents:
            state.current_stage = AgentStage(agent.name)
            state = agent.run(state)

        self._add_legacy_compatibility(state)
        return state

    def run_all(self, state: AgentRunState) -> AgentRunState:
        return self.run(state)

    def run_next(self, state: AgentRunState) -> AgentRunState:
        agent_names = [agent.name for agent in self.agents]
        current_index = agent_names.index(state.current_stage.value)
        next_index = min(current_index + 1, len(self.agents) - 1)
        next_agent = self.agents[next_index]
        state.current_stage = AgentStage(next_agent.name)
        state = next_agent.run(state)
        self._add_legacy_compatibility(state)
        return state

    def _run_text_generation_legacy_manual_pipeline(self, state: AgentRunState) -> AgentRunState:
        from src.services.prompt_registry import PromptRegistry

        text_provider = self.text_provider
        if text_provider is None:
            raise RuntimeError("Text provider is required for real text generation.")

        pname = state.product_input.product_name or "상품"
        system_prompt_dir = "prompts" if os.path.exists("prompts") else "backend/prompts"
        node_prompt_dir = (
            "src/agents/nodes"
            if os.path.exists("src/agents/nodes")
            else "backend/src/agents/nodes"
        )
        system_registry = PromptRegistry(base_path=system_prompt_dir)
        node_prompt_registry = PromptRegistry(base_path=node_prompt_dir)
        system_base = system_registry.load("system/sellform_agent_base")

        product_context = state.product_input.model_dump()

        def generate_output(schema_name, prompt_name, context, schema_cls):
            result = text_provider.generate_json(
                ProviderRequest(
                    provider="router",
                    model="configured",
                    system_prompt=system_base + "\n" + node_prompt_registry.load_agent_prompt(prompt_name),
                    user_prompt=json.dumps(context, ensure_ascii=False),
                    schema_name=schema_name,
                    product_name=pname,
                )
            )
            validated = schema_cls.model_validate(result["content"]).model_dump()
            state.provider_trace.append(
                {
                    "stage": schema_name,
                    "provider": result.get("provider"),
                    "model": result.get("model"),
                    "token_usage": result.get("token_usage"),
                    "cost": result.get("cost"),
                }
            )
            cost = result.get("cost")
            if isinstance(cost, (int, float)):
                state.actual_cost = (state.actual_cost or 0) + cost
            return validated

        # 1. input_router
        state.current_stage = AgentStage.INPUT_ROUTER
        state.outputs["input_router"] = {
            "input_type": "mixed",
            "missing_inputs": [],
        }

        # 2. source_collection
        state.current_stage = AgentStage.SOURCE_COLLECTION
        state.outputs["source_collection"] = {
            "sources": [],
            "status": "completed",
        }

        # 3. product_understanding
        state.current_stage = AgentStage.PRODUCT_UNDERSTANDING
        state.outputs["product_understanding"] = generate_output(
            "product_understanding",
            "product_understanding",
            {"product_input": product_context},
            ProductUnderstandingOutput,
        )

        # 4. reference_analysis
        state.current_stage = AgentStage.REFERENCE_ANALYSIS
        has_ref = bool(state.product_input.reference_urls or state.product_input.product_url)
        if not has_ref:
            state.outputs["reference_analysis"] = {"skipped": True}
        else:
            state.outputs["reference_analysis"] = {
                "skipped": False,
                "analyzed_references": ["참조 링크 분석 완료"],
            }

        # 5. sales_strategy
        state.current_stage = AgentStage.SALES_STRATEGY
        state.outputs["sales_strategy"] = generate_output(
            "sales_strategy",
            "sales_strategy",
            {
                "product_input": product_context,
                "product_understanding": state.outputs["product_understanding"],
            },
            SalesStrategyOutput,
        )

        # 6. page_planning
        state.current_stage = AgentStage.PAGE_PLANNING
        state.outputs["page_planning"] = generate_output(
            "page_plan",
            "page_planning",
            {
                "product_input": product_context,
                "product_understanding": state.outputs["product_understanding"],
                "sales_strategy": state.outputs["sales_strategy"],
            },
            DetailPagePlanOutput,
        )

        # 7. copywriting
        state.current_stage = AgentStage.COPYWRITING
        state.outputs["copywriting"] = generate_output(
            "copy_set",
            "copywriting",
            {
                "product_input": product_context,
                "product_understanding": state.outputs["product_understanding"],
                "sales_strategy": state.outputs["sales_strategy"],
                "page_plan": state.outputs["page_planning"],
            },
            CopySetOutput,
        )

        # 8. visual_planning
        state.current_stage = AgentStage.VISUAL_PLANNING
        state.outputs["visual_planning"] = generate_output(
            "visual_plan",
            "visual_planning",
            {
                "product_input": product_context,
                "page_plan": state.outputs["page_planning"],
                "copy_set": state.outputs["copywriting"],
            },
            VisualPlanOutput,
        )

        # 9. image_generation
        state.current_stage = AgentStage.IMAGE_GENERATION
        uploaded_list = []
        try:
            from src.db.database import SessionLocal
            from src.db.models import Asset
            db = SessionLocal()
            try:
                if state.product_input.asset_ids:
                    assets = db.query(Asset).filter(Asset.id.in_(state.product_input.asset_ids)).all()
                else:
                    assets = db.query(Asset).filter(Asset.project_id == state.project_id).all()
                for a in assets:
                    uploaded_list.append({
                        "id": a.id,
                        "filename": a.filename,
                        "url": f"/api/assets/{a.id}/file"
                    })
            finally:
                db.close()
        except Exception:
            pass


        # 10. page_assembly
        state.current_stage = AgentStage.PAGE_ASSEMBLY
        from src.agents.mock_outputs import build_mock_page_assembly
        copy_set = state.outputs.get("copywriting", {})
        state.outputs["page_assembly"] = build_mock_page_assembly(
            pname,
            uploaded_assets=uploaded_list,
            product_url=state.product_input.product_url or "",
            copy_set=copy_set
        )

        # 11. qa_review
        state.current_stage = AgentStage.QA_REVIEW
        state.outputs["qa_review"] = generate_output(
            "qa_report",
            "qa_review",
            {
                "product_input": product_context,
                "outputs": state.outputs,
            },
            QAReportOutput,
        )

        self._add_legacy_compatibility(state)
        return state

    def run_text_generation(
        self,
        state: AgentRunState,
        progress_callback: Callable[
            [str, str, AgentRunState, Exception | None],
            None,
        ]
        | None = None,
    ) -> AgentRunState:
        from src.services.prompt_registry import PromptRegistry

        product_name = state.product_input.product_name or "상품"
        text_provider = self.text_provider
        if text_provider is None:
            raise RuntimeError("Text provider is required for real text generation.")
        system_prompt_dir = "prompts" if os.path.exists("prompts") else "backend/prompts"
        node_prompt_dir = (
            "src/agents/nodes"
            if os.path.exists("src/agents/nodes")
            else "backend/src/agents/nodes"
        )
        system_registry = PromptRegistry(base_path=system_prompt_dir)
        node_prompt_registry = PromptRegistry(base_path=node_prompt_dir)
        system_base = system_registry.load("system/sellform_agent_base")

        def generate_output(schema_name, prompt_name, context, schema_cls):
            result = text_provider.generate_json(
                ProviderRequest(
                    provider="router",
                    model="configured",
                    system_prompt=system_base + "\n" + node_prompt_registry.load_agent_prompt(prompt_name),
                    user_prompt=json.dumps(context, ensure_ascii=False),
                    schema_name=schema_name,
                    product_name=product_name,
                )
            )
            validated = schema_cls.model_validate(result["content"]).model_dump()
            state.provider_trace.append(
                {
                    "stage": schema_name,
                    "provider": result.get("provider"),
                    "model": result.get("model"),
                    "token_usage": result.get("token_usage"),
                    "cost": result.get("cost"),
                }
            )
            cost = result.get("cost")
            if isinstance(cost, (int, float)):
                state.actual_cost = (state.actual_cost or 0) + cost
            return validated

        for agent in self.agents:
            state.current_stage = AgentStage(agent.name)
            if progress_callback:
                progress_callback(agent.name, "running", state, None)
            try:
                state = agent.run_real_text(state, generate_output)
            except Exception as exc:
                if progress_callback:
                    progress_callback(agent.name, "failed", state, exc)
                raise
            if progress_callback:
                progress_callback(agent.name, "completed", state, None)

        self._add_legacy_compatibility(state)
        return state

    def _add_legacy_compatibility(self, state: AgentRunState):
        state.outputs["legacy"] = {
            "product_understanding": state.outputs.get("product_understanding"),
            "sales_strategy": state.outputs.get("sales_strategy"),
            "page_plan": state.outputs.get("page_planning"),
            "copy_set": state.outputs.get("copywriting"),
            "visual_plan": state.outputs.get("visual_planning"),
            "page_assembly": state.outputs.get("page_assembly"),
            "qa_report": state.outputs.get("qa_review"),
        }

        # Root outputs compatibility keys for older tests/services
        state.outputs["copy_set"] = state.outputs.get("copywriting")
        state.outputs["page_plan"] = state.outputs.get("page_planning")
        state.outputs["visual_plan"] = state.outputs.get("visual_planning")
        state.outputs["qa_report"] = state.outputs.get("qa_review")
        image_generation = state.outputs.get("image_generation")
        if (
            isinstance(image_generation, dict)
            and not image_generation.get("skipped")
            and bool(image_generation.get("images"))
        ):
            state.outputs["generated_assets"] = image_generation
