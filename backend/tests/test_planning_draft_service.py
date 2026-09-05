import pytest
from sqlalchemy.orm import Session
from src.db.models import ProductProject, ProductFact
from src.services.detail_page_template_service import DetailPageTemplateService
from src.services.planning_draft_service import PlanningDraftService
from src.services.page_composer_service import PageComposerService

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
    assert first_card["source_fact_ids"] == []


def test_raw_seller_input_is_context_not_confirmed_generation_fact(db_session: Session, sample_project):
    sample_project.raw_input_text = "사용 시간 2시간, 무게 1kg, 근거 없는 친환경 표현"
    fact = ProductFact(
        project_id=sample_project.id,
        fact_text="무게: 1000g",
        verification_status="seller_confirmed",
    )
    db_session.add(fact)
    db_session.commit()

    normalized = PageComposerService.normalize_facts(sample_project, [fact])

    assert [item["id"] for item in normalized["product_facts"]] == [fact.id]
    assert normalized["seller_context"] == sample_project.raw_input_text
    draft = PlanningDraftService.generate_draft(sample_project, [fact], db_session)
    specification = next(card for card in draft["cards"] if card["type"] == "specifications")
    assert specification["source_fact_ids"] == [fact.id]
    assert specification["bullets"] == ["무게: 1000g"]

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


def test_mock_draft_uses_semantic_facts_and_canonical_spec_copy(db_session: Session, sample_project):
    sample_project.category = "living"
    facts = [
        ProductFact(
            project_id=sample_project.id,
            fact_text="마사지 헤드 수: 4개",
            field_key="massage_head_count",
            normalized_value="4",
            normalized_unit="개",
            scope="product",
            source_text="4个마사지 헤드",
            verification_status="seller_confirmed",
        ),
        ProductFact(
            project_id=sample_project.id,
            fact_text="사용 가능 시간: 2시간",
            field_key="total_use_time",
            normalized_value="2",
            normalized_unit="시간",
            scope="product",
            source_text="使用时间：2小时",
            verification_status="seller_confirmed",
        ),
        ProductFact(
            project_id=sample_project.id,
            fact_text="외박스 크기: 53 × 41.5 × 32cm",
            field_key="product_size",
            normalized_value="53 × 41.5 × 32",
            normalized_unit="cm",
            scope="master_carton",
            source_text="53x41.5x32cm",
            verification_status="seller_confirmed",
        ),
    ]
    db_session.add_all(facts)
    db_session.commit()

    draft = PlanningDraftService.generate_draft(sample_project, facts, db_session)
    features = next(card for card in draft["cards"] if card["type"] == "features")
    hero = next(card for card in draft["cards"] if card["type"] == "hero")
    specifications = next(card for card in draft["cards"] if card["type"] == "specifications")

    assert features["title"] == "확인된 핵심 기능을 한눈에"
    assert features["source_fact_ids"] == [facts[0].id, facts[1].id]
    assert features["bullets"] == ["마사지 헤드 수: 4개", "사용 가능 시간: 2시간"]
    assert facts[2].id not in features["source_fact_ids"]
    assert hero["source_fact_ids"] == [facts[1].id, facts[0].id]
    assert specifications["source_fact_ids"] == [fact.id for fact in facts]
    assert "소구점 정리 타이틀" not in features["title"]
    assert "상세 카피 내용" not in features["bullets"]
