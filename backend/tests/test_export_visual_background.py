from PIL import Image

from src.db.models import ProductProject
from src.services.export_service import run_export


def test_run_export_uses_selected_project_background_palette(db_session):
    project = ProductProject(
        id="project-bg-cooling",
        workspace_id="workspace-bg",
        brand_id="brand-bg",
        name="루메나 휴대용 무선 냉각선풍기",
        category="Living",
        selected_background="cooling-blue",
    )
    db_session.add(project)
    db_session.commit()

    snapshot = {
        "sections": [
            {
                "key": "problem_statement",
                "title": "작은 불편이 쌓이면 일상이 번거로워집니다",
                "body": "루메나 휴대용 무선 냉각선풍기는 시원한 사용 경험을 제안합니다.",
            },
            {
                "key": "product_information",
                "title": "상품 정보",
                "body": "모델명은 FAN JET ULTRA입니다.",
            },
        ],
    }

    result = run_export("project-bg-cooling", "version-bg-cooling", snapshot, db=db_session)

    with Image.open(result["long_vertical_image"]) as image:
        assert image.width >= 720
        # cooling-blue starts with #EAF4FF. The top hero should use that
        # palette instead of a plain white document background.
        pixel = image.getpixel((10, 10))
        assert 225 <= pixel[0] <= 240
        assert 235 <= pixel[1] <= 250
        assert pixel[2] == 255
        assert pixel != (255, 255, 255)
