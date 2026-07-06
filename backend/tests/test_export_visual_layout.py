from PIL import Image
from src.services.export_service import run_export


def test_run_export_creates_visual_detail_page_not_text_document():
    snapshot = {
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "visual_background": {"selected_background": "cooling-blue"},
        "sections": [
            {
                "key": "problem_statement",
                "title": "작은 불편이 쌓이면 일상이 번거로워집니다",
                "body": "더운 출근길과 야외 대기 시간, 손 안의 시원함이 필요한 순간을 짚어줍니다.",
            },
            {
                "key": "main_claim",
                "title": "일상의 불편을 덜어주는 실용적인 선택",
                "body": "휴대용 무선 팬으로 필요한 순간 간편하게 사용할 수 있습니다.",
            },
            {
                "key": "product_information",
                "title": "상품 정보",
                "body": "모델명은 FAN JET ULTRA입니다. KC 인증정보는 R-R-ONH-FANJETULTRA입니다.",
            },
        ],
    }

    result = run_export("project-visual-layout", "version-visual-layout", snapshot)

    with Image.open(result["long_vertical_image"]) as image:
        assert image.width >= 860
        assert image.height >= 1200
        top_pixel = image.getpixel((20, 20))
        assert top_pixel != (255, 255, 255)
