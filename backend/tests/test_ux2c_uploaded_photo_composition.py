from src.db.models import AgentRun, Asset, DetailPageVersion, ProductPage
from src.agents.mock_outputs import build_mock_page_assembly
from src.services.agent_run_service import AgentRunService
from src.services.commerce_content_quality_service import inspect_content_quality
from PIL import Image


def _auth_headers():
    return {
        "X-Mock-User-Id": "00000000-0000-0000-0000-000000000001",
        "X-Mock-Workspace-Id": "00000000-0000-0000-0000-000000000002",
    }


def _create_mock_page(client, db_session):
    created = client.post(
        "/api/agent-runs",
        headers=_auth_headers(),
        json={"product_name": "Neck massage pillow", "ux_auto_generate": True},
    ).json()
    assert client.post(
        f"/api/agent-runs/{created['id']}/run-mock", headers=_auth_headers()
    ).status_code == 200
    page = db_session.query(ProductPage).filter(
        ProductPage.project_id == created["project_id"]
    ).one()
    return created["project_id"], page


def _page_update_payload(page, *, hero_asset_id, hero_visual_kind="image", hero_payload=None):
    return {
        "theme_color": page.theme_color,
        "font_family": page.font_family,
        "sections": [
            {
                "id": section.id,
                "title": section.title,
                "body_copy": section.body_copy,
                "image_asset_id": hero_asset_id if section.section_type == "hero" else section.image_asset_id,
                "visual_kind": hero_visual_kind if section.section_type == "hero" else section.visual_kind,
                "visual_payload": hero_payload if section.section_type == "hero" else section.visual_payload,
                "sort_order": section.sort_order,
                "is_visible": section.is_visible,
            }
            for section in page.sections
        ],
    }


def test_ux2c_auto_placement_uses_each_eligible_photo_once_and_excludes_reference():
    assembly = build_mock_page_assembly(
        "Neck massage pillow",
        uploaded_assets=[
            {"id": "owned-main", "filename": "main.jpg", "source_type": "uploaded", "usage_status": "seller_owned"},
            {"id": "reference", "filename": "supplier.jpg", "source_type": "sourced", "usage_status": "reference_only"},
        ],
    )
    selected = [section["image_id"] for section in assembly["sections"] if section["image_id"]]
    assert selected == ["owned-main"]


def test_ux2c_auto_placement_uses_roles_for_four_distinct_photos():
    assembly = build_mock_page_assembly(
        "Neck massage pillow",
        uploaded_assets=[
            {"id": "components", "filename": "box.jpg", "mime_type": "image/jpeg", "source_type": "uploaded", "usage_status": "seller_owned", "asset_role": "components"},
            {"id": "usage", "filename": "using.jpg", "mime_type": "image/jpeg", "source_type": "uploaded", "usage_status": "seller_owned", "asset_role": "usage_scene"},
            {"id": "detail", "filename": "heat.jpg", "mime_type": "image/jpeg", "source_type": "uploaded", "usage_status": "seller_owned", "asset_role": "feature"},
            {"id": "main", "filename": "main.jpg", "mime_type": "image/jpeg", "source_type": "uploaded", "usage_status": "seller_owned", "asset_role": "product_main", "is_representative": True},
        ],
    )
    selected = {section["section_type"]: section["image_id"] for section in assembly["sections"]}
    assert selected["hero"] == "main"
    assert selected["feature_1"] == "detail"
    assert selected["usage_guide"] == "usage"
    assert selected["details_components"] == "components"
    assert len({asset_id for asset_id in selected.values() if asset_id}) == 4


def test_ux2d1_mock_automatic_placement_excludes_ocr_risk_and_duplicate_hashes():
    assembly = build_mock_page_assembly(
        "Neck massage pillow",
        uploaded_assets=[
            {
                "id": "safe-main",
                "filename": "main.jpg",
                "source_type": "uploaded",
                "usage_status": "seller_owned",
                "content_hash": "same-image",
                "asset_role": "product_main",
            },
            {
                "id": "safe-copy",
                "filename": "main-copy.jpg",
                "source_type": "uploaded",
                "usage_status": "seller_owned",
                "content_hash": "same-image",
                "asset_role": "product_main",
            },
            {
                "id": "supplier-text",
                "filename": "supplier-shot.jpg",
                "source_type": "uploaded",
                "usage_status": "seller_owned",
                "ocr_text": "产品参数 批发价格",
                "asset_role": "feature",
            },
        ],
    )
    selected = [section["image_id"] for section in assembly["sections"] if section["image_id"]]

    assert selected == ["safe-main"]
    assert all(image_id != "supplier-text" for image_id in selected)
    replacements = [section.get("ux2d1_auto_replacement") for section in assembly["sections"]]
    assert any(
        replacement and "foreign_text_exposed" in replacement["reason_codes"]
        for replacement in replacements
    )


