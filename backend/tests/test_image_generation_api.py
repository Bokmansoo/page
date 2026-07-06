import pytest
import io
import os
from unittest.mock import MagicMock, patch
from src.db.models import User, Workspace, Brand, ProductProject, Asset, ProductPage, PageSection, ImageGenerationJobRecord
from src.services.image_generation_provider import ImageGenerationResult


def generate_dummy_png(color="red", size=(512, 512)):
    from PIL import Image
    img = Image.new("RGB", size, color=color)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 100, 100], fill="blue" if color == "red" else "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def api_test_data(db_session):
    # Owner & Workspace 1
    user1 = User(email="user1@example.com", name="User One")
    db_session.add(user1)
    db_session.commit()

    workspace1 = Workspace(name="Workspace One", owner_id=user1.id)
    db_session.add(workspace1)
    db_session.commit()

    # User 2 in Workspace 2
    user2 = User(email="user2@example.com", name="User Two")
    db_session.add(user2)
    db_session.commit()

    workspace2 = Workspace(name="Workspace Two", owner_id=user2.id)
    db_session.add(workspace2)
    db_session.commit()

    brand1 = Brand(workspace_id=workspace1.id, name="Brand One")
    db_session.add(brand1)
    db_session.commit()

    project1 = ProductProject(
        workspace_id=workspace1.id,
        brand_id=brand1.id,
        name="Project One",
        visual_package_jobs=[
            {
                "job_id": "job-api-1",
                "section_id": "sec-1",
                "role": "cutout_product",
                "prompt": "Sleek cutout product shot",
                "source_asset_ids": ["asset-orig-1"],
                "preserve_product_identity": True,
                "output_size": "512x512",
                "cost_tier": "standard",
                "status": "planned"
            }
        ]
    )
    db_session.add(project1)
    db_session.commit()

    page1 = ProductPage(project_id=project1.id)
    db_session.add(page1)
    db_session.commit()

    sec1 = PageSection(
        page_id=page1.id,
        section_type="hero",
        id="sec-1",
        image_asset_id="asset-orig-1"
    )
    db_session.add(sec1)
    db_session.commit()

    # Original Asset
    ref_path = os.path.join(os.path.dirname(__file__), "api_ref.png")
    with open(ref_path, "wb") as f:
        f.write(generate_dummy_png(color="red"))

    asset_orig = Asset(
        id="asset-orig-1",
        project_id=project1.id,
        source_type="sourced",
        filename="api_ref.png",
        file_path=ref_path,
        mime_type="image/png",
        file_size=len(generate_dummy_png(color="red"))
    )
    db_session.add(asset_orig)
    db_session.commit()

    yield {
        "user1": user1,
        "workspace1": workspace1,
        "user2": user2,
        "workspace2": workspace2,
        "project1": project1,
        "page1": page1,
        "sec1": sec1,
        "asset_orig": asset_orig,
        "ref_path": ref_path
    }

    if os.path.exists(ref_path):
        os.remove(ref_path)


def test_api_workspace_scoping(client, api_test_data):
    project = api_test_data["project1"]

    # 1. Accessing via User 1 (authorized workspace 1)
    headers1 = {
        "x-mock-user-id": api_test_data["user1"].id,
        "x-mock-workspace-id": api_test_data["workspace1"].id
    }
    # GET status
    res = client.get(
        f"/api/v1/projects/{project.id}/visual-jobs/job-api-1",
        headers=headers1
    )
    assert res.status_code == 200
    assert res.json()["job_id"] == "job-api-1"
    assert res.json()["status"] == "planned"

    # 2. Accessing via User 2 (unauthorized Workspace 2)
    headers2 = {
        "x-mock-user-id": api_test_data["user2"].id,
        "x-mock-workspace-id": api_test_data["workspace2"].id
    }
    res = client.get(
        f"/api/v1/projects/{project.id}/visual-jobs/job-api-1",
        headers=headers2
    )
    # Should return 404 because the project does not belong to User 2's active workspace
    assert res.status_code == 404


