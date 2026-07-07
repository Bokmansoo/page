import re
from typing import Dict, Any, List

class CopyQualityGuard:
    FORBIDDEN_WORDS = [
        "정리합니다", "보여주세요", "입력 정보를 바탕으로", "안전한 표현",
        "핵심 사용 가치", "생활 패턴", "초보 구매자", "기존 대안",
        "또렷하게 정리해요", "포인트로 압축합니다", "체크할 항목을 정리",
        "줄이는 역할을 합니다", "분리해 보여줍니다", "안내해 드립니다",
        "작성 가이드", "내부 지시문", "지시문"
    ]
    
    EXAGGERATIONS = [
        "최고", "완벽", "무조건"
    ]

    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        # Remove markers and symbols
        text = text.replace("[AI 수정됨]", "")
        text = text.replace("+", "")
        text = text.replace("—", "")
        text = text.replace("-", "")  # Remove single hyphens that could be markers
        # Replace multiple spaces/newlines
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def validate_text(self, text: str) -> tuple[bool, str | None]:
        if not text:
            return False, "empty"
        
        # Check forbidden words
        for word in self.FORBIDDEN_WORDS:
            if word in text:
                return False, "forbidden_word"
        
        # Check exaggerations
        for ex in self.EXAGGERATIONS:
            if ex in text:
                return False, "exaggeration"
        
        return True, None

    def validate_title(self, title: str) -> tuple[bool, str | None]:
        title = self.clean_text(title)
        if not title or len(title) < 5:
            return False, "too_short"
        
        is_valid, reason = self.validate_text(title)
        if not is_valid:
            return False, reason
            
        return True, None

    def get_default_copy(self, section_type: str, product_name: str = "상품") -> Dict[str, Any]:
        """
        Returns a completely safe, buyer-facing copywriting default for the given section_type.
        """
        defaults = {
            "hero": {
                "title": f"{product_name}, 필요한 순간 바로 쓰는 편리한 선택",
                "bullets": ["언제 어디서나 일상의 편리함을 한층 더 높여 줍니다."]
            },
            "target_customer": {
                "title": "이런 분들께 가장 필요한 기능과 혜택",
                "bullets": ["실용적인 사용성과 간편한 관리를 최우선으로 생각하는 분들께 추천합니다."]
            },
            "problem_situation": {
                "title": "매일 마주하는 아쉬운 순간들, 이제 바꿀 때가 되었습니다",
                "bullets": ["사소한 불편함이 일상의 쾌적함을 방해하고 있지는 않으신가요?"]
            },
            "features": {
                "title": "우수한 성능과 안정성을 갖춘 핵심 설계",
                "bullets": ["기본에 충실하고 안심할 수 있는 기술력으로 일상의 편의를 제공합니다."]
            },
            "lifestyle_scene": {
                "title": "어떤 생활 공간에서도 자연스럽게 어울리는 디자인",
                "bullets": ["모던하고 미니멀한 실루엣으로 시각적인 즐거움과 편안함을 동시에 선사합니다."]
            },
            "comparison": {
                "title": "차별화된 편의 기능과 합리적인 선택의 기준",
                "bullets": ["비교가 필요한 지점을 쉽게 확인할 수 있도록 장점과 사용 기준을 분명하게 보여줍니다."]
            },
            "pre_purchase": {
                "title": "구매하기 전에 구성품과 규격을 꼼꼼하게 확인하세요",
                "bullets": ["제조 정보 및 주요 스펙을 투명하게 안내하여 신뢰를 더합니다."]
            },
            "specifications": {
                "title": "안내된 제품의 상세 스펙과 안전 구성",
                "bullets": ["실제 검증된 패키지 구성품과 기능성 상세 정보를 직관적으로 표기합니다."]
            },
            "caution": {
                "title": "오랫동안 고장 없이 사용하기 위한 안전 수칙",
                "bullets": ["사용 전에 동봉된 매뉴얼의 보관 요령 및 작동 유의사항을 숙지해 주세요."]
            },
            "cta": {
                "title": f"지금 바로 {product_name}를 선택하고 더 쾌적하게 시작해 보세요",
                "bullets": ["망설임 없는 선택이 내일의 더 나은 일상을 만들어 드립니다."]
            }
        }

        # Fallback mappings for problem-solution page narrative types if they differ
        type_mappings = {
            "problem_statement": "problem_situation",
            "main_claim": "hero",
            "secondary_benefit": "features",
            "main_claim_support": "lifestyle_scene",
            "benefit_list": "comparison",
            "summary_claim": "cta",
            "product_information": "specifications"
        }
        
        mapped_type = type_mappings.get(section_type, section_type)
        return defaults.get(mapped_type, {
            "title": f"{product_name}와 함께하는 특별하고 만족스러운 일상",
            "bullets": ["엄선된 기능과 실용적인 구성을 통해 삶의 질을 높여 드립니다."]
        })
