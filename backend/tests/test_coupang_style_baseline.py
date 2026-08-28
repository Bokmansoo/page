"""Compatibility filename retained; assertions cover the V2 baseline contract."""

from src.db.models import Asset, Brand, ExportJob, PageSection, ProductPage, ProductProject, User, Workspace
from src.services.commerce_story_baseline import inspect_commerce_story_baseline, list_baseline_products


def _project_page(db):
    user = User(id="baseline-user", email="baseline@example.com", name="Baseline")
    workspace = Workspace(id="baseline-workspace", name="Baseline", owner_id=user.id)
    brand = Brand(id="baseline-brand", workspace_id=workspace.id, name="Brand")
    project = ProductProject(id="baseline-project", workspace_id=workspace.id, brand_id=brand.id, name="Product")
    page = ProductPage(id="baseline-page", project_id=project.id)
    db.add_all([user, workspace, brand, project, page])
    db.commit()
    return project, page


def _asset(project_id, asset_id, source_type="self_shot", usage_status="seller_owned"):
    return Asset(id=asset_id, project_id=project_id, source_type=source_type, usage_status=usage_status,
                 filename=f"{asset_id}.jpg", file_path=f"{asset_id}.jpg", mime_type="image/jpeg",
                 file_size=100, quality_status="usable", quality_warnings=[])


def test_baseline_catalogue_is_v2_three_product_pack(client):
    response = client.get(
        "/api/v1/commerce-story-baselines",
        headers={
            "X-Mock-User-Id": "baseline-user",
            "X-Mock-Workspace-Id": "baseline-workspace",
        },
    )
    assert response.status_code == 200
    assert [product.key for product in list_baseline_products()] == [
        "yl-t02-massage-pillow", "roundlab-birch-moisture-cream", "locknlock-bisfree-container-set"
    ]
    assert response.json()[0]["key"] == "yl-t02-massage-pillow"


def test_baseline_records_jpg_and_blocks_reference_capture_in_output(db_session):
    project, page = _project_page(db_session)
    final_asset = _asset(project.id, "seller")
    supplier_asset = _asset(project.id, "supplier", "url-extracted", "reference_only")
    export_asset = _asset(project.id, "export", "exported_image", "blocked")
    db_session.add_all([
        final_asset, supplier_asset, export_asset,
        PageSection(id="hero", page_id=page.id, section_type="hero", image_asset_id=supplier_asset.id, sort_order=0),
        PageSection(id="spec", page_id=page.id, section_type="specifications", title="스펙", sort_order=1),
        ExportJob(id="job", project_id=project.id, preset_name="jpg", status="completed", created_by="baseline-user", output_images=[f"/api/v1/projects/{project.id}/page/export/download/{export_asset.id}"]),
    ])
    db_session.commit()
    report = inspect_commerce_story_baseline(db_session, page)
    assert report.completed_jpg_export is True
    assert "reference_only_asset_used" in {issue.code for issue in report.issues}