@patch("src.services.image_generation_service.OpenAIImageProvider")
def test_api_generate_approve_reject_flow(mock_provider_class, client, api_test_data, db_session):
    project = api_test_data["project1"]
    sec = api_test_data["sec1"]

    mock_provider = MagicMock()
    mock_provider_class.return_value = mock_provider
    mock_result = ImageGenerationResult(
        content=generate_dummy_png(color="red"),
        mime_type="image/png",
        provider="openai",
        model="gpt-image-1.5",
        usage_metadata={"cost": 0.04}
    )
    mock_provider.generate.return_value = mock_result

    headers = {
        "x-mock-user-id": api_test_data["user1"].id,
        "x-mock-workspace-id": api_test_data["workspace1"].id
    }

    # 1. Generate without cost approval -> returns awaiting_cost_approval
    res = client.post(
        f"/api/v1/projects/{project.id}/visual-jobs/job-api-1/generate",
        json={"cost_approved": False},
        headers=headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "awaiting_cost_approval"

    # 2. Generate with cost approval -> generates and returns needs_review
    res = client.post(
        f"/api/v1/projects/{project.id}/visual-jobs/job-api-1/generate",
        json={"cost_approved": True},
        headers=headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "needs_review"
    output_asset_id = res.json()["output_asset_id"]
    assert output_asset_id is not None

    # Clean up created asset file
    asset = db_session.query(Asset).filter(Asset.id == output_asset_id).first()
    assert asset is not None
    assert os.path.exists(asset.file_path)

    # 3. Approve the image -> transitions to approved, and section image_asset_id becomes output_asset_id
    res = client.post(
        f"/api/v1/projects/{project.id}/visual-jobs/job-api-1/approve",
        headers=headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    
    db_session.refresh(sec)
    assert sec.image_asset_id == output_asset_id

    # 4. Reject the image -> keeps the generated output for audit, but restores the original selection.
    res = client.post(
        f"/api/v1/projects/{project.id}/visual-jobs/job-api-1/reject",
        headers=headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"
    assert res.json()["output_asset_id"] == output_asset_id
    
    db_session.refresh(sec)
    assert sec.image_asset_id == "asset-orig-1"

    if os.path.exists(asset.file_path):
        os.remove(asset.file_path)


def test_api_regenerate_flow(client, api_test_data, db_session):
    project = api_test_data["project1"]
    sec = api_test_data["sec1"]

    headers = {
        "x-mock-user-id": api_test_data["user1"].id,
        "x-mock-workspace-id": api_test_data["workspace1"].id
    }

    # Call regenerate with a revised prompt
    res = client.post(
        f"/api/v1/projects/{project.id}/visual-jobs/job-api-1/regenerate",
        json={"prompt": "Revised apples prompt"},
        headers=headers
    )
    assert res.status_code == 200
    assert res.json()["status"] == "needs_generation"
    assert res.json()["prompt"] == "Revised apples prompt"
    assert res.json()["output_asset_id"] is None

    db_session.refresh(sec)
    assert sec.image_asset_id is None


def test_api_rejects_approval_before_review(client, api_test_data):
    project = api_test_data["project1"]
    headers = {
        "x-mock-user-id": api_test_data["user1"].id,
        "x-mock-workspace-id": api_test_data["workspace1"].id,
    }

    res = client.post(
        f"/api/v1/projects/{project.id}/visual-jobs/job-api-1/approve",
        headers=headers,
    )

    assert res.status_code == 409


def test_api_rejects_invalid_source_asset_before_generation(
    client, api_test_data, db_session
):
    project = api_test_data["project1"]
    record = ImageGenerationJobRecord(
        project_id=project.id,
        job_id="job-invalid-source",
        section_id="sec-1",
        role="cutout_product",
        source_asset_ids=["asset-from-another-project"],
        prompt="Product cutout",
        preserve_product_identity=True,
        status="needs_generation",
    )
    db_session.add(record)
    db_session.commit()
    headers = {
        "x-mock-user-id": api_test_data["user1"].id,
        "x-mock-workspace-id": api_test_data["workspace1"].id,
    }

    res = client.post(
        f"/api/v1/projects/{project.id}/visual-jobs/{record.job_id}/generate",
        json={"cost_approved": True},
        headers=headers,
    )

    assert res.status_code == 400
    assert "does not belong to project" in res.json()["detail"]
