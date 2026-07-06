import pytest
import json

@pytest.fixture
def mock_agent_runner(db_session):
    def _run(product_name, description=None, uploaded_asset_id=None, uploaded_filename=None, product_url=None):
        import uuid
        from src.db.models import User, Workspace, Brand, ProductProject, Asset
        from src.agents.state import AgentRunState, ProductInput
        from src.agents.graph import AgentGraph

        user = User(email=f"tester-{uuid.uuid4().hex}@example.com", name="Tester")
        db_session.add(user)
        db_session.commit()

        workspace = Workspace(name="WS", owner_id=user.id)
        db_session.add(workspace)
        db_session.commit()

        brand = Brand(workspace_id=workspace.id, name="Brand")
        db_session.add(brand)
        db_session.commit()

        project = ProductProject(
            workspace_id=workspace.id,
            brand_id=brand.id,
            name=product_name,
        )
        db_session.add(project)
        db_session.commit()

        asset_ids = []
        if uploaded_asset_id and uploaded_filename:
            asset = Asset(
                id=uploaded_asset_id,
                project_id=project.id,
                source_type="sourced",
                filename=uploaded_filename,
                file_path=f"./uploads/{uploaded_filename}",
                mime_type="image/png",
                file_size=100
            )
            db_session.add(asset)
            db_session.commit()
            asset_ids.append(uploaded_asset_id)

        product_input = ProductInput(
            product_name=product_name,
            description=description,
            product_url=product_url,
            asset_ids=asset_ids
        )

        state = AgentRunState(
            project_id=project.id,
            product_input=product_input
        )

        graph = AgentGraph.mock()
        completed = graph.run_all(state)
        return completed.outputs

    return _run


def test_mock_generation_uses_input_product_context(mock_agent_runner):
    result = mock_agent_runner(
        product_name="삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드",
        description="거실과 침실을 오가며 쓰는 이동형 스마트 모니터",
        uploaded_asset_id="asset-uploaded-samtan",
        uploaded_filename="삼탠바이미.png",
    )

    page_text = json.dumps(result["page_assembly"], ensure_ascii=False)

    assert "삼탠바이미" in page_text
    assert "스마트모니터" in page_text
    assert "자전거" not in page_text
    assert "마사지" not in page_text
    assert "의류" not in page_text


def test_mock_generation_prefers_uploaded_image_for_visual_slots(mock_agent_runner):
    result = mock_agent_runner(
        product_name="삼성 삼탠바이미 32인치 스마트모니터 TV + 무빙 스탠드",
        uploaded_asset_id="asset-uploaded-samtan",
        uploaded_filename="삼탠바이미.png",
    )

    hero_visual = result["page_assembly"]["sections"][0]["visual_slot"]

    assert hero_visual["source_type"] == "uploaded"
    assert hero_visual["asset_id"] == "asset-uploaded-samtan"
    assert "삼탠바이미.png" in hero_visual["label"]


def test_mock_generation_without_upload_or_url_uses_only_mock_generated_sources(mock_agent_runner):
    result = mock_agent_runner(
        product_name="Samsung Smart Monitor Moving Stand",
        description="A movable smart monitor for living rooms and bedrooms",
    )

    generated_images = result["generated_assets"]["images"]
    page_sections = result["page_assembly"]["sections"]
    source_types = {
        image["source_type"] for image in generated_images
    } | {
        section["visual_slot"]["source_type"] for section in page_sections
    }

    assert source_types == {"mock-generated", "html-graphic"}
    assert "mock-uploaded-dummy" not in {image["id"] for image in generated_images}
    assert "mock-comparison-visual" not in {image["id"] for image in generated_images}
    assert not any("images.unsplash.com" in image["url"] for image in generated_images)


def test_mock_generation_with_url_marks_only_url_extracted_slots(mock_agent_runner):
    result = mock_agent_runner(
        product_name="Samsung Smart Monitor Moving Stand",
        product_url="https://example.com/products/smart-monitor",
    )

    generated_images = result["generated_assets"]["images"]
    url_images = [image for image in generated_images if image["source_type"] == "url-extracted"]
    source_types = {image["source_type"] for image in generated_images}

    assert source_types <= {"url-extracted", "mock-generated"}
    assert len(url_images) == 1
    assert url_images[0]["id"] == "mock-url-extracted-image"
