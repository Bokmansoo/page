import logging
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import HTTPException

from src.db.models import ProductProject, ProductPage, PageSection, ImageGenerationJobRecord, ProductFact
from src.services.page_generator import PageGenerationService
from src.services.visual_page_renderer import build_visual_sections
from src.services.sales_strategy_service import generate_sales_strategy
from src.services.page_asset_policy import get_page_eligible_assets

logger = logging.getLogger(__name__)

# =====================================================================
# Pydantic Schemas for Detail Page Package
# =====================================================================

class DetailPagePackage(BaseModel):
    sales_strategy: Optional[Dict[str, Any]] = Field(None, description="확정된 판매 전략 정보")
    copy_sections: List[Dict[str, Any]] = Field(..., description="카피 텍스트가 적용된 섹션 목록")
    visual_plan: Optional[Dict[str, Any]] = Field(None, description="비주얼 계획서 정보")
    page_sections: List[Dict[str, Any]] = Field(..., description="렌더링에 적합하게 빌드된 비주얼 섹션 정보")
    marketplace_copy: Dict[str, Any] = Field(..., description="마켓플레이스용 복사 카피 정보")
    export_targets: List[str] = Field(..., description="내보내기 대상 포맷 목록")

class AiEditCommandPayload(BaseModel):
    section_id: str
    command_type: Literal[
        "stronger_headline",
        "natural_tone",
        "emotional_tone",
        "reduce_exaggeration",
        "change_background",
        "move_section",
        "remove_section",
        "custom_edit",
    ] = Field(..., description="AI 편집 명령 유형")
    freeform_instruction: Optional[str] = Field(None, description="사용자 직접 입력 지시사항")
    scope: Literal["section", "page"] = Field("section", description="변경 적용 범위")

# =====================================================================
# Detail Page Package Service
# =====================================================================

