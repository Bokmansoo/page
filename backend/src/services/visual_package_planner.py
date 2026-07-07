import uuid
import hashlib
import json
from typing import List, Dict, Any, Optional
from src.db.models import ProductProject, Asset
from src.services.commerce_visual_cut_builder import build_commerce_visual_cuts, CommerceVisualCut
from src.services.image_generation_contract import ImageGenerationJob, VisualRole
from src.services.image_asset_mapper import map_image_assets_to_sections
from src.services.visual_background_service import VisualBackgroundService


def _model_to_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value


def resolve_sales_strategy(
    project: ProductProject,
    generated_strategy: Optional[Any],
) -> Optional[Any]:
    snapshot = getattr(project, "intake_snapshot", None)
    if isinstance(snapshot, dict):
        confirmed = snapshot.get("confirmed_sales_strategy")
        if isinstance(confirmed, dict) and confirmed:
            return confirmed
    return generated_strategy


def build_visual_package_signature(
    project: ProductProject,
    page: Any,
    assets: List[Any],
    sales_strategy: Optional[Any],
) -> str:
    sections = page.get("sections", []) if isinstance(page, dict) else page.sections
    section_values = []
    for section in sections:
        if isinstance(section, dict):
            section_values.append({
                "id": section.get("id"),
                "section_type": section.get("section_type"),
                "title": section.get("title"),
                "body_copy": section.get("body_copy"),
                "image_asset_id": section.get("image_asset_id"),
                "sort_order": section.get("sort_order"),
            })
        else:
            section_values.append({
                "id": section.id,
                "section_type": section.section_type,
                "title": section.title,
                "body_copy": section.body_copy,
                "image_asset_id": section.image_asset_id,
                "sort_order": getattr(section, "sort_order", None),
            })

    asset_values = []
    for asset in assets:
        if isinstance(asset, dict):
            asset_values.append({
                "id": asset.get("id"),
                "filename": asset.get("filename"),
                "mime_type": asset.get("mime_type"),
                "source_type": asset.get("source_type"),
            })
        else:
            asset_values.append({
                "id": asset.id,
                "filename": asset.filename,
                "mime_type": asset.mime_type,
                "source_type": asset.source_type,
            })

    payload = {
        "project": {
            "id": getattr(project, "id", None),
            "name": getattr(project, "name", None),
            "selected_style": getattr(project, "selected_style", None),
            "selected_background": getattr(project, "selected_background", None),
        },
        "sections": sorted(section_values, key=lambda item: str(item["id"])),
        "assets": sorted(asset_values, key=lambda item: str(item["id"])),
        "sales_strategy": _model_to_dict(sales_strategy),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def get_visual_mood_desc(project: ProductProject) -> str:
    bg_id = getattr(project, "selected_background", "cooling-blue") or "cooling-blue"
    bg_service = VisualBackgroundService()
    candidates = bg_service.get_candidates(project.name)
    
    selected_bg = next((c for c in candidates if c["id"] == bg_id), None)
    if selected_bg:
        return f"{selected_bg['title']} ({selected_bg['description']})"
    return "cooling blue gradient, refreshing airflow look"

def generate_prompt_suggestion(
    role: str,
    cut: CommerceVisualCut,
    project: ProductProject,
    sales_strategy: Optional[Any] = None
) -> str:
    mood = get_visual_mood_desc(project)
    product_name = project.name or "상품"
    headline = cut.headline or ""
    subcopy = cut.subcopy or ""
    
    # Extract sales strategy details if available
    target_customer = ""
    buyer_problem = ""
    main_selling_point = ""
    tone = ""
    if sales_strategy:
        if isinstance(sales_strategy, dict):
            target_customer = sales_strategy.get("target_customer", "")
            buyer_problem = sales_strategy.get("buyer_problem", "")
            main_selling_point = sales_strategy.get("main_selling_point", "")
            tone = sales_strategy.get("tone", "")
        else:
            target_customer = getattr(sales_strategy, "target_customer", "")
            buyer_problem = getattr(sales_strategy, "buyer_problem", "")
            main_selling_point = getattr(sales_strategy, "main_selling_point", "")
            tone = getattr(sales_strategy, "tone", "")
            
    # Fallback to standard copy if strategy fields are empty
    buyer_problem = buyer_problem or headline or subcopy
    main_selling_point = main_selling_point or headline or subcopy
    target_customer = target_customer or "customers"
    tone = tone or "clean and modern style"
    
    base_prompt = ""
    if role == "representative_product":
        base_prompt = f"Place the provided product cutout of {product_name} on a high-quality studio background. Target audience: {target_customer}. Maintain the exact shape, details, and colors of the product cutout. background style: {mood}. Premium lighting, realistic shadows, clean and professional product composition."
    elif role == "cutout_product":
        base_prompt = f"Sleek cutout product shot of {product_name}, isolated on a pure white background. Highlight: {main_selling_point}. Sharp focus, clean edges, studio lighting."
    elif role == "lifestyle_scene":
        base_prompt = f"Place the provided product cutout of {product_name} in a realistic lifestyle scene: modern home environment suitable for {target_customer}. Maintain the exact shape, details, and colors of the product cutout. soft natural light, realistic shadows, seamless blend with background. Tone: {tone}."
    elif role == "problem_scene":
        base_prompt = f"A realistic, empathetic photo depicting the buyer's pain point: '{buyer_problem}'. Cinematic lighting, emotional and natural storytelling."
    elif role == "benefit_visual":
        base_prompt = f"Visual scene highlighting the core benefit of {product_name}: '{main_selling_point}'. Maintain the exact shape, details, and colors of the product cutout. Blended with clean layout components, set in a {mood} environment. Target audience: {target_customer}."
    elif role == "detail_closeup":
        base_prompt = f"Macro close-up photography of {product_name}, focusing on the build quality and design detail of '{headline or main_selling_point}'. Maintain the exact shape, details, and colors of the product cutout. Highly detailed, soft studio lighting."
    elif role == "comparison_graphic":
        base_prompt = f"A clean visual comparison scene between {product_name} and standard alternatives. Sleek, minimalist design, showing a side-by-side product view."
    elif role == "badge_set":
        base_prompt = f"A collection of abstract modern trust shapes and icons representing safety and reliability for {product_name} on a {mood} background."
    elif role == "faq_graphic":
        base_prompt = f"A clean visual graphic layout card suitable for Q&A representation, with a clean minimal layout on a {mood} background."
    elif role == "thumbnail":
        base_prompt = f"Catchy e-commerce thumbnail image for {product_name}, highlighting {main_selling_point}. Bright background, optimal crop, enticing representation. Target: {target_customer}."
    elif role == "cta_visual":
        base_prompt = f"Inviting call to action visual scene for {product_name}, with a premium visual appeal prompting purchase. Maintain the exact shape, details, and colors of the product cutout. Vibrant colors."
    else:
        base_prompt = f"Commerce visual for {product_name} highlighting '{headline or main_selling_point}'. Tone: {tone}. Maintain the exact shape, details, and colors of the product cutout. Background: {mood}."
        
    # Append strict exclusion clause to keep image clean and textless
    exclusion_clause = " Strictly do NOT include any text, words, letters, labels, logos, badges, or certification marks in the image. Focus purely on the visual scene. All text and labels will be overlaid as edit layers later."
    return base_prompt + exclusion_clause

class VisualPackagePlanner:
    def plan_visual_package(
        self,
        project: ProductProject,
        page: Any,
        assets: List[Any],
        sales_strategy: Optional[Any] = None,
        scene_plan: Optional[dict[str, Any]] = None,
    ) -> List[ImageGenerationJob]:
        sales_strategy = resolve_sales_strategy(project, sales_strategy)
        plan_signature = build_visual_package_signature(
            project,
            page,
            assets,
            sales_strategy,
        )

        # 1. Convert sqlalchemy objects to list of dicts for mapper and cuts
        # Build cuts
        assets_data = []
        image_asset_ids = []
        cutout_map = {}
        cutout_asset_ids = []
        for asset in assets:
            if isinstance(asset, dict):
                assets_data.append(asset)
                a_id = asset.get("id")
                src_asset_id = asset.get("source_asset_id")
                is_cutout = asset.get("background_removed") or asset.get("source_type") == "ai_corrected"
                if asset.get("mime_type", "").startswith("image/"):
                    image_asset_ids.append(a_id)
                if is_cutout:
                    cutout_asset_ids.append(a_id)
                if src_asset_id:
                    cutout_map[src_asset_id] = a_id
            else:
                assets_data.append({
                    "id": asset.id,
                    "filename": asset.filename,
                    "mime_type": asset.mime_type,
                    "source_type": asset.source_type,
                    "source_asset_id": getattr(asset, "source_asset_id", None),
                    "background_removed": getattr(asset, "background_removed", False),
                })
                a_id = asset.id
                src_asset_id = getattr(asset, "source_asset_id", None)
                is_cutout = getattr(asset, "background_removed", False) or asset.source_type == "ai_corrected"
                if asset.mime_type and asset.mime_type.startswith("image/"):
                    image_asset_ids.append(a_id)
                if is_cutout:
                    cutout_asset_ids.append(a_id)
                if src_asset_id:
                    cutout_map[src_asset_id] = a_id
        
        cuts = build_commerce_visual_cuts(page, assets_data, project)
        
        # Determine image assignments using the image asset mapper
        sections_data = []
        if isinstance(page, dict):
            sections = page.get("sections") or []
        else:
            sections = page.sections
            
        for sec in sections:
            if isinstance(sec, dict):
                sections_data.append({
                    "id": sec.get("id"),
                    "section_type": sec.get("section_type") or "",
                    "image_asset_id": sec.get("image_asset_id")
                })
            else:
                sections_data.append({
                    "id": sec.id,
                    "section_type": sec.section_type or "",
                    "image_asset_id": sec.image_asset_id
                })
                
        assignments = map_image_assets_to_sections(sections_data, assets_data)
        assignment_map = {a["section_id"]: a["asset_id"] for a in assignments}
        filename_map = {a["id"]: a["filename"] for a in assets_data}
        
        # Build a set of section IDs that should use html_graphic instead of image generation
        html_graphic_section_ids: set[str] = set()
        if scene_plan:
            for scene in scene_plan.get("sections") or []:
                if scene.get("visual_strategy") == "html_graphic":
                    html_graphic_section_ids.add(scene.get("target_slot_id", ""))

        jobs = []
        for cut in cuts:
            # Skip html_graphic sections, and skip Specs/Comparison/Pre-purchase sections — they use visual contract, not image generation
            if cut.section_id in html_graphic_section_ids or cut.section_type in {"specifications", "comparison", "pre_purchase", "product_information"}:
                continue

            # Check if there is an original photo mapped
            # Prefer the one explicitly set on the cut, otherwise check mapper assignment
            assigned_asset_id = cut.image_asset_id or assignment_map.get(cut.section_id)
            role = cut.visual_role
            
            # Ensure it is a valid visual role, otherwise map/fallback
            from src.services.image_generation_contract import VISUAL_ROLES
            if role not in VISUAL_ROLES:
                role = "lifestyle_scene"
                
            job_id = f"job-{uuid.uuid4().hex[:12]}"
            section_id = cut.section_id
            
            # Standard negative prompt to avoid text overlays and badges in AI generation
            neg_prompt = "text, words, letters, font, typography, logo, badge, certificate, stamp, watermark, sign, label, blurry, distorted, low quality, bad anatomy"
            
            if assigned_asset_id:
                filename = filename_map.get(assigned_asset_id, "original_photo.jpg")
                job = ImageGenerationJob(
                    job_id=job_id,
                    section_id=section_id,
                    plan_signature=plan_signature,
                    role=role,
                    source_asset_ids=[assigned_asset_id],
                    prompt=f"Original product photo used: {filename}",
                    negative_prompt=neg_prompt,
                    preserve_product_identity=True,
                    output_size="1024x1024",
                    cost_tier="standard",
                    status="planned"
                )
            else:
                # Needs AI image generation
                # Identity preservation is True for product-related roles
                preserve_identity = role in ("representative_product", "cutout_product", "lifestyle_scene", "detail_closeup")
                
                # If preserve_identity is True, we must have at least one source asset
                job_source_assets = []
                if preserve_identity:
                    # Prefer cutout versions of original images
                    if assigned_asset_id and assigned_asset_id in cutout_map:
                        job_source_assets = [cutout_map[assigned_asset_id]]
                    elif assigned_asset_id:
                        job_source_assets = [assigned_asset_id]
                    else:
                        job_source_assets = cutout_asset_ids if cutout_asset_ids else image_asset_ids
                    # If we don't have any images, we cannot preserve identity
                    if not job_source_assets:
                        preserve_identity = False
                        
                prompt_sugg = generate_prompt_suggestion(role, cut, project, sales_strategy)
                
                job = ImageGenerationJob(
                    job_id=job_id,
                    section_id=section_id,
                    plan_signature=plan_signature,
                    role=role,
                    source_asset_ids=job_source_assets,
                    prompt=prompt_sugg,
                    negative_prompt=neg_prompt,
                    preserve_product_identity=preserve_identity,
                    output_size="1024x1024",
                    cost_tier="standard",
                    status="needs_generation"
                )
            
            jobs.append(job)
            
        return jobs
