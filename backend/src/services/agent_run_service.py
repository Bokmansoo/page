import datetime
from sqlalchemy import text
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


class AssetUnderstandingNotReady(ValueError):
    def __init__(self, blockers: list[dict[str, str]]):
        super().__init__("Asset understanding review is required before fact extraction.")
        self.blockers = blockers


class FactEvidenceNotReady(ValueError):
    def __init__(self, blockers: list[dict[str, str]]):
        super().__init__("Fact and evidence review is required before content generation.")
        self.blockers = blockers


class AgentRunService:
    @staticmethod
    def _enforce_asset_understanding_gate(run: AgentRun, db: Session, asset_ids: list[str]) -> None:
        project = run.project
        snapshot = dict(project.intake_snapshot or {}) if project else {}
        if not snapshot.get("input_bundle_locked") or not asset_ids:
            return
        from src.services.asset_understanding_service import project_asset_understanding_blockers

        blockers = project_asset_understanding_blockers(
            run.project_id,
            db,
            asset_ids=asset_ids,
        )
        if blockers:
            raise AssetUnderstandingNotReady(blockers)

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
        from src.services.image_asset_inspector import backfill_project_asset_metadata
        backfill_project_asset_metadata(run.project_id, db)
        snapshot = dict(run.input_snapshot or {})
        project_assets = (
            db.query(Asset)
            .filter(
                Asset.project_id == run.project_id,
                Asset.mime_type.like("image/%"),
                Asset.quality_status != "rejected",
            )
            .order_by(Asset.is_representative.desc(), Asset.created_at.asc())
            .all()
        )
        if not project_assets:
            return []

        source_assets = [
            asset
            for asset in project_assets
            if asset.source_type
            in {"uploaded", "self_shot", "sourced", "url-extracted", "url-imported"}
        ]
        asset_ids_by_id = {asset.id: asset for asset in project_assets}
        requested_asset_ids = list(dict.fromkeys(snapshot.get("asset_ids") or []))
        # Sprint 1: preserve the seller's intake order.  Auto-detected assets
        # only fill in when no explicit bundle was submitted.
        selected_requested_ids = [
            asset_id
            for asset_id in requested_asset_ids
            if asset_id in asset_ids_by_id
            and asset_ids_by_id[asset_id].source_type
            in {"uploaded", "self_shot", "sourced", "url-extracted", "url-imported"}
        ]
        selected_assets = source_assets or project_assets
        asset_ids = selected_requested_ids or [asset.id for asset in selected_assets]
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

        # A development browser can issue the generation request twice while
        # React verifies effect cleanup. Serialize page materialization per
        # project so concurrent requests cannot both observe "no page" and
        # insert duplicate ProductPage rows.
        if db.get_bind().dialect.name == "postgresql":
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"sellform:product-page:{run.project_id}"},
            )

        page = (
            db.query(ProductPage)
            .filter(ProductPage.project_id == run.project_id)
            .order_by(ProductPage.created_at.asc(), ProductPage.id.asc())
            .first()
        )
        existing_sections = list(page.sections) if page else []
        existing_by_type = {
            section.section_type: section
            for section in existing_sections
            if section.section_type
        }
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
            # Re-materialization must not erase seller photo choices, hidden
            # state, fit mode or section order. Capture those choices first,
            # then rebuild the generated copy around them.
            db.query(PageSection).filter(PageSection.page_id == page.id).delete()
            db.flush()

        # Reference/supplier uploads remain useful in the evidence board but
        # must never be auto-placed in a seller-facing detail page.
        from src.services.page_asset_policy import get_page_eligible_assets
        project_assets = sorted(
            get_page_eligible_assets(db, run.project_id),
            key=lambda asset: asset.created_at,
        )
        asset_ids = {asset.id for asset in project_assets}
        assets_by_id = {asset.id: asset for asset in project_assets}
        # A seller-selected image is allowed, but it consumes its source group
        # for any remaining automatic sections on a later re-generation.
        # Otherwise an original and its manual copy could coexist silently.
        auto_used_asset_groups: set[str] = {
            asset.content_hash or f"asset:{asset.id}"
            for section in existing_sections
            if (section.visual_payload or {}).get("ux2c_selection_state") == "manual_image"
            for asset in [assets_by_id.get(section.image_asset_id)]
            if asset is not None
        }
        fallback_asset_ids = [
            asset_id
            for asset_id in (run.input_snapshot or {}).get("asset_ids", [])
            if asset_id in asset_ids
        ] or [asset.id for asset in project_assets]

        approved_facts = list((run.input_snapshot or {}).get("approved_facts") or [])
        ux2_mock_output = bool((run.input_snapshot or {}).get("ux_auto_generate"))
        from src.services.rule_based_copy_service import display_label

        def fact_card(item: dict) -> dict | None:
            fact_id = item.get("id")
            value = f"{item.get('value') or item.get('normalized_value') or item.get('fact_text') or ''}{item.get('unit') or item.get('normalized_unit') or ''}".strip()
            if not fact_id or not value:
                return None
            return {
                "title": display_label(
                    str(item.get("field_key") or ""), item.get("scope"), item.get("model_option")
                ),
                "body": value,
                "verification_status": "confirmed",
                "source_fact_ids": [fact_id],
            }

        grounded_cards = [card for item in approved_facts if (card := fact_card(item))]
        # UX-2D-1: a new automatic draft must never turn an OCR-risk supplier
        # visual into a default seller-facing photo. Manual choices stay
        # available and are governed by the separate acknowledgement flow.
        from src.services.commerce_content_quality_service import auto_placement_risk_codes
        generated_section_types = [
            (
                section.get("section_type")
                or section.get("visual_role")
                or section.get("id")
            )
            for section in sections
        ]
        generated_section_types = [
            str(section_type)
            for section_type in generated_section_types
            if section_type and section_type != "product_information"
        ]
        preserved_order = [
            section.section_type
            for section in sorted(existing_sections, key=lambda item: item.sort_order)
            if section.section_type in generated_section_types
            and section.section_type != "product_information"
        ]
        ordered_section_types = preserved_order + [
            section_type
            for section_type in generated_section_types
            if section_type not in preserved_order
        ]
        order_by_type = {
            section_type: index
            for index, section_type in enumerate(ordered_section_types)
        }

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
            # Supplier captures remain reference-only. UX-2 uses an HTML
            # product introduction instead of exposing them in a final page.
            if (
                mapped_image_id
                and (run.input_snapshot or {}).get("ux_auto_generate")
                and assets_by_id[mapped_image_id].source_type in {"sourced", "url-extracted", "url-imported"}
            ):
                mapped_image_id = None
            has_explicit_visual_result = "visual_slot" in section
            if (
                mapped_image_id is None
                and not has_explicit_visual_result
                and fallback_asset_ids
                and section_type != "product_information"
            ):
                # Do not silently repeat the last product photo throughout a
                # page. Sections without another suitable photo stay in their
                # grounded HTML layout until the seller chooses one.
                mapped_image_id = fallback_asset_ids[idx] if idx < len(fallback_asset_ids) else None

            title = section.get("title") or ""
            body_copy = section.get("body") or section.get("body_copy") or ""
            associated_fact_ids = list(section.get("associated_fact_ids") or [])
            visual_kind = section.get("visual_kind") or ("image" if mapped_image_id else "html_graphic")
            visual_payload = dict(section.get("visual_payload") or {})
            output_auto_replacement = section.get("ux2d1_auto_replacement")
            if isinstance(output_auto_replacement, dict) and not mapped_image_id:
                visual_payload.setdefault("ux2d1_auto_replacement", output_auto_replacement)
            is_visible = True
            preserved = existing_by_type.get(section_type)
            if preserved is not None:
                preserved_asset_id = (
                    preserved.image_asset_id
                    if preserved.image_asset_id in asset_ids
                    else None
                )
                mapped_image_id = preserved_asset_id
                visual_kind = preserved.visual_kind or (
                    "image" if preserved_asset_id else "html_graphic"
                )
                if visual_kind in {"image", "composed_product"} and not preserved_asset_id:
                    visual_kind = "html_graphic"
                visual_payload = dict(preserved.visual_payload or {})
                is_visible = preserved.is_visible
            if visual_kind == "html_graphic":
                visual_payload.setdefault("layout_variant", "image_text")
            manual_text_layout = (
                visual_payload.get("ux2c_selection_state") == "manual_text"
            )
            automatic_selection = (
                ux2_mock_output
                and visual_payload.get("ux2c_selection_state") not in {"manual_image", "manual_text"}
            )
            auto_replacement_marker: dict[str, Any] | None = None
            if automatic_selection and mapped_image_id:
                selected_asset = assets_by_id.get(mapped_image_id)
                risk_codes = auto_placement_risk_codes(selected_asset, db) if selected_asset else []
                asset_group = (
                    (selected_asset.content_hash or f"asset:{selected_asset.id}")
                    if selected_asset else f"asset:{mapped_image_id}"
                )
                if asset_group in auto_used_asset_groups:
                    risk_codes = [*risk_codes, "duplicate_asset_group"]
                if risk_codes:
                    mapped_image_id = None
                    visual_kind = "html_graphic"
                    auto_replacement_marker = {
                        "ux2d1_auto_replacement": {
                            "strategy": "html_information",
                            "reason_codes": sorted(set(risk_codes)),
                        }
                    }
                    visual_payload = {
                        "layout_variant": "image_text",
                        "ux2_mock_output": True,
                        **auto_replacement_marker,
                    }
                else:
                    auto_used_asset_groups.add(asset_group)
            if ux2_mock_output and mapped_image_id is None and not manual_text_layout:
                replacement_metadata = auto_replacement_marker or (
                    {"ux2d1_auto_replacement": visual_payload["ux2d1_auto_replacement"]}
                    if visual_payload.get("ux2d1_auto_replacement")
                    else {}
                )
                visual_payload["ux2_mock_output"] = True
                if section_type in {"feature_1", "feature_2", "feature_3"}:
                    card = next(
                        (card for card in grounded_cards if set(card["source_fact_ids"]).intersection(associated_fact_ids)),
                        None,
                    )
                    if card:
                        visual_payload = {
                            "layout_variant": "benefit_cards",
                            "cards": [card],
                            "ux2_mock_output": True,
                            **replacement_metadata,
                        }
                elif section_type == "details_components" and associated_fact_ids:
                    cards = [card for card in grounded_cards if set(card["source_fact_ids"]).intersection(associated_fact_ids)]
                    if cards:
                        visual_payload = {
                            "layout_variant": "benefit_cards",
                            "cards": cards,
                            "ux2_mock_output": True,
                            **replacement_metadata,
                        }
                elif section_type == "details_components" and grounded_cards:
                        visual_payload = {
                            "layout_variant": "benefit_cards",
                            "cards": grounded_cards[:3],
                            "ux2_mock_output": True,
                            **replacement_metadata,
                        }
            if section_type == "hero" and mapped_image_id is None:
                visual_payload["mock_safe_hero"] = True
            db.add(
                PageSection(
                    page_id=page.id,
                    section_type=section_type,
                    title=title,
                    body_copy=body_copy,
                    image_asset_id=mapped_image_id,
                    visual_kind=visual_kind,
                    visual_payload=visual_payload,
                    sort_order=order_by_type.get(section_type, idx),
                    is_visible=is_visible,
                    associated_fact_ids=associated_fact_ids,
                )
            )
            version_sections.append(
                {
                    "key": section_type,
                    "section_type": section_type,
                    "title": title,
                    "body": body_copy,
                    "body_copy": body_copy,
                    "associated_fact_ids": associated_fact_ids,
                    "image_asset_id": mapped_image_id,
                    "visual_kind": visual_kind,
                    "visual_payload": visual_payload,
                    "sort_order": order_by_type.get(section_type, idx),
                    "is_visible": is_visible,
                }
            )

        # UX-2: complete a Mock page with a final, grounded product
        # information section.  This avoids an empty “photo required” block
        # and keeps the required notice at the end of the commerce page.
        spec_rows = [
            {
                "label": display_label(
                    str(item.get("field_key") or ""), item.get("scope"), item.get("model_option")
                ),
                "value": f"{item.get('value') or item.get('normalized_value') or item.get('fact_text') or ''}{item.get('unit') or item.get('normalized_unit') or ''}".strip(),
                "verification_status": "confirmed",
                "source_fact_ids": [item["id"]],
            }
            for item in approved_facts
            if item.get("id") and item.get("value")
        ]
        preserved_final = existing_by_type.get("product_information")
        preserved_final_asset_id = (
            preserved_final.image_asset_id
            if preserved_final and preserved_final.image_asset_id in asset_ids
            else None
        )
        final_sort_order = len(ordered_section_types)
        if spec_rows:
            final_payload = {"layout_variant": "spec_table", "table_rows": spec_rows, "ux2_mock_output": True}
            final_visual_kind = "html_graphic"
            if preserved_final is not None and preserved_final_asset_id:
                final_payload = {**final_payload, **dict(preserved_final.visual_payload or {})}
                final_visual_kind = preserved_final.visual_kind or "image"
            final_section = PageSection(
                page_id=page.id,
                section_type="product_information",
                title="제품 사양·주의사항·필수 고지",
                body_copy="모델, 규격, 구성품과 판매 조건을 구매 전에 확인해 주세요.",
                associated_fact_ids=[row["source_fact_ids"][0] for row in spec_rows],
                image_asset_id=preserved_final_asset_id,
                visual_kind=final_visual_kind,
                visual_payload=final_payload,
                sort_order=final_sort_order,
                is_visible=True,
            )
            db.add(final_section)
            version_sections.append({
                "key": "product_information", "section_type": "product_information",
                "title": final_section.title, "body": final_section.body_copy,
                "body_copy": final_section.body_copy, "associated_fact_ids": final_section.associated_fact_ids,
                "image_asset_id": final_section.image_asset_id, "visual_kind": final_section.visual_kind,
                "visual_payload": final_section.visual_payload, "sort_order": final_section.sort_order,
                "is_visible": True,
            })
        else:
            # A product with no confirmed structured specification must still
            # finish with an honest notice section. It is intentionally plain
            # HTML copy, not an invented specification table.
            final_payload = {"layout_variant": "image_text", "ux2_mock_output": True}
            final_visual_kind = "html_graphic"
            if preserved_final is not None and preserved_final_asset_id:
                final_payload = {**final_payload, **dict(preserved_final.visual_payload or {})}
                final_visual_kind = preserved_final.visual_kind or "image"
            final_section = PageSection(
                page_id=page.id,
                section_type="product_information",
                title="제품 사양·주의사항·필수 고지",
                body_copy="판매자가 제공한 상품 정보와 주의사항을 구매 전에 확인해 주세요.",
                image_asset_id=preserved_final_asset_id,
                visual_kind=final_visual_kind,
                visual_payload=final_payload,
                sort_order=final_sort_order,
                is_visible=True,
            )
            db.add(final_section)
            version_sections.append({
                "key": "product_information", "section_type": "product_information",
                "title": final_section.title, "body": final_section.body_copy,
                "body_copy": final_section.body_copy, "associated_fact_ids": [],
                "image_asset_id": final_section.image_asset_id, "visual_kind": final_section.visual_kind,
                "visual_payload": final_section.visual_payload, "sort_order": final_section.sort_order,
                "is_visible": True,
            })

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
        # A completed run is immutable. Returning it prevents a browser retry
        # or refresh from creating a second page version or a second set of
        # image jobs.
        if run.status == "completed":
            return run

        input_snapshot = run.input_snapshot or {}
        asset_ids = AgentRunService._ensure_input_asset_ids(run, db)
        # UX-1 turns inspection and fact extraction into background steps.
        # The seller is interrupted only when the generation itself cannot
        # continue; advanced routes still retain the explicit review gate.
        if not (run.input_snapshot or {}).get("ux_auto_generate"):
            AgentRunService._enforce_asset_understanding_gate(run, db, asset_ids)
        # Sprint 3: persist the exact approved evidence set used by this run.
        # Draft/rejected/conflicted facts are intentionally excluded.
        from src.services.fact_evidence_service import approved_fact_snapshot, fact_board_blockers, refresh_evidence_board
        refresh_evidence_board(db, run.project, run.created_by)
        fact_blockers = fact_board_blockers(db, run.project_id)
        if fact_blockers and not (run.input_snapshot or {}).get("ux_auto_generate"):
            db.commit()
            raise FactEvidenceNotReady(fact_blockers)
        fact_snapshot = approved_fact_snapshot(db, run.project_id, run.created_by)
        input_snapshot = dict(input_snapshot)
        input_snapshot["approved_fact_snapshot_id"] = fact_snapshot.id
        input_snapshot["approved_fact_snapshot_hash"] = fact_snapshot.snapshot_hash
        input_snapshot["approved_facts"] = fact_snapshot.facts_json
        run.input_snapshot = input_snapshot
        db.flush()
        product_input = ProductInput(
            product_name=input_snapshot.get("product_name") or "",
            category=input_snapshot.get("category"),
            description=input_snapshot.get("description"),
            feature_details=input_snapshot.get("feature_details"),
            components=input_snapshot.get("components"),
            cautions=input_snapshot.get("cautions"),
            product_url=input_snapshot.get("product_url"),
            freeform_input=input_snapshot.get("freeform_input"),
            asset_ids=asset_ids,
            reference_urls=input_snapshot.get("reference_urls") or [],
            selling_points=input_snapshot.get("selling_points") or [],
            price=input_snapshot.get("price"),
            shipping=input_snapshot.get("shipping"),
            model_options=input_snapshot.get("model_options"),
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
        completed_stage_names = {
            step.stage
            for step in db.query(AgentRunStep)
            .filter(AgentRunStep.run_id == run.id, AgentRunStep.status == "completed")
            .all()
        }
        run.status = "running"
        run.completed_at = None
        db.add(run)
        db.commit()

        completed_state = state

        for agent in graph.agents:
            stage = agent.name
            if stage in completed_stage_names:
                continue
            completed_state.current_stage = AgentStage(stage)
            AgentRunService._record_stage_progress(run, db, stage, "running", completed_state, None)
            try:
                completed_state = agent.run(completed_state)
            except Exception as exc:
                AgentRunService._record_stage_progress(run, db, stage, "failed", completed_state, exc)
                raise
            AgentRunService._record_stage_progress(run, db, stage, "completed", completed_state, None)

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
            .with_for_update()
            .first()
        )
        if not run:
            raise ValueError(f"AgentRun not found: {run_id}")
        # Retries after a completed response are reads, not a second billable
        # generation or another page materialization.
        if run.status == "completed":
            return run

        input_snapshot = run.input_snapshot or {}
        asset_ids = AgentRunService._ensure_input_asset_ids(run, db)
        if not (run.input_snapshot or {}).get("ux_auto_generate"):
            AgentRunService._enforce_asset_understanding_gate(run, db, asset_ids)
        from src.services.fact_evidence_service import approved_fact_snapshot, fact_board_blockers, refresh_evidence_board
        refresh_evidence_board(db, run.project, run.created_by)
        fact_blockers = fact_board_blockers(db, run.project_id)
        if fact_blockers and not (run.input_snapshot or {}).get("ux_auto_generate"):
            db.commit()
            raise FactEvidenceNotReady(fact_blockers)
        fact_snapshot = approved_fact_snapshot(db, run.project_id, run.created_by)
        input_snapshot = dict(input_snapshot)
        input_snapshot["approved_fact_snapshot_id"] = fact_snapshot.id
        input_snapshot["approved_fact_snapshot_hash"] = fact_snapshot.snapshot_hash
        input_snapshot["approved_facts"] = fact_snapshot.facts_json
        run.input_snapshot = input_snapshot
        db.flush()
        product_input = ProductInput(
            product_name=input_snapshot.get("product_name") or "",
            category=input_snapshot.get("category"),
            description=input_snapshot.get("description"),
            feature_details=input_snapshot.get("feature_details"),
            components=input_snapshot.get("components"),
            cautions=input_snapshot.get("cautions"),
            product_url=input_snapshot.get("product_url"),
            freeform_input=input_snapshot.get("freeform_input"),
            asset_ids=asset_ids,
            reference_urls=input_snapshot.get("reference_urls") or [],
            selling_points=input_snapshot.get("selling_points") or [],
            price=input_snapshot.get("price"),
            shipping=input_snapshot.get("shipping"),
            model_options=input_snapshot.get("model_options"),
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