class DetailPagePackageService:
    @staticmethod
    def get_or_create_detail_page_package(project_id: str, db: Session) -> DetailPagePackage:
        project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
        if not project:
            raise HTTPException(status_code=404, detail="Product project not found")

        # 1. Resolve sales_strategy
        snapshot = project.intake_snapshot if isinstance(project.intake_snapshot, dict) else {}
        sales_strategy = snapshot.get("confirmed_sales_strategy")
        if not sales_strategy:
            try:
                sales_strategy_resp = generate_sales_strategy(project, db)
                sales_strategy = sales_strategy_resp.model_dump()
            except Exception as e:
                logger.error(f"Failed to generate sales strategy fallback: {e}")
                sales_strategy = {
                    "target_customer": "일반 소비자",
                    "buyer_problem": "상품의 차별점을 파악하기 어려움",
                    "main_selling_point": project.name or "기본 상품",
                    "supporting_points": [],
                    "tone": "modern"
                }

        # 2. Get or create ProductPage
        page = db.query(ProductPage).filter(ProductPage.project_id == project.id).first()
        if not page:
            # Generate new page draft
            confirmed_facts = db.query(ProductFact).filter(
                ProductFact.project_id == project.id,
                ProductFact.verification_status == "confirmed"
            ).all()
            facts_payload = [
                {"id": f.id, "fact_text": f.fact_text, "source_text": f.source_text}
                for f in confirmed_facts
            ]

            generator = PageGenerationService()
            style_preset = project.selected_style or "problem_solution"
            generated = generator.generate_page(
                category=project.category or "Living",
                confirmed_facts=facts_payload,
                style_preset=style_preset,
                narrative_template="problem_solution",
                sales_strategy=sales_strategy
            )

            page = ProductPage(
                project_id=project.id,
                theme_color=generated.theme_color,
                font_family=generated.font_family
            )
            db.add(page)
            db.flush()

            for index, sec in enumerate(generated.sections):
                page_sec = PageSection(
                    page_id=page.id,
                    section_type=sec.section_type,
                    title=sec.title,
                    body_copy=sec.body_copy,
                    associated_fact_ids=sec.associated_fact_ids,
                    sort_order=index,
                    is_visible=True
                )
                db.add(page_sec)
            db.commit()
            db.refresh(page)

        # Page generation establishes the default order; subsequent edits use
        # persisted sort_order so move commands remain visible.
        sorted_sections = sorted(page.sections, key=lambda s: s.sort_order)

        copy_sections_data = []
        for sec in sorted_sections:
            copy_sections_data.append({
                "id": sec.id,
                "section_type": sec.section_type,
                "title": sec.title,
                "body_copy": sec.body_copy,
                "associated_fact_ids": sec.associated_fact_ids or [],
                "image_asset_id": sec.image_asset_id,
                "sort_order": sec.sort_order,
                "is_visible": sec.is_visible,
                "role": sec.role,
                "headline": sec.headline,
                "body": sec.body,
                "evidence_fact_ids": sec.evidence_fact_ids,
                "visual_strategy": sec.visual_strategy,
                "editable": sec.editable,
            })

        # 4. Resolve Approved Assets
        jobs = db.query(ImageGenerationJobRecord).filter(ImageGenerationJobRecord.project_id == project.id).all()
        valid_assets_list = [
            {
                "id": asset.id,
                "filename": asset.filename,
                "file_path": asset.file_path,
                "mime_type": asset.mime_type,
                "source_type": asset.source_type,
            }
            for asset in get_page_eligible_assets(db, project.id)
        ]

        # 5. Build Page Sections with Visual Slots
        raw_sections = [
            {
                "key": sec.section_type,
                "section_type": sec.section_type,
                "title": sec.title,
                "body_copy": sec.body_copy,
                "associated_fact_ids": sec.associated_fact_ids or [],
                "image_asset_id": sec.image_asset_id
            }
            for sec in sorted_sections if sec.is_visible
        ]

        page_sections_rendered = build_visual_sections(
            product_name=project.name or "상품",
            category=project.category or "Living",
            sections=raw_sections,
            selected_background=project.selected_background,
            image_assets=valid_assets_list,
            selected_style=project.selected_style
        )

        for section in page_sections_rendered:
            visual_slot = section.get("visual_slot", {})
            asset_id = visual_slot.get("asset_id")
            
            if asset_id and not any(va["id"] == asset_id for va in valid_assets_list):
                section["visual_slot"] = {
                    "kind": "placeholder",
                    "role": visual_slot.get("role", section.get("layout")),
                    "fallback_label": "image needed"
                }
                section["image_asset_id"] = None
            elif not asset_id:
                section["visual_slot"] = {
                    "kind": "placeholder",
                    "role": visual_slot.get("role", section.get("layout")),
                    "fallback_label": "image needed"
                }

        # 6. Build Marketplace Copy
        main_selling = sales_strategy.get("main_selling_point", project.name or "")
        buyer_problem_desc = sales_strategy.get("buyer_problem", "")
        
        marketplace_copy = {
            "title": f"[핫딜] {project.name}",
            "description": f"{buyer_problem_desc} 문제를 해결하는 {main_selling}!",
            "bullet_points": [sec.title for sec in sorted_sections if sec.title and sec.section_type != "product_information"][:3]
        }

        # 7. Visual Plan & Export Targets
        visual_plan = {
            "selected_style": project.selected_style or "problem_solution",
            "selected_background": project.selected_background or "cooling-blue",
            "jobs_count": len(jobs)
        }

        return DetailPagePackage(
            sales_strategy=sales_strategy,
            copy_sections=copy_sections_data,
            visual_plan=visual_plan,
            page_sections=page_sections_rendered,
            marketplace_copy=marketplace_copy,
            export_targets=["figma", "png", "html"]
        )

    @staticmethod
    def process_ai_edit(project_id: str, section_id: str, payload: AiEditCommandPayload, db: Session) -> DetailPagePackage:
        if payload.section_id != section_id:
            raise HTTPException(status_code=400, detail="Section ID does not match request path")

        page = db.query(ProductPage).filter(
            ProductPage.project_id == project_id
        ).first()
        if not page:
            raise HTTPException(status_code=404, detail="Product page not found")
        section = db.query(PageSection).filter(
            PageSection.id == section_id,
            PageSection.page_id == page.id,
        ).first()
        if not section:
            raise HTTPException(status_code=404, detail="Page section not found")

        command = payload.command_type.lower()
        copy_commands = {
            "stronger_headline",
            "natural_tone",
            "emotional_tone",
            "reduce_exaggeration",
            "custom_edit",
        }
        if payload.scope == "page" and command not in copy_commands:
            raise HTTPException(
                status_code=400,
                detail="Structural commands only support section scope",
            )

        targets = (
            [target for target in page.sections if target.is_visible]
            if payload.scope == "page"
            else [section]
        )
        instruction = (payload.freeform_instruction or "").strip()
        instruction_marker = (
            f" [Instruction: {instruction}]" if instruction else ""
        )

        for target in targets:
            if command == "stronger_headline":
                target.title = (
                    f"강조: {target.title or ''} [Revision: Stronger Headline]"
                    f"{instruction_marker}"
                ).strip()
            elif command == "natural_tone":
                target.body_copy = (
                    f"{target.body_copy or ''} [Revision: Natural Tone]"
                    f"{instruction_marker}"
                ).strip()
            elif command == "emotional_tone":
                target.body_copy = (
                    f"{target.body_copy or ''} [Revision: Emotional Tone]"
                    f"{instruction_marker}"
                ).strip()
            elif command == "reduce_exaggeration":
                target.body_copy = (
                    f"{target.body_copy or ''} [Revision: Reduced Exaggeration]"
                    f"{instruction_marker}"
                ).strip()
            elif command == "custom_edit":
                target.body_copy = (
                    f"{target.body_copy or ''} [Revision: {instruction or 'Custom Edit'}]"
                ).strip()

        if command == "change_background":
            project = page.project
            project.selected_background = instruction or "minimal-white"
        elif command == "move_section":
            direction = instruction.lower()
            comparator = (
                PageSection.sort_order < section.sort_order
                if direction == "up"
                else PageSection.sort_order > section.sort_order
            )
            order_by = (
                PageSection.sort_order.desc()
                if direction == "up"
                else PageSection.sort_order.asc()
            )
            adjacent = db.query(PageSection).filter(
                PageSection.page_id == section.page_id,
                comparator,
            ).order_by(order_by).first()
            if adjacent:
                old_order = section.sort_order
                section.sort_order = adjacent.sort_order
                adjacent.sort_order = old_order
        elif command == "remove_section":
            section.is_visible = False

        db.commit()

        return DetailPagePackageService.get_or_create_detail_page_package(project_id, db)
