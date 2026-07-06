try:
    from src.services.export_service import build_export_manifest, normalize_sections_snapshot, run_export, load_export_font
except ImportError:
    from backend.src.services.export_service import build_export_manifest, normalize_sections_snapshot, run_export, load_export_font

from src.db.models import Brand, ProductProject, User, Workspace


def test_build_export_manifest_for_long_image_and_section_zip():
    manifest = build_export_manifest(
        project_id="project-1",
        version_id="version-1",
        sections=[
            {"key": "problem_statement", "title": "고객의 고민", "body": "더운 날 외출이 번거롭습니다."},
            {"key": "product_information", "title": "상품 정보", "body": "4,800mAh 배터리입니다."},
        ],
    )

    assert manifest["project_id"] == "project-1"
    assert manifest["version_id"] == "version-1"
    assert manifest["outputs"] == ["long_vertical_image", "section_images_zip"]
    assert len(manifest["sections"]) == 2


def test_normalizes_detail_page_version_snapshot_dict():
    snapshot = {
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "sections": [
            {"key": "problem_statement", "title": "고객의 고민", "body": "작은 불편을 줄입니다."},
        ],
    }

    sections = normalize_sections_snapshot(snapshot)

    assert sections == snapshot["sections"]


def test_run_export_accepts_detail_page_version_snapshot_dict():
    snapshot = {
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "sections": [
            {"key": "problem_statement", "title": "고객의 고민", "body": "작은 불편을 줄입니다."},
            {"key": "product_information", "title": "상품 정보", "body": "4,800mAh 배터리입니다."},
        ],
    }

    result = run_export("project-1", "version-1", snapshot)

    assert result["long_vertical_image"].endswith("_long.png")
    assert result["section_images_zip"].endswith("_sections.zip")


def test_load_export_font_supports_korean_text():
    font = load_export_font(24)

    bbox = font.getbbox("루메나 휴대용 무선 냉각선풍기")

    assert bbox[2] > bbox[0]
    assert bbox[3] > bbox[1]


def test_run_export_creates_readable_mobile_width_image_for_korean_content():
    snapshot = {
        "theme_color": "#3B82F6",
        "font_family": "sans-serif",
        "sections": [
            {
                "key": "problem_statement",
                "title": "작은 불편이 쌓이면 일상이 번거로워집니다",
                "body": "루메나 휴대용 무선 냉각선풍기는 외출과 실내 사용 환경에서 확인된 상품 정보를 바탕으로 시원한 사용 경험을 제안합니다.",
            },
            {
                "key": "product_information",
                "title": "상품 정보",
                "body": "KC 인증정보와 모델명 FAN JET ULTRA를 확인했습니다.",
            },
        ],
    }

    result = run_export("project-ko", "version-ko", snapshot)

    from PIL import Image

    with Image.open(result["long_vertical_image"]) as image:
        assert image.width >= 720
        assert image.height > 500


def test_run_export_passes_selected_style_to_visual_renderer(db_session, monkeypatch):
    captured = {}

    def fake_build_visual_sections(**kwargs):
        captured.update(kwargs)
        return [
            {
                "key": "problem_statement",
                "layout": "hero",
                "eyebrow": "PROBLEM_STATEMENT",
                "headline": "Style-aware export",
                "subcopy": "Selected style should reach PNG visual rendering.",
                "visual_slot": {"kind": "placeholder", "fallback_label": "placeholder"},
                "proofs": [],
                "style": {
                    "style_key": kwargs.get("selected_style") or "default",
                    "background_tone": "warm_neutral",
                },
            }
        ]

    monkeypatch.setattr(
        "src.services.visual_page_renderer.build_visual_sections",
        fake_build_visual_sections,
    )

    user = User(email="sprint37-export@example.com", name="Sprint 37")
    db_session.add(user)
    db_session.flush()
    workspace = Workspace(name="Sprint 37 Workspace", owner_id=user.id)
    db_session.add(workspace)
    db_session.flush()
    brand = Brand(workspace_id=workspace.id, name="Sprint 37 Brand")
    db_session.add(brand)
    db_session.flush()
    project = ProductProject(
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Style Project",
        category="Living",
        selected_style="lifestyle",
    )
    db_session.add(project)
    db_session.commit()

    run_export(
        project.id,
        "version-style",
        [{"key": "problem_statement", "title": "Title", "body": "Body"}],
        db=db_session,
    )

    assert captured["selected_style"] == "lifestyle"


def test_run_export_supports_jpg_output():
    from PIL import Image
    import zipfile

    snapshot = {
        "sections": [
            {
                "key": "hero",
                "title": "Portable cooling",
                "body": "A compact fan for everyday use.",
            }
        ]
    }

    result = run_export(
        "project-jpg",
        "version-jpg",
        snapshot,
        output_format="jpg",
    )

    assert result["long_vertical_image"].endswith("_long.jpg")
    with Image.open(result["long_vertical_image"]) as image:
        assert image.format == "JPEG"

    with zipfile.ZipFile(result["section_images_zip"]) as archive:
        assert archive.namelist() == ["01-hero.jpg"]
