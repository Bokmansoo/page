from src.agents.mock_outputs import build_mock_qa_report
from src.agents.nodes.base import AgentNode
from src.agents.schemas import QAReportOutput
from src.agents.state import AgentRunState


class QAReviewAgent(AgentNode):
    name = "qa_review"

    def _apply_export_gates(self, state: AgentRunState, qa_report: dict) -> dict:
        assembly = state.outputs.get("page_assembly") or {}
        sections = assembly.get("sections") or []
        warnings = qa_report.get("warnings") or []
        can_export = qa_report.get("can_export", True)

        for sec in sections:
            section_id = sec.get("section_id") or sec.get("id")
            slot = sec.get("visual_slot") or {}
            status = slot.get("status")
            source_type = slot.get("source_type")
            identity_check = slot.get("identity_check") or {}

            if status == "missing_image" or not slot.get("asset_id"):
                can_export = False
                warnings.append({
                    "code": "REQUIRED_IMAGE_MISSING",
                    "message": f"섹션 '{section_id}'에 필요한 이미지가 배치되지 않았습니다.",
                    "section_id": section_id,
                })
            elif source_type == "real-generated" and identity_check.get("status") != "passed":
                can_export = False
                warnings.append({
                    "code": "IMAGE_IDENTITY_NEEDS_REVIEW",
                    "message": f"생성 이미지의 상품 정체성 검수가 완료되지 않았습니다. ({section_id})",
                    "section_id": section_id,
                })

            unsupported_claims = sec.get("unsupported_claims") or []
            if unsupported_claims:
                can_export = False
                warnings.append({
                    "code": "UNSUPPORTED_ABSOLUTE_CLAIM",
                    "message": "근거 없는 절대 표현 또는 과장 표현이 포함되어 있습니다.",
                    "section_id": section_id,
                    "claims": unsupported_claims,
                })

        reference_analysis = state.outputs.get("reference_analysis") or {}
        copy_risk_notes = reference_analysis.get("copy_risk_notes") or []
        has_high_copy_risk = (
            str(reference_analysis.get("copy_risk_level") or "").lower() == "high"
            or reference_analysis.get("high_copy_risk") is True
            or any("high" in str(note).lower() or "높" in str(note) for note in copy_risk_notes)
        )
        if has_high_copy_risk:
            can_export = False
            warnings.append({
                "code": "REFERENCE_COPY_RISK_HIGH",
                "message": "참고 상세페이지와 너무 유사한 표현이 있어 그대로 내보낼 수 없습니다.",
            })

        qa_report["warnings"] = warnings
        qa_report["can_export"] = can_export
        qa_report["status"] = "passed" if can_export else "failed"
        return qa_report

    def run(self, state: AgentRunState) -> AgentRunState:
        product_name = state.product_input.product_name or "상품"
        qa_report = build_mock_qa_report(product_name)
        state.outputs[self.name] = self._apply_export_gates(state, qa_report)
        return state

    def run_real_text(self, state: AgentRunState, generate_output) -> AgentRunState:
        qa_report = generate_output(
            "qa_report",
            self.name,
            {
                "product_input": state.product_input.model_dump(),
                "outputs": state.outputs,
            },
            QAReportOutput,
        )
        if isinstance(qa_report, QAReportOutput):
            qa_report = qa_report.model_dump()

        state.outputs[self.name] = self._apply_export_gates(state, qa_report)
        return state
