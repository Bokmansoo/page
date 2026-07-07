from typing import Any, Dict, List
from src.db.models import ProductFact, ProductProject

class PageComposerService:
    @staticmethod
    def normalize_facts(project: ProductProject, facts: List[Any]) -> Dict[str, Any]:
        """
        Normalises product facts and input attributes for detail page generation.
        Supports both SQLAlchemy ProductFact models and dictionaries.
        Prioritizes URL sources and separates unverified/uncertain facts.
        """
        confirmed_facts = []
        needs_verification = []

        # 1. Classify facts by verification status and source
        for fact in facts:
            is_dict = isinstance(fact, dict)
            
            if is_dict:
                fact_id = fact.get("id")
                fact_text = fact.get("fact_text") or fact.get("text")
                fact_source = fact.get("source_text") or fact.get("source") or "unknown"
                fact_status = fact.get("verification_status", "confirmed")
            else:
                fact_id = fact.id
                fact_text = fact.fact_text
                fact_source = fact.extraction_source or "unknown"
                fact_status = fact.verification_status

            fact_data = {
                "id": fact_id,
                "text": fact_text,
                "source": fact_source,
            }

            if fact_status == "confirmed":
                confirmed_facts.append(fact_data)
            else:
                needs_verification.append(fact_data)

        # 2. Prioritize URL source if present
        confirmed_facts.sort(key=lambda f: 0 if f["source"] == "url" else 1)

        # 3. Incorporate user inputs, options, and image descriptions
        snapshot = project.intake_snapshot if isinstance(project.intake_snapshot, dict) else {}
        
        # User input text
        if project.raw_input_text:
            if not any(f["text"] == project.raw_input_text for f in confirmed_facts):
                confirmed_facts.append({
                    "id": "raw_input_text",
                    "text": project.raw_input_text,
                    "source": "manual_text"
                })

        # Product options from snapshot
        options = snapshot.get("options")
        if not options and "confirmed_understanding" in snapshot:
            options = snapshot["confirmed_understanding"].get("options", {}).get("value")
        
        if options:
            options_str = str(options)
            if not any(options_str in f["text"] for f in confirmed_facts):
                confirmed_facts.append({
                    "id": "intake_options",
                    "text": f"상품 옵션 정보: {options_str}",
                    "source": "options"
                })

        # Image descriptions
        image_desc = snapshot.get("image_descriptions")
        if not image_desc and "confirmed_understanding" in snapshot:
            image_desc = snapshot["confirmed_understanding"].get("image_candidates")
        
        if image_desc:
            desc_str = str(image_desc)
            if not any(desc_str in f["text"] for f in confirmed_facts):
                confirmed_facts.append({
                    "id": "image_descriptions",
                    "text": f"업로드 이미지 설명: {desc_str}",
                    "source": "image_description"
                })

        return {
            "product_facts": confirmed_facts,
            "needs_verification": needs_verification
        }
