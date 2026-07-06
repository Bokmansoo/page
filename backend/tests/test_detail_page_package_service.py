import pytest
from src.db.models import ProductProject, ProductPage, PageSection, Asset, ImageGenerationJobRecord, ProductFact
from src.api.auth import DEFAULT_BRAND_ID
from src.services.detail_page_package_service import DetailPagePackageService

@pytest.fixture
def setup_package_project(client):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    payload = {
        "name": "Sprint 45 Cooling Fan",
        "brand_id": DEFAULT_BRAND_ID,
        "raw_input_text": "LUMENA FAN JET ULTRA portable cooling fan. KC certification R-R-ONH-FANJETULTRA."
    }
    res = client.post("/api/v1/projects", json=payload, headers=headers)
    assert res.status_code == 201
    return res.json()["id"]

def test_detail_page_package_generation_and_order(client, setup_package_project, db_session):
    project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # Add confirmed facts first so default page generator has data
    fact1 = ProductFact(
        project_id=project_id,
        fact_text="루메나 휴대용 무선 냉각선풍기 모델명 FAN JET ULTRA",
        source_text="LUMENA FAN JET ULTRA",
        verification_status="confirmed",
        needs_review=False
    )
    db_session.add(fact1)
    db_session.commit()

    # 1. Fetch package
    res = client.get(f"/api/v1/projects/{project_id}/detail-page-package", headers=headers)
    assert res.status_code == 200
    pkg = res.json()

    assert "sales_strategy" in pkg
    assert "copy_sections" in pkg
    assert "visual_plan" in pkg
    assert "page_sections" in pkg
    assert "marketplace_copy" in pkg
    assert "export_targets" in pkg

    # Verify default section order
    copy_sections = pkg["copy_sections"]
    section_types = [s["section_type"] for s in copy_sections]
    
    # Page must contain problem_statement, main_claim, secondary_benefit, main_claim_support, benefit_list, summary_claim, product_information
    expected_order = [
        "problem_statement",
        "main_claim",
        "secondary_benefit",
        "main_claim_support",
        "benefit_list",
        "summary_claim",
        "product_information"
    ]
    # Filter to only those expected sections present in generated sections
    actual_matched_order = [t for t in section_types if t in expected_order]
    
    # Confirm it is sorted according to expected order
    sorted_expected = sorted(actual_matched_order, key=lambda x: expected_order.index(x))
    assert actual_matched_order == sorted_expected

