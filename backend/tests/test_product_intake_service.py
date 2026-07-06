import pytest
from src.services.product_intake_service import ProductIntakeInput, normalize_intake_input

def test_normalize_empty_input_raises_value_error():
    # Completely empty lists and None description
    empty_input = ProductIntakeInput(
        urls=[],
        description=None,
        asset_ids=[],
        reference_urls=[],
        competitor_urls=[]
    )
    with pytest.raises(ValueError, match="Product intake input cannot be completely empty"):
        normalize_intake_input(empty_input)

    # Empty strings/spaces inside lists and description
    whitespace_input = ProductIntakeInput(
        urls=["   ", ""],
        description="    ",
        asset_ids=[""],
        reference_urls=[],
        competitor_urls=[" "]
    )
    with pytest.raises(ValueError, match="Product intake input cannot be completely empty"):
        normalize_intake_input(whitespace_input)


def test_normalize_mixed_input_success():
    valid_input = ProductIntakeInput(
        urls=["  https://example.com/item1  ", "https://example.com/item1", "  https://example.com/item2 "],
        description="  Premium Bamboo Table Mat  ",
        asset_ids=["asset-1", " asset-2 ", "asset-1"],
        reference_urls=[" https://ref.com ", "https://ref.com"],
        competitor_urls=["https://comp.com/1", "   "]
    )
    
    normalized = normalize_intake_input(valid_input)
    
    # Assert deduplication and trimming of URLs
    assert normalized.urls == ["https://example.com/item1", "https://example.com/item2"]
    
    # Assert trimming of description
    assert normalized.description == "Premium Bamboo Table Mat"
    
    # Assert deduplication and trimming of asset_ids
    assert normalized.asset_ids == ["asset-1", "asset-2"]
    
    # Assert reference URLs
    assert normalized.reference_urls == ["https://ref.com"]
    
    # Assert competitor URLs
    assert normalized.competitor_urls == ["https://comp.com/1"]


def test_normalize_single_source_success():
    # Only description is provided
    description_only = ProductIntakeInput(description="Only some text description")
    normalized = normalize_intake_input(description_only)
    assert normalized.description == "Only some text description"
    assert len(normalized.urls) == 0

    # Only URLs provided
    urls_only = ProductIntakeInput(urls=["https://only-url.com"])
    normalized_urls = normalize_intake_input(urls_only)
    assert normalized_urls.urls == ["https://only-url.com"]
    assert normalized_urls.description is None
