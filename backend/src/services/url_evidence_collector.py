from __future__ import annotations

import ipaddress
import json
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlparse

import httpx


class UnsafeSourceURLError(ValueError):
    pass


@dataclass
class URLEvidence:
    url: str
    title: str = ""
    description: str = ""
    image_urls: list[str] = field(default_factory=list)
    specs: list[dict[str, str]] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)
    ocr_text_blocks: list[str] = field(default_factory=list)


class _EvidenceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta_images: list[str] = []
        self.images: list[str] = []
        self.json_ld: list[str] = []
        self.table_specs: list[dict[str, str]] = []
        self.text_blocks: list[str] = []
        self._tag = ""
        self._buffer: list[str] = []
        self._table_cells: list[str] = []

    def handle_starttag(self, tag, attrs):
        self._tag = tag
        attrs_map = dict(attrs)
        if tag == "meta" and attrs_map.get("property") in {"og:image", "twitter:image"}:
            if attrs_map.get("content"):
                self.meta_images.append(attrs_map["content"])
        if tag == "img" and attrs_map.get("src"):
            self.images.append(attrs_map["src"])
        if tag in {"title", "script", "th", "td", "li", "p"}:
            self._buffer = []

    def handle_data(self, data):
        if self._tag in {"title", "script", "th", "td", "li", "p"}:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        text = " ".join("".join(self._buffer).split())
        if tag == "title" and text:
            self.title = text
        elif tag == "script" and text:
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = None
            if parsed is not None:
                self.json_ld.append(text)
        elif tag in {"th", "td"} and text:
            self._table_cells.append(text)
        elif tag == "tr":
            if len(self._table_cells) >= 2:
                self.table_specs.append(
                    {"label": self._table_cells[0], "value": self._table_cells[1]}
                )
            self._table_cells = []
        elif tag in {"li", "p"} and text:
            self.text_blocks.append(text)
        self._tag = ""
        self._buffer = []


def _resolve_host(host: str) -> list[str]:
    return list(
        {
            item[4][0]
            for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    )


def _validate_url(
    url: str,
    resolve_host: Callable[[str], list[str]],
) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeSourceURLError("Only public HTTP(S) product URLs are allowed.")
    if parsed.hostname.lower() == "localhost":
        raise UnsafeSourceURLError("Local URLs are not allowed.")
    try:
        addresses = resolve_host(parsed.hostname)
    except OSError as exc:
        raise UnsafeSourceURLError("The source host could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeSourceURLError("Private or reserved source addresses are not allowed.")


def _default_fetch_html(url: str) -> str:
    response = httpx.get(
        url,
        headers={"User-Agent": "SellformSourceCollector/1.0"},
        timeout=10.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    if "text/html" not in response.headers.get("content-type", ""):
        raise ValueError("Source URL did not return HTML.")
    content = response.content[:2_000_000]
    return content.decode(response.encoding or "utf-8", errors="replace")


def _iter_json_objects(value):
    if isinstance(value, list):
        for item in value:
            yield from _iter_json_objects(item)
    elif isinstance(value, dict):
        yield value
        if "@graph" in value:
            yield from _iter_json_objects(value["@graph"])


def collect_url_evidence(
    url: str,
    *,
    fetch_html: Callable[[str], str] = _default_fetch_html,
    resolve_host: Callable[[str], list[str]] = _resolve_host,
    ocr_image: Callable[[str], str] | None = None,
) -> URLEvidence:
    _validate_url(url, resolve_host)
    html = fetch_html(url)
    parser = _EvidenceParser()
    parser.feed(html)

    result = URLEvidence(url=url, title=parser.title, text_blocks=parser.text_blocks[:50])
    json_images: list[str] = []
    for raw_json in parser.json_ld:
        try:
            payload = json.loads(raw_json)
        except ValueError:
            continue
        for item in _iter_json_objects(payload):
            item_type = item.get("@type")
            if isinstance(item_type, list):
                is_product = "Product" in item_type
            else:
                is_product = item_type == "Product"
            if not is_product:
                continue
            result.title = str(item.get("name") or result.title)
            result.description = str(item.get("description") or result.description)
            images = item.get("image") or []
            if isinstance(images, str):
                images = [images]
            json_images.extend(str(image) for image in images if image)
            for prop in item.get("additionalProperty") or []:
                if isinstance(prop, dict) and prop.get("name") and prop.get("value") is not None:
                    result.specs.append(
                        {"label": str(prop["name"]), "value": str(prop["value"])}
                    )

    result.specs.extend(parser.table_specs)
    seen: set[str] = set()
    for image in [*parser.meta_images, *json_images, *parser.images]:
        absolute = urljoin(url, image)
        if absolute not in seen:
            result.image_urls.append(absolute)
            seen.add(absolute)

    if ocr_image:
        for image_url in result.image_urls[:3]:
            text = ocr_image(image_url).strip()
            if text and text not in result.ocr_text_blocks:
                result.ocr_text_blocks.append(text)
    return result