def test_asset_approval_filtering_and_fallback(client, setup_package_project, db_session):
    project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # Add confirmed facts
    fact = ProductFact(
        project_id=project_id,
        fact_text="선풍기",
        verification_status="confirmed",
        needs_review=False
    )
    db_session.add(fact)
    db_session.commit()

    # Get page package to initialize page draft
    res = client.get(f"/api/v1/projects/{project_id}/detail-page-package", headers=headers)
    assert res.status_code == 200
    page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    
    # Create two assets:
    # 1. Original asset (sourced)
    orig_asset = Asset(
        project_id=project_id,
        source_type="sourced",
        filename="original_product.jpg",
        file_path="/uploads/original_product.jpg",
        mime_type="image/jpeg",
        file_size=1024
    )
    # 2. AI generated asset (ai_corrected) - but unapproved
    ai_unapproved_asset = Asset(
        project_id=project_id,
        source_type="ai_corrected",
        filename="ai_generated_unapproved.jpg",
        file_path="/uploads/ai_generated_unapproved.jpg",
        mime_type="image/jpeg",
        file_size=2048
    )
    # 3. AI generated asset - approved
    ai_approved_asset = Asset(
        project_id=project_id,
        source_type="ai_corrected",
        filename="ai_generated_approved.jpg",
        file_path="/uploads/ai_generated_approved.jpg",
        mime_type="image/jpeg",
        file_size=4096
    )
    db_session.add_all([orig_asset, ai_unapproved_asset, ai_approved_asset])
    db_session.commit()

    # Create job records for AI assets
    unapproved_job = ImageGenerationJobRecord(
        project_id=project_id,
        job_id="job-unapproved",
        section_id=page.sections[0].id,
        role="hero",
        prompt="cooling blue airflow",
        status="generating",  # Not approved!
        output_asset_id=ai_unapproved_asset.id
    )
    approved_job = ImageGenerationJobRecord(
        project_id=project_id,
        job_id="job-approved",
        section_id=page.sections[1].id,
        role="image_text",
        prompt="detailed button layout",
        status="approved",  # Approved!
        output_asset_id=ai_approved_asset.id
    )
    db_session.add_all([unapproved_job, approved_job])
    db_session.commit()

    # Map sections to these assets
    page.sections[0].image_asset_id = ai_unapproved_asset.id  # Unapproved AI asset mapped to section 0
    page.sections[1].image_asset_id = ai_approved_asset.id    # Approved AI asset mapped to section 1
    # Check section 2 with original asset
    if len(page.sections) > 2:
        page.sections[2].image_asset_id = orig_asset.id
    db_session.commit()

    # Fetch package and check visual rendering
    res_pkg = client.get(f"/api/v1/projects/{project_id}/detail-page-package", headers=headers)
    assert res_pkg.status_code == 200
    pkg_data = res_pkg.json()

    page_sections = pkg_data["page_sections"]
    
    # Section 0 (unapproved AI asset) must have fallback "image needed"
    sec0_visual = page_sections[0]["visual_slot"]
    assert sec0_visual["kind"] == "placeholder"
    assert sec0_visual["fallback_label"] == "image needed"

    # Section 1 (approved AI asset) must show the product image correctly
    sec1_visual = page_sections[1]["visual_slot"]
    assert sec1_visual["kind"] == "product_image"
    assert sec1_visual["asset_id"] == ai_approved_asset.id

    # Section 2 (original asset) must show the product image correctly
    if len(page_sections) > 2:
        sec2_visual = page_sections[2]["visual_slot"]
        assert sec2_visual["kind"] == "product_image"
        assert sec2_visual["asset_id"] == orig_asset.id

def test_ai_edit_command_execution(client, setup_package_project, db_session):
    project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # Add facts & setup package page
    fact = ProductFact(
        project_id=project_id,
        fact_text="선풍기",
        verification_status="confirmed",
        needs_review=False
    )
    db_session.add(fact)
    db_session.commit()

    client.get(f"/api/v1/projects/{project_id}/detail-page-package", headers=headers)
    page = db_session.query(ProductPage).filter(ProductPage.project_id == project_id).first()
    target_section = page.sections[0]
    section_id = target_section.id

    # 1. Trigger Stronger Headline
    payload = {
        "section_id": section_id,
        "command_type": "stronger_headline",
        "freeform_instruction": "Make the title sound cooler"
    }
    res = client.post(f"/api/v1/projects/{project_id}/page/sections/{section_id}/ai-edit", json=payload, headers=headers)
    assert res.status_code == 200
    
    # Verify mock revision is appended in DB & Response
    db_session.refresh(target_section)
    assert target_section.title.startswith("강조:")
    assert "[Revision: Stronger Headline]" in target_section.title
    assert "Make the title sound cooler" in target_section.title

    # 2. Trigger Remove Section
    remove_payload = {
        "section_id": section_id,
        "command_type": "remove_section"
    }
    res_remove = client.post(f"/api/v1/projects/{project_id}/page/sections/{section_id}/ai-edit", json=remove_payload, headers=headers)
    assert res_remove.status_code == 200
    
    db_session.refresh(target_section)
    assert target_section.is_visible is False


def test_ai_edit_rejects_section_from_another_project(
    client, setup_package_project, db_session
):
    first_project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    second = client.post(
        "/api/v1/projects",
        json={
            "name": "Other Project",
            "brand_id": DEFAULT_BRAND_ID,
            "raw_input_text": "Other product",
        },
        headers=headers,
    )
    assert second.status_code == 201
    second_project_id = second.json()["id"]
    client.get(
        f"/api/v1/projects/{second_project_id}/detail-page-package",
        headers=headers,
    )
    second_page = db_session.query(ProductPage).filter(
        ProductPage.project_id == second_project_id
    ).first()
    foreign_section = second_page.sections[0]
    original_title = foreign_section.title

    response = client.post(
        f"/api/v1/projects/{first_project_id}/page/sections/{foreign_section.id}/ai-edit",
        json={
            "section_id": foreign_section.id,
            "command_type": "stronger_headline",
            "scope": "section",
        },
        headers=headers,
    )

    assert response.status_code == 404
    db_session.refresh(foreign_section)
    assert foreign_section.title == original_title


