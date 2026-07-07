from PIL import Image

from src.config import settings
from src.db.models import Asset, Brand, ProductProject, User, Workspace
from src.services.product_cutout_service import ProductCutoutService


def test_generate_cutout_creates_transparent_png_with_source_metadata(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))

    user = User(id="cutout-user", email="cutout@example.com", name="Cutout User")
    workspace = Workspace(id="cutout-workspace", name="Cutout Workspace", owner_id=user.id)
    brand = Brand(id="cutout-brand", workspace_id=workspace.id, name="Cutout Brand")
    project = ProductProject(
        id="cutout-project",
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Portable fan",
        category="living",
        raw_input_text="handheld fan",
    )

    source_path = tmp_path / "source.png"
    image = Image.new("RGB", (4, 4), "white")
    image.putpixel((1, 1), (10, 20, 30))
    image.save(source_path)

    source_asset = Asset(
        id="source-asset",
        project_id=project.id,
        source_type="self_shot",
        filename="source.png",
        file_path=str(source_path),
        mime_type="image/png",
        file_size=source_path.stat().st_size,
    )
    db_session.add_all([user, workspace, brand, project, source_asset])
    db_session.commit()

    cutout = ProductCutoutService(db_session).generate_cutout(source_asset.id)

    assert cutout.project_id == project.id
    assert cutout.source_type == "ai_corrected"
    assert cutout.source_asset_id == source_asset.id
    assert cutout.cutout_status == "completed"
    assert cutout.background_removed is True
    assert cutout.product_identity_preserved is True
    assert cutout.mime_type == "image/png"

    with Image.open(cutout.file_path) as output:
        assert output.mode == "RGBA"
        assert output.getpixel((0, 0))[3] == 0
        assert output.getpixel((1, 1))[3] == 255
