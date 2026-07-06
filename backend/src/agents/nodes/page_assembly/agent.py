from src.agents.nodes.base import AgentNode
from src.agents.state import AgentRunState
from src.agents.mock_outputs import build_mock_page_assembly

class PageAssemblyAgent(AgentNode):
    name = "page_assembly"

    def run(self, state: AgentRunState) -> AgentRunState:
        pname = state.product_input.product_name or "상품"
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

        copy_set = state.outputs.get("copywriting") or {}
        state.outputs[self.name] = build_mock_page_assembly(
            pname,
            uploaded_assets=uploaded_list,
            product_url=state.product_input.product_url,
            copy_set=copy_set
        )

        # -------------------------------------------------------------
        # Sprint 55 / 56: Map Selected / Recommended image candidates & copy
        # -------------------------------------------------------------
        assembly_output = state.outputs.get(self.name) or {}
        sections = assembly_output.get("sections") or []
        img_gen = state.outputs.get("image_generation") or {}
        candidates = img_gen.get("candidates") or {}
        job_status_by_slot = {
            job.get("slot_id"): job.get("status")
            for job in img_gen.get("jobs") or []
            if job.get("slot_id")
        }
        scene_plan = (state.outputs.get("visual_planning") or {}).get("scene_plan") or {}
        scene_by_slot = {
            scene.get("target_slot_id"): scene
            for scene in scene_plan.get("sections") or []
            if scene.get("target_slot_id")
        }
        selected_candidates = state.selected_image_candidates or {}
        
        for section in sections:
            sec_id = section.get("id") or section.get("section_type") or "hero"
            slot_id = sec_id
            if slot_id.startswith("sec-"):
                mapping = {
                    "sec-1": "hero",
                    "sec-2": "comparison",
                    "sec-3": "detail_1",
                    "sec-4": "detail_2",
                    "sec-5": "guarantee"
                }
                slot_id = mapping.get(slot_id, "hero")

            scene = scene_by_slot.get(slot_id)
            if scene:
                section["scene_section_id"] = scene.get("section_id")
                section["visual_strategy"] = scene.get("visual_strategy")
                section["identity_risk"] = scene.get("identity_risk")
                section["text_free_required"] = scene.get("text_free_required", True)

            # Map copy from copywriting by section_id/slot_id
            sections_copy = copy_set.get("sections") or {}
            sec_copy = sections_copy.get(sec_id) or sections_copy.get(slot_id) or {}
            if sec_copy:
                section["title"] = sec_copy.get("title") or section.get("title") or ""
                section["body_copy"] = sec_copy.get("body") or sec_copy.get("body_copy") or section.get("body_copy") or ""

            if scene and scene.get("visual_strategy") == "html_graphic":
                section["visual_slot"] = {
                    "asset_id": None,
                    "source_type": "html-graphic",
                    "status": "html_rendered",
                    "label": "HTML graphic",
                    "candidate_id": None,
                    "identity_check": {"status": "not_required"},
                }
                section["visual_kind"] = "html_graphic"
                section["visual_payload"] = scene.get("visual_payload") or {
                    "layout_variant": {
                        "comparison": "comparison_cards",
                        "detail_1": "benefit_cards",
                        "guarantee": "spec_table",
                    }.get(slot_id, "image_text")
                }
                section["image_asset_id"] = None
                continue

            
            selected_cand_id = selected_candidates.get(slot_id)
            slot_cand_list = candidates.get(slot_id) or []
            
            target_cand = None
            if selected_cand_id:
                for c in slot_cand_list:
                    if c.get("candidate_id") == selected_cand_id:
                        target_cand = c
                        break
            
            if not target_cand:
                for c in slot_cand_list:
                    if c.get("is_recommended"):
                        target_cand = c
                        break
            
            generation_status = job_status_by_slot.get(slot_id)
            generation_failed = generation_status not in {None, "success"}

            if not target_cand and slot_cand_list and not generation_failed:
                target_cand = slot_cand_list[0]
                
            if target_cand:
                section["visual_slot"] = {
                    "asset_id": target_cand.get("asset_id"),
                    "source_type": target_cand.get("source_type"),
                    "status": "completed",
                    "label": target_cand.get("label", ""),
                    "candidate_id": target_cand.get("candidate_id"),
                    "identity_check": target_cand.get("identity_check"),
                }

                if "image_asset_id" in section:
                    section["image_asset_id"] = target_cand.get("asset_id")
            else:
                section["visual_slot"] = {
                    "asset_id": None,
                    "source_type": None,
                    "status": "generation_failed" if generation_failed else "missing_image",
                    "label": "이미지 누락",
                    "candidate_id": None,
                    "identity_check": None,
                    "error_code": generation_status if generation_failed else None,
                }
                section["image_asset_id"] = None

        return state