def test_ai_edit_rejects_unknown_command(client, setup_package_project, db_session):
    project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    client.get(f"/api/v1/projects/{project_id}/detail-page-package", headers=headers)
    page = db_session.query(ProductPage).filter(
        ProductPage.project_id == project_id
    ).first()
    section = page.sections[0]

    response = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{section.id}/ai-edit",
        json={
            "section_id": section.id,
            "command_type": "not_a_real_command",
            "scope": "section",
        },
        headers=headers,
    )

    assert response.status_code == 422


def test_move_section_changes_package_order(client, setup_package_project, db_session):
    project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    initial = client.get(
        f"/api/v1/projects/{project_id}/detail-page-package",
        headers=headers,
    ).json()
    first_id = initial["copy_sections"][0]["id"]
    second_id = initial["copy_sections"][1]["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{first_id}/ai-edit",
        json={
            "section_id": first_id,
            "command_type": "move_section",
            "freeform_instruction": "down",
            "scope": "section",
        },
        headers=headers,
    )

    assert response.status_code == 200
    reordered_ids = [section["id"] for section in response.json()["copy_sections"]]
    assert reordered_ids[:2] == [second_id, first_id]


def test_page_scope_applies_copy_command_to_all_visible_sections(
    client, setup_package_project, db_session
):
    project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    package = client.get(
        f"/api/v1/projects/{project_id}/detail-page-package",
        headers=headers,
    ).json()
    section_id = package["copy_sections"][0]["id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/page/sections/{section_id}/ai-edit",
        json={
            "section_id": section_id,
            "command_type": "natural_tone",
            "scope": "page",
        },
        headers=headers,
    )

    assert response.status_code == 200
    visible = [
        section
        for section in response.json()["copy_sections"]
        if section["is_visible"]
    ]
    assert all(
        "[Revision: Natural Tone]" in (section["body_copy"] or "")
        for section in visible
    )


def test_page_patch_rejects_unapproved_generated_asset(
    client, setup_package_project, db_session
):
    project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    package = client.get(
        f"/api/v1/projects/{project_id}/detail-page-package",
        headers=headers,
    ).json()
    generated = Asset(
        project_id=project_id,
        source_type="ai_generated",
        filename="unapproved.png",
        file_path="/uploads/unapproved.png",
        mime_type="image/png",
        file_size=100,
    )
    db_session.add(generated)
    db_session.commit()
    sections = package["copy_sections"]
    sections[0]["image_asset_id"] = generated.id

    response = client.patch(
        f"/api/v1/projects/{project_id}/page",
        json={
            "sections": [
                {
                    "id": section["id"],
                    "title": section["title"],
                    "body_copy": section["body_copy"],
                    "image_asset_id": section["image_asset_id"],
                    "sort_order": section["sort_order"],
                    "is_visible": section["is_visible"],
                }
                for section in sections
            ]
        },
        headers=headers,
    )

    assert response.status_code == 400


def test_uploaded_original_asset_is_renderable(
    client, setup_package_project, db_session
):
    project_id = setup_package_project
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1",
    }
    client.get(f"/api/v1/projects/{project_id}/detail-page-package", headers=headers)
    page = db_session.query(ProductPage).filter(
        ProductPage.project_id == project_id
    ).first()
    uploaded = Asset(
        project_id=project_id,
        source_type="uploaded",
        filename="uploaded-product.png",
        file_path="/uploads/uploaded-product.png",
        mime_type="image/png",
        file_size=100,
    )
    db_session.add(uploaded)
    db_session.commit()
    page.sections[0].image_asset_id = uploaded.id
    db_session.commit()

    package = client.get(
        f"/api/v1/projects/{project_id}/detail-page-package",
        headers=headers,
    ).json()

    assert package["page_sections"][0]["visual_slot"]["asset_id"] == uploaded.id

