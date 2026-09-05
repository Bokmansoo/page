import pytest
import io
import os
from PIL import Image
from unittest.mock import MagicMock
from src.db.models import User, Workspace, Brand, ProductProject, Asset, ImageGenerationJobRecord
from src.services.image_generation_provider import ImageGenerationResult
from src.services.image_generation_service import (
    _split_provider_error,
    get_or_create_job_record,
    execute_image_generation,
    sync_job_to_project_json
)
from src.services.product_identity_validator import (
    ProductIdentityValidationError,
    ProductIdentityValidator,
)


def generate_dummy_png(color="red", size=(512, 512)):
    img = Image.new("RGB", size, color=color)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 100, 100], fill="blue" if color == "red" else "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_redesigned_png(color="red", size=(512, 512)):
    """Keep product colour while changing the composition from the reference."""
    img = Image.new("RGB", size, color=color)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.rectangle([220, 220, 360, 360], fill="blue" if color == "red" else "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def db_setup(db_session):
    user = User(email="test_service@example.com", name="Service Tester")
    db_session.add(user)
    db_session.commit()

    workspace = Workspace(name="Service WS", owner_id=user.id)
    db_session.add(workspace)
    db_session.commit()

    brand = Brand(workspace_id=workspace.id, name="Service Brand")
    db_session.add(brand)
    db_session.commit()

    project = ProductProject(
        workspace_id=workspace.id,
        brand_id=brand.id,
        name="Service Project",
        visual_package_jobs=[
            {
                "job_id": "job-service-1",
                "section_id": "sec-1",
                "plan_signature": "sig-1",
                "role": "cutout_product",
                "prompt": "Sleek cutout product shot",
                "source_asset_ids": ["asset-ref-1"],
                "preserve_product_identity": True,
                "output_size": "512x512",
                "cost_tier": "standard",
                "status": "planned"
            },
            {
                "job_id": "job-service-2",
                "section_id": "sec-2",
                "plan_signature": "sig-1",
                "role": "badge_set",
                "prompt": "Logo of the organic certification",
                "source_asset_ids": [],
                "preserve_product_identity": False,
                "output_size": "512x512",
                "cost_tier": "standard",
                "status": "planned"
            }
        ]
    )
    db_session.add(project)
    db_session.commit()

    # Create dummy source assets
    ref_image_path = os.path.join(os.path.dirname(__file__), "dummy_ref.png")
    with open(ref_image_path, "wb") as f:
        f.write(generate_dummy_png(color="red"))

    asset_ref = Asset(
        id="asset-ref-1",
        project_id=project.id,
        source_type="sourced",
        filename="dummy_ref.png",
        file_path=ref_image_path,
        mime_type="image/png",
        file_size=len(generate_dummy_png(color="red"))
    )
    db_session.add(asset_ref)
    db_session.commit()

    yield {
        "user": user,
        "workspace": workspace,
        "brand": brand,
        "project": project,
        "asset_ref": asset_ref,
        "ref_image_path": ref_image_path
    }

    # Clean up dummy ref file
    if os.path.exists(ref_image_path):
        os.remove(ref_image_path)


def test_get_or_create_job_record(db_session, db_setup):
    project = db_setup["project"]
    record = get_or_create_job_record(project.id, "job-service-1", db_session)
    assert record.job_id == "job-service-1"
    assert record.role == "cutout_product"
    assert record.status == "planned"

    # Fetch again to verify same record is returned from DB
    record_2 = get_or_create_job_record(project.id, "job-service-1", db_session)
    assert record_2.id == record.id


def test_execute_image_generation_requires_cost_approval(db_session, db_setup):
    project = db_setup["project"]
    
    # 1. First execution without cost_approved: sets awaiting_cost_approval
    record = execute_image_generation(project.id, "job-service-1", db_session, cost_approved=False)
    assert record.status == "awaiting_cost_approval"

    # Check project JSON sync
    db_session.refresh(project)
    synced_job = next(j for j in project.visual_package_jobs if j["job_id"] == "job-service-1")
    assert synced_job["status"] == "awaiting_cost_approval"


def test_execute_image_generation_success(db_session, db_setup):
    project = db_setup["project"]
    
    # Mock Provider
    mock_provider = MagicMock()
    mock_result = ImageGenerationResult(
        content=generate_redesigned_png(color="red"), # keeps colour but changes layout
        mime_type="image/png",
        provider="openai",
        model="gpt-image-1.5",
        usage_metadata={"cost": 0.04}
    )
    mock_provider.generate.return_value = mock_result

    # Execute with cost_approved=True
    record = execute_image_generation(
        project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
    )

    assert record.status == "needs_review"
    assert record.error_code is None
    assert record.output_asset_id is not None
    assert record.warnings is None or len(record.warnings) == 0
    assert record.actual_cost == 0.04

    # Verify output asset was registered
    out_asset = db_session.query(Asset).filter(Asset.id == record.output_asset_id).first()
    assert out_asset is not None
    assert out_asset.source_type == "ai_generated"
    assert os.path.exists(out_asset.file_path)

    # Clean up generated image file
    if os.path.exists(out_asset.file_path):
        os.remove(out_asset.file_path)

    # Idempotency check: execute again, should not call generate again
    mock_provider.reset_mock()
    record_idempotent = execute_image_generation(
        project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
    )
    assert record_idempotent.status == "needs_review"
    mock_provider.generate.assert_not_called()


def test_execute_image_generation_color_drift_warning(db_session, db_setup):
    project = db_setup["project"]
    
    # Mock Provider returning a BLUE image (differs from RED source image)
    mock_provider = MagicMock()
    mock_result = ImageGenerationResult(
        content=generate_redesigned_png(color="blue"),
        mime_type="image/png",
        provider="openai",
        model="gpt-image-1.5",
        usage_metadata={"cost": 0.04}
    )
    mock_provider.generate.return_value = mock_result

    # Execute
    record = execute_image_generation(
        project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
    )

    # Output is still needs_review but contains warning for color drift
    assert record.status == "needs_review"
    assert record.warnings is not None
    assert any("color drift" in w.lower() for w in record.warnings)

    # Clean up output file
    out_asset = db_session.query(Asset).filter(Asset.id == record.output_asset_id).first()
    if out_asset and os.path.exists(out_asset.file_path):
        os.remove(out_asset.file_path)


def test_execute_image_generation_rejection_identity_gate(db_session, db_setup):
    project = db_setup["project"]
    
    # job-service-2 requests "logo" in prompt. Since badge_set is preserve_product_identity=False in json,
    # let's modify record preserve_product_identity to True and role to product related, or verify directly.
    # Actually, job-service-1 is cutout_product. If we update its prompt to contain "logo":
    record = get_or_create_job_record(project.id, "job-service-1", db_session)
    record.prompt = "Sleek cutout product shot containing text logo"
    record.usage_metadata = {"langgraph_run_id": "lg9-identity-gate-run"}
    record.input_snapshot = {
        "scene_prompt": {
            "rights_snapshot": [{"asset_id": "asset-ref-1", "rights_status": "reference_only"}],
        }
    }
    db_session.commit()

    mock_provider = MagicMock()
    mock_result = ImageGenerationResult(
        content=generate_redesigned_png(color="red"),
        mime_type="image/png",
        provider="openai",
        model="gpt-image-1.5",
        usage_metadata={"cost": 0.04}
    )
    mock_provider.generate.return_value = mock_result

    record = execute_image_generation(
        project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
    )

    assert record.status == "failed"
    assert record.error_code == "IDENTITY_GATE_REJECTED"
    assert record.validation_result["schema_version"] == "lg9-image-validation-v1"
    assert record.validation_result["status"] == "blocked"
    assert record.validation_result["checks"]["identity"] == "blocked"

    # Clean up output file
    out_asset = db_session.query(Asset).filter(Asset.id == record.output_asset_id).first()
    if out_asset and os.path.exists(out_asset.file_path):
        os.remove(out_asset.file_path)


def test_execute_image_generation_provider_failure(db_session, db_setup):
    project = db_setup["project"]
    
    mock_provider = MagicMock()
    mock_provider.generate.side_effect = RuntimeError("RATE_LIMIT_EXCEEDED")

    with pytest.raises(RuntimeError) as exc:
        execute_image_generation(
            project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
        )
    assert "RATE_LIMIT_EXCEEDED" in str(exc.value)

    record = get_or_create_job_record(project.id, "job-service-1", db_session)
    assert record.status == "failed"
    assert record.error_code == "RATE_LIMIT_EXCEEDED"


def test_split_provider_error_rejects_raw_exception_text_from_persisted_code_or_action():
    markers = (
        "PROMPT_SECRET_7F3A",
        "https://signed.example/private?token=SECRET_TOKEN_9C2",
        "customer@example.com",
    )

    code, action = _split_provider_error(RuntimeError(" ".join(markers)))

    assert code == "PROVIDER_ERROR"
    assert action
    assert all(marker not in action for marker in markers)


def test_execute_image_generation_persists_only_safe_provider_failure_detail(db_session, db_setup):
    project = db_setup["project"]

    mock_provider = MagicMock()
    mock_provider.generate.side_effect = RuntimeError(
        "INVALID_REQUEST: Invalid parameter: quality is not supported for this model"
    )

    with pytest.raises(RuntimeError):
        execute_image_generation(
            project.id,
            "job-service-1",
            db_session,
            cost_approved=True,
            provider_override=mock_provider,
        )

    record = get_or_create_job_record(project.id, "job-service-1", db_session)
    assert record.status == "failed"
    assert record.error_code == "INVALID_REQUEST"
    assert record.warnings
    assert "quality is not supported" not in record.warnings[0]
    assert record.warnings[0]


def test_execute_retries_one_transient_provider_failure(db_session, db_setup):
    project = db_setup["project"]
    mock_provider = MagicMock()
    mock_provider.generate.side_effect = [
        RuntimeError("RATE_LIMIT_EXCEEDED"),
        ImageGenerationResult(
            content=generate_redesigned_png(color="red"),
            mime_type="image/png",
            provider="openai",
            model="gpt-image-1.5",
        ),
    ]

    record = execute_image_generation(
        project.id,
        "job-service-1",
        db_session,
        cost_approved=True,
        provider_override=mock_provider,
    )

    assert record.status == "needs_review"
    assert mock_provider.generate.call_count == 2
    assert [item["status"] for item in record.usage_metadata["attempt_history"]] == [
        "failed",
        "needs_review",
    ]
    assert record.usage_metadata["attempt_history"][0]["error_code"] == "RATE_LIMIT_EXCEEDED"

    output = db_session.query(Asset).filter(Asset.id == record.output_asset_id).first()
    if output and os.path.exists(output.file_path):
        os.remove(output.file_path)


def test_langgraph_real_provider_failure_is_not_retried_or_failed_over(monkeypatch, db_session, db_setup):
    """Paid production scenes require an explicit seller-approved retry."""

    project = db_setup["project"]
    record = get_or_create_job_record(project.id, "job-service-1", db_session)
    record.usage_metadata = {"langgraph_run_id": "lg9-provider-policy"}
    db_session.commit()
    monkeypatch.setattr(
        "src.services.image_generation_service.settings.SELLFORM_IMAGE_GENERATION_MODE",
        "real",
    )
    mock_provider = MagicMock()
    mock_provider.generate.side_effect = RuntimeError("TIMEOUT")

    with pytest.raises(RuntimeError, match="TIMEOUT"):
        execute_image_generation(
            project.id,
            "job-service-1",
            db_session,
            cost_approved=True,
            provider_override=mock_provider,
        )

    assert mock_provider.generate.call_count == 1
    db_session.refresh(record)
    assert record.status == "failed"
    assert record.error_code == "TIMEOUT"
    attempts = record.usage_metadata["attempt_history"]
    assert len(attempts) == 1
    assert attempts[0]["attempt"] == 1
    assert attempts[0]["status"] == "failed"
    assert attempts[0]["error_code"] == "TIMEOUT"


def test_execute_blocks_missing_source_file_before_provider_call(db_session, db_setup):
    project = db_setup["project"]
    db_setup["asset_ref"].file_path = "missing/source.png"
    db_session.commit()
    mock_provider = MagicMock()

    with pytest.raises(ValueError, match="Source asset file"):
        execute_image_generation(
            project.id,
            "job-service-1",
            db_session,
            cost_approved=True,
            provider_override=mock_provider,
        )

    mock_provider.generate.assert_not_called()


def test_negative_exclusion_prompt_does_not_trigger_identity_rejection(db_session, db_setup):
    project = db_setup["project"]
    record = get_or_create_job_record(project.id, "job-service-1", db_session)
    record.prompt = (
        "Sleek cutout product shot. Strictly do NOT include any text, "
        "words, logos, badges, or certification marks in the image."
    )
    db_session.commit()

    mock_provider = MagicMock()
    mock_provider.generate.return_value = ImageGenerationResult(
        content=generate_redesigned_png(color="red"),
        mime_type="image/png",
        provider="openai",
        model="gpt-image-1.5",
    )

    record = execute_image_generation(
        project.id,
        "job-service-1",
        db_session,
        cost_approved=True,
        provider_override=mock_provider,
    )

    assert record.status == "needs_review"


def test_generated_price_or_market_text_is_blocked(db_session, db_setup, monkeypatch):
    from src.services import asset_understanding_service

    project = db_setup["project"]
    job = get_or_create_job_record(project.id, "job-service-1", db_session)
    job.usage_metadata = {"langgraph_run_id": "lg9-validation-run"}
    job.input_snapshot = {
        "scene_prompt": {
            "rights_snapshot": [{"asset_id": "asset-ref-1", "rights_status": "reference_only"}],
        }
    }
    db_session.commit()
    monkeypatch.setattr(
        asset_understanding_service,
        "extract_ocr_blocks",
        lambda _asset: ([{"text": "쿠팡 특가 39,900원"}], "test_ocr"),
    )
    mock_provider = MagicMock()
    mock_provider.generate.return_value = ImageGenerationResult(
        content=generate_redesigned_png(color="red"),
        mime_type="image/png",
        provider="openai",
        model="gpt-image-1.5",
    )

    record = execute_image_generation(
        project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
    )

    assert record.status == "blocked"
    assert record.error_code == "UNSAFE_GENERATED_CONTENT_DETECTED"
    assert record.validation_result["schema_version"] == "lg9-image-validation-v1"
    assert record.validation_result["checks"]["safety"] == "blocked"
    assert record.validation_result["checks"]["ocr"] == "needs_review"
    assert record.validation_result["status"] == "blocked"
    assert set(record.validation_result["risk_codes"]) >= {"price_exposed", "market_or_competitor_text"}
    output = db_session.query(Asset).filter(Asset.id == record.output_asset_id).first()
    assert output.quality_status == "rejected"
    if output and os.path.exists(output.file_path):
        os.remove(output.file_path)

    output = db_session.query(Asset).filter(Asset.id == record.output_asset_id).first()
    if output and os.path.exists(output.file_path):
        os.remove(output.file_path)


def test_langgraph_job_with_blocked_reference_rights_is_blocked(db_session, db_setup):
    project = db_setup["project"]
    job = get_or_create_job_record(project.id, "job-service-1", db_session)
    job.usage_metadata = {"langgraph_run_id": "lg9-rights-run"}
    job.input_snapshot = {
        "scene_prompt": {
            "rights_snapshot": [{"asset_id": "asset-ref-1", "rights_status": "blocked"}],
        }
    }
    db_session.commit()
    mock_provider = MagicMock()
    mock_provider.generate.return_value = ImageGenerationResult(
        content=generate_redesigned_png(color="red"),
        mime_type="image/png",
        provider="openai",
        model="gpt-image-1.5",
    )

    record = execute_image_generation(
        project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
    )

    assert record.status == "blocked"
    assert record.error_code == "RIGHTS_BLOCKED"
    assert record.validation_result["checks"]["rights"] == "blocked"
    assert record.validation_result["status"] == "blocked"
    output = db_session.query(Asset).filter(Asset.id == record.output_asset_id).first()
    assert output.quality_status == "rejected"
    if output and os.path.exists(output.file_path):
        os.remove(output.file_path)


def test_langgraph_validation_routes_resolution_and_crop_thresholds_to_review(db_session, db_setup):
    project = db_setup["project"]
    job = get_or_create_job_record(project.id, "job-service-1", db_session)
    job.preserve_product_identity = False
    job.usage_metadata = {"langgraph_run_id": "lg9-threshold-review-run"}
    job.input_snapshot = {
        "scene_prompt": {
            "rights_snapshot": [{"asset_id": "asset-ref-1", "rights_status": "reference_only"}],
        }
    }
    db_session.commit()
    mock_provider = MagicMock()
    mock_provider.generate.return_value = ImageGenerationResult(
        content=generate_redesigned_png(color="red", size=(512, 1024)),
        mime_type="image/png",
        provider="openai",
        model="gpt-image-1.5",
    )

    record = execute_image_generation(
        project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
    )

    assert record.status == "needs_review"
    assert record.validation_result["status"] == "needs_review"
    assert record.validation_result["checks"]["resolution"] == "needs_review"
    assert record.validation_result["checks"]["crop"] == "needs_review"
    output = db_session.query(Asset).filter(Asset.id == record.output_asset_id).first()
    if output and os.path.exists(output.file_path):
        os.remove(output.file_path)


def test_langgraph_quality_gate_failure_has_blocked_validation_report(db_session, db_setup):
    project = db_setup["project"]
    job = get_or_create_job_record(project.id, "job-service-1", db_session)
    job.usage_metadata = {"langgraph_run_id": "lg9-quality-gate-run"}
    job.input_snapshot = {
        "scene_prompt": {
            "rights_snapshot": [{"asset_id": "asset-ref-1", "rights_status": "reference_only"}],
        }
    }
    db_session.commit()
    mock_provider = MagicMock()
    mock_provider.generate.return_value = ImageGenerationResult(
        content=generate_redesigned_png(color="red"),
        mime_type="image/webp",
        provider="openai",
        model="gpt-image-1.5",
    )

    record = execute_image_generation(
        project.id, "job-service-1", db_session, cost_approved=True, provider_override=mock_provider
    )

    assert record.status == "blocked"
    assert record.error_code == "QUALITY_GATE_FAILED"
    assert record.validation_result["schema_version"] == "lg9-image-validation-v1"
    assert record.validation_result["status"] == "blocked"
    assert record.validation_result["checks"]["identity"] == "not_run"
    assert record.validation_result["checks"]["resolution"] == "not_run"


def test_quality_gate_rejects_mime_type_mismatch():
    with pytest.raises(ProductIdentityValidationError, match="MIME type"):
        ProductIdentityValidator.validate_image_quality(
            content_bytes=generate_dummy_png(),
            mime_type="image/webp",
        )


def test_lg9_structural_identity_checks_do_not_pass_without_feature_evidence(tmp_path):
    source_path = tmp_path / "identity-source.png"
    source = Image.new("RGB", (128, 128), "white")
    source.save(source_path)
    output = Image.new("RGB", (128, 128), "white")
    from PIL import ImageDraw

    ImageDraw.Draw(output).rectangle((48, 48, 80, 80), fill="gray")

    report = ProductIdentityValidator.inspect_identity_preservation(
        img=output,
        source_asset_paths=[str(source_path)],
        prompt="Preserve the product structure in a new composition.",
        role="representative_product",
        identity_constraints={"preserve_exactly": ["buttons", "ports", "components", "logo"]},
    )

    assert report["status"] == "needs_review"
    for element in ("buttons", "ports", "components", "logo"):
        assert report["checks"][element] == {
            "status": "needs_review",
            "reason": "structured_reference_unavailable",
        }


def test_lg9_structural_identity_regions_check_each_required_element(tmp_path):
    from PIL import ImageDraw

    boxes = {
        "buttons": [0.05, 0.05, 0.2, 0.2],
        "ports": [0.8, 0.05, 0.95, 0.2],
        "components": [0.05, 0.8, 0.2, 0.95],
        "logo": [0.8, 0.8, 0.95, 0.95],
    }
    pixel_boxes = {
        key: tuple(int(round(value * 128)) for value in box)
        for key, box in boxes.items()
    }
    colors = {"buttons": "black", "ports": "navy", "components": "green", "logo": "purple"}
    source = Image.new("RGB", (128, 128), "white")
    source_draw = ImageDraw.Draw(source)
    for element, box in pixel_boxes.items():
        source_draw.rectangle(box, fill=colors[element])
    source_path = tmp_path / "identity-regions-source.png"
    source.save(source_path)

    output = source.copy()
    ImageDraw.Draw(output).rectangle((48, 48, 80, 80), fill="gray")
    constraints = {
        "feature_regions": {
            element: [{"reference_box": box, "output_box": box}]
            for element, box in boxes.items()
        }
    }
    preserved = ProductIdentityValidator.inspect_identity_preservation(
        img=output,
        source_asset_paths=[str(source_path)],
        prompt="Preserve the product structure in a new composition.",
        role="representative_product",
        identity_constraints=constraints,
    )
    assert preserved["status"] == "passed"
    assert all(preserved["checks"][element]["status"] == "passed" for element in boxes)

    changed = output.copy()
    ImageDraw.Draw(changed).rectangle(pixel_boxes["ports"], fill="white")
    mismatched = ProductIdentityValidator.inspect_identity_preservation(
        img=changed,
        source_asset_paths=[str(source_path)],
        prompt="Preserve the product structure in a new composition.",
        role="representative_product",
        identity_constraints=constraints,
    )
    assert mismatched["status"] == "needs_review"
    assert mismatched["checks"]["ports"]["status"] == "needs_review"
    assert mismatched["checks"]["ports"]["reason"] == "region_mismatch"
    assert all(
        mismatched["checks"][element]["status"] == "passed"
        for element in ("buttons", "components", "logo")
    )
