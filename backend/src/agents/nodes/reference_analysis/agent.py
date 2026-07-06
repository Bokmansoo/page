from src.agents.nodes.base import AgentNode
from src.agents.state import AgentRunState

class ReferenceAnalysisAgent(AgentNode):
    name = "reference_analysis"

    def run(self, state: AgentRunState) -> AgentRunState:
        source_col = state.outputs.get("source_collection") or {}
        has_ref = bool(
            source_col.get("product_url") or 
            source_col.get("reference_text_blocks") or 
            (state.product_input.reference_urls if state.product_input else None) or 
            (state.product_input.product_url if state.product_input else None)
        )
        
        if not has_ref:
            state.outputs[self.name] = {"skipped": True, "reference_available": False}
        else:
            state.outputs[self.name] = {
                "skipped": False,
                "reference_available": True,
                "structure_takeaways": ["문제 제기형 히어로", "사용 장면 중심 보강", "구매 전 걱정 해소"],
                "visual_takeaways": ["상단 대표컷", "중간 사용 장면", "하단 FAQ"],
                "copy_risk_notes": ["원문 제목 직접 복제 금지", "문장 구조를 새로 작성"],
                "recommended_rewrite_direction": "참고 페이지의 흐름만 활용하고 문구와 섹션명은 새로 작성합니다.",
            }
        return state
