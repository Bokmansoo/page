from src.db.models import Asset, Brand, PageSection, ProductFact, ProductPage, ProductProject, User, Workspace
from src.services.commerce_policy import final_spec_is_last, initial_asset_usage_status, resolved_asset_usage_status
from src.services.commerce_story_baseline import EVALUATION_ITEMS, inspect_commerce_story_baseline, list_baseline_products
from src.services.page_asset_policy import get_page_eligible_assets
from src.services.page_readiness_service import inspect_page_readiness


def _project_page(db):
    user = User(id="v2-user", email="v2@example.com", name="V2")
    workspace = Workspace(id="v2-workspace", name="V2", owner_id=user.id)
    brand = Brand(id="v2-brand", workspace_id=workspace.id, name="V2 Brand")
    project = ProductProject(id="v2-project", workspace_id=workspace.id, brand_id=brand.id, name="V2 product")
    page = ProductPage(id="v2-page", project_id=project.id)
    db.add_all([user, workspace, brand, project, page])
    db.commit()
    return project, page


def _asset(project_id, asset_id, source_type, usage_status="unknown"):
    return Asset(
        id=asset_id,
        project_id=project_id,
        source_type=source_type,
        usage_status=usage_status,
        filename=f"{asset_id}.jpg",
        file_path=f"{asset_id}.jpg",
        mime_type="image/jpeg",
        file_size=100,
        quality_status="usable",
        quality_warnings=[],
    )


def test_v2_baseline_has_fixed_three_product_pack():
    products = list_baseline_products()
    assert [product.key for product in products] == [
        "yl-t02-massage-pillow", "roundlab-birch-moisture-cream", "locknlock-bisfree-container-set"
    ]
    assert "4개/6개 이상 상충" in products[0].known_risks[0]
    assert products[0].fact_conflicts[0].status == "conflicted"


def test_reference_only_supplier_asset_is_not_render_eligible_or_baseline_approved(db_session):
    project, page = _project_page(db_session)
    reference = _asset(project.id, "supplier-capture", "url-extracted")
    db_session.add_all([
        reference,
        PageSection(id="hero", page_id=page.id, section_type="hero", image_asset_id=reference.id, sort_order=0),
    ])
    db_session.commit()

    assert resolved_asset_usage_status(reference) == "reference_only"
    assert initial_asset_usage_status("unrecognized-import") == "blocked"
    assert get_page_eligible_assets(db_session, project.id) == []
    report = inspect_commerce_story_baseline(db_session, page)
    assert "reference_only_asset_used" in {issue.code for issue in report.issues}
    readiness = inspect_page_readiness(page, db_session)
    assert "asset_not_eligible" in {issue.code for issue in readiness.blockers}


def test_reference_only_source_requires_ai_redesign_before_export(db_session):
    project, page = _project_page(db_session)
    db_session.add_all([
        PageSection(
            id="hero-redesign",
            page_id=page.id,
            section_type="hero",
            visual_kind="html_graphic",
            visual_payload={
                "layout_variant": "hero_overlay",
                "missing_state": "ai_redesign_required",
            },
            sort_order=0,
        ),
        PageSection(
            id="spec-redesign",
            page_id=page.id,
            section_type="specifications",
            visual_kind="html_graphic",
            visual_payload={
                "layout_variant": "spec_table",
                "table_rows": [{
                    "label": "정격 소비전력",
                    "value": "8W",
                    "verification_status": "confirmed",
                    "source_fact_ids": ["seller-fact"],
                }],
            },
            sort_order=1,
        ),
        ProductFact(
            id="seller-fact",
            project_id=project.id,
            fact_text="판매자 제공 사양: 정격 소비전력은 8W입니다.",
            source_text="8W",
            verification_status="seller_confirmed",
            extraction_source="seller_input",
            needs_review=False,
        ),
    ])
    db_session.commit()

    readiness = inspect_page_readiness(page, db_session)
    assert readiness.ready is False
    assert "ai_redesign_required" in {issue.code for issue in readiness.blockers}


