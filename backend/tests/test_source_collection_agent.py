from src.agents.nodes.source_collection.agent import SourceCollectionAgent
from src.agents.nodes.source_collection.schema import AgentOutputSchema
from src.agents.state import AgentRunState, ProductInput


def test_source_collection_preserves_uploaded_and_url_sources():
    state = AgentRunState(
        project_id="project-1",
        input_snapshot={
            "product_name": "삼성 삼탠바이미 32인치 스마트모니터",
            "product_url": "https://example.com/product",
            "uploaded_assets": [
                {"asset_id": "asset-1", "filename": "삼탠바이미.png", "mime_type": "image/png"}
            ],
            "url_images": [
                {"asset_id": "url-asset-1", "filename": "상세페이지-참고.png", "source_type": "url-extracted"}
            ],
        },
    )

    result = SourceCollectionAgent().run(state)
    sources = result.outputs["source_collection"]
    parsed = AgentOutputSchema.model_validate(sources)

    assert parsed.product_url == "https://example.com/product"
    assert parsed.uploaded_images[0].asset_id == "asset-1"
    assert parsed.uploaded_images[0].source_type == "uploaded"
    assert parsed.url_images[0].asset_id == "url-asset-1"
    assert parsed.url_images[0].source_type == "url-extracted"
    assert parsed.source_summary.has_uploaded_image is True
    assert parsed.source_summary.has_product_url is True


def test_source_collection_preserves_freeform_and_reference_urls():
    state = AgentRunState(
        project_id="project-1",
        product_input=ProductInput(
            product_name="",
            description="",
            product_url="https://example.com/product",
            asset_ids=["asset-1"],
            reference_urls=["https://example.com/reference"],
            freeform_input="아이 첫 자전거입니다. LED 조명이 있습니다.",
        ),
    )

    result = SourceCollectionAgent().run(state)
    output = result.outputs["source_collection"]

    assert output["product_url"] == "https://example.com/product"
    assert output["reference_urls"] == ["https://example.com/reference"]
    assert output["freeform_input"] == "아이 첫 자전거입니다. LED 조명이 있습니다."
    assert output["source_summary"]["has_freeform_input"] is True
