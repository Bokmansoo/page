import pytest

from src.services.url_evidence_collector import (
    UnsafeSourceURLError,
    collect_url_evidence,
)


HTML = """
<html>
  <head>
    <title>LED 어린이 자전거</title>
    <meta property="og:image" content="/images/hero.jpg">
    <script type="application/ld+json">
      {
        "@type": "Product",
        "name": "LED 어린이 자전거",
        "image": ["/images/product-front.jpg"],
        "description": "보조 바퀴를 탈착할 수 있습니다.",
        "additionalProperty": [
          {"name": "무게", "value": "6kg"},
          {"name": "권장 연령", "value": "3~6세"}
        ]
      }
    </script>
  </head>
  <body>
    <table><tr><th>소재</th><td>알루미늄</td></tr></table>
    <img src="/images/detail.jpg" alt="제품 측면">
  </body>
</html>
"""


def test_collect_url_evidence_extracts_images_and_specs():
    result = collect_url_evidence(
        "https://shop.example.com/products/bike",
        fetch_html=lambda _url: HTML,
        resolve_host=lambda _host: ["8.8.8.8"],
        ocr_image=lambda url: "LED 표시창" if url.endswith("detail.jpg") else "",
    )

    assert result.title == "LED 어린이 자전거"
    assert result.image_urls == [
        "https://shop.example.com/images/hero.jpg",
        "https://shop.example.com/images/product-front.jpg",
        "https://shop.example.com/images/detail.jpg",
    ]
    assert {"label": "무게", "value": "6kg"} in result.specs
    assert {"label": "권장 연령", "value": "3~6세"} in result.specs
    assert {"label": "소재", "value": "알루미늄"} in result.specs
    assert result.ocr_text_blocks == ["LED 표시창"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://localhost/admin",
        "file:///etc/passwd",
    ],
)
def test_collect_url_evidence_blocks_private_or_non_http_sources(url):
    with pytest.raises(UnsafeSourceURLError):
        collect_url_evidence(url, fetch_html=lambda _url: HTML)
