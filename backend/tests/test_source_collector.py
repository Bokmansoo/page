import pytest
import httpx
from unittest.mock import patch, MagicMock
from src.services.source_collector import fetch_url_source, collect_project_sources, URLCollectionResult
from src.services.web_browsing_collector import WebBrowsingCollectionResult
from src.db.models import ProductProject


def test_fetch_url_source_success():
    # Mock successful response
    target_url = "https://example.com/product/123"
    
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = "<html><head><style>body {background: red;}</style></head><body><h1>루메나 선풍기</h1><p>4,800mAh 대용량 배터리 탑재</p><script>console.log('test')</script></body></html>"
    
    with patch("httpx.get", return_value=mock_response) as mock_get:
        result = fetch_url_source(target_url)
        mock_get.assert_called_once()

        
        assert result.ok is True
        assert result.url == target_url
        assert result.host == "example.com"
        assert "background: red" not in result.text
        assert "console.log" not in result.text
        assert "루메나 선풍기" in result.text
        assert "4,800mAh" in result.text


def test_fetch_url_source_forbidden():
    target_url = "https://coupang.com/product/456"
    
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 403
    mock_response.text = "Forbidden"
    
    with patch("httpx.get", return_value=mock_response):
        result = fetch_url_source(target_url)
        assert result.ok is False
        assert result.status_code == 403
        assert result.failure_reason == "blocked_or_forbidden"


def test_fetch_url_source_timeout():
    target_url = "https://slow.com/product"
    
    with patch("httpx.get", side_effect=httpx.TimeoutException("Timeout")):
        result = fetch_url_source(target_url)
        assert result.ok is False
        assert result.failure_reason == "timeout"


def test_fetch_url_source_network_error():
    target_url = "https://invalid-domain-name.com"
    
    with patch("httpx.get", side_effect=httpx.NetworkError("Network error")):
        result = fetch_url_source(target_url)
        assert result.ok is False
        assert result.failure_reason == "network_error"


def test_collect_project_sources_reports_web_browsing_api_key_missing(monkeypatch):
    project = ProductProject(
        id="project-1",
        workspace_id="workspace-1",
        brand_id="brand-1",
        name="루메나 휴대용 무선 냉각선풍기",
        raw_input_url="https://www.coupang.com/vp/products/example",
        raw_input_text="",
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class FakeDB:
        def query(self, *args, **kwargs):
            return FakeQuery()

    monkeypatch.setattr(
        "src.services.source_collector.fetch_url_source",
        lambda url: URLCollectionResult(
            ok=False,
            url=url,
            host="www.coupang.com",
            text="",
            status_code=403,
            failure_reason="blocked_or_forbidden",
        ),
    )

    class FakeWebCollector:
        def collect(self, url, product_name=None):
            return WebBrowsingCollectionResult(
                ok=False,
                text="",
                provider="openai",
                model="gpt-5.4-nano",
                failure_reason="web_browsing_api_key_missing",
            )

    monkeypatch.setattr("src.services.source_collector.WebBrowsingCollector", lambda: FakeWebCollector())

    result = collect_project_sources(project, FakeDB())

    assert any(
        failed.source == "url" and failed.reason == "web_browsing_api_key_missing"
        for failed in result.failed_sources
    )
