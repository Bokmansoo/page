from src.agents.nodes.base import AgentNode
from src.agents.state import AgentRunState

class ImageGenerationAgent(AgentNode):
    name = "image_generation"

    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def _is_cost_approved(self, state: AgentRunState) -> bool:
        if state.cost_approval_status == "approved":
            return True
        if state.cost_approval_status == "not_required":
            try:
                from src.config import settings
                return not settings.SELLFORM_IMAGE_COST_APPROVAL_REQUIRED
            except Exception:
                return False
        return False

    def _persist_generated_asset(self, state: AgentRunState, slot_id: str, job_id: str, result) -> str | None:
        if not result.content:
            return None
        try:
            import os
            import uuid
            from src.config import settings
            from src.db.database import SessionLocal
            from src.db.models import Asset

            extension = {
                "image/jpeg": "jpg",
                "image/webp": "webp",
                "image/png": "png",
            }.get(result.mime_type, "png")
            safe_job_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (job_id or slot_id))
            filename = f"ai_generated/{safe_job_id}_{uuid.uuid4().hex}.{extension}"
            full_path = os.path.join(settings.UPLOAD_DIR, filename)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "wb") as f:
                f.write(result.content)

            db = SessionLocal()
            try:
                asset = Asset(
                    project_id=state.project_id,
                    source_type="real-generated",
                    filename=filename,
                    file_path=full_path,
                    mime_type=result.mime_type,
                    file_size=len(result.content),
                )
                db.add(asset)
                db.commit()
                db.refresh(asset)
                return asset.id
            finally:
                db.close()
        except Exception:
            return None

    def run(self, state: AgentRunState) -> AgentRunState:
        uploaded_list = []
        asset_paths = {}
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
                        "url": a.file_path if str(a.file_path).startswith("http") else f"/api/v1/files/assets/{a.id}",
                        "source_type": a.source_type,
                    })
                    if a.file_path:
                        asset_paths[a.id] = a.file_path
            finally:
                db.close()
        except Exception:
            pass

        # Load planned jobs from visual_planning
        visual_plan = state.outputs.get("visual_planning") or {}
        image_jobs = visual_plan.get("image_jobs") or []

        # Existing seller/URL photos never require image-generation cost approval.
        source_col = state.outputs.get("source_collection") or {}
        uploaded_imgs = source_col.get("uploaded_images") or []
        url_imgs = source_col.get("url_images") or []
        has_existing_product_image = any(
            image.get("asset_id") and not str(image.get("asset_id")).startswith("mock-")
            for image in [*uploaded_imgs, *url_imgs]
        )

        # If real mode and cost is not approved, block before spending credits.
        cost_approved = self._is_cost_approved(state)
        if self.mode == "real" and not cost_approved and not has_existing_product_image:
            jobs_report = []
            candidates = {}
            for job in image_jobs:
                slot_id = job.get("slot_id") or "hero"
                jobs_report.append({
                    "job_id": job.get("job_id"),
                    "slot_id": slot_id,
                    "status": "blocked_cost_approval",
                    "text_free_required": job.get("text_free_required", False),
                    "visual_strategy": job.get("visual_strategy"),
                    "source_asset_ids": job.get("source_asset_ids") or job.get("reference_asset_ids") or [],
                })
                candidates[slot_id] = []
            
            state.outputs[self.name] = {
                "jobs": jobs_report,
                "candidates": candidates,
                "images": []
            }
            return state

        # Build candidates per slot.
        slots_data = visual_plan.get("visual_slots")
        if not slots_data and image_jobs:
            slots_data = [
                {
                    "slot_id": job.get("slot_id") or job.get("job_id") or "hero",
                    "role": job.get("role") or "representative_product",
                }
                for job in image_jobs
            ]
        if not slots_data:
            slots_data = [
                {"slot_id": "hero", "role": "대표 상품 컷"},
                {"slot_id": "comparison", "role": "비교 장면 컷"},
                {"slot_id": "detail_1", "role": "상세 스펙 컷 1"},
                {"slot_id": "detail_2", "role": "상세 스펙 컷 2"},
                {"slot_id": "guarantee", "role": "보증 컷"},
            ]
        
        from src.services.image_generation_provider import ImageGenerationProviderRouter, ImageGenerationRequest
        router = ImageGenerationProviderRouter(mode=self.mode)

        candidates = {}
        jobs_report = []
        generated_images = []
        
        for item in slots_data:
            if isinstance(item, dict):
                slot_id = item.get("slot_id") or "hero"
                role = item.get("role") or "representative_product"
                visual_strategy = item.get("visual_strategy")
            else:
                slot_id = str(item)
                role = "representative_product"
                visual_strategy = None

            if visual_strategy == "html_graphic":
                candidates[slot_id] = [
                    {
                        "candidate_id": f"candidate-{slot_id}-html-graphic",
                        "slot_id": slot_id,
                        "asset_id": None,
                        "source_type": "html-graphic",
                        "label": "HTML graphic",
                        "is_recommended": True,
                        "needs_identity_review": False,
                        "identity_check": {"status": "not_required"},
                    }
                ]
                jobs_report.append(
                    {
                        "job_id": None,
                        "slot_id": slot_id,
                        "status": "skipped_html_graphic",
                        "visual_strategy": visual_strategy,
                        "text_free_required": True,
                        "source_asset_ids": [],
                    }
                )
                continue
                
            slot_candidates = []
            matching_job = next(
                (job for job in image_jobs if job.get("slot_id") == slot_id),
                None,
            )
            # Sprint 1: use seller-provided product photos before any generated
            # candidate. Uploads always win over URL-collected images; a filename
            # that suggests a main/front/hero product cut wins within the same
            # source group. URL images remain candidates until the user selects
            # one, which is the explicit approval step for collected images.
            def source_sort_key(img):
                filename = str(img.get("filename") or "").lower()
                is_main_product_cut = any(
                    keyword in filename
                    for keyword in ("hero", "main", "front", "대표", "정면")
                )
                return (0 if img.get("is_representative") else 1,
                        0 if img.get("source_type") in {"uploaded", "self_shot", "sourced"} else 1,
                        0 if is_main_product_cut else 1,
                        filename)

            real_source_images = sorted(
                [
                    img
                    for img in [*uploaded_imgs, *url_imgs]
                    if (
                        img.get("asset_id")
                        and not str(img.get("asset_id")).startswith("mock-")
                        and img.get("quality_status") != "rejected"
                    )
                ],
                key=source_sort_key,
            )
            for idx, img in enumerate(real_source_images):
                asset_id = img["asset_id"]
                source_type = img.get("source_type") or "uploaded"
                slot_candidates.append({
                    "candidate_id": f"candidate-{slot_id}-{source_type}-{asset_id}",
                    "slot_id": slot_id,
                    "asset_id": asset_id,
                    "source_type": source_type,
                    "label": img.get("filename") or "상품 사진",
                    "is_recommended": False,
                    "needs_identity_review": False,
                    "quality_warnings": img.get("quality_warnings") or [],
                    "identity_check": {"status": "not_required"},
                })

            uploaded_candidate_indexes = [
                index
                for index, candidate in enumerate(slot_candidates)
                if candidate["source_type"] in {"uploaded", "self_shot", "sourced"}
                and not (
                    slot_id == "hero"
                    and {"LOW_RESOLUTION", "EXTREME_ASPECT_RATIO", "DUPLICATE_FILE", "IMAGE_INTEGRITY_WARNING"}.intersection(candidate.get("quality_warnings") or [])
                )
            ]
            selected_candidate_id = state.selected_image_candidates.get(slot_id)
            selected_candidate = next(
                (
                    candidate
                    for candidate in slot_candidates
                    if candidate["candidate_id"] == selected_candidate_id
                ),
                None,
            )

            for candidate in slot_candidates:
                candidate["requires_approval"] = candidate["source_type"] in {
                    "url-extracted",
                    "url-imported",
                }

            if slot_candidates and (uploaded_candidate_indexes or selected_candidate):
                # HERO uses the main product image. The product-introduction slot
                # uses a second photo when one is available, while preserving the
                # original asset id if only one uploaded photo was supplied.
                # A selected URL candidate is the user's explicit approval.
                if selected_candidate:
                    preferred_index = slot_candidates.index(selected_candidate)
                elif slot_id == "hero":
                    preferred_index = uploaded_candidate_indexes[0]
                else:
                    preferred_index = uploaded_candidate_indexes[min(1, len(uploaded_candidate_indexes) - 1)]
                slot_candidates[preferred_index]["is_recommended"] = True
                selected = slot_candidates[preferred_index]
                jobs_report.append({
                    "job_id": matching_job.get("job_id") if matching_job else None,
                    "slot_id": slot_id,
                    "status": "skipped_existing_product_image",
                    "visual_strategy": visual_strategy,
                    "source_asset_ids": [candidate["asset_id"] for candidate in slot_candidates],
                })
                if not any(image.get("id") == selected["asset_id"] for image in generated_images):
                    source = next(
                        (img for img in real_source_images if img.get("asset_id") == selected["asset_id"]),
                        {},
                    )
                    generated_images.append({
                        "id": selected["asset_id"],
                        "role": role,
                        "url": source.get("url") or f"/api/v1/files/assets/{selected['asset_id']}",
                        "filename": selected["label"],
                        "source_type": selected["source_type"],
                        "slot_id": slot_id,
                        "label": selected["label"],
                    })
                candidates[slot_id] = slot_candidates
                continue

            if slot_candidates:
                # URL-derived assets are not silently applied. Keep their real
                # asset ids in the candidate panel so the user can approve one.
                candidates[slot_id] = slot_candidates
                jobs_report.append({
                    "job_id": matching_job.get("job_id") if matching_job else None,
                    "slot_id": slot_id,
                    "status": "awaiting_source_approval",
                    "visual_strategy": visual_strategy,
                    "source_asset_ids": [candidate["asset_id"] for candidate in slot_candidates],
                })
                continue

            # In mock mode, an absent product photo is a structured missing
            # state, never a red mock/generated image.
            if self.mode != "real":
                candidates[slot_id] = [
                    {
                        "candidate_id": f"candidate-{slot_id}-photo-required",
                        "slot_id": slot_id,
                        "asset_id": None,
                        "source_type": "missing-image",
                        "label": "상품 사진을 추가해 주세요",
                        "is_recommended": True,
                        "needs_identity_review": False,
                        "identity_check": {"status": "not_required"},
                    }
                ]
                jobs_report.append({
                    "job_id": matching_job.get("job_id") if matching_job else None,
                    "slot_id": slot_id,
                    "status": "missing_product_image",
                    "visual_strategy": visual_strategy,
                    "source_asset_ids": [],
                })
                continue

            # C. Generate real candidate only when the real image provider is
            # explicitly selected and no seller/URL product image exists.
            if matching_job:
                # Call provider router
                reference_asset_ids = matching_job.get("reference_asset_ids") or state.product_input.asset_ids or []
                source_asset_paths = [
                    asset_paths[asset_id]
                    for asset_id in reference_asset_ids
                    if asset_id in asset_paths
                ]
                if self.mode == "real" and reference_asset_ids and not source_asset_paths:
                    jobs_report.append({
                        "job_id": matching_job.get("job_id"),
                        "slot_id": slot_id,
                        "status": "missing_reference_asset",
                        "text_free_required": matching_job.get("text_free_required", False),
                        "visual_strategy": matching_job.get("visual_strategy"),
                        "source_asset_ids": matching_job.get("source_asset_ids") or reference_asset_ids,
                    })
                    slot_candidates.append({
                        "candidate_id": f"candidate-{slot_id}-regeneration-required",
                        "slot_id": slot_id,
                        "asset_id": None,
                        "source_type": "regeneration-required",
                        "label": "재생성 필요",
                        "is_recommended": False,
                        "needs_identity_review": False,
                        "identity_check": {
                            "status": "failed",
                            "reason": "reference_asset_paths_missing",
                        },
                    })
                    candidates[slot_id] = slot_candidates
                    continue
                req = ImageGenerationRequest(
                    job_id=matching_job.get("job_id") or f"{slot_id}-1",
                    slot_id=slot_id,
                    role=role,
                    prompt=matching_job.get("prompt") or "상세페이지 이미지",
                    source_asset_paths=source_asset_paths,
                    reference_asset_ids=reference_asset_ids,
                    preserve_product_identity=bool(reference_asset_ids),
                    cost_approved=cost_approved,
                    product_identity_required=matching_job.get("product_identity_required", True),
                )
                res = router.generate(req)
                jobs_report.append({
                    "job_id": matching_job.get("job_id"),
                    "slot_id": slot_id,
                    "status": res.status,
                    "provider": res.provider,
                    "model": res.model,
                    "text_free_required": matching_job.get("text_free_required", False),
                    "visual_strategy": matching_job.get("visual_strategy"),
                    "source_asset_ids": matching_job.get("source_asset_ids") or reference_asset_ids,
                    "error_code": (
                        res.usage_metadata.get("error")
                        if isinstance(res.usage_metadata, dict)
                        else None
                    ),
                })

                if res.status != "success":
                    candidates[slot_id] = slot_candidates
                    continue
                
                # Check identity validator needs_review status
                needs_review = True if matching_job.get("product_identity_required") else False
                
                # Check if identity verification is failed based on metadata or status
                is_failed = False
                if isinstance(res.usage_metadata, dict) and res.usage_metadata.get("identity_check") == "failed":
                    is_failed = True
                elif res.status == "failed" or res.status == "provider_error":
                    is_failed = True
                
                asset_id = res.assets[0] if res.assets else None
                if not asset_id and self.mode == "real":
                    asset_id = self._persist_generated_asset(
                        state,
                        slot_id=slot_id,
                        job_id=matching_job.get("job_id") or f"{slot_id}-1",
                        result=res,
                    )
                if not asset_id:
                    jobs_report[-1]["status"] = "asset_persist_failed"
                    candidates[slot_id] = slot_candidates
                    continue
                source_type = "real-generated" if self.mode == "real" else "mock-generated"
                
                if is_failed:
                    label = "재생성 필요"
                    slot_candidates.append({
                        "candidate_id": f"candidate-{slot_id}-identity-failed",
                        "slot_id": slot_id,
                        "asset_id": None,
                        "source_type": "regeneration-required",
                        "label": label,
                        "is_recommended": False,
                        "needs_identity_review": False,
                        "identity_check": {"status": "failed"},
                    })
                    candidates[slot_id] = slot_candidates
                    continue
                else:
                    label = "생성 이미지" if self.mode == "real" else "목업 이미지"
                    if self.mode == "real":
                        for candidate in slot_candidates:
                            candidate["is_recommended"] = False
                        is_rec = True
                    else:
                        is_rec = not any(
                            candidate["is_recommended"]
                            for candidate in slot_candidates
                        )
                    identity_status = "needs_review" if needs_review else "passed"

                slot_candidates.append({
                    "candidate_id": f"candidate-{slot_id}-{source_type}",
                    "slot_id": slot_id,
                    "asset_id": asset_id,
                    "source_type": source_type,
                    "label": label,
                    "is_recommended": is_rec,
                    "needs_identity_review": needs_review and not is_failed,
                    "identity_check": {"status": identity_status}
                })
                generated_images.append({
                    "id": asset_id,
                    "role": role,
                    "url": f"/api/v1/files/assets/{asset_id}",
                    "filename": f"{slot_id}.png",
                    "prompt": matching_job.get("prompt") or "",
                    "text_free_required": matching_job.get("text_free_required", False),
                    "visual_strategy": matching_job.get("visual_strategy"),
                    "source_asset_ids": matching_job.get("source_asset_ids") or reference_asset_ids,
                    "source_type": source_type,
                    "slot_id": slot_id,
                    "label": label,
                    "provider": res.provider,
                    "model": res.model,
                    "usage_metadata": res.usage_metadata,
                })
            else:
                slot_candidates.append({
                    "candidate_id": f"candidate-{slot_id}-photo-required",
                    "slot_id": slot_id,
                    "asset_id": None,
                    "source_type": "missing-image",
                    "label": "상품 사진을 추가해 주세요",
                    "is_recommended": True,
                    "needs_identity_review": False,
                })

            candidates[slot_id] = slot_candidates

        state.outputs[self.name] = {
            "jobs": jobs_report,
            "candidates": candidates,
            "images": generated_images
        }
        return state

    def run_real_text(self, state: AgentRunState, generate_output) -> AgentRunState:
        original_mode = self.mode
        try:
            from src.config import settings
            self.mode = settings.SELLFORM_IMAGE_GENERATION_MODE
        except Exception:
            self.mode = state.mode.value if hasattr(state.mode, "value") else str(state.mode)
        try:
            return self.run(state)
        finally:
            self.mode = original_mode
