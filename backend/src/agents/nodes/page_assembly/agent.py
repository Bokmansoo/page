from src.agents.nodes.base import AgentNode
from src.agents.state import AgentRunState
from src.agents.mock_outputs import build_mock_page_assembly


HERO_AUTO_ASSIGN_BLOCKING_WARNINGS = {
    "LOW_RESOLUTION",
    "EXTREME_ASPECT_RATIO",
    "DUPLICATE_FILE",
    "IMAGE_INTEGRITY_WARNING",
    "SAFE_CROP_REVIEW_REQUIRED",
}


def _has_hero_auto_assign_blocker(candidate: dict) -> bool:
    """Keep quality-warning assets available for manual review, never auto-use."""
    return bool(
        HERO_AUTO_ASSIGN_BLOCKING_WARNINGS.intersection(
            set(candidate.get("quality_warnings") or [])
        )
    )


class PageAssemblyAgent(AgentNode):
    name = "page_assembly"

    def run(self, state: AgentRunState) -> AgentRunState:
        pname = state.product_input.product_name or "상품"
        uploaded_list = []
        assets_by_id = {}
        try:
            from src.db.database import SessionLocal
            from src.db.models import Asset
            db = SessionLocal()
            try:
                if state.product_input.asset_ids:
                    requested_asset_ids = list(state.product_input.asset_ids)
                    assets = db.query(Asset).filter(Asset.id.in_(requested_asset_ids)).all()
                    # Include a prepared local-upscale preview without making
                    # it the automatically selected image.
                    previews = (
                        db.query(Asset)
                        .filter(
                            Asset.project_id == state.project_id,
                            Asset.source_type == "local_upscaled",
                            Asset.source_asset_id.in_(requested_asset_ids),
                        )
                        .all()
                    )
                    known_ids = {item.id for item in assets}
                    assets.extend(preview for preview in previews if preview.id not in known_ids)
                else:
                    assets = db.query(Asset).filter(Asset.project_id == state.project_id).all()
                for a in assets:
                    item = {
                        "id": a.id,
                        "filename": a.filename,
                        "url": a.file_path if str(a.file_path).startswith("http") else f"/api/v1/files/assets/{a.id}",
                        "source_type": a.source_type,
                        "usage_status": a.usage_status,
                        "mime_type": a.mime_type,
                        "asset_role": getattr(a, "asset_role", "unknown"),
                        "quality_status": getattr(a, "quality_status", "warning"),
                        "quality_warnings": getattr(a, "quality_warnings", []) or [],
                        "safe_crop_status": getattr(a, "safe_crop_status", "needs_review"),
                        "is_representative": getattr(a, "is_representative", False),
                        "ocr_text": getattr(a, "ocr_text", "") or "",
                        "content_hash": getattr(a, "content_hash", None),
                    }
                    uploaded_list.append(item)
                    assets_by_id[a.id] = item
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

        # UX-2 is deliberately HTML-first while no image provider is
        # connected. Do not run the legacy candidate-selection path below:
        # it turns missing scenes into blocking image placeholders and can
        # re-select URL/supplier references. The assembler has already kept
        # only seller-owned assets for final placement.
        if (state.input_snapshot or {}).get("ux_auto_generate"):
            for section in state.outputs[self.name].get("sections") or []:
                visual_slot = section.get("visual_slot") or {}
                image_asset_id = visual_slot.get("asset_id")
                section["image_asset_id"] = image_asset_id
                section["visual_kind"] = "image" if image_asset_id else "html_graphic"
                section["visual_payload"] = {
                    "layout_variant": "image_text",
                    "ux2_mock_output": True,
                    **({"ux2d1_auto_replacement": section["ux2d1_auto_replacement"]} if section.get("ux2d1_auto_replacement") else {}),
                    **({"mock_safe_hero": True} if section.get("section_type") == "hero" and not image_asset_id else {}),
                }
            return state

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
            generation_failed = generation_status in {
                "failed",
                "provider_error",
                "asset_persist_failed",
                "missing_reference_asset",
            }

            awaiting_source_approval = bool(slot_cand_list) and all(
                candidate.get("requires_approval")
                for candidate in slot_cand_list
            )
            if not target_cand and slot_cand_list and not generation_failed and not awaiting_source_approval:
                # A low-quality HERO stays available for manual review, but is
                # never picked by this automatic fallback.
                auto_assignable_candidates = slot_cand_list
                if slot_id == "hero":
                    auto_assignable_candidates = [
                        candidate
                        for candidate in slot_cand_list
                        if not _has_hero_auto_assign_blocker(candidate)
                        # A local upscale generated at upload time is a
                        # suggestion, not an implicit seller confirmation.
                        and candidate.get("source_type") != "local_upscaled"
                    ]
                if auto_assignable_candidates:
                    target_cand = auto_assignable_candidates[0]

            quality_review_required = bool(
                slot_id == "hero"
                and not target_cand
                and any(
                    candidate.get("asset_id") and _has_hero_auto_assign_blocker(candidate)
                    for candidate in slot_cand_list
                )
            )
                
            if target_cand and target_cand.get("asset_id"):
                linked_asset = assets_by_id.get(target_cand.get("asset_id")) or {}
                source_type = linked_asset.get("source_type") or target_cand.get("source_type")
                label = linked_asset.get("filename") or target_cand.get("label", "")
                section["visual_slot"] = {
                    "asset_id": target_cand.get("asset_id"),
                    "source_type": source_type,
                    "status": "completed",
                    "label": label,
                    "candidate_id": target_cand.get("candidate_id"),
                    "identity_check": target_cand.get("identity_check"),
                }

                section["image_asset_id"] = target_cand.get("asset_id")
                if slot_id == "hero":
                    from src.services.hero_composition import build_composed_product_payload

                    composed_payload = build_composed_product_payload(
                        assets_by_id.get(target_cand.get("asset_id")),
                        getattr(state, "selected_style", None),
                    )
                    if composed_payload:
                        section["visual_kind"] = "composed_product"
                        section["visual_payload"] = composed_payload
                    else:
                        section["visual_kind"] = "image"
                        section["visual_payload"] = {"layout_variant": "hero_overlay"}
                else:
                    section["visual_kind"] = "image"
                    section["visual_payload"] = section.get("visual_payload") or {
                        "layout_variant": "image_text"
                    }
            else:
                section["visual_slot"] = {
                    "asset_id": None,
                    "source_type": target_cand.get("source_type") if target_cand else None,
                    "status": (
                        "generation_failed"
                        if generation_failed
                        else "awaiting_source_approval"
                        if awaiting_source_approval
                        else "quality_review_required"
                        if quality_review_required
                        else "missing_image"
                    ),
                    "label": (
                        "URL 상품 사진을 선택해 주세요"
                        if awaiting_source_approval
                        else "HERO에 사용할 고화질 상품 사진을 추가하거나 품질 경고를 확인해 주세요"
                        if quality_review_required
                        else "상품 사진을 추가해 주세요"
                    ),
                    "candidate_id": target_cand.get("candidate_id") if target_cand else None,
                    "identity_check": None,
                    "error_code": generation_status if generation_failed else None,
                }
                section["image_asset_id"] = None
                section["visual_kind"] = "image"
                section["visual_payload"] = {
                    "layout_variant": "hero_overlay" if slot_id == "hero" else "image_text",
                    "missing_state": (
                        "source_approval_required"
                        if awaiting_source_approval
                        else "quality_review_required"
                        if quality_review_required
                        else "photo_required"
                    ),
                }

        return state
