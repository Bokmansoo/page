import pytest
from src.services.image_generation_provider import (
    ImageGenerationRequest,
    ImageGenerationProviderRouter,
)
from src.services.openai_image_provider import OpenAIImageProvider
from src.agents.nodes.visual_planning.agent import VisualPlanningAgent
from src.agents.nodes.image_generation.agent import ImageGenerationAgent
from src.agents.state import AgentRunMode, AgentRunState, ProductInput

def test_real_image_generation_is_blocked_without_cost_approval():
    router = ImageGenerationProviderRouter(mode="real", primary_provider="openai")
    request = ImageGenerationRequest(
        job_id="job-1",
        slot_id="hero",
        role="representative_product",
        prompt="밝은 거실에서 스마트모니터가 공간을 넓게 쓰게 해주는 상세페이지 대표 이미지",
        reference_asset_ids=["asset-uploaded-1"],
        cost_approved=False,
        product_identity_required=True,
    )

    result = router.generate(request)
    assert result.status == "blocked_cost_approval"
    assert result.assets == []

def test_visual_planning_creates_commerce_image_jobs():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "page_planning": {
                "sections": [
                    {"section_id": "hero", "role": "hero"},
                    {"section_id": "comparison", "role": "problem"},
                ]
            },
            "copywriting": {
                "sections": {
                    "hero": {"title": "32인치에서 TV처럼, 모니터처럼"},
                    "comparison": {"title": "TV는 거실에만, 모니터는 책상에만 있었나요?"},
                }
            },
            "product_understanding": {
                "product_type": "smart_monitor",
                "identity_rules": ["화면과 무빙 스탠드 형태 보존"],
            },
        },
    )

    result = VisualPlanningAgent().run(state)
    jobs = result.outputs["visual_planning"]["image_jobs"]

    assert jobs[0]["slot_id"] == "hero"
    assert "상세페이지" in jobs[0]["prompt"]
    assert jobs[0]["product_identity_required"] is True

def test_visual_planning_marks_generated_jobs_as_text_free():
    state = AgentRunState(
        project_id="project-1",
        product_input=ProductInput(
            product_name="아이 LED 자전거",
            description="LED 조명과 보조바퀴",
            asset_ids=["asset-1"],
        ),
    )

    result = VisualPlanningAgent().run(state)
    jobs = result.outputs["visual_planning"]["image_jobs"]

    assert jobs
    assert all(job["text_free_required"] is True for job in jobs)
    assert all("No text" in job["prompt"] for job in jobs)
    assert all("no Korean letters" in job["prompt"] for job in jobs)
    assert all(job["visual_strategy"] == "cutout_composite" for job in jobs)
    assert all(job["source_asset_ids"] == ["asset-1"] for job in jobs)


def test_image_generation_skips_html_graphic_slots():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "visual_planning": {
                "visual_slots": [
                    {
                        "slot_id": "comparison",
                        "role": "comparison",
                        "visual_strategy": "html_graphic",
                    }
                ],
                "image_jobs": [],
            }
        },
    )

    output = ImageGenerationAgent(mode="mock").run(state).outputs["image_generation"]

    assert output["candidates"]["comparison"][0]["source_type"] == "html-graphic"
    assert output["jobs"][0]["status"] == "skipped_html_graphic"


def test_image_generation_agent_records_blocked_jobs_when_not_approved():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "visual_planning": {
                "image_jobs": [
                    {
                        "job_id": "hero-1",
                        "slot_id": "hero",
                        "prompt": "상세페이지 대표 이미지",
                        "reference_asset_ids": ["asset-1"],
                        "product_identity_required": True,
                    }
                ]
            }
        },
        cost_approval_status="not_approved",
    )

    result = ImageGenerationAgent(mode="real").run(state)
    image_output = result.outputs["image_generation"]

    assert image_output["jobs"][0]["status"] == "blocked_cost_approval"
    assert image_output["candidates"]["hero"] == []

def test_image_generation_agent_uses_image_jobs_when_visual_slots_are_missing():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "visual_planning": {
                "image_jobs": [
                    {
                        "job_id": "usage-1",
                        "slot_id": "usage_scene",
                        "role": "usage_scene",
                        "prompt": "상세페이지 사용 장면 이미지",
                        "reference_asset_ids": ["asset-1"],
                        "product_identity_required": True,
                    }
                ]
            }
        },
        cost_approval_status="approved",
    )

    result = ImageGenerationAgent(mode="mock").run(state)
    image_output = result.outputs["image_generation"]

    assert "usage_scene" in image_output["candidates"]
    assert image_output["jobs"][0]["slot_id"] == "usage_scene"

