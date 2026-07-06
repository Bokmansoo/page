import pytest
from pydantic import ValidationError
from src.services.image_generation_contract import ImageGenerationJob

def test_planned_job_requires_original_asset():
    with pytest.raises(ValidationError) as excinfo:
        ImageGenerationJob(
            job_id="job-1",
            section_id="sec-1",
            plan_signature="signature-1",
            role="representative_product",
            prompt="A nice product photo",
            status="planned",
        )

    assert "planned status" in str(excinfo.value)

def test_valid_needs_generation_job():
    job = ImageGenerationJob(
        job_id="job-2",
        section_id="sec-2",
        plan_signature="signature-1",
        role="lifestyle_scene",
        source_asset_ids=["asset-1"],
        prompt="Lifestyle shot with the fan on a table",
        preserve_product_identity=True,
        status="needs_generation"
    )
    assert job.status == "needs_generation"

def test_needs_generation_missing_prompt():
    with pytest.raises(ValidationError) as excinfo:
        ImageGenerationJob(
            job_id="job-3",
            section_id="sec-3",
            plan_signature="signature-1",
            role="cutout_product",
            source_asset_ids=["asset-1"],
            prompt="   ",
            status="needs_generation"
        )
    assert "Prompt must not be empty" in str(excinfo.value)

def test_needs_generation_missing_source_assets():
    with pytest.raises(ValidationError) as excinfo:
        ImageGenerationJob(
            job_id="job-4",
            section_id="sec-4",
            plan_signature="signature-1",
            role="representative_product",
            source_asset_ids=[],
            prompt="Nice photo",
            preserve_product_identity=True,
            status="needs_generation"
        )
    assert "source_asset_ids must not be empty" in str(excinfo.value)

def test_needs_generation_no_identity_preservation_empty_source():
    # If preserve_product_identity is False, source_asset_ids can be empty
    job = ImageGenerationJob(
        job_id="job-5",
        section_id="sec-5",
        plan_signature="signature-1",
        role="problem_scene",
        source_asset_ids=[],
        prompt="A hot summer room",
        preserve_product_identity=False,
        status="needs_generation"
    )
    assert job.status == "needs_generation"
    assert len(job.source_asset_ids) == 0