def test_ux2d1_duplicate_copy_records_the_exact_information_replacement_reason():
    assembly = build_mock_page_assembly(
        "Neck massage pillow",
        uploaded_assets=[
            {
                "id": "original",
                "filename": "main.jpg",
                "source_type": "uploaded",
                "usage_status": "seller_owned",
                "content_hash": "same-image",
            },
            {
                "id": "copy",
                "filename": "main-copy.jpg",
                "source_type": "uploaded",
                "usage_status": "seller_owned",
                "content_hash": "same-image",
            },
        ],
    )
    by_type = {section["section_type"]: section for section in assembly["sections"]}

    assert by_type["hero"]["image_id"] == "original"
    assert by_type["feature_1"]["image_id"] is None
    assert by_type["feature_1"]["ux2d1_auto_replacement"] == {
        "strategy": "html_information",
        "reason_codes": ["duplicate_asset_group"],
    }
    assert "ux2d1_auto_replacement" not in by_type["pain_point"]


def test_ux2d1_seven_input_photos_auto_place_only_safe_unique_assets():
    """A typical 7-photo upload must not leak risky/duplicate supplier assets."""
    assembly = build_mock_page_assembly(
        "Neck massage pillow",
        uploaded_assets=[
            {"id": "main", "filename": "main.jpg", "source_type": "uploaded", "usage_status": "seller_owned", "content_hash": "main", "asset_role": "product_main"},
            {"id": "feature", "filename": "feature.jpg", "source_type": "uploaded", "usage_status": "seller_owned", "content_hash": "feature", "asset_role": "feature"},
            {"id": "usage", "filename": "usage.jpg", "source_type": "uploaded", "usage_status": "seller_owned", "content_hash": "usage", "asset_role": "usage_scene"},
            {"id": "components", "filename": "components.jpg", "source_type": "uploaded", "usage_status": "seller_owned", "content_hash": "components", "asset_role": "components"},
            {"id": "supplier", "filename": "supplier.jpg", "source_type": "uploaded", "usage_status": "seller_owned", "content_hash": "supplier", "ocr_text": "Supplier call 010-1234-5678", "asset_role": "feature"},
            {"id": "market", "filename": "market.jpg", "source_type": "uploaded", "usage_status": "seller_owned", "content_hash": "market", "ocr_text": "쿠팡 19,900원", "asset_role": "feature"},
            {"id": "main-copy", "filename": "main-copy.jpg", "source_type": "uploaded", "usage_status": "seller_owned", "content_hash": "main", "asset_role": "product_main"},
        ],
    )

    selected = [section["image_id"] for section in assembly["sections"] if section["image_id"]]
    assert set(selected) == {"main", "feature", "usage", "components"}
    assert len(selected) == len(set(selected))
    assert not {"supplier", "market", "main-copy"}.intersection(selected)


def test_ux2d1_persisted_page_uses_information_layout_for_ocr_risk_photo(client, db_session):
    created = client.post(
        "/api/agent-runs",
        headers=_auth_headers(),
        json={"product_name": "Neck massage pillow", "ux_auto_generate": True},
    ).json()
    safe = Asset(
        project_id=created["project_id"],
        source_type="uploaded",
        usage_status="seller_owned",
        filename="main.jpg",
        file_path="/tmp/main.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="product_main",
        identity_status="confirmed",
        is_representative=True,
    )
    risky = Asset(
        project_id=created["project_id"],
        source_type="uploaded",
        usage_status="seller_owned",
        filename="supplier-shot.jpg",
        file_path="/tmp/supplier-shot.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="feature",
        identity_status="confirmed",
        ocr_text="产品参数 批发价格",
    )
    db_session.add_all([safe, risky])
    db_session.commit()

    response = client.post(
        f"/api/agent-runs/{created['id']}/run-mock", headers=_auth_headers()
    )
    assert response.status_code == 200, response.text

    db_session.expire_all()
    page = db_session.query(ProductPage).filter(
        ProductPage.project_id == created["project_id"]
    ).one()
    assert all(section.image_asset_id != risky.id for section in page.sections)
    assert any(
        (section.visual_payload or {}).get("ux2d1_auto_replacement")
        for section in page.sections
    )
    report = inspect_content_quality(page, db_session)
    assert any(
        issue["code"] == "auto_replaced_with_information"
        for issue in report["recommendations"]
    )
    generated_version = db_session.query(DetailPageVersion).filter(
        DetailPageVersion.project_id == created["project_id"],
        DetailPageVersion.name == "AI 생성 상세페이지",
    ).one()
    assert any(
        (section.get("visual_payload") or {}).get("ux2d1_auto_replacement")
        for section in generated_version.sections_json
    )


