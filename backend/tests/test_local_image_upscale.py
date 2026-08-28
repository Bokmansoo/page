from pathlib import Path

from PIL import Image

from src.api.auth import DEFAULT_BRAND_ID
from src.config import settings
from src.db.models import Asset, PageSection, ProductPage
from src.services.page_readiness_service import inspect_page_readiness


HEADERS = {
    "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
    "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
}


def test_low_resolution_photo_can_be_compared_and_applied_as_local_upscale(
    client, db_session, tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "enhanced"))
    created = client.post(
        "/api/v1/projects",
        json={"name": "Upscale product", "brand_id": DEFAULT_BRAND_ID},
        headers=HEADERS,
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    source_path = tmp_path / "product-main.jpg"
    Image.new("RGB", (300, 300), color=(235, 235, 235)).save(source_path, quality=92)
    source = Asset(
        id="upscale-source",
        project_id=project_id,
        source_type="uploaded",
        filename="product-main.jpg",
        file_path=str(source_path),
        mime_type="image/jpeg",
        file_size=source_path.stat().st_size,
        asset_role="product_main",
        role_confidence=1.0,
        role_source="manual",
        quality_status="warning",
        quality_warnings=["LOW_RESOLUTION"],
        width=300,
        height=300,
        safe_crop_status="safe",
        is_representative=True,
        representative_source="manual",
        classification_version=2,
    )
    generated = Asset(
        id="upscale-generated-child",
        project_id=project_id,
        source_type="ai-generated",
        filename="generated.png",
        file_path=str(source_path),
        mime_type="image/png",
        file_size=source_path.stat().st_size,
        source_asset_id=source.id,
        quality_status="warning",
        quality_warnings=["LOW_RESOLUTION"],
        width=512,
        height=512,
        classification_version=2,
    )
    page = ProductPage(id="upscale-page", project_id=project_id)
    hero = PageSection(
        id="upscale-hero",
        page_id=page.id,
        section_type="hero",
        title="고화질 상품",
        body_copy="선명한 대표 이미지",
        image_asset_id=generated.id,
        visual_kind="image",
        visual_payload={"layout_variant": "hero_overlay"},
        sort_order=0,
    )
    db_session.add_all([source, generated, page, hero])
    db_session.commit()

    preview_response = client.post(
        f"/api/v1/files/assets/{source.id}/upscale",
        headers=HEADERS,
    )
    assert preview_response.status_code == 201
    preview = preview_response.json()
    assert preview["source_type"] == "local_upscaled"
    assert preview["source_asset_id"] == source.id
    assert preview["width"] == 1200
    assert preview["height"] == 1200
    assert "LOW_RESOLUTION" not in preview["quality_warnings"]
    assert source_path.exists(), "The source photo must remain untouched"

    apply_response = client.post(
        f"/api/v1/files/assets/{preview['id']}/upscale/apply",
        headers=HEADERS,
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["is_representative"] is True

    db_session.refresh(hero)
    enhanced = db_session.query(Asset).filter(Asset.id == preview["id"]).one()
    assert hero.image_asset_id == enhanced.id
    assert hero.visual_kind == "image"
    assert hero.visual_payload == {"layout_variant": "hero_overlay"}
    readiness = inspect_page_readiness(page, db_session)
    assert not any(issue.code == "hero_asset_quality_blocking" for issue in readiness.blockers)
