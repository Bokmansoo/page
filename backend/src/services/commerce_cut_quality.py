from typing import Any


def inspect_commerce_cuts_quality(cuts: list[dict[str, Any] | Any]) -> list[str]:
    """Inspect quality of advertising cuts and return actionable warning messages."""
    warnings = []

    for idx, cut in enumerate(cuts):
        # Support both dict and object
        if isinstance(cut, dict):
            sec_type = cut.get("section_type") or "unknown"
            layout_type = cut.get("layout_type") or "unknown"
            headline = cut.get("headline") or ""
            subcopy = cut.get("subcopy") or ""
            image_asset_id = cut.get("image_asset_id")
        else:
            sec_type = getattr(cut, "section_type", "unknown")
            layout_type = getattr(cut, "layout_type", "unknown")
            headline = getattr(cut, "headline", "")
            subcopy = getattr(cut, "subcopy", "")
            image_asset_id = getattr(cut, "image_asset_id", None)

        # 1. Headline length inspection (>36)
        if len(headline) > 36:
            warnings.append(f"[{sec_type}] 컷의 헤드라인이 너무 깁니다 ({len(headline)}자). 36자 이하로 줄여주세요.")

        # 2. Subcopy length inspection (>90)
        if len(subcopy) > 90 and sec_type != "product_information":
            warnings.append(f"[{sec_type}] 컷의 서브카피가 너무 깁니다 ({len(subcopy)}자). 90자 이하로 압축해 주세요.")

        # 3. Missing image warning for critical sections
        if not image_asset_id and sec_type in {"header", "problem_statement", "main_claim"}:
            warnings.append(f"[{sec_type}] 컷은 페이지 주목도 향상을 위해 상품/상황 이미지가 필수로 요구됩니다.")

        # 4. Long spec table warning
        if sec_type == "product_information" and len(subcopy) > 400:
            warnings.append(f"[{sec_type}] 확인 정보의 텍스트가 너무 길어 표가 복잡해집니다. 주요 제원만 남기고 간소화해 주세요.")

    return warnings
