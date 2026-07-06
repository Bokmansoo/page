import os
import uuid
import zipfile
import logging
import datetime
import time
from typing import List, Dict, Any, Tuple
from sqlalchemy.orm import Session
from PIL import Image, ImageDraw
from src.services.page_asset_policy import get_page_eligible_asset

logger = logging.getLogger(__name__)

PRESETS = {
    "coupang": {
        "width": 780,
        "max_height": 5000,
        "format": "PNG"
    },
    "smartstore": {
        "width": 860,
        "max_height": 20000,
        "format": "PNG"
    },
    "default": {
        "width": 800,
        "max_height": 5000,
        "format": "PNG"
    }
}

class PageRendererService:
    def __init__(self, upload_dir: str = "uploads"):
        self.upload_dir = upload_dir
        self.exports_dir = os.path.join(upload_dir, "exports")
        os.makedirs(self.exports_dir, exist_ok=True)

    def render_and_slice(self, db: Session, page: Any, preset_name: str) -> Tuple[str, List[str]]:
        """
        Renders the page to a full screenshot, slices it based on preset height limits,
        and packages the slices into a ZIP archive.
        
        Returns:
            Tuple[str, List[str]]: (ZIP file path, list of slice image paths)
        """
        preset = PRESETS.get(preset_name.lower(), PRESETS["default"])
        width = preset["width"]
        max_height = preset["max_height"]
        
        job_id = str(uuid.uuid4())
        
        # 1. HTML 컴파일
        html_content = self._compile_html(db, page, width)
        
        # 2. 이미지 렌더링 (Playwright 시도, 실패 시 Pillow Fallback)
        full_image_path = os.path.join(self.exports_dir, f"full_{job_id}.png")
        rendered_success = False
        
        # FACTORY_RAG_RUNTIME_MOCK과 유사하게, 환경 변수로 Mock 강제 가능
        force_mock = os.getenv("RENDERER_MOCK", "false").lower() == "true"
        
        if not force_mock:
            try:
                from playwright.sync_api import sync_playwright
                rendered_success = self._render_with_playwright(html_content, width, full_image_path)
            except Exception as e:
                logger.error(f"Playwright rendering failed, falling back to Mock Pillow renderer: {e}")
                rendered_success = False

        if not rendered_success:
            logger.info("Using Pillow Mock fallback to generate screenshot image.")
            self._render_with_pillow_fallback(page, width, full_image_path)

        # 3. Pillow로 스냅샷 분할 슬라이싱
        slice_paths = self._slice_image(full_image_path, max_height, job_id)
        
        # 4. ZIP 압축
        zip_filename = f"export_{preset_name}_{job_id}.zip"
        zip_path = os.path.join(self.exports_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            # 슬라이스 이미지 파일들을 추가
            for idx, slice_p in enumerate(slice_paths):
                arcname = f"section_{idx+1:02d}.png"
                zipf.write(slice_p, arcname)
            
            # 메타데이터 텍스트 파일 추가
            meta_content = (
                f"Sellform Export Metadata\n"
                f"Project: {page.project.name}\n"
                f"Date: {datetime.datetime.utcnow().isoformat()}\n"
                f"Preset: {preset_name}\n"
                f"Width: {width}px\n"
                f"Total Slices: {len(slice_paths)}\n"
            )
            zipf.writestr("metadata.txt", meta_content)
            
        # 전체 캡처 임시 이미지는 삭제
        self._remove_temporary_file(full_image_path)
            
        return zip_path, slice_paths

    def _remove_temporary_file(self, path: str) -> None:
        if not os.path.exists(path):
            return

        for attempt in range(3):
            try:
                os.remove(path)
                return
            except PermissionError:
                if attempt == 2:
                    logger.warning("Could not remove temporary render file: %s", path, exc_info=True)
                    return
                time.sleep(0.1)

    def _compile_html(self, db: Session, page: Any, width: int) -> str:
        theme_color = page.theme_color or "#3B82F6"
        font_family = page.font_family or "sans-serif"
        
        sections_html = []
        visible_sections = [sec for sec in page.sections if sec.is_visible]
        # sort_order 정렬
        visible_sections = sorted(visible_sections, key=lambda s: s.sort_order)
        
        for sec in visible_sections:
            img_html = ""
            if sec.image_asset_id:
                # 에셋 경로 확인
                asset = get_page_eligible_asset(
                    db, page.project_id, sec.image_asset_id
                )
                if asset and os.path.exists(asset.file_path):
                    # Playwright 로컬 파일 경로 사용
                    abs_path = os.path.abspath(asset.file_path)
                    file_url = f"file:///{abs_path.replace('\\', '/')}"
                    img_html = f'<img class="section-image" src="{file_url}" alt="section image"/>'
            
            if sec.section_type == "header":
                sections_html.append(f"""
                <div class="section section-header" style="background-color: {theme_color};">
                    <h1 style="margin:0; font-size: 32px;">{sec.title or ''}</h1>
                    <p style="margin-top: 15px; font-size: 18px; line-height:1.6; white-space: pre-wrap;">{sec.body_copy or ''}</p>
                    {img_html}
                </div>
                """)
            else:
                sections_html.append(f"""
                <div class="section">
                    <div class="section-title" style="border-left: 5px solid {theme_color}; padding-left: 10px;">{sec.title or ''}</div>
                    <div class="section-body">{sec.body_copy or ''}</div>
                    {img_html}
                </div>
                """)
                
        sections_str = "\n".join(sections_html)
        
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    margin: 0;
    padding: 0;
    font-family: '{font_family}', sans-serif;
    background-color: #f9f9f9;
    color: #333;
    width: {width}px;
  }}
  .section {{
    padding: 40px 20px;
    border-bottom: 1px solid #eee;
    background-color: #fff;
    box-sizing: border-box;
    width: 100%;
  }}
  .section-header {{
    color: #fff;
    text-align: center;
    padding: 60px 20px;
  }}
  .section-title {{
    font-size: 24px;
    margin-bottom: 15px;
    font-weight: bold;
  }}
  .section-body {{
    font-size: 16px;
    line-height: 1.6;
    white-space: pre-wrap;
  }}
  .section-image {{
    max-width: 100%;
    height: auto;
    margin-top: 20px;
    display: block;
    margin-left: auto;
    margin-right: auto;
    border-radius: 8px;
  }}
