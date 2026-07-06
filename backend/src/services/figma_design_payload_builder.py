import os
from typing import Any, Dict
from sqlalchemy.orm import Session
from src.config import settings
from src.db.models import ProductProject, ProductPage, Asset
from src.services.commerce_visual_cut_builder import build_commerce_visual_cuts
from src.services.figma_visual_layout_builder import build_figma_visual_layout
from src.services.page_asset_policy import get_page_eligible_assets


def build_figma_design_payload(
    project: ProductProject,
    page: ProductPage,
    db: Session,
    public_asset_base_url: str | None = None,
) -> Dict[str, Any]:
    """
    Generate clean, editable Figma design payload from page cuts.
    Filters sensitive database identifiers out of the result.
    """
    # 1. Gather brand/style context safely
    brand = getattr(project, "brand", None)
    brand_info = {
        "name": getattr(brand, "name", None) or "Default Brand",
        "primary_color": getattr(page, "theme_color", "#5B7CFA") or "#5B7CFA",
        "font_family": getattr(page, "font_family", "Sans-Serif") or "Sans-Serif"
    }
    asset_base_url = (
        public_asset_base_url
        or settings.SELLFORM_PUBLIC_ASSET_BASE_URL
    ).rstrip("/")

    # 2. Build ad-cuts structure using commerce cuts builder (Sprint 31)
    cuts = []
    # Fetch assets for the project
    assets = get_page_eligible_assets(db, project.id)
    visual_cuts = build_commerce_visual_cuts(page, assets, project)
    image_urls_by_asset_id: dict[str, str] = {}

    for v_cut in visual_cuts:
        image_url = None
        if v_cut.image_asset_id:
            # Query the filename from Asset table
            asset = next(
                (
                    candidate
                    for candidate in assets
                    if candidate.id == v_cut.image_asset_id
                ),
                None,
            )
            if asset:
                stored_filename = os.path.basename(asset.file_path or asset.filename)
                if stored_filename:
                    image_url = f"{asset_base_url}/uploads/{stored_filename}"
                    image_urls_by_asset_id[v_cut.image_asset_id] = image_url

        cuts.append({
            "section_id": v_cut.section_id,
            "section_type": v_cut.section_type,
            "layout_type": v_cut.layout_type,
            "headline": v_cut.headline,
            "subcopy": v_cut.subcopy,
            "supporting_text": v_cut.supporting_text,
            "image_url": image_url,
            "background_style": f"clean_{v_cut.section_type}"
        })

    visual_layout = build_figma_visual_layout(
        project=project,
        page=page,
        assets=assets,
        image_urls_by_asset_id=image_urls_by_asset_id,
    )

    # 3. Assemble JSON Payload structure
    payload = {
        "schema_version": "1.0",
        "project": {
            "id": project.id,
            "name": project.name,
            "category": project.category or "Unknown"
        },
        "brand": brand_info,
        "page": {
            "canvas_width": 860,
            "channel": getattr(project, "channel", "smartstore") or "smartstore",
            "style_key": project.selected_style or "default"
        },
        "cuts": cuts,
        "visual_layout": visual_layout,
    }

    return payload
