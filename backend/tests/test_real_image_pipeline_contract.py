import pytest
from src.services.image_generation_provider import ImageGenerationRequest

def test_image_provider_requires_cost_approval_for_real_jobs():
    # Since MockImageGenerationProvider is not yet implemented/imported, this will fail.
    from src.services.image_generation_provider import MockImageGenerationProvider
    
    provider = MockImageGenerationProvider()
    request = ImageGenerationRequest(
        job_id="job-1",
        role="hero",
        prompt="밝은 거실에서 유아 자전거를 보여주는 상세페이지 이미지",
        reference_asset_ids=["asset-1"],
        requires_cost_approval=True,
        cost_approved=False,
    )
    result = provider.generate(request)
    assert result.status == "blocked_cost_approval"


@pytest.fixture
def image_generation_service(db_session):
    from src.services.image_generation_service import ImageGenerationService
    return ImageGenerationService(db_session)


def test_generated_product_image_requires_identity_check(image_generation_service):
    result = image_generation_service.review_generated_asset(
        source_asset_id="asset-original",
        generated_asset_id="asset-generated",
        product_identity_required=True,
    )
    assert result["identity_check"]["status"] in {"passed", "needs_review", "failed"}
