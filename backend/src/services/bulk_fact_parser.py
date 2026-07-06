import re


COMMERCE_NOISE_PATTERNS = [
    "무료배송",
    "배송비",
    "구매후기",
    "상품평",
    "리뷰",
    "쿠팡 추천",
    "광고",
    "판매자",
    "장바구니",
    "찜하기",
]


def _clean_bulk_fact_line(raw_line: str) -> str:
    line = raw_line.strip()
    line = re.sub(r"^[-*•\d\.\)\s]+", "", line).strip()
    return line


def _is_noise_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line).lower()
    return any(re.sub(r"\s+", "", pattern).lower() in compact for pattern in COMMERCE_NOISE_PATTERNS)


def parse_bulk_fact_text(text: str, max_items: int = 50) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for raw_line in normalized.split("\n"):
        line = _clean_bulk_fact_line(raw_line)
        if not line:
            continue
        if len(line) < 3:
            continue
        if _is_noise_line(line):
            continue
        lines.append(line)

    unique: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = re.sub(r"\s+", "", line).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(line)
        if len(unique) >= max_items:
            break
    return unique
