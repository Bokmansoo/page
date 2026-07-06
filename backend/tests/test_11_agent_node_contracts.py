from src.agents.nodes.base import AgentNode
from src.agents.state import AgentRunState


class EchoNode(AgentNode):
    name = "echo"

    def run(self, state: AgentRunState) -> AgentRunState:
        state.outputs["echo"] = {"ok": True}
        return state


def test_agent_node_contract_returns_state():
    state = AgentRunState(project_id="project-1")
    result = EchoNode().run(state)
    assert result.outputs["echo"] == {"ok": True}


def test_all_11_agent_nodes_are_importable():
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

    assert InputRouterAgent().name == "input_router"
    assert SourceCollectionAgent().name == "source_collection"
    assert ProductUnderstandingAgent().name == "product_understanding"
    assert ReferenceAnalysisAgent().name == "reference_analysis"
    assert SalesStrategyAgent().name == "sales_strategy"
    assert PagePlanningAgent().name == "page_planning"
    assert CopywritingAgent().name == "copywriting"
    assert VisualPlanningAgent().name == "visual_planning"
    assert ImageGenerationAgent().name == "image_generation"
    assert PageAssemblyAgent().name == "page_assembly"
    assert QAReviewAgent().name == "qa_review"