def test_final_specification_must_be_last_visible_section(db_session):
    project, page = _project_page(db_session)
    seller_asset = _asset(project.id, "seller-photo", "self_shot", "seller_owned")
    db_session.add_all([
        seller_asset,
        PageSection(id="spec", page_id=page.id, section_type="specifications", title="스펙", image_asset_id=seller_asset.id, sort_order=0),
        PageSection(id="cta", page_id=page.id, section_type="cta", title="구매", sort_order=1),
    ])
    db_session.commit()

    assert final_spec_is_last(page.sections) is False
    report = inspect_commerce_story_baseline(db_session, page)
    assert "final_specification_not_last" in {issue.code for issue in report.issues}


def test_unconfirmed_numeric_or_conflicted_fact_blocks_baseline(db_session):
    project, page = _project_page(db_session)
    seller_asset = _asset(project.id, "seller-photo", "self_shot", "seller_owned")
    conflict = ProductFact(
        id="heads-conflict", project_id=project.id, fact_text="마사지 헤드 6개", verification_status="conflicted", needs_review=True
    )
    db_session.add_all([
        seller_asset,
        conflict,
        PageSection(id="hero", page_id=page.id, section_type="hero", title="6개 헤드", body_copy="2000mAh 배터리", image_asset_id=seller_asset.id, associated_fact_ids=[conflict.id], sort_order=0),
        PageSection(id="spec", page_id=page.id, section_type="specifications", title="스펙", sort_order=1),
    ])
    db_session.commit()

    report = inspect_commerce_story_baseline(db_session, page)
    codes = {issue.code for issue in report.issues}
    assert {"unconfirmed_fact_used", "unsupported_numeric_claim"}.issubset(codes)
    readiness = inspect_page_readiness(page, db_session)
    blocker_codes = {issue.code for issue in readiness.blockers}
    assert "unverified_fact_linked" in blocker_codes
    assert "grounding_numeric_claim_without_evidence" in blocker_codes


def test_v2_baseline_registration_api_persists_reference_and_jpg(client, db_session):
    project, page = _project_page(db_session)
    reference = _asset(project.id, "reference", "url-extracted")
    export = _asset(project.id, "export", "exported_image", "blocked")
    db_session.add_all([reference, export, PageSection(id="spec", page_id=page.id, section_type="specifications", title="스펙", sort_order=0)])
    db_session.commit()
    response = client.put(
        "/api/v1/commerce-story-baselines/yl-t02-massage-pillow/registration",
        headers={"X-Mock-User-Id": "v2-user", "X-Mock-Workspace-Id": "v2-workspace"},
        json={
            "project_id": project.id,
            "reference_capture_asset_id": reference.id,
            "baseline_export_asset_id": export.id,
            "evaluation": {key: True for key in EVALUATION_ITEMS},
        },
    )
    assert response.status_code == 200
    assert response.json()["reference_capture_asset_id"] == reference.id
    catalogue = client.get(
        "/api/v1/commerce-story-baselines",
        headers={"X-Mock-User-Id": "v2-user", "X-Mock-Workspace-Id": "v2-workspace"},
    )
    yl_t02 = next(item for item in catalogue.json() if item["key"] == "yl-t02-massage-pillow")
    assert yl_t02["ready"] is True


