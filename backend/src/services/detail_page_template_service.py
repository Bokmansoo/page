from __future__ import annotations

from typing import Any, Dict


TEMPLATES: Dict[str, Dict[str, Any]] = {
    "general_sales": {
        "id": "general_sales",
        "name": "기본 판매형",
        "sections": [
            {"type": "problem", "role": "문제 제기", "optional": False, "visual_strategy": "text_only"},
            {"type": "hero", "role": "메인 소구점 강조", "optional": False, "visual_strategy": "image_overlay"},
            {"type": "benefit_a", "role": "소구점 A", "optional": False, "visual_strategy": "lifestyle_image"},
            {"type": "benefit_b", "role": "소구점 B", "optional": True, "visual_strategy": "lifestyle_image"},
            {"type": "hero_reemphasize", "role": "소구점 A 재강조", "optional": True, "visual_strategy": "image_overlay"},
            {"type": "benefits_summary", "role": "소구점 B~D 정리", "optional": False, "visual_strategy": "graphic_chart"},
            {"type": "overall_summary", "role": "전체 요약", "optional": False, "visual_strategy": "text_only"},
            {"type": "product_info", "role": "상품 정보", "optional": False, "visual_strategy": "html_graphic"},
        ],
    },
    "problem_solving": {
        "id": "problem_solving",
        "name": "문제 해결형",
        "sections": [
            {"type": "problem", "role": "문제 제기", "optional": False, "visual_strategy": "text_only"},
            {"type": "target_customer", "role": "타깃 고객", "optional": False, "visual_strategy": "text_only"},
            {"type": "hero", "role": "메인 소구점 강조", "optional": False, "visual_strategy": "image_overlay"},
            {"type": "features", "role": "소구점 정리", "optional": False, "visual_strategy": "graphic_chart"},
            {"type": "caution", "role": "주의사항", "optional": True, "visual_strategy": "text_only"},
            {"type": "cta", "role": "최종 CTA", "optional": False, "visual_strategy": "image_overlay"},
        ],
    },
    "lifestyle": {
        "id": "lifestyle",
        "name": "라이프스타일형",
        "sections": [
            {"type": "hero", "role": "메인 소구점 강조", "optional": False, "visual_strategy": "image_overlay"},
            {"type": "lifestyle_scene", "role": "사용 장면", "optional": False, "visual_strategy": "lifestyle_image"},
            {"type": "benefit_a", "role": "소구점 A", "optional": False, "visual_strategy": "lifestyle_image"},
            {"type": "benefits_summary", "role": "소구점 B~D 정리", "optional": True, "visual_strategy": "graphic_chart"},
            {"type": "overall_summary", "role": "전체 요약", "optional": False, "visual_strategy": "text_only"},
            {"type": "cta", "role": "최종 CTA", "optional": False, "visual_strategy": "image_overlay"},
        ],
    },
    "comparison_focused": {
        "id": "comparison_focused",
        "name": "스펙 비교형",
        "sections": [
            {"type": "hero", "role": "메인 소구점 강조", "optional": False, "visual_strategy": "image_overlay"},
            {"type": "comparison", "role": "비교 포인트", "optional": False, "visual_strategy": "html_graphic"},
            {"type": "specifications", "role": "구성품/스펙", "optional": False, "visual_strategy": "html_graphic"},
            {"type": "pre_purchase", "role": "구매 전 확인사항", "optional": True, "visual_strategy": "html_graphic"},
            {"type": "product_info", "role": "상품 정보", "optional": False, "visual_strategy": "html_graphic"},
        ],
    },
    "beginner_seller": {
        "id": "beginner_seller",
        "name": "초보 셀러형",
        "sections": [
            {"type": "problem", "role": "문제 제기", "optional": False, "visual_strategy": "text_only"},
            {"type": "hero", "role": "메인 소구점 강조", "optional": False, "visual_strategy": "image_overlay"},
            {"type": "features", "role": "소구점 정리", "optional": False, "visual_strategy": "graphic_chart"},
            {"type": "pre_purchase", "role": "구매 전 확인사항", "optional": False, "visual_strategy": "html_graphic"},
            {"type": "caution", "role": "주의사항", "optional": True, "visual_strategy": "text_only"},
            {"type": "cta", "role": "최종 CTA", "optional": False, "visual_strategy": "image_overlay"},
        ],
    },
    "premium": {
        "id": "premium",
        "name": "프리미엄형",
        "sections": [
            {"type": "hero", "role": "메인 소구점 강조", "optional": False, "visual_strategy": "image_overlay"},
            {"type": "lifestyle_scene", "role": "사용 장면", "optional": False, "visual_strategy": "lifestyle_image"},
            {"type": "overall_summary", "role": "전체 요약", "optional": False, "visual_strategy": "text_only"},
            {"type": "features", "role": "소구점 정리", "optional": False, "visual_strategy": "graphic_chart"},
            {"type": "product_info", "role": "상품 정보", "optional": False, "visual_strategy": "html_graphic"},
        ],
    },
}


class DetailPageTemplateService:
    @staticmethod
    def get_template(template_id: str) -> Dict[str, Any] | None:
        return TEMPLATES.get(template_id)

    @staticmethod
    def select_template_id(category: str | None, intake_snapshot: dict | None) -> str:
        category_text = (category or "").lower()
        snapshot = intake_snapshot or {}
        purpose = str(snapshot.get("selling_purpose") or "").lower()
        audience = str(snapshot.get("target_audience") or "").lower()
        combined = f"{purpose} {audience}"

        if any(keyword in combined for keyword in ["comparison", "compare", "스펙", "비교", "구성품"]):
            return "comparison_focused"
        if any(keyword in combined for keyword in ["premium", "고급", "프리미엄", "브랜드"]):
            return "premium"
        if any(keyword in combined for keyword in ["lifestyle", "라이프", "감성", "사용 장면"]):
            return "lifestyle"
        if any(keyword in combined for keyword in ["problem", "불편", "해결", "고민", "문제"]):
            return "problem_solving"
        if any(keyword in combined for keyword in ["beginner", "초보", "쉬운", "안전"]):
            return "beginner_seller"

        if category_text in ["beauty", "fashion", "뷰티", "패션"]:
            return "premium"
        if category_text in ["living", "생활용품", "리빙"]:
            return "problem_solving"

        return "general_sales"
