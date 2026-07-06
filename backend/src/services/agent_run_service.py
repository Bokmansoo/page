import datetime
from sqlalchemy.orm import Session
from src.agents.graph import AgentGraph
from src.agents.state import AgentRunMode, AgentRunState, AgentStage, ProductInput
from src.config import settings
from src.db.models import (
    AgentRun,
    AgentRunStep,
    Asset,
    DetailPageVersion,
    PageSection,
    ProductPage,
)


class AgentRunService:
    @staticmethod
    def _record_stage_progress(
        run: AgentRun,
        db: Session,
        stage: str,
        status: str,
        state: AgentRunState,
        error: Exception | None,
    ) -> None:
        step = (
            db.query(AgentRunStep)
            .filter(
                AgentRunStep.run_id == run.id,
                AgentRunStep.stage == stage,
            )
            .first()
        )
        if step is None:
            step = AgentRunStep(
                run_id=run.id,
                stage=stage,
                status="pending",
            )

        now = datetime.datetime.utcnow()
        run.status = "failed" if status == "failed" else "running"
        run.current_stage = stage
        run.outputs_json = dict(state.outputs)
        run.provider_trace = list(state.provider_trace)
        run.actual_cost = state.actual_cost
        step.status = status

        if status == "running":
            step.started_at = step.started_at or now
            step.completed_at = None
            step.error_message = None
        elif status == "completed":
            step.started_at = step.started_at or now
            step.completed_at = now
            step.output_json = state.outputs.get(stage) or {}
            step.error_message = None
        elif status == "failed":
            message = str(error) if error else "Agent stage failed"
            step.started_at = step.started_at or now
            step.completed_at = now
            step.error_message = message
            run.error_log = [*(run.error_log or []), {"stage": stage, "message": message}]

        db.add(step)
        db.add(run)
        db.commit()

    @staticmethod
    def _ensure_input_asset_ids(run: AgentRun, db: Session) -> list[str]:
        snapshot = dict(run.input_snapshot or {})
        asset_ids = [asset_id for asset_id in snapshot.get("asset_ids") or [] if asset_id]
        if asset_ids:
            return asset_ids

        project_assets = (
            db.query(Asset)
            .filter(Asset.project_id == run.project_id, Asset.mime_type.like("image/%"))
            .order_by(Asset.created_at.asc())
            .all()
        )
        if not project_assets:
            return []

        source_assets = [asset for asset in project_assets if asset.source_type != "real-generated"]
        selected_assets = source_assets or project_assets
        asset_ids = [asset.id for asset in selected_assets]
        snapshot["asset_ids"] = asset_ids
        run.input_snapshot = snapshot
        db.add(run)
        db.flush()
        return asset_ids

    @staticmethod
    def _materialize_page_from_outputs(run: AgentRun, db: Session) -> ProductPage | None:
        page_assembly = (run.outputs_json or {}).get("page_assembly") or {}
        sections = page_assembly.get("sections") or []
        if not sections:
            return None

        page = db.query(ProductPage).filter(ProductPage.project_id == run.project_id).first()
        if not page:
            visual_plan = (run.outputs_json or {}).get("visual_plan") or {}
            palette = visual_plan.get("color_palette") or []
            page = ProductPage(
                project_id=run.project_id,
                theme_color=palette[0] if palette else "#10B981",
                font_family="sans-serif",
            )
            db.add(page)
            db.flush()
        else:
            db.query(PageSection).filter(PageSection.page_id == page.id).delete()
            db.flush()

        project_assets = (
            db.query(Asset)
            .filter(Asset.project_id == run.project_id, Asset.mime_type.like("image/%"))
            .order_by(Asset.created_at.asc())
            .all()
        )
        asset_ids = {asset.id for asset in project_assets}
        fallback_asset_ids = [
            asset_id
            for asset_id in (run.input_snapshot or {}).get("asset_ids", [])
            if asset_id in asset_ids
        ] or [asset.id for asset in project_assets]

        version_sections = []
        for idx, section in enumerate(sections):
            visual_slot = section.get("visual_slot") or {}
            image_id = (
                visual_slot.get("asset_id")
                if "visual_slot" in section
                else section.get("image_id")
            )
            section_type = (
                section.get("section_type")
                or section.get("visual_role")
                or section.get("id")
                or f"section_{idx + 1}"
            )
            mapped_image_id = image_id if image_id in asset_ids else None
            has_explicit_visual_result = "visual_slot" in section
            if (
                mapped_image_id is None
                and not has_explicit_visual_result
                and fallback_asset_ids
                and section_type != "product_information"
            ):
                mapped_image_id = fallback_asset_ids[min(idx, len(fallback_asset_ids) - 1)]

            title = section.get("title") or ""
            body_copy = section.get("body") or section.get("body_copy") or ""
            db.add(
                PageSection(
                    page_id=page.id,
                    section_type=section_type,
                    title=title,
                    body_copy=body_copy,
                    image_asset_id=mapped_image_id,
                    sort_order=idx,
                    is_visible=True,
                )
            )
            version_sections.append(
                {
                    "key": section_type,
                    "section_type": section_type,
                    "title": title,
                    "body": body_copy,
                    "body_copy": body_copy,
                    "image_asset_id": mapped_image_id,
                    "sort_order": idx,
                    "is_visible": True,
                }
            )

        project = page.project
        db.add(
            DetailPageVersion(
                project_id=run.project_id,
                name="AI 생성 상세페이지",
                style_key=(project.selected_style if project else None) or "problem_solution",
                sections_json=version_sections,
                is_final=False,
            )
        )

        return page

    @staticmethod
    def run_mock(run_id: str, workspace_id: str, db: Session) -> AgentRun:
        run = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id, AgentRun.workspace_id == workspace_id)
            .first()
        )
        if not run:
            raise ValueError(f"AgentRun not found: {run_id}")

        input_snapshot = run.input_snapshot or {}
        asset_ids = AgentRunService._ensure_input_asset_ids(run, db)
        product_input = ProductInput(
            product_name=input_snapshot.get("product_name") or "",
            description=input_snapshot.get("description"),
            product_url=input_snapshot.get("product_url"),
            freeform_input=input_snapshot.get("freeform_input"),
            asset_ids=asset_ids,
            reference_urls=input_snapshot.get("reference_urls") or [],
            selling_points=input_snapshot.get("selling_points") or [],
            price=input_snapshot.get("price"),
            shipping=input_snapshot.get("shipping"),
            desired_mood=input_snapshot.get("desired_mood") or [],
        )

        state = AgentRunState(
            run_id=run.id,
            project_id=run.project_id,
            product_input=product_input,
            current_stage=run.current_stage,
            outputs=run.outputs_json or {},
            cost_approval_status=run.cost_approval_status,
            input_snapshot=input_snapshot,
        )

        graph = AgentGraph.mock()
        completed_state = graph.run_all(state)

        run.outputs_json = completed_state.outputs
        AgentRunService._materialize_page_from_outputs(run, db)
        run.current_stage = completed_state.current_stage.value
        if run.current_stage == "qa_review":
            run.current_stage = "review_editor"
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

        input_snapshot = run.input_snapshot or {}
        asset_ids = AgentRunService._ensure_input_asset_ids(run, db)
        product_input = ProductInput(
            product_name=input_snapshot.get("product_name") or "",
            description=input_snapshot.get("description"),
            product_url=input_snapshot.get("product_url"),
            freeform_input=input_snapshot.get("freeform_input"),
            asset_ids=asset_ids,
            reference_urls=input_snapshot.get("reference_urls") or [],
            selling_points=input_snapshot.get("selling_points") or [],
            price=input_snapshot.get("price"),
            shipping=input_snapshot.get("shipping"),
            desired_mood=input_snapshot.get("desired_mood") or [],
        )

        run_mode = (
            AgentRunMode.REAL
            if settings.SELLFORM_GENERATION_MODE == AgentRunMode.REAL.value
            else AgentRunMode.MOCK
        )
        state = AgentRunState(
            run_id=run.id,
            project_id=run.project_id,
            mode=run_mode,
            product_input=product_input,
            current_stage=run.current_stage,
            outputs=run.outputs_json or {},
            cost_approval_status=run.cost_approval_status,
            input_snapshot=input_snapshot,
        )

        from src.services.llm_router import get_text_provider_by_settings
        text_provider = get_text_provider_by_settings()

        graph = AgentGraph.real_text(text_provider=text_provider)
        run.mode = run_mode.value
        run.status = "running"
        run.current_stage = AgentStage.INPUT_ROUTER.value
        run.completed_at = None
        db.add(run)
        db.commit()

        completed_state = graph.run_text_generation(
            state,
            progress_callback=lambda stage, status, current_state, error: (
                AgentRunService._record_stage_progress(
                    run,
                    db,
                    stage,
                    status,
                    current_state,
                    error,
                )
            ),
        )

        run.outputs_json = completed_state.outputs
        AgentRunService._materialize_page_from_outputs(run, db)
        run.mode = completed_state.mode.value
        run.current_stage = completed_state.current_stage.value
        if run.current_stage == "qa_review":
            run.current_stage = "review_editor"
        run.provider_trace = completed_state.provider_trace
        run.actual_cost = completed_state.actual_cost
        run.status = "completed"
        run.completed_at = datetime.datetime.utcnow()

        db.add(run)
        db.commit()
        db.refresh(run)

        return run
