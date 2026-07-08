import pytest
from sqlalchemy.orm import Session
from src.db.models import ProductProject, ProductFact
from src.services.detail_page_template_service import DetailPageTemplateService
from src.services.planning_draft_service import PlanningDraftService

@pytest.fixture
def sample_project(db_session: Session):
    project = ProductProject(
        id="test-planning-proj-1",
        workspace_id="ws-1",
        brand_id="b-1",
        name="테스트용 가습기",
        raw_input_text="원터치 간편 세척, 4L 대용량 가습기",
        status="draft"
    )
    db_session.add(project)
    db_session.commit()
    return project

def test_generate_draft_mock(db_session: Session, sample_project):
    # 팩트 생성
    fact = ProductFact(
        project_id=sample_project.id,
        fact_text="4L 대용량 수조",
        verification_status="confirmed"
    )
    db_session.add(fact)
    db_session.commit()

    draft = PlanningDraftService.generate_draft(sample_project, [fact], db_session)
    
    assert draft is not None
    assert "cards" in draft
    template_id = DetailPageTemplateService.select_template_id(
        sample_project.category,
        sample_project.intake_snapshot,
    )
    template = DetailPageTemplateService.get_template(template_id)
    expected_types = [section["type"] for section in template["sections"]]
    assert draft["template_id"] == template["id"]
    assert draft["template_name"] == template["name"]
    assert len(draft["cards"]) == len(expected_types)
    
    # 10개 필수 카드 종류 및 순서 확인
    card_types = [c["type"] for c in draft["cards"]]
    assert card_types == expected_types
    
    # 사실 매핑 확인 (첫번째 카드에 mapping)
    first_card = draft["cards"][0]
    assert first_card["source_fact_ids"] == [fact.id]

def test_planning_draft_quality_rules(db_session: Session, sample_project):
    fact = ProductFact(
        project_id=sample_project.id,
        fact_text="4L 대용량 수조",
        verification_status="confirmed"
    )
    db_session.add(fact)
    db_session.commit()

    draft = PlanningDraftService.generate_draft(sample_project, [fact], db_session)
    assert draft is not None
    assert "cards" in draft

    forbidden_patterns = [
        "정리합니다", "보여주세요", "입력 정보를 바탕으로", "안전한 표현",
        "[AI 수정됨]", "+", "—", "최고", "완벽", "무조건",
        "핵심 사용 가치", "생활 패턴", "초보 구매자", "기존 대안",
        "또렷하게 정리해요", "포인트로 압축합니다", "체크할 항목을 정리",
        "줄이는 역할을 합니다", "분리해 보여줍니다", "안내해 드립니다"
    ]

    for card in draft["cards"]:
        title = card["title"]
        bullets = card["bullets"]

        # 제목에 금지 마커나 지시문이 없는지 확인
        for pattern in forbidden_patterns:
            assert pattern not in title, f"Title '{title}' contains forbidden pattern '{pattern}'"
            for bullet in bullets:
                assert pattern not in bullet, f"Bullet '{bullet}' contains forbidden pattern '{pattern}'"