def test_real_provider_failure_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(OpenAIImageProvider, "__init__", lambda self, *args, **kwargs: None)

    def fail_generate(self, request):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(OpenAIImageProvider, "generate", fail_generate)
    router = ImageGenerationProviderRouter(mode="real", primary_provider="openai")
    request = ImageGenerationRequest(
        job_id="job-1",
        slot_id="hero",
        role="representative_product",
        prompt="상세페이지 대표 이미지",
        reference_asset_ids=["asset-uploaded-1"],
        cost_approved=True,
        product_identity_required=True,
    )

    result = router.generate(request)

    assert result.status == "provider_error"
    assert result.assets == []
    assert result.usage_metadata["error"] == "provider unavailable"

def test_real_text_image_generation_calls_provider_from_visual_plan(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "real")
    calls = []

    def fake_generate(self, request):
        calls.append(request)
        from src.services.image_generation_provider import ImageGenerationResult

        return ImageGenerationResult(
            content=b"fake-image",
            provider="openai",
            model="gpt-image-1-mini",
            status="success",
            assets=["asset-generated-hero"],
            usage_metadata={"image_output_tokens": 100},
        )

    monkeypatch.setattr(ImageGenerationProviderRouter, "generate", fake_generate)

    state = AgentRunState(
        project_id="project-1",
        mode=AgentRunMode.REAL,
        product_input=ProductInput(
            product_name="삼탠바이미",
            asset_ids=[],
        ),
        outputs={
            "visual_planning": {
                "image_jobs": [
                    {
                        "job_id": "hero-job",
                        "slot_id": "hero",
                        "role": "representative_product",
                        "prompt": "삼탠바이미 상세페이지 히어로 이미지",
                        "reference_asset_ids": [],
                        "product_identity_required": False,
                    }
                ]
            }
        },
        cost_approval_status="approved",
    )

    result = ImageGenerationAgent(mode="real").run_real_text(state, generate_output=None)
    image_output = result.outputs["image_generation"]

    assert len(calls) == 1
    assert calls[0].prompt == "삼탠바이미 상세페이지 히어로 이미지"
    assert image_output.get("skipped") is not True
    assert image_output["jobs"][0]["status"] == "success"
    assert image_output["candidates"]["hero"][0]["asset_id"] == "asset-generated-hero"
    assert image_output["images"][0]["id"] == "asset-generated-hero"


def test_generated_candidate_is_recommended_over_uploaded_source(monkeypatch):
    from src.services.image_generation_provider import ImageGenerationResult

    def fake_generate(self, request):
        return ImageGenerationResult(
            content=b"fake-image",
            provider="openai",
            model="gpt-image-1-mini",
            status="success",
            assets=["asset-generated-hero"],
        )

    monkeypatch.setattr(ImageGenerationProviderRouter, "generate", fake_generate)

    state = AgentRunState(
        project_id="project-1",
        product_input=ProductInput(product_name="삼탠바이미"),
        outputs={
            "source_collection": {
                "uploaded_images": [
                    {
                        "asset_id": "asset-uploaded-1",
                        "filename": "삼탠바이미.png",
                        "source_type": "uploaded",
                    }
                ]
            },
            "visual_planning": {
                "visual_slots": [{"slot_id": "hero", "role": "representative_product"}],
                "image_jobs": [
                    {
                        "job_id": "hero-1",
                        "slot_id": "hero",
                        "role": "representative_product",
                        "prompt": "거실에서 사용하는 삼탠바이미 히어로 장면",
                        "reference_asset_ids": [],
                        "product_identity_required": False,
                    }
                ],
            },
        },
        cost_approval_status="approved",
    )

    result = ImageGenerationAgent(mode="real").run(state)
    candidates = result.outputs["image_generation"]["candidates"]["hero"]

    uploaded = next(item for item in candidates if item["source_type"] == "uploaded")
    generated = next(item for item in candidates if item["source_type"] == "real-generated")
    assert uploaded["is_recommended"] is False
    assert generated["is_recommended"] is True