def test_ux2c_lists_eligible_and_reference_photos_with_permission_state(client, db_session):
    project_id, _ = _create_mock_page(client, db_session)
    owned = Asset(
        project_id=project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename="pillow-main.jpg",
        file_path="/tmp/pillow-main.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="product_main",
        identity_status="confirmed",
        is_representative=True,
    )
    reference = Asset(
        project_id=project_id,
        source_type="sourced",
        usage_status="reference_only",
        filename="supplier-reference.jpg",
        file_path="/tmp/supplier-reference.jpg",
        mime_type="image/jpeg",
        file_size=10,
    )
    db_session.add_all([owned, reference])
    db_session.commit()

    response = client.get(f"/api/v1/projects/{project_id}/page", headers=_auth_headers())
    assert response.status_code == 200
    hero = next(section for section in response.json()["sections"] if section["section_type"] == "hero")
    candidates = {candidate["asset_id"]: candidate for candidate in hero["image_candidates"]}
    assert candidates[owned.id]["eligible"] is True
    assert candidates[owned.id]["is_recommended"] is True
    assert candidates[reference.id]["eligible"] is False
    assert candidates[reference.id]["usage_status"] == "reference_only"
    assert candidates[reference.id]["block_reason"]


def test_ux2c_requires_permission_then_persists_photo_and_text_layout(client, db_session):
    project_id, page = _create_mock_page(client, db_session)
    reference = Asset(
        project_id=project_id,
        source_type="sourced",
        usage_status="reference_only",
        filename="seller-approved-pillow.jpg",
        file_path="/tmp/seller-approved-pillow.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="product_main",
        identity_status="confirmed",
    )
    db_session.add(reference)
    db_session.commit()

    blocked = client.patch(
        f"/api/v1/projects/{project_id}/page",
        headers=_auth_headers(),
        json=_page_update_payload(page, hero_asset_id=reference.id),
    )
    assert blocked.status_code == 422

    approved = client.patch(
        f"/api/v1/files/assets/{reference.id}/usage-status",
        headers=_auth_headers(),
        json={"usage_status": "seller_owned"},
    )
    assert approved.status_code == 200

    selected = client.patch(
        f"/api/v1/projects/{project_id}/page",
        headers=_auth_headers(),
        json=_page_update_payload(page, hero_asset_id=reference.id),
    )
    assert selected.status_code == 200, selected.text
    assert next(item for item in selected.json()["sections"] if item["section_type"] == "hero")["image_asset_id"] == reference.id

    selected_version = db_session.query(DetailPageVersion).filter(
        DetailPageVersion.project_id == project_id
    ).order_by(DetailPageVersion.created_at.desc()).first()
    assert selected_version.sections_json["sections"][0]["image_asset_id"] == reference.id

    db_session.expire_all()
    current_page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).one()
    text_layout = client.patch(
        f"/api/v1/projects/{project_id}/page",
        headers=_auth_headers(),
        json=_page_update_payload(
            current_page,
            hero_asset_id=None,
            hero_visual_kind="html_graphic",
            hero_payload={"layout_variant": "image_text", "mock_safe_hero": True},
        ),
    )
    assert text_layout.status_code == 200
    hero = next(item for item in text_layout.json()["sections"] if item["section_type"] == "hero")
    assert hero["image_asset_id"] is None
    assert hero["visual_kind"] == "html_graphic"

    restored = client.post(
        f"/api/v1/projects/{project_id}/page/versions/{selected_version.id}/restore",
        headers=_auth_headers(),
    )
    assert restored.status_code == 200
    restored_hero = next(item for item in restored.json()["sections"] if item["section_type"] == "hero")
    assert restored_hero["image_asset_id"] == reference.id


