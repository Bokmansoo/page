import pytest
from src.services.ai_cost_policy import AICostPolicy

def test_should_require_approval_with_high_cost_jobs():
    # 1. 고비용 planned 작업 존재 시 승인 필요
    jobs = [
        {"cost_tier": "standard", "status": "planned"},
        {"cost_tier": "high", "status": "planned"}
    ]
    assert AICostPolicy.should_require_approval(jobs) is True

    jobs = [
        {"cost_tier": "premium", "status": "planned"}
    ]
    assert AICostPolicy.should_require_approval(jobs) is True

    # 2. 고비용 awaiting_cost_approval 작업 존재 시 승인 필요
    jobs = [
        {"cost_tier": "high", "status": "awaiting_cost_approval"}
    ]
    assert AICostPolicy.should_require_approval(jobs) is True

    # 3. 고비용 작업들이 이미 승인되었거나 생성 중이면 추가 승인 필요 없음
    jobs = [
        {"cost_tier": "high", "status": "generating"},
        {"cost_tier": "high", "status": "approved"}
    ]
    assert AICostPolicy.should_require_approval(jobs) is False

def test_should_require_approval_with_low_cost_only():
    # 고비용 작업이 없을 때는 승인 필요 없음
    jobs = [
        {"cost_tier": "low", "status": "planned"},
        {"cost_tier": "standard", "status": "planned"}
    ]
    assert AICostPolicy.should_require_approval(jobs) is False


def test_image_planning_tier_does_not_start_generation():
    assert AICostPolicy.get_tier_for_action("image_planning") == "standard"
    assert AICostPolicy.get_tier_for_action("image_generation") == "premium"
    assert AICostPolicy.should_require_approval([
        {"cost_tier": "standard", "status": "planned"},
        {"cost_tier": "standard", "status": "needs_generation"},
    ]) is False

def test_filter_cost_approved_jobs():
    jobs = [
        {"cost_tier": "low", "status": "planned", "name": "job1"},
        {"cost_tier": "high", "status": "planned", "name": "job2"},  # 필터링 대상
        {"cost_tier": "high", "status": "generating", "name": "job3"},  # 승인됨
        {"cost_tier": "high", "status": "approved", "name": "job4"},  # 승인됨
        {"cost_tier": "standard", "status": "planned", "name": "job5"},
        {"cost_tier": "premium", "status": "planned", "name": "job6"},
        {"cost_tier": "premium", "status": "needs_review", "name": "job7"},
    ]
    approved = AICostPolicy.filter_cost_approved_jobs(jobs)
    approved_names = [j["name"] for j in approved]
    
    assert "job1" in approved_names
    assert "job2" not in approved_names
    assert "job3" in approved_names
    assert "job4" in approved_names
    assert "job5" in approved_names
    assert "job6" not in approved_names
    assert "job7" in approved_names
