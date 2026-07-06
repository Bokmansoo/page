import pytest
from src.services.web_browsing_collector import WebBrowsingCollector, WebBrowsingCollectionResult


def test_web_browsing_collector_returns_disabled_when_api_key_missing(monkeypatch):
    monkeypatch.setattr("src.services.web_browsing_collector.settings.OPENAI_API_KEY", None)

    result = WebBrowsingCollector().collect(
        url="https://www.coupang.com/vp/products/example",
        product_name="루메나 휴대용 무선 냉각선풍기",
    )

    assert result.ok is False
    assert result.failure_reason == "web_browsing_api_key_missing"
    assert result.text == ""


def test_web_browsing_collector_uses_openai_responses_web_search(monkeypatch):
    monkeypatch.setattr("src.services.web_browsing_collector.settings.OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("src.services.web_browsing_collector.settings.SELLFORM_WEB_BROWSING_MODEL", "gpt-5.4-nano")

    class FakeOutputText:
        type = "output_text"
        text = "4,800mAh 배터리와 최대 18시간 무선 사용 가능 정보가 확인되었습니다."

    class FakeMessage:
        content = [FakeOutputText()]

    class FakeResponse:
        output = [FakeMessage()]

    class FakeResponses:
        def create(self, **kwargs):
            assert kwargs["model"] == "gpt-5.4-nano"
            assert kwargs["tools"] == [{"type": "web_search_preview"}]
            assert "루메나 휴대용 무선 냉각선풍기" in kwargs["input"]
            return FakeResponse()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr("src.services.web_browsing_collector.OpenAI", lambda api_key: FakeClient())

    result = WebBrowsingCollector().collect(
        url="https://www.coupang.com/vp/products/example",
        product_name="루메나 휴대용 무선 냉각선풍기",
    )

    assert result.ok is True
    assert "4,800mAh" in result.text
    assert result.provider == "openai"
    assert result.model == "gpt-5.4-nano"


def test_web_browsing_collector_prompt_is_readable_korean(monkeypatch):
    monkeypatch.setattr("src.services.web_browsing_collector.settings.OPENAI_API_KEY", "test-key")
    captured: dict[str, str] = {}

    class FakeOutputText:
        type = "output_text"
        text = "상품명과 링크를 기준으로 확인 가능한 정보가 요약되었습니다."

    class FakeMessage:
        content = [FakeOutputText()]

    class FakeResponse:
        output = [FakeMessage()]

    class FakeResponses:
        def create(self, **kwargs):
            captured["input"] = kwargs["input"]
            return FakeResponse()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr("src.services.web_browsing_collector.OpenAI", lambda api_key: FakeClient())

    result = WebBrowsingCollector().collect(
        url="https://www.coupang.com/vp/products/example",
        product_name="루메나 휴대용 무선 냉각선풍기",
    )

    assert result.ok is True
    assert "검증 가능한 상품 정보" in captured["input"]
    assert "근거가 불분명하면 추정하지 말고" in captured["input"]
    assert "루메나 휴대용 무선 냉각선풍기" in captured["input"]
