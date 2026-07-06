from dataclasses import dataclass
from openai import OpenAI
from src.config import settings


@dataclass(frozen=True)
class WebBrowsingCollectionResult:
    ok: bool
    text: str
    provider: str | None = None
    model: str | None = None
    failure_reason: str | None = None


def _extract_output_text(response) -> str:
    chunks: list[str] = []
    for output in getattr(response, "output", []) or []:
        for content in getattr(output, "content", []) or []:
            if getattr(content, "type", None) == "output_text":
                chunks.append(getattr(content, "text", ""))
    return "\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())


class WebBrowsingCollector:
    def collect(self, url: str, product_name: str | None = None) -> WebBrowsingCollectionResult:
        if not settings.SELLFORM_WEB_BROWSING_ENABLED:
            return WebBrowsingCollectionResult(
                ok=False,
                text="",
                failure_reason="web_browsing_disabled",
            )

        if not settings.OPENAI_API_KEY:
            return WebBrowsingCollectionResult(
                ok=False,
                text="",
                provider=settings.SELLFORM_WEB_BROWSING_PROVIDER,
                model=settings.SELLFORM_WEB_BROWSING_MODEL,
                failure_reason="web_browsing_api_key_missing",
            )

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        query = (
            "다음 상품 링크와 상품명을 바탕으로 상세페이지 사실 카드에 쓸 수 있는 "
            "검증 가능한 상품 정보만 한국어로 요약하세요. "
            "근거가 불분명하면 추정하지 말고 불확실하다고 말하세요.\n\n"
            f"상품명: {product_name or ''}\n"
            f"상품 링크: {url}"
        )

        try:
            response = client.responses.create(
                model=settings.SELLFORM_WEB_BROWSING_MODEL,
                tools=[{"type": "web_search_preview"}],
                input=query,
                timeout=settings.SELLFORM_WEB_BROWSING_TIMEOUT_SECONDS,
            )
            text = _extract_output_text(response)
            if len(text) > settings.SELLFORM_WEB_BROWSING_MAX_CHARS:
                text = text[: settings.SELLFORM_WEB_BROWSING_MAX_CHARS]
            if not text.strip():
                return WebBrowsingCollectionResult(
                    ok=False,
                    text="",
                    provider="openai",
                    model=settings.SELLFORM_WEB_BROWSING_MODEL,
                    failure_reason="web_browsing_empty_result",
                )
            return WebBrowsingCollectionResult(
                ok=True,
                text=text,
                provider="openai",
                model=settings.SELLFORM_WEB_BROWSING_MODEL,
            )
        except Exception:
            return WebBrowsingCollectionResult(
                ok=False,
                text="",
                provider="openai",
                model=settings.SELLFORM_WEB_BROWSING_MODEL,
                failure_reason="web_browsing_failed",
            )