def test_registered_baseline_stays_blocked_until_jpg_and_evaluation_are_complete(client, db_session):
    project, page = _project_page(db_session)
    reference = _asset(project.id, "reference", "url-extracted")
    seller_asset = _asset(project.id, "seller", "self_shot", "seller_owned")
    seller_asset.is_representative = True
    db_session.add_all([
        reference,
        seller_asset,
        PageSection(id="hero", page_id=page.id, section_type="hero", title="상품", image_asset_id=seller_asset.id, sort_order=0),
        PageSection(id="spec", page_id=page.id, section_type="specifications", title="최종 스펙", sort_order=1),
    ])
    db_session.commit()
    response = client.put(
        "/api/v1/commerce-story-baselines/yl-t02-massage-pillow/registration",
        headers={"X-Mock-User-Id": "v2-user", "X-Mock-Workspace-Id": "v2-workspace"},
        json={
            "project_id": project.id,
            "reference_capture_asset_id": reference.id,
            "evaluation": {key: key != "preview_export_parity" for key in EVALUATION_ITEMS},
        },
    )
    assert response.status_code == 200

    report = inspect_commerce_story_baseline(
        db_session,
        page,
        baseline_key="yl-t02-massage-pillow",
        workspace_id="v2-workspace",
    )
    blockers = {issue.code for issue in report.issues if issue.severity == "blocker"}
    assert {"evaluation_pending", "baseline_jpg_missing"}.issubset(blockers)
    assert report.ready_for_commerce_story is False


def test_asset_usage_status_api_exposes_seller_policy_choice(client, db_session):
    project, _ = _project_page(db_session)
    asset = _asset(project.id, "manual-photo", "self_shot", "seller_owned")
    db_session.add(asset)
    db_session.commit()
    response = client.patch(
        f"/api/v1/files/assets/{asset.id}/usage-status",
        headers={"X-Mock-User-Id": "v2-user", "X-Mock-Workspace-Id": "v2-workspace"},
        json={"usage_status": "reference_only"},
    )
    assert response.status_code == 200
    assert response.json()["usage_status"] == "reference_only"


def test_fact_api_accepts_only_v2_write_statuses(client, db_session):
    project, _ = _project_page(db_session)
    headers = {"X-Mock-User-Id": "v2-user", "X-Mock-Workspace-Id": "v2-workspace"}
    created = client.post(
        f"/api/v1/projects/{project.id}/facts",
        headers=headers,
        json={"fact_text": "정격 소비전력 8W"},
    )
    assert created.status_code == 201
    assert created.json()["verification_status"] == "extracted"
    legacy = client.patch(
        f"/api/v1/projects/{project.id}/facts/{created.json()['id']}",
        headers=headers,
        json={"verification_status": "confirmed"},
    )
    assert legacy.status_code == 422
    approved = client.patch(
        f"/api/v1/projects/{project.id}/facts/{created.json()['id']}",
        headers=headers,
        json={"verification_status": "seller_confirmed"},
    )
    assert approved.status_code == 200
    assert approved.json()["needs_review"] is False


def test_page_api_rejects_storyboard_with_content_after_final_specs(client, db_session):
    project, page = _project_page(db_session)
    spec = PageSection(id="spec", page_id=page.id, section_type="specifications", title="최종 스펙", sort_order=0)
    cta = PageSection(id="cta", page_id=page.id, section_type="cta", title="구매하기", sort_order=1)
    db_session.add_all([spec, cta])
    db_session.commit()
    response = client.patch(
        f"/api/v1/projects/{project.id}/page",
        headers={"X-Mock-User-Id": "v2-user", "X-Mock-Workspace-Id": "v2-workspace"},
        json={
            "sections": [
                {"id": spec.id, "sort_order": 0, "is_visible": True},
                {"id": cta.id, "sort_order": 1, "is_visible": True},
            ]
        },
    )
    assert response.status_code == 422
    assert "last visible section" in response.json()["detail"]


def test_supplier_banner_ocr_blocks_final_output(db_session):
    project, page = _project_page(db_session)
    asset = _asset(project.id, "seller-image", "self_shot", "seller_owned")
    asset.ocr_text = "智能3键设计 一键启动"
    db_session.add_all([
        asset,
        PageSection(id="hero", page_id=page.id, section_type="hero", title="상품", image_asset_id=asset.id, sort_order=0),
        PageSection(id="spec", page_id=page.id, section_type="specifications", title="최종 스펙", sort_order=1),
    ])
    db_session.commit()
    readiness = inspect_page_readiness(page, db_session)
    assert "supplier_banner_exposed" in {issue.code for issue in readiness.blockers}
