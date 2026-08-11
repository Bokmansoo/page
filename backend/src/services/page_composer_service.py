from typing import Any, Dict, List
from src.db.models import ProductFact, ProductProject
from src.services.commerce_policy import is_confirmed_fact_status

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
                fact_status = fact.get("verification_status", "extracted")
            else:
                fact_id = fact.id
                fact_text = fact.fact_text
                fact_source = fact.extraction_source or "unknown"
                fact_status = fact.verification_status

            field_key = fact.get("field_key") if is_dict else fact.field_key
            normalized_value = fact.get("normalized_value") if is_dict else fact.normalized_value
            normalized_unit = fact.get("normalized_unit") if is_dict else fact.normalized_unit
            if field_key == "charging_port" and str(normalized_value or "").replace("-", "").lower() in {
                "typec",
                "usbc",
            }:
                normalized_value = "Type-C"
            display_text = fact_text
            if normalized_value not in (None, "") and ":" in (fact_text or ""):
                label = fact_text.split(":", 1)[0].strip()
                display_text = f"{label}: {str(normalized_value).strip()}{str(normalized_unit or '').strip()}"

            fact_data = {
                "id": fact_id,
                "text": display_text,
                "source": fact_source,
                "field_key": field_key,
                "normalized_value": normalized_value,
                "normalized_unit": normalized_unit,
                "scope": (fact.get("scope") if is_dict else fact.scope) or "product",
                "model_option": fact.get("model_option") if is_dict else fact.model_option,
            }

            if is_confirmed_fact_status(fact_status):
                confirmed_facts.append(fact_data)
            else:
                needs_verification.append(fact_data)

        # 2. Prioritize URL source if present
        confirmed_facts.sort(key=lambda f: 0 if f["source"] == "url" else 1)

        # 3. Keep seller input as context only. Raw intake text may contain
        # unreviewed numbers or claims, so it must never be promoted into the
        # confirmed fact list used for section copy and grounding checks.
        snapshot = project.intake_snapshot if isinstance(project.intake_snapshot, dict) else {}

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
            "needs_verification": needs_verification,
            "seller_context": project.raw_input_text or "",
        }
