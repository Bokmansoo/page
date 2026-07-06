import os
import zipfile
import uuid
import datetime
from io import BytesIO
from typing import Literal
from urllib.parse import urlencode
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy.orm import Session
from src.db.models import ExportArtifact
from src.services.page_asset_policy import get_page_eligible_assets


def capture_next_render_export(
    *,
    project_id: str,
    version_id: str,
    output_format: Literal["png", "jpg", "jpeg"] = "png",
    output_dir: str | None = None,
    render_base_url: str | None = None,
    auth_headers: dict[str, str] | None = None,
    playwright=None,
) -> dict[str, str]:
    """Capture the canonical Next.js render route as one image and section ZIP."""
    normalized_format = output_format.lower()
    if normalized_format == "jpeg":
        normalized_format = "jpg"
    if normalized_format not in {"png", "jpg"}:
        raise ValueError("output_format must be png, jpg, or jpeg")

    output_dir = os.path.abspath(
        output_dir or os.path.join(os.getcwd(), "uploads", "exports")
    )
    os.makedirs(output_dir, exist_ok=True)
    render_base_url = (
        render_base_url
        or os.getenv("SELLFORM_EXPORT_RENDER_BASE_URL")
        or "http://127.0.0.1:3000"
    ).rstrip("/")
    auth_headers = auth_headers or {}
    query = urlencode(
        {
            "version_id": version_id,
            "user_id": auth_headers.get("X-Mock-User-Id", ""),
            "workspace_id": auth_headers.get("X-Mock-Workspace-Id", ""),
        }
    )
    render_url = f"{render_base_url}/workspace/projects/{project_id}/render?{query}"
    image_path = os.path.join(
        output_dir,
        f"{project_id}_{version_id}_long.{normalized_format}",
    )
    zip_path = os.path.join(output_dir, f"{project_id}_{version_id}_sections.zip")
    section_paths: list[tuple[str, str]] = []
    browser = None
    owns_playwright = playwright is None
    playwright_manager = None
    owned_playwright = None

    try:
        if owns_playwright:
            from playwright.sync_api import sync_playwright

            playwright_manager = sync_playwright()
            playwright = playwright_manager.start()
            owned_playwright = playwright

        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 900, "height": 1200},
            extra_http_headers=auth_headers,
        )
        page.goto(render_url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector(
            "html[data-export-ready='true']",
            state="attached",
            timeout=30000,
        )

        screenshot_type = "jpeg" if normalized_format == "jpg" else "png"
        screenshot_options = {
            "path": image_path,
            "type": screenshot_type,
        }
        if screenshot_type == "jpeg":
            screenshot_options["quality"] = 92
        page.locator("[data-detail-page-document='true']").screenshot(
            **screenshot_options
        )

        sections = page.locator("[data-detail-page-section='true']")
        for index in range(sections.count()):
            filename = f"{index + 1:02d}-section.{normalized_format}"
            section_path = os.path.join(
                output_dir,
                f"temp_{project_id}_{version_id}_{filename}",
            )
            section_options = {
                "path": section_path,
                "type": screenshot_type,
            }
            if screenshot_type == "jpeg":
                section_options["quality"] = 92
            sections.nth(index).screenshot(**section_options)
            section_paths.append((filename, section_path))

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, section_path in section_paths:
                archive.write(section_path, arcname=filename)

        return {
            "long_vertical_image": image_path,
            "section_images_zip": zip_path,
        }
    except Exception:
        for path in [image_path, zip_path, *(path for _, path in section_paths)]:
            if os.path.exists(path):
                os.remove(path)
        raise
    finally:
        for _, section_path in section_paths:
            if os.path.exists(section_path):
                os.remove(section_path)
        if browser is not None:
            browser.close()
        if owned_playwright is not None:
            owned_playwright.stop()


def load_export_font(size: int, bold: bool = False):
    """Load a Korean-capable font for exported detail-page images.

    Pillow's default bitmap font cannot render Korean text, so exported PNGs
    become unreadable on Windows/local runs. Prefer explicit env override, then
    common Korean fonts on Windows and Linux, and only fall back to Pillow's
    default font as a last resort.
    """
    env_font_path = os.getenv("SELLFORM_EXPORT_BOLD_FONT_PATH" if bold else "SELLFORM_EXPORT_FONT_PATH")
    candidates = [
        env_font_path,
        r"C:\Windows\Fonts\NotoSansKR-VF.ttf",
        r"C:\Windows\Fonts\malgunbd.ttf" if bold else r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\NGULIM.TTF",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for font_path in candidates:
        if not font_path or not os.path.exists(font_path):
            continue
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_width(text: str, font) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    wrapped_lines: list[str] = []
    for raw_line in str(text or "").splitlines() or [""]:
        words = raw_line.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if _text_width(candidate, font) <= max_width:
                current = candidate
                continue
            if current:
                wrapped_lines.append(current)
                current = word
                continue
            # Very long unspaced strings, e.g. model codes/URLs.
            fragment = ""
            for char in word:
                candidate_fragment = f"{fragment}{char}"
                if _text_width(candidate_fragment, font) <= max_width:
                    fragment = candidate_fragment
                else:
                    if fragment:
                        wrapped_lines.append(fragment)
                    fragment = char
            current = fragment
        if current:
            wrapped_lines.append(current)
    return wrapped_lines

def build_export_manifest(project_id: str, version_id: str, sections: list[dict]) -> dict:
    sections = normalize_sections_snapshot(sections)
    return {
        "project_id": project_id,
        "version_id": version_id,
        "outputs": ["long_vertical_image", "section_images_zip"],
        "sections": [
            {
                "index": index + 1,
                "key": section.get("key"),
                "title": section.get("title"),
                "filename": f"{index + 1:02d}-{section.get('key', 'section')}.png",
            }
            for index, section in enumerate(sections)
        ],
    }

def normalize_sections_snapshot(sections_snapshot) -> list[dict]:
    if isinstance(sections_snapshot, dict):
        return sections_snapshot.get("sections", [])
    return sections_snapshot or []


def _draw_gradient_vertical(draw, width: int, height: int, start_color: str, end_color: str):
    r1, g1, b1 = int(start_color[1:3], 16), int(start_color[3:5], 16), int(start_color[5:7], 16)
    r2, g2, b2 = int(end_color[1:3], 16), int(end_color[3:5], 16), int(end_color[5:7], 16)
    for y in range(height):
        ratio = y / max(1, height)
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def _draw_hero_section(draw, section, width, height, palette, title_font, body_font, label_font):
    accent = (37, 99, 235)
    text = (15, 23, 42)
    muted = (71, 85, 105)
    draw.rounded_rectangle([(48, 48), (width - 48, height - 48)], radius=36, fill=(255, 255, 255))
    draw.text((76, 82), section["eyebrow"], fill=muted, font=label_font)
    draw.text((76, 132), section["headline"], fill=accent, font=title_font)
    y = 196
    for line in _wrap_text(section["subcopy"], body_font, width - 152):
        draw.text((76, y), line, fill=text, font=body_font)
        y += 38
    draw.ellipse([(width - 260, height - 260), (width - 80, height - 80)], fill=palette[1])
    draw.arc([(width - 230, height - 230), (width - 110, height - 110)], start=20, end=320, fill=accent, width=10)


def _draw_image_text_section(img, draw, section, width, height, palette, title_font, body_font, label_font):
    accent = (37, 99, 235)
    text = (15, 23, 42)
    muted = (71, 85, 105)
    draw.rounded_rectangle([(44, 30), (width - 44, height - 30)], radius=24, fill=(255, 255, 255))
    
    visual_slot = section.get("visual_slot", {})
    image_drawn = False
    
    if visual_slot.get("kind") == "product_image" and visual_slot.get("file_path"):
        raw_path = visual_slot["file_path"]
        candidate_paths = [
            raw_path,
            os.path.join(os.getcwd(), "uploads", raw_path),
            os.path.join(os.getcwd(), raw_path),
            os.path.abspath(os.path.join(os.getcwd(), "..", "uploads", raw_path)),
            os.path.abspath(os.path.join(os.getcwd(), "backend", "uploads", raw_path))
        ]
        actual_path = None
        for p_path in candidate_paths:
            if os.path.exists(p_path):
                actual_path = p_path
                break
                
        if actual_path:
            try:
                box_width = width - 72 - 72
                box_height = 250 - 64
                with open(actual_path, "rb") as image_file:
                    image_bytes = image_file.read()
                with Image.open(BytesIO(image_bytes)) as prod_img:
                    prod_img_rgb = prod_img.convert("RGB")
                    prod_img_rgb.load()

                fitted_img = ImageOps.fit(prod_img_rgb, (box_width, box_height))
                try:
                    mask = Image.new("L", (box_width, box_height), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.rounded_rectangle([(0, 0), (box_width, box_height)], radius=20, fill=255)
                    
                    img.paste(fitted_img, (72, 64), mask=mask)
                    image_drawn = True
                finally:
                    fitted_img.close()
                    prod_img_rgb.close()
            except Exception:
                pass
                
    if not image_drawn:
        draw.rounded_rectangle([(72, 64), (width - 72, 250)], radius=20, fill=palette[1])
        draw.text((92, 92), visual_slot.get("fallback_label", "상품 이미지"), fill=muted, font=body_font)

    draw.text((72, 292), section["headline"], fill=accent, font=title_font)
    y = 350
    for line in _wrap_text(section["subcopy"], body_font, width - 144):
        draw.text((72, y), line, fill=text, font=body_font)
        y += 38


def _draw_commerce_cut(img, draw, sec, width, height, palette, title_font, body_font, label_font):
    accent = (37, 99, 235)
    text = (15, 23, 42)
    muted = (71, 85, 105)
    
    # 1. Background round box
    draw.rounded_rectangle([(30, 30), (width - 30, height - 30)], radius=32, fill=(255, 255, 255))
    
    visual_slot = sec.get("visual_slot", {})
    image_drawn = False
    
    # Image area allocation: 764x420 (approx 49.7% of total 860x750 area)
    box_width = width - 96
    box_height = 420
    img_x = 48
    img_y = 64
    
    if visual_slot.get("kind") == "product_image" and visual_slot.get("file_path"):
        raw_path = visual_slot["file_path"]
        candidate_paths = [
            raw_path,
            os.path.join(os.getcwd(), "uploads", raw_path),
            os.path.join(os.getcwd(), raw_path),
            os.path.abspath(os.path.join(os.getcwd(), "..", "uploads", raw_path)),
            os.path.abspath(os.path.join(os.getcwd(), "backend", "uploads", raw_path))
        ]
        actual_path = None
        for p_path in candidate_paths:
            if os.path.exists(p_path):
                actual_path = p_path
                break
                
        if actual_path:
            try:
                with open(actual_path, "rb") as image_file:
                    from io import BytesIO
                    image_bytes = image_file.read()
                with Image.open(BytesIO(image_bytes)) as prod_img:
                    prod_img_rgb = prod_img.convert("RGB")
                    prod_img_rgb.load()
                    
                fitted_img = ImageOps.fit(prod_img_rgb, (box_width, box_height))
                try:
                    mask = Image.new("L", (box_width, box_height), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.rounded_rectangle([(0, 0), (box_width, box_height)], radius=24, fill=255)
                    
                    img.paste(fitted_img, (img_x, img_y), mask=mask)
                    image_drawn = True
                finally:
                    fitted_img.close()
                    prod_img_rgb.close()
            except Exception:
                pass
                
    if not image_drawn:
        draw.rounded_rectangle([(img_x, img_y), (img_x + box_width, img_y + box_height)], radius=24, fill=palette[1])
        role_label = visual_slot.get("role", "lifestyle_scene")
        draw.text((img_x + 36, img_y + 36), f"⚠️ [{role_label}] 촬영 컷 배치가 필요합니다", fill=muted, font=body_font)
        draw.text((img_x + 36, img_y + 76), "상황이나 라이프스타일 묘사 컷 업로드를 권장합니다.", fill=muted, font=label_font)

    headline = sec.get("headline", "")
    subcopy = sec.get("subcopy", "")
    supporting_text = sec.get("supporting_text")
    
    text_y = 510
    draw.text((48, text_y), headline, fill=accent, font=title_font)
    text_y += 54
    
    for line in _wrap_text(subcopy, body_font, width - 96):
        draw.text((48, text_y), line, fill=text, font=body_font)
        text_y += 34
        
    if supporting_text:
        text_y += 8
        for line in _wrap_text(supporting_text, label_font, width - 96):
            draw.text((48, text_y), line, fill=muted, font=label_font)
            text_y += 24


def _draw_spec_table_section(draw, section, width, height, title_font, body_font, label_font):
    text = (15, 23, 42)
    muted = (71, 85, 105)
    border = (226, 232, 240)
    draw.rounded_rectangle([(44, 30), (width - 44, height - 30)], radius=24, fill=(255, 255, 255))
    draw.text((72, 72), "구매 전 확인 정보", fill=text, font=title_font)
    y = 140
    for row in section.get("spec_rows", []):
        draw.line([(72, y), (width - 72, y)], fill=border, width=1)
        draw.text((72, y + 24), row["label"], fill=muted, font=label_font)
        draw.text((240, y + 24), row["value"], fill=text, font=body_font)
        y += 76


def run_export(
    project_id: str,
    version_id: str,
    sections: list[dict],
    db: Session = None,
    use_commerce_cut: bool = False,
    output_format: Literal["png", "jpg", "jpeg"] = "png",
) -> dict:
    from src.db.models import ProductProject
    from src.services.visual_page_renderer import build_visual_sections

    normalized_format = output_format.lower()
    if normalized_format == "jpeg":
        normalized_format = "jpg"
    if normalized_format not in {"png", "jpg"}:
        raise ValueError("output_format must be png, jpg, or jpeg")

    image_extension = normalized_format
    pillow_format = "PNG" if normalized_format == "png" else "JPEG"

    def save_export_image(image: Image.Image, path: str) -> None:
        if pillow_format == "JPEG":
            image.convert("RGB").save(path, format=pillow_format, quality=92, optimize=True)
        else:
            image.save(path, format=pillow_format, optimize=True)

    original_snapshot = sections
    sections = normalize_sections_snapshot(sections)
    export_dir = os.path.abspath(os.path.join(os.getcwd(), "uploads", "exports"))
    os.makedirs(export_dir, exist_ok=True)
    
    selected_bg = None
    selected_style = None
    project = None
    if db is not None:
        project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
        if project and project.selected_background:
            selected_bg = project.selected_background
        if project and project.selected_style:
            selected_style = project.selected_style
    else:
        if isinstance(original_snapshot, dict):
            vb = original_snapshot.get("visual_background", {})
            if isinstance(vb, dict):
                selected_bg = vb.get("selected_background")
            selected_style = original_snapshot.get("style_key")

    BACKGROUND_PALETTES = {
        "cooling-blue": ["#EAF4FF", "#DDEBFF", "#FFFFFF"],
        "minimal-white": ["#F8F9FA", "#E9ECEF", "#FFFFFF"],
        "lifestyle-summer": ["#FFF9F2", "#FFEEDD", "#FFFFFF"]
    }
    
    palette = BACKGROUND_PALETTES.get(selected_bg) if selected_bg else BACKGROUND_PALETTES["cooling-blue"]
    
    image_assets = []
    if db is not None:
        assets = get_page_eligible_assets(db, project_id)
        image_assets = [
            {
                "id": a.id,
                "filename": a.filename,
                "file_path": a.file_path,
                "mime_type": a.mime_type,
                "source_type": a.source_type
            }
            for a in assets
        ]
    else:
        if isinstance(original_snapshot, dict):
            image_assets = original_snapshot.get("assets_snapshot", [])

    visual_sections = build_visual_sections(
        product_name=getattr(project, "title", "상품") if db is not None and project else "상품",
        category=getattr(project, "category", "Living") if db is not None and project else "Living",
        sections=sections,
        selected_background=selected_bg,
        image_assets=image_assets,
        use_commerce_cut=use_commerce_cut,
        selected_style=selected_style,
    )
    
    width = 860
    
    def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
        return (int(hex_str[1:3], 16), int(hex_str[3:5], 16), int(hex_str[5:7], 16))
        
    bg_color = hex_to_rgb(palette[0])
    
    label_font = load_export_font(16)
    title_font = load_export_font(34, bold=True)
    body_font = load_export_font(24)
    
    temp_files = []
    
    try:
        for idx, sec in enumerate(visual_sections):
            layout = sec["layout"]
            
            if use_commerce_cut:
                if layout in {"spec_visual", "spec_table"}:
                    section_height = max(350, 160 + len(sec.get("spec_rows", [])) * 76)
                else:
                    section_height = 750
            else:
                if layout == "hero":
                    title_lines = _wrap_text(sec["headline"], title_font, width - 152)
                    subcopy_lines = _wrap_text(sec["subcopy"], body_font, width - 152)
                    section_height = max(500, 260 + len(title_lines) * 46 + len(subcopy_lines) * 38)
                elif layout == "spec_table":
                    section_height = max(350, 160 + len(sec.get("spec_rows", [])) * 76)
                else:
                    title_lines = _wrap_text(sec["headline"], title_font, width - 144)
                    subcopy_lines = _wrap_text(sec["subcopy"], body_font, width - 144)
                    section_height = max(550, 380 + len(title_lines) * 46 + len(subcopy_lines) * 38)
                
            img = Image.new("RGB", (width, section_height), bg_color)
            draw = ImageDraw.Draw(img)
            
            if use_commerce_cut:
                if layout in {"spec_visual", "spec_table"}:
                    _draw_spec_table_section(draw, sec, width, section_height, title_font, body_font, label_font)
                else:
                    _draw_gradient_vertical(draw, width, section_height, palette[0], palette[1])
                    _draw_commerce_cut(img, draw, sec, width, section_height, palette, title_font, body_font, label_font)
            else:
                if layout == "hero":
                    _draw_gradient_vertical(draw, width, section_height, palette[0], palette[1])
                    _draw_hero_section(draw, sec, width, section_height, palette, title_font, body_font, label_font)
                elif layout == "spec_table":
                    _draw_spec_table_section(draw, sec, width, section_height, title_font, body_font, label_font)
                else:
                    _draw_image_text_section(img, draw, sec, width, section_height, palette, title_font, body_font, label_font)
            
            filename = f"{idx + 1:02d}-{sec['key']}.{image_extension}"
            file_path = os.path.join(export_dir, f"temp_{project_id}_{version_id}_{filename}")
            save_export_image(img, file_path)
            temp_files.append((filename, file_path, img))
            
        total_height = sum(img.height for _, _, img in temp_files)
        long_img = Image.new("RGB", (width, total_height), bg_color)
        
        current_y = 0
        for _, _, img in temp_files:
            long_img.paste(img, (0, current_y))
            current_y += img.height
            
        long_image_path = os.path.join(
            export_dir,
            f"{project_id}_{version_id}_long.{image_extension}",
        )
        save_export_image(long_img, long_image_path)
        long_img.close()
        
        zip_path = os.path.join(export_dir, f"{project_id}_{version_id}_sections.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for filename, file_path, _ in temp_files:
                zipf.write(file_path, arcname=filename)
                
        for _, file_path, img in temp_files:
            try:
                img.close()
                os.remove(file_path)
            except Exception:
                pass
                
        if db is not None:
            artifact_long = ExportArtifact(
                project_id=project_id,
                version_id=version_id,
                artifact_type="long_vertical_image",
                file_path=long_image_path
            )
            artifact_zip = ExportArtifact(
                project_id=project_id,
                version_id=version_id,
                artifact_type="section_images_zip",
                file_path=zip_path
            )
            db.add(artifact_long)
            db.add(artifact_zip)
            db.commit()
            
        return {
            "long_vertical_image": long_image_path,
            "section_images_zip": zip_path
        }
    except Exception as e:
        for _, file_path, img in temp_files:
            try:
                img.close()
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
        raise e
