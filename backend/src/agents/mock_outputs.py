from urllib.parse import quote


def _mock_placeholder_url(role: str, product_name: str) -> str:
    title = (product_name or "Sellform product")[:48]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="640" viewBox="0 0 960 640">
  <rect width="960" height="640" fill="#F4FAF6"/>
  <rect x="96" y="80" width="768" height="480" rx="36" fill="#FFFFFF" stroke="#B8DEC6" stroke-width="4"/>
  <circle cx="480" cy="260" r="96" fill="#DDF2E5"/>
  <rect x="280" y="392" width="400" height="24" rx="12" fill="#A8D8B8"/>
  <rect x="340" y="440" width="280" height="18" rx="9" fill="#D7EDE0"/>
  <text x="480" y="528" text-anchor="middle" font-family="Arial, sans-serif" font-size="28" font-weight="700" fill="#2F6B4F">{role}</text>
  <text x="480" y="570" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" fill="#5B6B63">{title}</text>
</svg>"""
    return "data:image/svg+xml;charset=utf-8," + quote(svg)


def build_mock_product_understanding(product_name: str, description: str = "") -> dict:
    desc = description or "뛰어난 편의성과 디자인을 자랑하는 제품"
    return {
        "product_type": product_name,
        "target_customer": f"{product_name} 구매를 고려하는 스마트한 소비자",
        "verified_facts": [
            f"공식 정품 {product_name}",
            f"{desc}",
            "안전 규격 준수 및 철저한 품질 관리"
        ],
        "assumptions": ["사용자 편의성과 실용성을 중시하는 고객 군"],
        "verification_required": ["추가 색상 및 크기 옵션 정보 확인 필요"],
        "forbidden_claims": ["비교 불가능한 최고의 품질", "절대 고장 나지 않는 내구성"],
    }


def build_mock_sales_strategy(product_name: str, description: str = "") -> dict:
    return {
        "hook_headline": f"더욱 새로워진 일상의 변화, {product_name}와 함께 시작하세요!",
        "selling_points": [
            f"{product_name}의 혁신적 설계",
            f"실용적인 성능과 {description or '뛰어난 사용 편의성'}",
            "철저한 사후 보장 혜택 제공"
        ],
        "tone_and_manner": "신뢰할 수 있고, 모던하며, 직관적인 마케팅 톤",
    }


def build_mock_page_plan(product_name: str) -> dict:
    return {
        "layout_concept": "세련되고 신뢰감을 주는 모던한 레이아웃",
        "sections": [
            {"id": "sec-1", "name": "인트로 헤로"},
            {"id": "sec-2", "name": "기존 제품 대비 개선점"},
            {"id": "sec-3", "name": "핵심 특장점 1"},
            {"id": "sec-4", "name": "핵심 특장점 2"},
            {"id": "sec-5", "name": "구매 보장 & 안내"},
        ],
    }


def build_mock_copy_set(product_name: str, description: str = "") -> dict:
    desc = description or "일상에 새로운 가치를 더하는 혁신적인 제품"
    return {
        "hero_title": f"공간의 가치를 더하는 {product_name}",
        "hero_subtitle": f"{desc}으로 한 차원 높은 경험을 시작해 보세요",
        "painpoint_title": "아직도 번거로운 방식을 고집하시나요?",
        "painpoint_body": "불편함을 해소하고 일상을 더 스마트하고 효율적으로 바꿀 수 있습니다.",
        "feature_1_title": "기능과 디자인을 모두 잡은 최적화 설계",
        "feature_1_body": "세련된 외관과 실용적인 구조로 설계되어 사용 시 최상의 만족도를 제공합니다.",
        "feature_2_title": "안전 검증 및 신뢰 마크 획득 완료",
        "feature_2_body": "공식 검증 기관을 통해 입증된 높은 안전 기준을 바탕으로 완벽히 통과했습니다.",
        "guarantee_title": "공식 정품 안심 보장 서비스",
        "guarantee_body": "제조사 정품 인증을 마친 제품으로, 구매 후에도 철저한 사후 관리를 보장합니다.",
        "cta_text": "지금 특별 혜택가로 만나보기",
    }


def build_mock_visual_plan(product_name: str) -> dict:
    return {
        "hero_image_prompt": f"A beautiful editorial product photography of {product_name} in a modern clean interior, studio lighting",
        "detail_image_prompt": f"Close up details of {product_name}, clean minimalist view, macro shot",
        "color_palette": ["#10B981", "#14B8A6", "#FFFFFF", "#F3F4F6"],
    }


def build_mock_generated_assets(
    product_name: str,
    uploaded_assets: list = None,
    product_url: str = None
) -> dict:
    if uploaded_assets is None:
        uploaded_assets = []

    images = []

    # 1. Map uploaded assets first
    for idx, asset in enumerate(uploaded_assets):
        images.append({
            "id": asset["id"],
            "role": f"uploaded_asset_{idx}",
            "url": asset["url"],
            "source_type": "uploaded",
            "label": asset["filename"]
        })

    # 2. Add URL extracted asset if product_url exists
    if product_url:
        images.append({
            "id": "mock-url-extracted-image",
            "role": "extracted",
            "url": _mock_placeholder_url("url-extracted", product_name),
            "source_type": "url-extracted",
            "label": "url-extracted-image.png"
        })

    # 3. Add default mock generated assets
    images.append({
        "id": "mock-hero-visual",
        "role": "hero",
        "url": _mock_placeholder_url("hero", product_name),
        "source_type": "mock-generated",
        "label": "hero-placeholder.png"
    })
    images.append({
        "id": "mock-detail-1-visual",
        "role": "detail_1",
        "url": _mock_placeholder_url("detail_1", product_name),
        "source_type": "mock-generated",
        "label": "detail-1-placeholder.png"
    })
    images.append({
        "id": "mock-detail-2-visual",
        "role": "detail_2",
        "url": _mock_placeholder_url("detail_2", product_name),
        "source_type": "mock-generated",
        "label": "detail-2-placeholder.png"
    })
    images.append({
        "id": "mock-guarantee-visual",
        "role": "guarantee",
        "url": _mock_placeholder_url("guarantee", product_name),
        "source_type": "mock-generated",
        "label": "guarantee-placeholder.png"
    })

    return {"images": images}


def build_mock_page_assembly(
    product_name: str,
    uploaded_assets: list = None,
    product_url: str = None,
    copy_set: dict = None
) -> dict:
    if uploaded_assets is None:
        uploaded_assets = []

    if not copy_set:
        copy_set = build_mock_copy_set(product_name)

    # Determine visuals for each slot
    # 1. Hero
    if uploaded_assets:
        hero_visual = {
            "source_type": "uploaded",
            "asset_id": uploaded_assets[0]["id"],
            "label": uploaded_assets[0]["filename"]
        }
        hero_image_id = uploaded_assets[0]["id"]
    elif product_url:
        hero_visual = {
            "source_type": "url-extracted",
            "asset_id": "mock-url-extracted-image",
            "label": "url-extracted-image.png"
        }
        hero_image_id = "mock-url-extracted-image"
    else:
        hero_visual = {
            "source_type": "mock-generated",
            "asset_id": "mock-hero-visual",
            "label": "hero-placeholder.png"
        }
        hero_image_id = "mock-hero-visual"

    # 2. Comparison
    if len(uploaded_assets) > 1:
        comp_visual = {
            "source_type": "uploaded",
            "asset_id": uploaded_assets[1]["id"],
            "label": uploaded_assets[1]["filename"]
        }
        comp_image_id = uploaded_assets[1]["id"]
    elif product_url:
        comp_visual = {
            "source_type": "url-extracted",
            "asset_id": "mock-url-extracted-image",
            "label": "url-extracted-image.png"
        }
        comp_image_id = "mock-url-extracted-image"
    else:
        comp_visual = {
            "source_type": "mock-generated",
            "asset_id": "mock-detail-1-visual",
            "label": "detail-1-placeholder.png"
        }
        comp_image_id = "mock-detail-1-visual"

    # 3. Detail_1
    if len(uploaded_assets) > 2:
        d1_visual = {
            "source_type": "uploaded",
            "asset_id": uploaded_assets[2]["id"],
            "label": uploaded_assets[2]["filename"]
        }
        d1_image_id = uploaded_assets[2]["id"]
    else:
        d1_visual = {
            "source_type": "mock-generated",
            "asset_id": "mock-detail-1-visual",
            "label": "detail-1-placeholder.png"
        }
        d1_image_id = "mock-detail-1-visual"

    # 4. Detail_2
    if len(uploaded_assets) > 3:
        d2_visual = {
            "source_type": "uploaded",
            "asset_id": uploaded_assets[3]["id"],
            "label": uploaded_assets[3]["filename"]
        }
        d2_image_id = uploaded_assets[3]["id"]
    else:
        d2_visual = {
            "source_type": "mock-generated",
            "asset_id": "mock-detail-2-visual",
            "label": "detail-2-placeholder.png"
        }
        d2_image_id = "mock-detail-2-visual"

    # 5. Guarantee
    if len(uploaded_assets) > 4:
        guar_visual = {
            "source_type": "uploaded",
            "asset_id": uploaded_assets[4]["id"],
            "label": uploaded_assets[4]["filename"]
        }
        guar_image_id = uploaded_assets[4]["id"]
    else:
        guar_visual = {
            "source_type": "mock-generated",
            "asset_id": "mock-guarantee-visual",
            "label": "guarantee-placeholder.png"
        }
        guar_image_id = "mock-guarantee-visual"

    sections = [
        {
            "id": "sec-1",
            "title": copy_set.get("hero_title", f"공간의 가치를 더하는 {product_name}"),
            "body": copy_set.get("hero_subtitle", "편리함으로 가득한 일상을 시작해 보세요."),
            "visual_role": "hero",
            "image_id": hero_image_id,
            "visual_slot": hero_visual
        },
        {
            "id": "sec-2",
            "title": copy_set.get("painpoint_title", "번거로움은 이제 그만"),
            "body": copy_set.get("painpoint_body", "더 간편하고 스마트한 선택을 도와드립니다."),
            "visual_role": "comparison",
            "image_id": comp_image_id,
            "visual_slot": comp_visual
        },
        {
            "id": "sec-3",
            "title": copy_set.get("feature_1_title", "믿을 수 있는 기술력"),
            "body": copy_set.get("feature_1_body", "오직 고객을 위해 설계된 뛰어난 기능성"),
            "visual_role": "detail_1",
            "image_id": d1_image_id,
            "visual_slot": d1_visual
        },
        {
            "id": "sec-4",
            "title": copy_set.get("feature_2_title", "엄격한 안전 검증 통과"),
            "body": copy_set.get("feature_2_body", "가족 모두 안심하고 사용할 수 있는 제품"),
            "visual_role": "detail_2",
            "image_id": d2_image_id,
            "visual_slot": d2_visual
        },
        {
            "id": "sec-5",
            "title": copy_set.get("guarantee_title", "정품 등록 및 철저한 A/S"),
            "body": copy_set.get("guarantee_body", "구매 이후에도 지속적인 사후 혜택을 약속합니다."),
            "visual_role": "guarantee",
            "image_id": guar_image_id,
            "visual_slot": guar_visual
        }
    ]

    return {"sections": sections}


def build_mock_qa_report(product_name: str) -> dict:
    return {
        "status": "passed",
        "checked_at": "2026-07-03T14:30:00Z",
        "warnings": [],
        "passed_checks": ["과장 표현 검증 완료", "유해 성분 언급 적합성 통과"],
    }
