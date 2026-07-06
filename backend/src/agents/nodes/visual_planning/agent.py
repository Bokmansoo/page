from typing import Any

from src.agents.mock_outputs import build_mock_visual_plan
from src.agents.nodes.base import AgentNode
from src.agents.schemas import VisualPlanOutput
from src.agents.state import AgentRunState
from src.services.detail_page_scene_planner import build_scene_plan


TEXT_FREE_IMAGE_POLICY = "No text, no Korean letters, no English letters, no logo, no watermark, no label."


class VisualPlanningAgent(AgentNode):
    name = "visual_planning"

    _SLOTS = [
        {"slot_id": "hero", "role": "representative_product", "label": "대표"},
        {"slot_id": "comparison", "role": "comparison", "label": "비교"},
        {"slot_id": "detail_1", "role": "detail_1", "label": "상세 스펙 1"},
        {"slot_id": "detail_2", "role": "detail_2", "label": "상세 스펙 2"},
        {"slot_id": "guarantee", "role": "guarantee", "label": "구매 안심"},
    ]

    def _copy_text_for_slot(self, copy_set: dict[str, Any], slot_id: str) -> str:
        sections = copy_set.get("sections") or {}
        if isinstance(sections, dict):
            section = sections.get(slot_id) or {}
            if isinstance(section, dict):
                section_text = " ".join(
                    str(value)
                    for key, value in section.items()
                    if key in {"title", "headline", "subtitle", "body", "body_copy"} and value
                ).strip()
                if section_text:
                    return section_text

        key_map = {
            "hero": ["hero_title", "hero_subtitle", "headline", "subheadline"],
            "comparison": ["painpoint_title", "painpoint_body", "comparison_title", "comparison_body"],
            "detail_1": ["feature_1_title", "feature_1_body", "detail_1_title", "detail_1_body"],
            "detail_2": ["feature_2_title", "feature_2_body", "detail_2_title", "detail_2_body"],
            "guarantee": ["guarantee_title", "guarantee_body", "trust_title", "trust_body"],
        }
        return " ".join(str(copy_set.get(key)) for key in key_map.get(slot_id, []) if copy_set.get(key)).strip()

    def _section_name_for_slot(self, page_plan: dict[str, Any], slot_id: str) -> str:
        for section in page_plan.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_id = section.get("id") or section.get("section_id") or section.get("slot_id")
            section_role = section.get("role")
            if section_id == slot_id or section_role == slot_id:
                return str(section.get("name") or section.get("title") or section_role or slot_id)
        return slot_id

    def _prompt_for_slot(
        self,
        *,
        product_name: str,
        slot_id: str,
        visual_plan: dict[str, Any],
        page_plan: dict[str, Any],
        copy_set: dict[str, Any],
    ) -> str:
        section_name = self._section_name_for_slot(page_plan, slot_id)
        copy_text = self._copy_text_for_slot(copy_set, slot_id)
        base = (
            f"{product_name} 상세페이지에 들어갈 {section_name} 섹션 이미지. "
            "업로드한 참조 이미지의 상품 정체성, 형태, 주요 부품, 색상, 비율을 유지한다. "
            "실제 판매 상세페이지처럼 상품이 중심에 있고, 자연스러운 배경/사용 장면과 "
            "문구가 들어갈 여백을 함께 설계한다. "
        )
        if copy_text:
            base += f"섹션 문구 맥락: {copy_text}. "

        if slot_id == "hero":
            return base + (
                visual_plan.get("hero_image_prompt")
                or "첫 화면 대표 이미지. 상품을 실제 사용 환경에 놓고 구매자가 바로 이해할 수 있게 연출한다."
            )
        if slot_id == "comparison":
            return base + "사용 전 불편과 사용 후 장점을 한눈에 비교할 수 있는 문제 해결형 상세페이지 이미지."
        if slot_id == "detail_1":
            return base + (
                visual_plan.get("detail_image_prompt")
                or "상품의 핵심 기능과 사용 장면을 가까이 보여주는 상세 기능 이미지."
            )
        if slot_id == "detail_2":
            return base + "상품 크기, 구성, 설치/조절 방식 등 구매 판단에 필요한 정보를 보여주는 상세 이미지."
        return base + "구매 전 확인할 스펙, 신뢰 포인트, 안심 요소를 정리하는 상세페이지 이미지."

    def _attach_image_jobs(self, state: AgentRunState, visual_plan: dict[str, Any]) -> dict[str, Any]:
        product_name = state.product_input.product_name or "상품"
        source_asset_ids = state.product_input.asset_ids or []
        scene_plan = build_scene_plan(
            product_name=product_name,
            asset_ids=source_asset_ids,
            confirmed_facts=state.product_input.selling_points,
            desired_mood=state.product_input.desired_mood,
        )
        copy_set = state.outputs.get("copywriting") or {}
        copy_context = " ".join(
            str(value)
            for value in copy_set.values()
            if isinstance(value, str) and value
        )
        slot_by_id = {slot["slot_id"]: slot for slot in self._SLOTS}
        image_jobs = []
        visual_slots = []
        for scene in scene_plan["sections"]:
            slot_id = scene["target_slot_id"]
            slot = slot_by_id[slot_id]
            visual_slots.append(
                {
                    **slot,
                    "scene_section_id": scene["section_id"],
                    "visual_strategy": scene["visual_strategy"],
                    "identity_risk": scene["identity_risk"],
                }
            )
            if not scene["image_prompt"]:
                continue
            image_jobs.append(
                {
                    "job_id": f"{slot_id}-1",
                    "slot_id": slot_id,
                    "role": slot["role"],
                    "prompt": (
                        f"{scene['image_prompt']} Marketing context only: {copy_context}."
                        if copy_context
                        else scene["image_prompt"]
                    ),
                    "reference_asset_ids": source_asset_ids,
                    "source_asset_ids": scene["source_asset_ids"],
                    "visual_strategy": scene["visual_strategy"],
                    "text_free_required": scene["text_free_required"],
                    "scene_section_id": scene["section_id"],
                    "identity_risk": scene["identity_risk"],
                    "candidate_count": 1,
                    "product_identity_required": True,
                    "estimated_cost_required": True,
                }
            )

        visual_plan["scene_plan"] = scene_plan
        visual_plan["visual_slots"] = visual_slots
        visual_plan["image_jobs"] = image_jobs
        return visual_plan

    def run(self, state: AgentRunState) -> AgentRunState:
        product_name = state.product_input.product_name or "상품"
        visual_plan = build_mock_visual_plan(product_name)
        state.outputs[self.name] = self._attach_image_jobs(state, visual_plan)
        return state

    def run_real_text(self, state: AgentRunState, generate_output) -> AgentRunState:
        visual_plan = generate_output(
            "visual_plan",
            self.name,
            {
                "product_input": state.product_input.model_dump(),
                "page_plan": state.outputs.get("page_planning"),
                "copy_set": state.outputs.get("copywriting"),
            },
            VisualPlanOutput,
        )
        if isinstance(visual_plan, VisualPlanOutput):
            visual_plan = visual_plan.model_dump()
        if not isinstance(visual_plan, dict):
            visual_plan = {}

        state.outputs[self.name] = self._attach_image_jobs(state, visual_plan)
        return state
