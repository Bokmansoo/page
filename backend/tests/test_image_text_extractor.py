from src.services.image_text_extractor import MockImageTextExtractor


def test_mock_image_text_extractor_returns_text_for_spec_like_filename():
    extractor = MockImageTextExtractor()

    result = extractor.extract(
        asset_id="asset-1",
        filename="portable_fan_4000mah_usb_c_spec.jpg",
        file_path="uploads/portable_fan_4000mah_usb_c_spec.jpg",
    )

    assert result.asset_id == "asset-1"
    assert "USB-C" in result.extracted_text
    assert "4000mAh" in result.extracted_text
    assert result.confidence >= 0.5
    assert result.provider == "mock"


def test_mock_image_text_extractor_reports_no_text_for_generic_image():
    extractor = MockImageTextExtractor()

    result = extractor.extract(
        asset_id="asset-2",
        filename="plain_product_photo.jpg",
        file_path="uploads/plain_product_photo.jpg",
    )

    assert result.extracted_text == ""
    assert result.confidence == 0.0
    assert "no_text_detected" in result.warnings
