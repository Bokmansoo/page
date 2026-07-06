from typing import Any


class VisualBackgroundService:
    def get_candidates(self, project_name: str, category: str | None = None) -> list[dict[str, Any]]:
        # Default 3 candidates for Living category
        candidates = [
            {
                "id": "cooling-blue",
                "title": "쿨링 블루 그라데이션형",
                "description": "시원한 공기감과 휴대용 선풍기 사용 상황을 연상시키는 배경입니다.",
                "palette": ["#EAF4FF", "#DDEBFF", "#FFFFFF"],
                "style_key": "cooling_gradient",
                "safety_note": "실제 제품 이미지, 로고, 인증마크는 생성하지 않습니다."
            },
            {
                "id": "minimal-white",
                "title": "미니멀 화이트 제품 강조형",
                "description": "깨끗하고 세련된 화이트 톤으로 선풍기 본연의 심플한 디자인을 돋보이게 합니다.",
                "palette": ["#F8F9FA", "#E9ECEF", "#FFFFFF"],
                "style_key": "minimal_white",
                "safety_note": "실제 제품 이미지, 로고, 인증마크는 생성하지 않습니다."
            },
            {
                "id": "lifestyle-summer",
                "title": "여름/실내 라이프스타일 무드형",
                "description": "따뜻한 햇살 아래 실내 인테리어와 조화롭게 어우러지는 감성적인 배경입니다.",
                "palette": ["#FFF9F2", "#FFEEDD", "#FFFFFF"],
                "style_key": "lifestyle_summer",
                "safety_note": "실제 제품 이미지, 로고, 인증마크는 생성하지 않습니다."
            }
        ]
        return candidates