</style>
</head>
<body>
  {sections_str}
</body>
</html>
"""
        return html

    def _render_with_playwright(self, html_content: str, width: int, output_path: str) -> bool:
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            # headless 브라우저 실행
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # viewport 가로폭 설정, 세로는 기본으로 충분히 크게 설정
            page.set_viewport_size({"width": width, "height": 800})
            
            # HTML 내용 로드
            page.set_content(html_content)
            
            # 이미지 렌더링 대기를 위해 잠시 대기
            page.wait_for_timeout(1000)
            
            # fullPage 캡처
            page.screenshot(path=output_path, full_page=True)
            browser.close()
            
        return os.path.exists(output_path)

    def _render_with_pillow_fallback(self, page: Any, width: int, output_path: str):
        """
        Generates a dummy high-resolution image using Pillow listing the text content of the page.
        Used as a fallback when Playwright is unavailable.
        """
        # 임의로 긴 세로 크기를 계산
        visible_sections = [sec for sec in page.sections if sec.is_visible]
        section_count = len(visible_sections)
        estimated_height = max(800, section_count * 400 + 200)
        
        # 가짜 이미지 생성
        image = Image.new("RGB", (width, estimated_height), "#F3F4F6")
        draw = ImageDraw.Draw(image)
        
        # 테마 컬러 및 디자인 구성
        theme_color = page.theme_color or "#3B82F6"
        
        # 심플하게 각 섹션을 텍스트 상자로 렌더링
        y_offset = 20
        
        # 헤더 텍스트 드로잉
        draw.rectangle([(10, y_offset), (width - 10, y_offset + 80)], fill=theme_color)
        draw.text((20, y_offset + 30), f"Mock Rendering: {page.project.name}", fill="#FFFFFF")
        y_offset += 120
        
        for idx, sec in enumerate(visible_sections):
            box_height = 200
            # 섹션 박스
            draw.rectangle([(10, y_offset), (width - 10, y_offset + box_height)], fill="#FFFFFF", outline="#E5E7EB")
            
            # 텍스트
            draw.text((20, y_offset + 15), f"Section {idx+1}: {sec.section_type}", fill="#4B5563")
            draw.text((20, y_offset + 40), f"Title: {sec.title or 'N/A'}", fill="#1F2937")
            
            # 본문 말줄임 처리
            body = (sec.body_copy or "")[:60] + "..." if len(sec.body_copy or "") > 60 else (sec.body_copy or "")
            draw.text((20, y_offset + 70), f"Body: {body}", fill="#6B7280")
            
            if sec.image_asset_id:
                draw.rectangle([(20, y_offset + 120), (120, y_offset + box_height - 20)], fill="#D1D5DB")
                draw.text((30, y_offset + 130), "[Image Asset]", fill="#4B5563")
                
            y_offset += box_height + 20
            
        # 저장
        image.save(output_path, "PNG")
        image.close()

    def _slice_image(self, full_image_path: str, max_height: int, job_id: str) -> List[str]:
        image = Image.open(full_image_path)
        img_width, img_height = image.size
        
        slice_paths = []
        num_slices = (img_height + max_height - 1) // max_height
        
        for i in range(num_slices):
            top = i * max_height
            bottom = min((i + 1) * max_height, img_height)
            
            # 잘라내기 영역
            box = (0, top, img_width, bottom)
            cropped_image = image.crop(box)
            
            slice_filename = f"slice_{job_id}_{i+1:02d}.png"
            slice_path = os.path.join(self.exports_dir, slice_filename)
            cropped_image.save(slice_path, "PNG")
            cropped_image.close()
            slice_paths.append(slice_path)

        image.close()
        return slice_paths
