try:
    from src.services.grounding_validator import detect_claim_risks, map_section_to_facts, build_grounding_review
except ImportError:
    from backend.src.services.grounding_validator import detect_claim_risks, map_section_to_facts, build_grounding_review


def test_detects_numeric_and_performance_claim_without_evidence():
    warnings = detect_claim_risks(
        text="1초 만에 체감 온도 -10도, 업계 최고 냉각 성능을 제공합니다.",
        confirmed_facts=["4,800mAh 배터리", "최대 18시간 무선 사용"],
    )

    assert len(warnings) >= 2
    assert any(warning.risk_type == "numeric_claim_without_evidence" for warning in warnings)
    assert any(warning.risk_type == "performance_claim_without_evidence" for warning in warnings)


def test_maps_section_to_relevant_confirmed_facts():
    matched = map_section_to_facts(
        section_text="4,800mAh 대용량 배터리로 최대 18시간 무선 사용이 가능합니다.",
        confirmed_facts=[
            "4,800mAh 배터리",
            "최대 18시간 무선 사용",
            "휴대용 무선 냉각 선풍기",
        ],
    )

    assert matched == ["4,800mAh 배터리", "최대 18시간 무선 사용"]


def test_builds_grounding_review_summary():
    review = build_grounding_review(
        sections=[
            {"key": "main_claim", "title": "오래 지속되는 시원함", "body": "4,800mAh 배터리로 최대 18시간 무선 사용이 가능합니다."},
            {"key": "benefit_list", "title": "강력한 냉각", "body": "업계 최고 냉각 성능을 제공합니다."},
        ],
        confirmed_facts=["4,800mAh 배터리", "최대 18시간 무선 사용"],
    )

    assert review["summary"]["warning_count"] >= 1
    assert review["summary"]["grounded_section_count"] == 1
    assert review["summary"]["used_fact_count"] == 2


def test_get_page_grounding_review_endpoint(client, db_session):
    from src.api.auth import DEFAULT_BRAND_ID
    from src.db.models import ProductFact
    
    headers = {
        "X-Mock-User-Id": "user-1",
        "X-Mock-Workspace-Id": "workspace-1"
    }
    
    # Create project
    create_res = client.post(
        "/api/v1/projects",
        json={"name": "Sprint 20 Project", "brand_id": DEFAULT_BRAND_ID, "raw_input_text": "Spec sheet"},
        headers=headers
    )
    assert create_res.status_code == 201
    project_id = create_res.json()["id"]

    # Add confirmed fact
    fact = ProductFact(
        project_id=project_id,
        fact_text="4,800mAh 배터리",
        source_text="Battery spec",
        verification_status="confirmed"
    )
    db_session.add(fact)
    db_session.commit()

    # Create page draft (mock generation will use this fact text in body copy)
    page_res = client.post(
        f"/api/v1/projects/{project_id}/page",
        json={"style_preset": "modern"},
        headers=headers
    )
    assert page_res.status_code == 201

    # Request grounding review
    res = client.get(
        f"/api/v1/projects/{project_id}/page/grounding-review",
        headers=headers
    )
    assert res.status_code == 200
    review_data = res.json()
    assert "summary" in review_data
    assert "sections" in review_data
    assert review_data["summary"]["used_fact_count"] >= 1



