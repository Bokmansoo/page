import pytest
import base64
from unittest.mock import MagicMock, patch
from src.services.image_generation_provider import ImageGenerationRequest, ImageGenerationResult
from src.services.openai_image_provider import OpenAIImageProvider
from openai import AuthenticationError, RateLimitError, APITimeoutError, BadRequestError


def test_image_generation_request_validation():
    # 1. preserve_product_identity=True and empty source_asset_paths should fail
    with pytest.raises(ValueError) as exc:
        ImageGenerationRequest(
            job_id="job-1",
            role="cutout_product",
            prompt="A sleek red apple juice bottle",
            preserve_product_identity=True,
            source_asset_paths=[]
        )
    assert "source_asset_paths must not be empty" in str(exc.value)

    # 2. preserve_product_identity=False and empty source_asset_paths should pass
    req = ImageGenerationRequest(
        job_id="job-2",
        role="badge_set",
        prompt="Organic certification badge",
        preserve_product_identity=False,
        source_asset_paths=[]
    )
    assert req.job_id == "job-2"
    assert req.preserve_product_identity is False


@patch("src.services.openai_image_provider.OpenAI")
def test_openai_provider_generate_text_only(mock_openai_class):
    # Mock client and response
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_response = MagicMock()
    mock_img_obj = MagicMock()
    mock_img_obj.b64_json = base64.b64encode(b"MOCK_PNG_DATA").decode("utf-8")
    mock_img_obj.revised_prompt = "A detailed prompt"
    mock_response.data = [mock_img_obj]

    mock_client.images.generate.return_value = mock_response

    provider = OpenAIImageProvider(api_key="mock-key", model="gpt-image-1.5")
    req = ImageGenerationRequest(
        job_id="job-non-product",
        role="badge_set",
        prompt="Organic badge",
        preserve_product_identity=False,
        source_asset_paths=[]
    )

    result = provider.generate(req)
    assert result.content == b"MOCK_PNG_DATA"
    assert result.provider == "openai"
    assert result.model == "gpt-image-1.5"
    assert result.revised_prompt == "A detailed prompt"

    mock_client.images.generate.assert_called_once_with(
        model="gpt-image-1.5",
        prompt="Organic badge",
        size="1024x1024",
        quality="medium",
        background="opaque",
        output_format="png",
    )
    mock_client.images.edit.assert_not_called()