def test_provider_error_is_exposed_on_job_report(monkeypatch):
    from src.services.image_generation_provider import ImageGenerationResult

    def fake_generate(self, request):
        return ImageGenerationResult(
            content=b"",
            provider="openai",
            model="gpt-image-1-mini",
            status="provider_error",
            usage_metadata={"error": "ORGANIZATION_VERIFICATION_REQUIRED"},
        )

    monkeypatch.setattr(ImageGenerationProviderRouter, "generate", fake_generate)

    state = AgentRunState(
        project_id="project-1",
        product_input=ProductInput(product_name="삼탠바이미"),
        outputs={
            "visual_planning": {
                "visual_slots": [{"slot_id": "hero", "role": "representative_product"}],
                "image_jobs": [
                    {
                        "job_id": "hero-1",
                        "slot_id": "hero",
                        "role": "representative_product",
                        "prompt": "거실 사용 장면",
                        "reference_asset_ids": [],
                        "product_identity_required": False,
                    }
                ],
            }
        },
        cost_approval_status="approved",
    )

    result = ImageGenerationAgent(mode="real").run(state)
    report = result.outputs["image_generation"]["jobs"][0]

    assert report["status"] == "provider_error"
    assert report["error_code"] == "ORGANIZATION_VERIFICATION_REQUIRED"


def test_visual_planning_builds_section_specific_reference_jobs():
    state = AgentRunState(
        project_id="project-1",
        product_input=ProductInput(
            product_name="삼탠바이미 32인치 스마트모니터",
            asset_ids=["asset-uploaded-1"],
        ),
        outputs={
            "page_planning": {
                "sections": [
                    {"id": "hero", "name": "대표 연출"},
                    {"id": "comparison", "name": "불편 비교"},
                    {"id": "detail_1", "name": "사용 장면"},
                    {"id": "detail_2", "name": "기능 강조"},
                    {"id": "guarantee", "name": "구매 전 확인"},
                ]
            },
            "copywriting": {
                "hero_title": "공간마다 옮겨 쓰는 스마트모니터",
                "hero_subtitle": "거실과 침실을 오가며 편하게 시청하세요.",
                "painpoint_title": "TV는 고정되어 불편했나요?",
                "feature_1_title": "무빙 스탠드로 각도 조절",
                "feature_2_title": "32인치 화면을 원하는 곳에서",
                "guarantee_title": "구매 전 핵심 스펙 확인",
            },
        },
    )

    result = VisualPlanningAgent().run(state)
    jobs = result.outputs["visual_planning"]["image_jobs"]

    assert [job["slot_id"] for job in jobs] == ["hero", "detail_2"]
    assert all(job["reference_asset_ids"] == ["asset-uploaded-1"] for job in jobs)
    assert all(job["candidate_count"] == 1 for job in jobs)
    assert all("상세페이지" in job["prompt"] for job in jobs)
    assert "공간마다 옮겨 쓰는 스마트모니터" in jobs[0]["prompt"]
    assert "TV는 고정되어 불편했나요?" in jobs[1]["prompt"]


def test_real_image_generation_does_not_fallback_to_text_only_when_reference_path_is_missing(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "SELLFORM_IMAGE_GENERATION_MODE", "real")
    calls = []

    def fake_generate(self, request):
        calls.append(request)
        raise AssertionError("provider must not be called without source_asset_paths")

    monkeypatch.setattr(ImageGenerationProviderRouter, "generate", fake_generate)

    state = AgentRunState(
        project_id="project-1",
        mode=AgentRunMode.REAL,
        product_input=ProductInput(
            product_name="삼탠바이미 32인치 스마트모니터",
            asset_ids=["missing-asset"],
        ),
        outputs={
            "visual_planning": {
                "image_jobs": [
                    {
                        "job_id": "hero-job",
                        "slot_id": "hero",
                        "role": "representative_product",
                        "prompt": "삼탠바이미 상세페이지 대표 이미지",
                        "reference_asset_ids": ["missing-asset"],
                        "product_identity_required": True,
                    }
                ]
            }
        },
        cost_approval_status="approved",
    )

    result = ImageGenerationAgent(mode="real").run_real_text(state, generate_output=None)
    image_output = result.outputs["image_generation"]

    assert calls == []
    assert image_output["jobs"][0]["status"] == "missing_reference_asset"
    assert image_output["images"] == []
