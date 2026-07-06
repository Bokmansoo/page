import pytest
from src.agents.nodes.qa_review.agent import QAReviewAgent
from src.agents.state import AgentRunState

def test_qa_warns_when_product_image_identity_needs_review():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "page_assembly": {
                "sections": [
                    {
                        "section_id": "hero",
                        "visual_slot": {
                            "asset_id": "asset-real-hero",
                            "source_type": "real-generated",
                            "identity_check": {"status": "needs_review"},
                        },
                    }
                ]
            }
        },
    )

    result = QAReviewAgent().run(state)
    qa = result.outputs["qa_review"]

    assert qa["warnings"][0]["code"] == "IMAGE_IDENTITY_NEEDS_REVIEW"
    assert qa["can_export"] is False

def test_qa_warns_when_image_is_missing():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "page_assembly": {
                "sections": [
                    {
                        "section_id": "hero",
                        "visual_slot": {
                            "asset_id": None,
                            "source_type": None,
                            "status": "missing_image",
                        },
                    }
                ]
            }
        },
    )

    result = QAReviewAgent().run(state)
    qa = result.outputs["qa_review"]

    assert qa["warnings"][0]["code"] == "REQUIRED_IMAGE_MISSING"
    assert qa["can_export"] is False

def test_qa_blocks_high_reference_copy_risk():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "reference_analysis": {
                "copy_risk_level": "high",
                "copy_risk_notes": ["원문 상세페이지 표현과 너무 유사합니다."],
            },
            "page_assembly": {
                "sections": [
                    {
                        "section_id": "hero",
                        "visual_slot": {
                            "asset_id": "asset-uploaded-1",
                            "source_type": "uploaded",
                            "status": "completed",
                        },
                    }
                ]
            },
        },
    )

    result = QAReviewAgent().run(state)
    qa = result.outputs["qa_review"]

    assert any(w["code"] == "REFERENCE_COPY_RISK_HIGH" for w in qa["warnings"])
    assert qa["can_export"] is False

def test_qa_blocks_unsupported_absolute_claims():
    state = AgentRunState(
        project_id="project-1",
        outputs={
            "page_assembly": {
                "sections": [
                    {
                        "section_id": "hero",
                        "unsupported_claims": ["국내 최저가"],
                        "visual_slot": {
                            "asset_id": "asset-uploaded-1",
                            "source_type": "uploaded",
                            "status": "completed",
                        },
                    }
                ]
            },
        },
    )

    result = QAReviewAgent().run(state)
    qa = result.outputs["qa_review"]

    assert any(w["code"] == "UNSUPPORTED_ABSOLUTE_CLAIM" for w in qa["warnings"])
    assert qa["can_export"] is False
