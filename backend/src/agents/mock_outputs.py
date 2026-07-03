def build_mock_product_understanding(product_name: str) -> dict:
    return {
        "product_type": product_name,
        "target_customer": "첫 아이 자전거 선물을 찾는 30-40대 부모",
        "verified_facts": ["12인치/14인치 제공", "안전 보조 바퀴 기본 장착", "견고한 스틸 프레임"],
        "assumptions": ["주로 공원이나 아파트 단지 내에서 이용할 것이다."],
        "verification_required": ["색상 옵션이 파스텔 블루 외에 더 있는지 확인 필요"],
        "forbidden_claims": ["최고의 자전거", "절대 다치지 않는 안전성"],
    }


def build_mock_sales_strategy(product_name: str) -> dict:
    return {
        "hook_headline": f"우리 아이 첫 페달링, {product_name}와 함께 안전하게 시작하세요!",
        "selling_points": ["안전 설계", "성장 단계 맞춤 조절", "아이들이 좋아하는 감성 디자인"],
        "tone_and_manner": "따뜻하고, 안심을 주며, 직관적인 마케팅 톤",
    }


def build_mock_page_plan(product_name: str) -> dict:
    return {
        "layout_concept": "감성적이고 따뜻한 느낌의 파스텔톤 레이아웃",
        "sections": [
            {"id": "sec-1", "name": "인트로 헤로"},
            {"id": "sec-2", "name": "문제 제기 / 필요성"},
            {"id": "sec-3", "name": "핵심 강점 1"},
            {"id": "sec-4", "name": "핵심 강점 2"},
            {"id": "sec-5", "name": "품질 인증 & 구매 유도"},
        ],
    }


def build_mock_copy_set(product_name: str) -> dict:
    return {
        "hero_title": f"넘어질 걱정 없는 안심 {product_name}",
        "hero_subtitle": "조립부터 탑승까지 초보 부모도 10분이면 안심 케어 완료",
        "painpoint_title": "첫 자전거, 왜 보조바퀴가 중요할까요?",
        "feature_1_title": "체형 성장에 맞추어 안장 높이 3단 조절 가능",
        "feature_2_title": "KC 유해물질 불검출 안전 검증 완료 프레임",
        "cta_text": "지금 구매하고 헬멧 사은품 받기",
    }


def build_mock_visual_plan(product_name: str) -> dict:
    return {
        "hero_image_prompt": f"A cute child riding {product_name} in a bright sunny park, warm lighting, photography",
        "detail_image_prompt": "Close up of training wheel with soft non-slip rubber, studio shot",
        "color_palette": ["#10B981", "#14B8A6", "#FFFFFF", "#F3F4F6"],
    }


def build_mock_generated_assets(product_name: str) -> dict:
    return {
        "images": [
            {
                "id": "mock-hero-visual",
                "role": "hero",
                "url": "https://images.unsplash.com/photo-1544161515-4ab6ce6db874",
                "source_type": "uploaded",
            },
            {
                "id": "mock-comparison-visual",
                "role": "comparison",
                "url": "https://images.unsplash.com/photo-1485965120184-e220f721d03e",
                "source_type": "URL-extracted",
            },
            {
                "id": "mock-detail-1-visual",
                "role": "detail_1",
                "url": "https://images.unsplash.com/photo-1517649763962-0c623066013b",
                "source_type": "mock-generated",
            },
            {
                "id": "mock-detail-2-visual",
                "role": "detail_2",
                "url": "https://images.unsplash.com/photo-1485965120184-e220f721d03e",
                "source_type": "pending real generation",
            },
            {
                "id": "mock-guarantee-visual",
                "role": "guarantee",
                "url": "https://images.unsplash.com/photo-1544161515-4ab6ce6db874",
                "source_type": "mock-generated",
            },
        ]
    }



def build_mock_page_assembly(product_name: str) -> dict:
    return {
        "sections": [
            {
                "id": "sec-1",
                "title": f"안심하고 태우는 우리 아이 첫 {product_name}",
                "body": "넘어질 우려 없는 튼튼한 보조 바퀴 디자인",
                "visual_role": "hero",
                "image_id": "mock-hero-visual",
            },
            {
                "id": "sec-2",
                "title": "흔들리고 위험한 저가형 자전거와 비교해 보세요",
                "body": "프레임 흔들림 최소화 공법 적용",
                "visual_role": "comparison",
                "image_id": "mock-comparison-visual",
            },
            {
                "id": "sec-3",
                "title": "안심할 수 있는 튼튼한 보조 바퀴",
                "body": "쉽게 마모되지 않고 흔들림을 잡아줍니다",
                "visual_role": "detail_1",
                "image_id": "mock-detail-1-visual",
            },
            {
                "id": "sec-4",
                "title": "성장판을 배려한 인체공학 안장설계",
                "body": "아이들의 체형에 최적화된 라운딩 마감",
                "visual_role": "detail_2",
                "image_id": "mock-detail-2-visual",
            },
            {
                "id": "sec-5",
                "title": "안심 구매 보장 & 공식 정품 마크",
                "body": "본 제품은 공식 정품이며 정식 수입 통관을 필한 자전거입니다.",
                "visual_role": "guarantee",
                "image_id": "mock-guarantee-visual",
            },
        ]
    }


def build_mock_qa_report(product_name: str) -> dict:
    return {
        "status": "passed",
        "checked_at": "2026-07-03T14:30:00Z",
        "warnings": [],
        "passed_checks": ["과장 표현 검증 완료", "유해 성분 언급 적합성 통과"],
    }