def test_ux2c_rematerialization_preserves_manual_photo_visibility_fit_and_order(client, db_session):
    project_id, page = _create_mock_page(client, db_session)
    owned = Asset(
        project_id=project_id,
        source_type="uploaded",
        usage_status="seller_owned",
        filename="manual-main.jpg",
        file_path="/tmp/manual-main.jpg",
        mime_type="image/jpeg",
        file_size=10,
        asset_role="product_main",
        identity_status="confirmed",
    )
    db_session.add(owned)
    db_session.commit()

    payload = _page_update_payload(
        page,
        hero_asset_id=owned.id,
        hero_payload={"layout_variant": "image_text", "image_fit": "cover"},
    )
    for section in payload["sections"]:
        if section["id"] == next(item.id for item in page.sections if item.section_type == "hero"):
            section["sort_order"] = 1
        elif section["id"] == next(item.id for item in page.sections if item.section_type == "pain_point"):
            section["sort_order"] = 0
        elif section["id"] == next(item.id for item in page.sections if item.section_type == "feature_1"):
            section["is_visible"] = False
    saved = client.patch(
        f"/api/v1/projects/{project_id}/page",
        headers=_auth_headers(),
        json=payload,
    )
    assert saved.status_code == 200, saved.text

    run = db_session.query(AgentRun).filter(AgentRun.project_id == project_id).one()
    AgentRunService._materialize_page_from_outputs(run, db_session)
    db_session.commit()
    db_session.expire_all()

    rematerialized = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).one()
    by_type = {section.section_type: section for section in rematerialized.sections}
    assert by_type["hero"].image_asset_id == owned.id
    assert by_type["hero"].visual_kind == "image"
    assert by_type["hero"].visual_payload["image_fit"] == "cover"
    assert by_type["hero"].visual_payload["ux2c_selection_state"] == "manual_image"
    assert by_type["pain_point"].sort_order < by_type["hero"].sort_order
    assert by_type["feature_1"].is_visible is False
    assert by_type["product_information"].sort_order == max(
        section.sort_order for section in rematerialized.sections
    )


def test_ux2d1_manual_copy_prevents_same_hash_automatic_image_on_regeneration(client, db_session, tmp_path):
    created = client.post(
        "/api/agent-runs",
        headers=_auth_headers(),
        json={"product_name": "Neck massage pillow", "ux_auto_generate": True},
    ).json()
    original_path = tmp_path / "original.jpg"
    copy_path = tmp_path / "manual-copy.jpg"
    Image.new("RGB", (1200, 1200), "gray").save(original_path)
    Image.new("RGB", (1200, 1200), "gray").save(copy_path)
    original = Asset(
        project_id=created["project_id"], source_type="uploaded", usage_status="seller_owned",
        filename="original.jpg", file_path=str(original_path), mime_type="image/jpeg", file_size=original_path.stat().st_size,
        asset_role="product_main", identity_status="confirmed", content_hash="same-image",
    )
    manual_copy = Asset(
        project_id=created["project_id"], source_type="uploaded", usage_status="seller_owned",
        filename="manual-copy.jpg", file_path=str(copy_path), mime_type="image/jpeg", file_size=copy_path.stat().st_size,
        asset_role="feature", identity_status="confirmed", content_hash="same-image",
    )
    db_session.add_all([original, manual_copy])
    db_session.commit()
    assert client.post(
        f"/api/agent-runs/{created['id']}/run-mock", headers=_auth_headers()
    ).status_code == 200

    page = db_session.query(ProductPage).filter_by(project_id=created["project_id"]).one()
    feature = next(section for section in page.sections if section.section_type == "feature_1")
    feature.image_asset_id = manual_copy.id
    feature.visual_kind = "image"
    feature.visual_payload = {"layout_variant": "image_text", "ux2c_selection_state": "manual_image"}
    db_session.commit()

    run = db_session.query(AgentRun).filter_by(project_id=created["project_id"]).one()
    AgentRunService._materialize_page_from_outputs(run, db_session)
    db_session.commit()
    db_session.expire_all()

    rematerialized = db_session.query(ProductPage).filter_by(project_id=created["project_id"]).one()
    by_type = {section.section_type: section for section in rematerialized.sections}
    assert by_type["feature_1"].image_asset_id == manual_copy.id
    assert by_type["hero"].image_asset_id is None
    assert by_type["hero"].visual_payload["ux2d1_auto_replacement"]["reason_codes"] == ["duplicate_asset_group"]
