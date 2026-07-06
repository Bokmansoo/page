import os
import uuid
from PIL import Image
from src.services.export_service import run_export


def test_run_export_draws_real_image_fit_into_slots():
    # 1. Prepare temp image file to simulate uploaded asset
    upload_dir = os.path.abspath(os.path.join(os.getcwd(), "uploads", "test-assets"))
    os.makedirs(upload_dir, exist_ok=True)
    filename = f"temp_test_product_{uuid.uuid4().hex}.png"
    temp_img_path = os.path.join(upload_dir, filename)

    img = Image.new("RGB", (300, 300), color=(0, 255, 0))  # Bright Green Image
    try:
        img.save(temp_img_path)
    finally:
        img.close()

    snapshot = {
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "visual_background": {"selected_background": "cooling-blue"},
        "sections": [
            {
                "key": "problem_statement",
                "title": "문제 제기",
                "body": "불편함을 짚어줍니다.",
            },
            {
                "key": "main_claim",
                "title": "일상의 불편을 덜어주는 실용적인 선택",
                "body": "테스트용 상품 설명 문구입니다.",
                "image_asset_id": "asset-test-img",
            }
        ],
        "assets_snapshot": [
                {
                    "id": "asset-test-img",
                    "source_type": "uploaded",
                    "filename": filename,
                    "file_path": temp_img_path,
                    "mime_type": "image/png",
                }
            ],
        }

    try:
        result = run_export("proj-export-img", "version-export-img", snapshot)
        long_img_path = result["long_vertical_image"]

        # 2. Check if the long image actually contains green pixels from the loaded asset
        with Image.open(long_img_path) as long_img:
            has_green = False
            w, h = long_img.size
            for x in range(w):
                for y in range(h):
                    r, g, b = long_img.getpixel((x, y))
                    if g > 200 and r < 50 and b < 50:  # Green-ish pixel
                        has_green = True
                        break
                if has_green:
                    break
            assert has_green, "Pillow should have rendered the uploaded green image."
    finally:
        # The managed Windows test sandbox can deny Python-level deletion of
        # newly written files. Use unique filenames so repeated runs remain
        # isolated even if the sandbox leaves the file in place.
        pass