@patch("src.services.openai_image_provider.OpenAI")
def test_openai_provider_generate_image_edit(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_response = MagicMock()
    mock_img_obj = MagicMock()
    mock_img_obj.b64_json = base64.b64encode(b"MOCK_EDITED_PNG").decode("utf-8")
    mock_img_obj.revised_prompt = None
    mock_response.data = [mock_img_obj]

    mock_client.images.edit.return_value = mock_response

    provider = OpenAIImageProvider(api_key="mock-key", model="gpt-image-1.5")
    req = ImageGenerationRequest(
        job_id="job-product",
        role="cutout_product",
        prompt="Sleek product shot",
        preserve_product_identity=True,
        source_asset_paths=[__file__, __file__],
        transparent_background=True
    )

    result = provider.generate(req)
    assert result.content == b"MOCK_EDITED_PNG"

    edit_kwargs = mock_client.images.edit.call_args.kwargs
    assert edit_kwargs["model"] == "gpt-image-1.5"
    assert edit_kwargs["quality"] == "medium"
    assert edit_kwargs["background"] == "transparent"
    assert edit_kwargs["output_format"] == "png"
    assert edit_kwargs["input_fidelity"] == "high"
    assert len(edit_kwargs["image"]) == 2
    mock_client.images.generate.assert_not_called()


@patch("src.services.openai_image_provider.OpenAI")
def test_openai_mini_edit_omits_unsupported_input_fidelity(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    mock_response = MagicMock()
    mock_img_obj = MagicMock()
    mock_img_obj.b64_json = base64.b64encode(b"MINI_EDITED_PNG").decode("utf-8")
    mock_img_obj.revised_prompt = None
    mock_response.data = [mock_img_obj]
    mock_client.images.edit.return_value = mock_response

    provider = OpenAIImageProvider(api_key="mock-key", model="gpt-image-1-mini")
    provider.generate(
        ImageGenerationRequest(
            job_id="mini-product",
            role="representative_product",
            prompt="상품 정체성을 유지한 거실 사용 장면",
            preserve_product_identity=True,
            source_asset_paths=[__file__],
        )
    )

    edit_kwargs = mock_client.images.edit.call_args.kwargs
    assert edit_kwargs["model"] == "gpt-image-1-mini"
    assert "input_fidelity" not in edit_kwargs


@patch("src.services.openai_image_provider.OpenAI")
def test_openai_provider_requires_edit_assets_when_preserving_identity(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    provider = OpenAIImageProvider(api_key="mock-key", model="gpt-image-1.5")
    req = ImageGenerationRequest(
        job_id="job-product",
        role="representative_product",
        prompt="Create a detail page product scene",
        preserve_product_identity=True,
        reference_asset_ids=["asset-uploaded-1"],
        source_asset_paths=[],
    )

    with pytest.raises(RuntimeError, match="REFERENCE_ASSET_PATHS_REQUIRED"):
        provider.generate(req)

    mock_client.images.edit.assert_not_called()
    mock_client.images.generate.assert_not_called()


@patch("src.services.openai_image_provider.OpenAI")
def test_openai_provider_error_mapping(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    # 1. Auth failure
    mock_client.images.generate.side_effect = AuthenticationError(
        message="Invalid API Key", response=MagicMock(status_code=401), body={}
    )
    provider = OpenAIImageProvider(api_key="invalid-key")
    req = ImageGenerationRequest(
        job_id="job-error",
        role="badge_set",
        prompt="badge",
        preserve_product_identity=False,
        source_asset_paths=[]
    )

    with pytest.raises(RuntimeError) as exc:
        provider.generate(req)
    assert "AUTHENTICATION_FAILED" in str(exc.value)

    # 2. Rate limit
    mock_client.images.generate.side_effect = RateLimitError(
        message="Too many requests", response=MagicMock(status_code=429), body={}
    )
    with pytest.raises(RuntimeError) as exc:
        provider.generate(req)
    assert "RATE_LIMIT_EXCEEDED" in str(exc.value)

    # 3. Timeout
    mock_client.images.generate.side_effect = APITimeoutError(
        request=MagicMock()
    )
    with pytest.raises(RuntimeError) as exc:
        provider.generate(req)
    assert "TIMEOUT" in str(exc.value)

    # 4. Moderation
    mock_client.images.generate.side_effect = BadRequestError(
        message="Your request was rejected by our safety system", response=MagicMock(status_code=400), body={}
    )
    with pytest.raises(RuntimeError) as exc:
        provider.generate(req)
    assert "MODERATION_REJECTED" in str(exc.value)


@patch("src.services.openai_image_provider.OpenAI")
def test_openai_provider_preserves_bad_request_detail(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    mock_client.images.generate.side_effect = BadRequestError(
        message="Invalid parameter: quality is not supported for this model",
        response=MagicMock(status_code=400),
        body={},
    )

    provider = OpenAIImageProvider(api_key="mock-key")
    req = ImageGenerationRequest(
        job_id="job-invalid-request",
        role="badge_set",
        prompt="badge",
        preserve_product_identity=False,
        source_asset_paths=[],
    )

    with pytest.raises(RuntimeError) as exc:
        provider.generate(req)

    message = str(exc.value)
    assert "INVALID_REQUEST" in message
    assert "quality is not supported" in message


@patch("src.services.openai_image_provider.OpenAI")
def test_openai_provider_maps_billing_hard_limit(mock_openai_class):
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client
    mock_client.images.generate.side_effect = BadRequestError(
        message="Billing hard limit has been reached.",
        response=MagicMock(status_code=400),
        body={
            "error": {
                "type": "billing_limit_user_error",
                "code": "billing_hard_limit_reached",
            }
        },
    )

    provider = OpenAIImageProvider(api_key="mock-key")
    req = ImageGenerationRequest(
        job_id="job-billing-limit",
        role="badge_set",
        prompt="badge",
        preserve_product_identity=False,
        source_asset_paths=[],
    )

    with pytest.raises(RuntimeError) as exc:
        provider.generate(req)

    message = str(exc.value)
    assert "BILLING_HARD_LIMIT_REACHED" in message
    assert "Billing hard limit" in message


def test_openai_provider_reports_missing_api_key_with_stable_error(monkeypatch):
    monkeypatch.setattr("src.services.openai_image_provider.settings.OPENAI_API_KEY", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="AUTHENTICATION_FAILED"):
        OpenAIImageProvider()
