from src.db.models import ProductProject
from src.services.sales_strategy_service import generate_sales_strategy

def test_generate_sales_strategy_kids_product():
    project = ProductProject(
        name="아이들 유아용 장난감 매트",
        raw_input_text="안전하게 아기들이 뒹굴 수 있는 장난감 매트입니다.",
        category="Living",
        assets=[]
    )
    
    strategy = generate_sales_strategy(project, None)
    
    assert "부모" in strategy.target_customer
    assert "안전" in strategy.main_selling_point
    assert "KC 어린이 안전 인증 획득" not in strategy.supporting_points
    assert strategy.price_strategy == "N/A"
    assert strategy.image_selection == []
    assert len(strategy.confirmation_rows) == 5

def test_generate_sales_strategy_home_product():
    project = ProductProject(
        name="감성 주방 식탁 테이블 매트",
        raw_input_text="예쁜 대나무 테이블 매트",
        category="Living",
        assets=[]
    )
    
    strategy = generate_sales_strategy(project, None)
    
    assert "주방" in strategy.target_customer
    assert "관리" in strategy.main_selling_point
    assert len(strategy.directions) == 3

def test_generate_sales_strategy_tech_product():
    project = ProductProject(
        name="스마트 진공 온도가변형 텀블러",
        raw_input_text="보온 성능이 뛰어나고 누수 방지 캡이 있는 스마트 텀블러 충전기",
        category="Living",
        assets=[]
    )
    
    strategy = generate_sales_strategy(project, None)
    
    assert "IT" in strategy.target_customer
    assert "성능" in strategy.main_selling_point
    assert all("24시간" not in point for point in strategy.supporting_points)
    assert all("100%" not in point for point in strategy.supporting_points)


def test_generate_sales_strategy_uses_confirmed_understanding():
    project = ProductProject(
        name="일반 상품",
        raw_input_text="일반 설명",
        category="Living",
        assets=[],
        intake_snapshot={
            "confirmed_understanding": {
                "product_type": {"value": "유아용 안전 장난감", "is_suggestion": False},
                "target_customer": {"value": "안전성을 확인하는 영유아 부모", "is_suggestion": False},
                "buyer_problem": {"value": "상품의 안전 근거를 확인하기 어려움", "is_suggestion": False},
                "main_angle_candidates": [],
                "tone_candidates": ["차분하고 신뢰감 있는 톤"],
                "image_candidates": [],
                "unknowns": ["KC 인증 여부"],
            }
        },
    )

    strategy = generate_sales_strategy(project, None)

    assert strategy.target_customer == "안전성을 확인하는 영유아 부모"
    assert strategy.buyer_problem == "상품의 안전 근거를 확인하기 어려움"
    assert strategy.tone == "차분하고 신뢰감 있는 톤"
    assert "확인 필요: KC 인증 여부" in strategy.risk_notes


def test_generate_sales_strategy_does_not_invent_price_or_image_assets():
    project = ProductProject(
        name="유아용 장난감",
        raw_input_text="아이와 사용하는 제품입니다.",
        category="Living",
        assets=[],
    )

    strategy = generate_sales_strategy(project, None)
    price_row = next(row for row in strategy.confirmation_rows if row.field_key == "price_strategy")
    image_row = next(row for row in strategy.confirmation_rows if row.field_key == "image_selection")

    assert strategy.price_strategy == "N/A"
    assert price_row.confidence == "low"
    assert strategy.image_selection == []
    assert image_row.confidence == "low"
