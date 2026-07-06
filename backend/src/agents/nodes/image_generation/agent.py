from src.agents.nodes.base import AgentNode
from src.agents.state import AgentRunState
from src.agents.mock_outputs import build_mock_generated_assets

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
        pname = state.product_input.product_name or "무명 상품"
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
                        "url": f"/api/assets/{a.id}/file"
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

        # If real mode and cost is not approved, block before spending credits.
        cost_approved = self._is_cost_approved(state)
        if self.mode == "real" and not cost_approved:
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

        # 1. Collect existing uploaded/url candidates from Sprint 55
        source_col = state.outputs.get("source_collection") or {}
        uploaded_imgs = source_col.get("uploaded_images") or []
        url_imgs = source_col.get("url_images") or []

        # 2. Build candidates per slot
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
            prefer_generated_candidate = matching_job is not None and self.mode == "real"

            # A. Add uploaded candidates
            for idx, img in enumerate(uploaded_imgs):
                asset_id = img.get("asset_id")
                if not asset_id:
                    continue
                slot_candidates.append({
                    "candidate_id": f"candidate-{slot_id}-uploaded-{asset_id}",
                    "slot_id": slot_id,
                    "asset_id": asset_id,
                    "source_type": "uploaded",
                    "label": img.get("filename") or "업로드 이미지",
                    "is_recommended": not prefer_generated_candidate and idx == 0,
                    "needs_identity_review": False,
                })

            # B. Add URL candidates
            uploaded_count = len(slot_candidates)
            for idx, img in enumerate(url_imgs):
                asset_id = img.get("asset_id") or f"url-image-{idx + 1}"
                slot_candidates.append({
                    "candidate_id": f"candidate-{slot_id}-url-{asset_id}",
                    "slot_id": slot_id,
                    "asset_id": asset_id,
                    "source_type": img.get("source_type") or "url-extracted",
                    "label": img.get("filename") or "URL 추출 이미지",
                    "is_recommended": (
                        not prefer_generated_candidate
                        and uploaded_count == 0
                        and idx == 0
                    ),
                    "needs_identity_review": False,
                })

            # C. Generate real/mock candidate based on image_jobs
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
                if not asset_id and self.mode != "real":
                    asset_id = f"mock-{slot_id}-visual"
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
                has_recommended = any(c["is_recommended"] for c in slot_candidates)
                slot_candidates.append({
                    "candidate_id": f"candidate-{slot_id}-mock-generated",
                    "slot_id": slot_id,
                    "asset_id": f"mock-{slot_id}-visual",
                    "source_type": "mock-generated",
                    "label": "목업 이미지",
                    "is_recommended": not has_recommended,
                    "needs_identity_review": False
                })

            candidates[slot_id] = slot_candidates

        if not generated_images and self.mode != "real":
            generated_images = build_mock_generated_assets(
                pname,
                uploaded_assets=uploaded_list,
                product_url=state.product_input.product_url,
            ).get("images", [])
        else:
            for image in url_imgs:
                asset_id = image.get("asset_id")
                if asset_id and not any(item.get("id") == asset_id for item in generated_images):
                    generated_images.append(
                        {
                            "id": asset_id,
                            "role": "url_reference",
                            "url": image.get("url") or state.product_input.product_url or "",
                            "filename": image.get("filename") or "url-image.png",
                            "source_type": image.get("source_type") or "url-extracted",
                        }
                    )

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
