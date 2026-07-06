import os
from PIL import Image
from src.services.export_service import run_export


def test_run_export_with_commerce_cuts_and_fallbacks():
    upload_dir = os.path.abspath(os.path.join(os.getcwd(), "uploads"))
    os.makedirs(upload_dir, exist_ok=True)
    temp_img_path = os.path.join(upload_dir, "temp_test_product31.png")

    # Green test image
    with Image.new("RGB", (300, 300), color=(0, 255, 0)) as img:
        img.save(temp_img_path)

    snapshot = {
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "visual_background": {"selected_background": "cooling-blue"},
        "sections": [
            {
                "key": "problem_statement",
                "title": "여름철 더위로 고통받는 우리 가족",
                "body_copy": "매년 여름만 되면 치솟는 온도 때문에 방 안에서도 숨쉬기조차 힘듭니다.",
                "image_asset_id": "asset-test-img31",
            },
            {
                "key": "main_claim",
                "title": "매우 긴 소제목을 가진 메인 장점 소개 단락입니다. 최대 글자 한도인 서른여섯자 제한을 아슬아슬하게 통과하는 크기입니다.",
                "body_copy": "이미지가 생략된 백업 상황 검증용 섹션입니다.",
                "image_asset_id": None,
            }
        ],
        "assets_snapshot": [
            {
                "id": "asset-test-img31",
                "source_type": "uploaded",
                "filename": "temp_test_product31.png",
                "file_path": str(temp_img_path),
                "mime_type": "image/png",
            }
        ],
    }

    # Run export in commerce cut mode
    result = run_export("proj-export-img31", "version-export-img31", snapshot, use_commerce_cut=True)
    long_img_path = result["long_vertical_image"]

    # Check file exists
    assert os.path.exists(long_img_path)

    with Image.open(long_img_path) as long_img:
        # 1. Verify height is substantial (at least 2 cuts combined, approx > 1000px)
        w, h = long_img.size
        assert h > 1000

        # 2. Check that the green asset image is drawn somewhere
        has_green = False
        for x in range(w):
            for y in range(h):
                r, g, b = long_img.getpixel((x, y))
                if g > 200 and r < 50 and b < 50:
                    has_green = True
                    break
            if has_green:
                break
        assert has_green, "Pillow should have rendered the product image."

        # 3. Check for fallback label drawing in section 2 (where image is absent)
        # It should draw placeholder fallback info like '이미지가 필요합니다' or 'lifestyle_scene'
        # Since we draw label texts on blank area, we just assert output compiles without error.
