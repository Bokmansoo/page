from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.models import Asset, ProductProject
from src.services.web_browsing_collector import WebBrowsingCollector


SourceKind = Literal["url", "manual_text", "image", "metadata"]


@dataclass(frozen=True)
class CollectedSource:
    source: SourceKind
    text: str
    asset_id: str | None = None


@dataclass(frozen=True)
class FailedSource:
    source: SourceKind
    reason: str
    message: str


@dataclass(frozen=True)
class SourceCollectionResult:
    sources: list[CollectedSource]
    failed_sources: list[FailedSource]


class URLCollectionResult(BaseModel):
    ok: bool
    url: str
    host: str
    text: str
    status_code: Optional[int] = None
    failure_reason: Optional[str] = None


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fed: list[str] = []
        self.in_ignored_tag = False

    def handle_starttag(self, tag, attrs):
        if tag in ["script", "style", "nav", "footer", "header", "noscript"]:
            self.in_ignored_tag = True

    def handle_endtag(self, tag):
        if tag in ["script", "style", "nav", "footer", "header", "noscript"]:
            self.in_ignored_tag = False

    def handle_data(self, data):
        if not self.in_ignored_tag:
            self.fed.append(data)

    def get_data(self):
        text = "".join(self.fed)
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join([line for line in lines if line])


def fetch_url_source(url: str) -> URLCollectionResult:
    try:
        parsed_url = urlparse(url)
        host = parsed_url.netloc or ""
    except Exception:
        host = ""

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        response = httpx.get(url, headers=headers, timeout=10.0)
        status_code = response.status_code
        if response.status_code == 200:
            extractor = HTMLTextExtractor()
            extractor.feed(response.text)
            extracted_text = extractor.get_data()

            if len(extracted_text) > 20000:
                extracted_text = extracted_text[:20000]

            return URLCollectionResult(
                ok=True,
                url=url,
                host=host,
                text=extracted_text,
                status_code=200,
            )

        if response.status_code in [403, 401, 429]:
            return URLCollectionResult(
                ok=False,
                url=url,
                host=host,
                text="",
                status_code=status_code,
                failure_reason="blocked_or_forbidden",
            )

        return URLCollectionResult(
            ok=False,
            url=url,
            host=host,
            text="",
            status_code=status_code,
            failure_reason="network_error",
        )

    except httpx.TimeoutException:
        return URLCollectionResult(
            ok=False,
            url=url,
            host=host,
            text="",
            failure_reason="timeout",
        )
    except Exception:
        return URLCollectionResult(
            ok=False,
            url=url,
            host=host,
            text="",
            failure_reason="network_error",
        )


def collect_project_sources(project: ProductProject, db: Session) -> SourceCollectionResult:
    sources: list[CollectedSource] = []
    failed_sources: list[FailedSource] = []

    if project.raw_input_url:
        url_res = fetch_url_source(project.raw_input_url)
        if url_res.ok:
            sources.append(
                CollectedSource(
                    source="url",
                    text=url_res.text,
                )
            )
        else:
            web_result = WebBrowsingCollector().collect(
                url=project.raw_input_url,
                product_name=project.name,
            )
            if web_result.ok and web_result.text.strip():
                sources.append(
                    CollectedSource(
                        source="url",
                        text=web_result.text.strip(),
                    )
                )
            else:
                failed_sources.append(
                    FailedSource(
                        source="url",
                        reason=web_result.failure_reason or "web_browsing_failed",
                        message=(
                            "AI web browsing fallback failed: "
                            f"{web_result.failure_reason or 'web_browsing_failed'}"
                        ),
                    )
                )

    if project.raw_input_text and project.raw_input_text.strip():
        sources.append(
            CollectedSource(
                source="manual_text",
                text=project.raw_input_text.strip(),
            )
        )

    if project.name:
        sources.append(
            CollectedSource(
                source="metadata",
                text=f"Product name: {project.name}",
            )
        )

    assets = db.query(Asset).filter(Asset.project_id == project.id).all()
    from src.services.image_text_extractor import MockImageTextExtractor

    image_extractor = MockImageTextExtractor()
    for asset in assets:
        extracted = image_extractor.extract(
            asset_id=asset.id,
            filename=asset.filename,
            file_path=asset.file_path,
        )
        if extracted.extracted_text:
            sources.append(
                CollectedSource(
                    source="image",
                    text=extracted.extracted_text,
                    asset_id=asset.id,
                )
            )
        else:
            sources.append(
                CollectedSource(
                    source="image",
                    text=f"Uploaded image asset: {asset.filename}",
                    asset_id=asset.id,
                )
            )
            failed_sources.append(
                FailedSource(
                    source="image",
                    reason="image_text_unavailable",
                    message=f"이미지 '{asset.filename}'에서 읽을 수 있는 텍스트를 찾지 못했습니다.",
                )
            )

    return SourceCollectionResult(sources=sources, failed_sources=failed_sources)
