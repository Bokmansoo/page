import pytest
from src.api.auth import DEFAULT_BRAND_ID
from src.db.models import ProductFact, ProductProject, Asset

def test_visual_package_api_full_flow(client, db_session):
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }

    # 1. Create project
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "루메나 휴대용 선풍기", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "시원한 여름용 휴대용 선풍기 스펙입니다."},
        headers=headers
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    # Add confirmed fact to satisfy generation if needed
    fact = ProductFact(
        project_id=project_id,
        fact_text="가볍고 시원한 선풍기입니다.",
        verification_status="confirmed"
    )
    # Add a valid image asset for testing update endpoint validations
    asset = Asset(
        id="test-image-asset",
        project_id=project_id,
        filename="test_photo.jpg",
        file_path="uploads/test_photo.jpg",
        mime_type="image/jpeg",
        file_size=1024,
        source_type="uploaded"
    )
    db_session.add_all([fact, asset])
    db_session.commit()

    # 2. Create page draft
    page_res = client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers
    )
    assert page_res.status_code == 201

    # 3. GET visual package (it will plan first)
    get_res = client.get(
        f"/api/v1/projects/{project_id}/visual-package",
        headers=headers
    )
    assert get_res.status_code == 200
    jobs = get_res.json()
    assert len(jobs) > 0
    
    representative_job = next((j for j in jobs if j["role"] == "representative_product"), None)
    assert representative_job is not None
    assert representative_job["status"] == "needs_generation"
    assert representative_job["job_id"] is not None
    assert representative_job["section_id"] is not None
    job_id = representative_job["job_id"]

    # 4. Try updating with a non-existent asset (should fail with 400)
    invalid_update_res = client.post(
        f"/api/v1/projects/{project_id}/visual-package/jobs/{job_id}/update",
        json={
            "status": "planned",
            "source_asset_ids": ["non-existent-asset"]
        },
        headers=headers
    )
    assert invalid_update_res.status_code == 400
    assert "not found" in invalid_update_res.json()["detail"]

    # 5. Update job status to planned with valid mock asset
    update_res = client.post(
        f"/api/v1/projects/{project_id}/visual-package/jobs/{job_id}/update",
        json={
            "status": "planned",
            "source_asset_ids": ["test-image-asset"],
            "prompt": "Original photo of fan",
            "preserve_product_identity": True
        },
        headers=headers
    )
    assert update_res.status_code == 200
    updated_job = update_res.json()
    assert updated_job["status"] == "planned"
    assert updated_job["source_asset_ids"] == ["test-image-asset"]

    persisted_res = client.get(
        f"/api/v1/projects/{project_id}/visual-package",
        headers=headers,
    )
    assert persisted_res.status_code == 200
    persisted_job = next(
        job for job in persisted_res.json() if job["job_id"] == job_id
    )
    assert persisted_job["status"] == "planned"

    # 6. Planned means an original asset is actually connected.
    empty_planned_res = client.post(
        f"/api/v1/projects/{project_id}/visual-package/jobs/{job_id}/update",
        json={
            "status": "planned",
            "source_asset_ids": [],
        },
        headers=headers,
    )
    assert empty_planned_res.status_code == 400

    # 7. Switch back to needs_generation with empty prompt to verify prompt auto-generation
    switch_res = client.post(
        f"/api/v1/projects/{project_id}/visual-package/jobs/{job_id}/update",
        json={
            "status": "needs_generation",
            "prompt": ""
        },
        headers=headers
    )
    assert switch_res.status_code == 200
    switched_job = switch_res.json()
    assert switched_job["status"] == "needs_generation"
    # Prompt should have been automatically generated
    assert switched_job["prompt"] != ""
    assert "Strictly do NOT include any text" in switched_job["prompt"]

    # 8. Get recommended alternative prompt
    recommend_res = client.post(
        f"/api/v1/projects/{project_id}/visual-package/jobs/{job_id}/recommend",
        headers=headers
    )
    assert recommend_res.status_code == 200
    recommended_job = recommend_res.json()
    assert "Alternative version" in recommended_job["prompt"]

    # 9. Test visual package regeneration
    regen_res = client.post(
        f"/api/v1/projects/{project_id}/visual-package/regenerate",
        headers=headers
    )
    assert regen_res.status_code == 200
    regen_jobs = regen_res.json()
    assert len(regen_jobs) > 0
    # The updated job is cleared/replaced by a new plan
    new_representative_job = next((j for j in regen_jobs if j["role"] == "representative_product"), None)
    assert new_representative_job["job_id"] != job_id

    # 10. Changing confirmed strategy invalidates the cached package.
    project = db_session.query(ProductProject).filter(ProductProject.id == project_id).one()
    project.intake_snapshot = {
        **(project.intake_snapshot or {}),
        "confirmed_sales_strategy": {
            "target_customer": "직접 확정한 고객",
            "buyer_problem": "직접 확정한 고민",
            "main_selling_point": "직접 확정한 소구점",
            "supporting_points": [],
            "tone": "직접 확정한 톤",
            "price_strategy": "",
            "image_selection": [],
            "risk_notes": [],
            "selected_direction": "emotional",
            "style_key": "lifestyle",
        },
    }
    db_session.commit()

    refreshed_res = client.get(
        f"/api/v1/projects/{project_id}/visual-package",
        headers=headers,
    )
    assert refreshed_res.status_code == 200
    refreshed_jobs = refreshed_res.json()
    refreshed_representative = next(
        j for j in refreshed_jobs if j["role"] == "representative_product"
    )
    assert refreshed_representative["job_id"] != new_representative_job["job_id"]
    assert "직접 확정한 고객" in refreshed_representative["prompt"]
