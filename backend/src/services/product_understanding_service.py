from pydantic import BaseModel
from typing import List, Optional
from src.db.models import ProductProject, ProductFact, Asset

class UnderstandingField(BaseModel):
    value: str
    is_suggestion: bool = False

class ProductUnderstandingResponse(BaseModel):
    product_type: UnderstandingField
    target_customer: UnderstandingField
    buyer_problem: UnderstandingField
    main_angle_candidates: List[str]
    tone_candidates: List[str]
    image_candidates: List[str]
    unknowns: List[str]

def generate_understanding_summary(project: ProductProject, db) -> ProductUnderstandingResponse:
    # 1. Gather descriptive texts and filenames
    project_name = project.name or ""
    raw_text = project.raw_input_text or ""
    
    # Get facts from database if not preloaded
    facts = project.facts
    fact_text_combined = " ".join([f.fact_text for f in facts]).lower()
    
    # Get asset filenames
    assets = project.assets
    asset_filenames_combined = " ".join([a.filename for a in assets]).lower()
    
    combined_content = f"{project_name} {raw_text} {fact_text_combined} {asset_filenames_combined}".lower()
    
    # 2. Determine Product Type
    product_type_val = "미정"
    product_type_is_sugg = True
    
    if any(k in combined_content for k in ["매트", "식탁매트", "테이블 매트", "mat"]):
        product_type_val = "테이블 매트"
        product_type_is_sugg = False
    elif any(k in combined_content for k in ["텀블러", "tumbler"]):
        product_type_val = "텀블러"
        product_type_is_sugg = False
    elif any(k in combined_content for k in ["셔츠", "의류", "바지", "옷", "shirt", "pants"]):
        product_type_val = "의류"
        product_type_is_sugg = False
    elif any(k in combined_content for k in ["크림", "세럼", "화장품", "뷰티", "cream", "serum", "cosmetic"]):
        product_type_val = "화장품"
        product_type_is_sugg = False
    else:
        # Fallback to category if available, otherwise project name
        if project.category == "Fashion":
            product_type_val = "패션 의류"
        elif project.category == "Beauty":
            product_type_val = "화장품"
        elif project.category == "Food":
            product_type_val = "식품"
        elif project.category == "Living":
            product_type_val = "생활용품"
        elif project_name:
            product_type_val = project_name
            
    # 3. Determine Target Customer
    target_customer_val = "합리적인 가격과 기본 품질을 중시하는 소비자"
    target_customer_is_sugg = True
    
    if product_type_val == "테이블 매트":
        target_customer_val = "친환경 식기 및 감성 테이블 데코를 선호하는 주부 및 1인 가구"
        target_customer_is_sugg = False
    elif product_type_val == "텀블러":
        target_customer_val = "휴대성과 보온/보냉 기능을 중시하는 직장인 및 학생"
        target_customer_is_sugg = False
    elif "오가닉" in combined_content or "친환경" in combined_content:
        target_customer_val = "친환경/오가닉 제품을 선호하고 환경 보호에 관심이 많은 가치소비 고객"
        target_customer_is_sugg = False
    elif project.category == "Beauty" or product_type_val == "화장품":
        target_customer_val = "피부 자극이 적고 순한 스킨케어를 찾는 20-30대 남녀"
        target_customer_is_sugg = True
    elif project.category == "Fashion" or product_type_val == "의류":
        target_customer_val = "심플하고 트렌디한 일상룩을 선호하는 20-30대"
        target_customer_is_sugg = True

    # 4. Determine Buyer Problem
    buyer_problem_val = "성능 및 성분을 확실히 믿고 구매할 정보가 부족함"
    buyer_problem_is_sugg = True
    
    if product_type_val == "테이블 매트":
        buyer_problem_val = "식사 중 국물이 스며들거나 오염되어 세척이 어렵고 유해 물질 걱정이 있는 문제"
        buyer_problem_is_sugg = False
    elif product_type_val == "텀블러":
        buyer_problem_val = "음료 온도가 쉽게 변하고 누수가 자주 일어나며 세척이 번거로운 문제"
        buyer_problem_is_sugg = False
    elif project.category == "Beauty" or product_type_val == "화장품":
        buyer_problem_val = "건조하고 민감한 피부의 잦은 트러블과 자극 없는 영양 공급 필요"
        buyer_problem_is_sugg = True
    elif project.category == "Fashion" or product_type_val == "의류":
        buyer_problem_val = "체형 커버가 안 되고 재질이 얇아 쉽게 늘어나는 문제"
        buyer_problem_is_sugg = True

    # 5. Determine Marketing Angles
    if product_type_val == "테이블 매트":
        main_angles = [
            "100% 천연 오가닉 대나무 소재의 안전성",
            "물세척 및 방수 기능으로 위생적인 관리 가능",
            "모던하고 따뜻한 디자인의 테이블 스타일링 완성"
        ]
    elif product_type_val == "텀블러":
        main_angles = [
            "이중 진공 구조로 강력한 24시간 보온/보냉 유지",
            "100% 밀폐 설계로 가방 안에서도 누수 걱정 제로",
            "원터치 세척 및 분리형 뚜껑으로 간편한 위생 관리"
        ]
    else:
        main_angles = [
            "엄선된 원재료를 사용한 우수한 안전성",
            "일상의 편리함을 더하는 실용적인 설계",
            "누구나 만족하는 모던하고 미니멀한 디자인"
        ]

    # 6. Determine Tone
    if product_type_val == "테이블 매트":
        tones = [
            "따뜻하고 감성적인 에코 프렌들리 톤",
            "실용성과 안전성을 강조하는 신뢰감 있는 톤"
        ]
    elif product_type_val == "텀블러":
        tones = [
            "기능성과 활동성을 부각하는 스마트한 톤",
            "일상의 여유를 전하는 친근한 톤"
        ]
    else:
        tones = [
            "신뢰와 전문성을 보여주는 깔끔한 톤",
            "친근하고 설득력 있는 자연스러운 톤"
        ]

    # 7. Image Candidates
    # Use asset paths/filenames
    image_candidates = [a.filename for a in assets]
    if not image_candidates:
        # Fallback placeholder if no assets uploaded
        image_candidates = []

    # 8. Determine Unknowns
    unknowns = []
    # Check sizes
    if not any(k in combined_content for k in ["cm", "mm", "사이즈", "규격", "크기", "width", "height"]):
        unknowns.append("상세 규격 및 사이즈 정보")
    # Check origin
    if not any(k in combined_content for k in ["원산지", "제조", "국산", "수입", "china", "korea"]):
        unknowns.append("원산지 및 제조국 정보")
    # Check materials
    if not any(k in combined_content for k in ["소재", "재질", "성분", "%", "대나무", "가죽", "bamboo", "leather"]):
        unknowns.append("정확한 소재 구성비 및 원재료 정보")

    return ProductUnderstandingResponse(
        product_type=UnderstandingField(value=product_type_val, is_suggestion=product_type_is_sugg),
        target_customer=UnderstandingField(value=target_customer_val, is_suggestion=target_customer_is_sugg),
        buyer_problem=UnderstandingField(value=buyer_problem_val, is_suggestion=buyer_problem_is_sugg),
        main_angle_candidates=main_angles,
        tone_candidates=tones,
        image_candidates=image_candidates,
        unknowns=unknowns
    )
