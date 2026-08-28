from PIL import Image

from src.db.models import Asset, PageSection, ProductPage, ProductProject
from src.services.hero_composition import build_composed_product_payload
from src.services.page_visual_contract import normalize_visual, validate_visual
from src.services.visual_contract_backfill import backfill_page_visuals


def _asset(**overrides):
    values = {
        "id": "hero-asset",
        "project_id": "hero-composition-project",
        "source_type": "uploaded",
        "filename": "product-main.jpg",
        "file_path": "https://example.com/product-main.jpg",
        "mime_type": "image/jpeg",
        "file_size": 1024,
        "asset_role": "product_main",
        "quality_status": "usable",
        "quality_warnings": [],
        "safe_crop_status": "safe",
        "is_representative": True,
        "classification_version": 2,
    }
    values.update(overrides)
    return Asset(**values)


def test_composed_product_is_a_complete_visual_contract():
    visual = normalize_visual(
        section_type="hero",
        image_asset_id="hero-asset",
        visual_kind="composed_product",
        visual_payload=build_composed_product_payload(_asset()),
    )

    assert validate_visual(visual) == []
    assert visual["visual_payload"]["product_fit"] == "contain"
    assert visual["visual_payload"]["text_safe_area"] == "left"


def test_composed_product_contract_rejects_incomplete_design_tokens():
    visual = normalize_visual(
        section_type="hero",
        image_asset_id="hero-asset",
        visual_kind="composed_product",
        visual_payload={
            "layout_variant": "hero_product_right",
            "product_fit": "cover",
            "text_safe_area": "overlay",
            "background_token": "unknown_surface",
        },
    )

    issues = validate_visual(visual)
    assert "invalid_product_fit" in issues
    assert "invalid_text_safe_area" in issues
    assert "invalid_background_token" in issues
    assert "decoration_tokens_required" in issues


def test_narrow_photo_uses_center_bottom_safe_area_and_bad_quality_is_not_composed():
    narrow = build_composed_product_payload(_asset(safe_crop_status="needs_review"))
    blocked = build_composed_product_payload(_asset(quality_warnings=["LOW_RESOLUTION"]))

    assert narrow["layout_variant"] == "hero_product_center"
    assert narrow["text_safe_area"] == "bottom"
    assert blocked is None


def test_unconfirmed_or_non_product_photo_is_not_composed():
    unconfirmed = build_composed_product_payload(_asset(is_representative=False))
    package_photo = build_composed_product_payload(_asset(asset_role="package"))

    assert unconfirmed is None
    assert package_photo is None


def test_legacy_default_hero_is_upgraded_but_custom_image_layout_is_preserved(db_session):
    project = ProductProject(
        id="hero-composition-project",
        workspace_id="ws-1",
        brand_id="brand-1",
        name="HERO composition product",
        status="draft",
    )
    page = ProductPage(id="hero-composition-page", project_id=project.id)
    hero = PageSection(
        id="hero-composition-section",
        page_id=page.id,
        section_type="hero",
        image_asset_id="hero-asset",
        visual_kind="image",
        visual_payload={"layout_variant": "hero_overlay"},
        sort_order=0,
    )
    custom = PageSection(
        id="custom-image-section",
        page_id=page.id,
        section_type="detail_1",
        image_asset_id="hero-asset",
        visual_kind="image",
        visual_payload={"layout_variant": "image_text"},
        sort_order=1,
    )
    db_session.add_all([project, page, _asset(), hero, custom])
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)

    db_session.refresh(hero)
    db_session.refresh(custom)
    assert report.updated == 1
    assert hero.visual_kind == "composed_product"
    assert hero.visual_payload["layout_variant"] == "hero_product_right"
    assert custom.visual_kind == "image"
    assert custom.visual_payload["layout_variant"] == "image_text"


def test_legacy_page_classifies_asset_before_first_hero_upgrade(db_session, tmp_path):
    image_path = tmp_path / "product-main-front.png"
    Image.new("RGB", (1200, 1200), color="white").save(image_path)
    project = ProductProject(
        id="first-load-project",
        workspace_id="ws-1",
        brand_id="brand-1",
        name="First load product",
        status="draft",
    )
    page = ProductPage(id="first-load-page", project_id=project.id)
    asset = Asset(
        id="first-load-asset",
        project_id=project.id,
        source_type="uploaded",
        filename="product-main-front.png",
        file_path=str(image_path),
        mime_type="image/png",
        file_size=image_path.stat().st_size,
    )
    hero = PageSection(
        id="first-load-hero",
        page_id=page.id,
        section_type="hero",
        image_asset_id=asset.id,
        visual_kind="image",
        visual_payload={"layout_variant": "hero_overlay"},
        sort_order=0,
    )
    db_session.add_all([project, page, asset, hero])
    db_session.commit()

    report = backfill_page_visuals(db_session, project.id)

    db_session.refresh(asset)
    db_session.refresh(hero)
    assert report.updated == 1
    assert asset.classification_version == 2
    assert asset.is_representative is True
    assert hero.visual_kind == "composed_product"
