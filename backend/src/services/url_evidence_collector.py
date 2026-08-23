from __future__ import annotations

import ipaddress
import hashlib
import http.client
import json
import socket
import ssl
from datetime import datetime, timezone
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx


class UnsafeSourceURLError(ValueError):
    pass


class OwnedURLCaptureError(ValueError):
    """A recoverable owned-product capture outcome with a stable reason code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ValidatedPublicURLTarget:
    """A URL whose DNS answers have been checked and pinned for one request.

    The fetcher must connect to ``connect_ip`` rather than resolving
    ``hostname`` again.  ``hostname`` remains the HTTP Host header and HTTPS
    SNI/certificate name, so URL semantics and TLS verification are retained.
    """

    normalized_url: str
    hostname: str
    port: int
    connect_ip: str
    resolved_ips: tuple[str, ...]

    @property
    def scheme(self) -> str:
        return urlsplit(self.normalized_url).scheme

    @property
    def request_target(self) -> str:
        parsed = urlsplit(self.normalized_url)
        return urlunsplit(("", "", parsed.path or "/", parsed.query, ""))

    @property
    def host_header(self) -> str:
        default_port = 443 if self.scheme == "https" else 80
        return self.hostname if self.port == default_port else f"{self.hostname}:{self.port}"


@dataclass
class URLEvidence:
    url: str
    title: str = ""
    description: str = ""
    image_urls: list[str] = field(default_factory=list)
    specs: list[dict[str, str]] = field(default_factory=list)
    text_blocks: list[str] = field(default_factory=list)
    ocr_text_blocks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class URLCaptureHTTPResponse:
    """The small, body-bounded transport result used by owned URL capture."""

    status_code: int
    headers: Mapping[str, str]
    content: bytes


@dataclass(frozen=True)
class OwnedProductURLCapture:
    """Structured capture output; raw HTML deliberately never leaves this service."""

    normalized_url: str
    final_url: str
    redirect_chain: tuple[str, ...]
    captured_at: str
    capture_version: str
    parser_version: str
    source_content_hash: str
    title: str
    description: str
    image_urls: tuple[str, ...]
    specs: tuple[dict[str, str], ...]


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


def normalize_public_http_url(url: str) -> str:
    """Return the stable URL identity used before any remote capture.

    Host DNS verification is intentionally repeated by ``validate_public_url``
    immediately before every request and redirect.  This helper only owns
    syntax/identity normalization, so it never turns a mutable URL body into
    an intake source.
    """

    if not isinstance(url, str) or not url.strip():
        raise UnsafeSourceURLError("A product URL is required.")
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise UnsafeSourceURLError("Only public HTTP(S) product URLs are allowed.")
    if parsed.username or parsed.password:
        raise UnsafeSourceURLError("Product URLs must not contain credentials.")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeSourceURLError("Local URLs are not allowed.")
    if hostname in {"metadata", "metadata.google.internal", "metadata.internal"}:
        raise UnsafeSourceURLError("Metadata source URLs are not allowed.")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise UnsafeSourceURLError("Private or reserved source addresses are not allowed.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeSourceURLError("Product URL has an invalid port.") from exc
    netloc = hostname
    if port is not None and not ((parsed.scheme.lower() == "http" and port == 80) or (parsed.scheme.lower() == "https" and port == 443)):
        netloc = f"{hostname}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path or "/", parsed.query, ""))


def resolve_validated_public_url_target(
    url: str,
    resolve_host: Callable[[str], list[str]],
) -> ValidatedPublicURLTarget:
    """Resolve a public source once and return its connect-time target.

    The fail-closed "all answers must be public" policy prevents a hostname
    with mixed public/private A or AAAA answers from choosing a private answer
    during a later DNS resolution.
    """

    normalized = normalize_public_http_url(url)
    parsed = urlsplit(normalized)
    assert parsed.hostname is not None
    try:
        addresses = resolve_host(parsed.hostname)
    except OSError as exc:
        raise OwnedURLCaptureError("capture_failed", "The source host could not be resolved.") from exc
    if not addresses:
        raise OwnedURLCaptureError("capture_failed", "The source host could not be resolved.")
    parsed_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for address in set(addresses):
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeSourceURLError("The source host returned an invalid address.") from exc
        if not ip.is_global:
            raise UnsafeSourceURLError("Private or reserved source addresses are not allowed.")
        parsed_ips.append(ip)
    parsed_ips.sort(key=lambda value: (value.version, int(value)))
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return ValidatedPublicURLTarget(
        normalized_url=normalized,
        hostname=parsed.hostname,
        port=port,
        connect_ip=str(parsed_ips[0]),
        resolved_ips=tuple(str(item) for item in parsed_ips),
    )


def validate_public_url(
    url: str,
    resolve_host: Callable[[str], list[str]],
) -> None:
    """Compatibility validation for non-owned URL collectors.

    Owned product capture uses ``resolve_validated_public_url_target`` and
    consumes the returned connection target.  Older callers retain their
    existing validation-only interface.
    """

    try:
        resolve_validated_public_url_target(url, resolve_host)
    except OwnedURLCaptureError as exc:
        raise UnsafeSourceURLError(str(exc)) from exc


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


class _ValidatedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a validated IP while preserving hostname TLS validation."""

    def __init__(self, target: ValidatedPublicURLTarget):
        super().__init__(
            host=target.connect_ip,
            port=target.port,
            timeout=10.0,
            context=ssl.create_default_context(),
        )
        self._sellform_server_hostname = target.hostname

    def connect(self) -> None:
        self.sock = self._create_connection((self.host, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self._sellform_server_hostname)


def _default_capture_fetch(target: ValidatedPublicURLTarget) -> URLCaptureHTTPResponse:
    """Fetch only through the IP selected by validated DNS resolution.

    This intentionally does not call ``httpx.get(hostname)``: doing so would
    resolve the hostname a second time and reopen the DNS rebinding window.
    """

    try:
        if target.scheme == "https":
            connection: http.client.HTTPConnection = _ValidatedHTTPSConnection(target)
        else:
            connection = http.client.HTTPConnection(target.connect_ip, target.port, timeout=10.0)
        connection.request(
            "GET",
            target.request_target,
            headers={
                "Host": target.host_header,
                "User-Agent": "SellformOwnedProductCapture/1.0",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        response = connection.getresponse()
        content = response.read(2_000_001)
        headers = {str(key).lower(): str(value) for key, value in response.getheaders()}
        status_code = int(response.status)
        connection.close()
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise OwnedURLCaptureError("capture_failed", "Owned product URL capture timed out.") from exc
    return URLCaptureHTTPResponse(
        status_code=status_code,
        headers=headers,
        content=content,
    )


def _capture_failure_for_status(status_code: int) -> OwnedURLCaptureError:
    if status_code in {401, 407}:
        return OwnedURLCaptureError("authentication_required", "The product source requires authentication.")
    if status_code == 403:
        return OwnedURLCaptureError("access_denied", "The product source denied capture access.")
    if status_code in {429, 451}:
        return OwnedURLCaptureError("robots_or_policy_blocked", "The product source blocked automated capture.")
    if 400 <= status_code < 500:
        return OwnedURLCaptureError("unsupported_source", "The product URL is not available for capture.")
    return OwnedURLCaptureError("capture_failed", "The product source could not be captured.")


def capture_owned_product_url(
    url: str,
    *,
    fetch: Callable[[ValidatedPublicURLTarget], URLCaptureHTTPResponse] = _default_capture_fetch,
    resolve_host: Callable[[str], list[str]] = _resolve_host,
    captured_at: str | None = None,
    capture_version: str = "lg12i-owned-url-capture-v1",
    parser_version: str = "url-evidence-parser-v1",
) -> OwnedProductURLCapture:
    """Capture one owned product page through the existing evidence parser.

    Every redirect target is normalized and public-host validated before it is
    requested.  The returned value intentionally exposes structured evidence
    only; callers must persist references/hashes rather than the HTML body.
    """

    current_url = normalize_public_http_url(url)
    redirect_chain: list[str] = [current_url]
    response: URLCaptureHTTPResponse | None = None
    for _ in range(6):
        target = resolve_validated_public_url_target(current_url, resolve_host)
        response = fetch(target)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = next((value for key, value in response.headers.items() if key.lower() == "location"), "")
            if not location:
                raise OwnedURLCaptureError("capture_failed", "The product URL redirect has no destination.")
            next_url = normalize_public_http_url(urljoin(current_url, location))
            # The next loop resolves this hop exactly once and pins that
            # freshly validated result as its actual connection target.
            current_url = next_url
            redirect_chain.append(current_url)
            continue
        break
    else:
        raise OwnedURLCaptureError("unsupported_source", "The product URL has too many redirects.")
    assert response is not None
    if response.status_code < 200 or response.status_code >= 300:
        raise _capture_failure_for_status(response.status_code)
    content_type = next((value for key, value in response.headers.items() if key.lower() == "content-type"), "")
    if "text/html" not in content_type.lower():
        raise OwnedURLCaptureError("unsupported_source", "The product URL did not return HTML content.")
    if len(response.content) > 2_000_000:
        raise OwnedURLCaptureError("unsupported_source", "The product source response is too large to capture safely.")
    html = response.content.decode("utf-8", errors="replace")
    # Reuse the established parser only; OCR is deliberately omitted from this
    # adapter and belongs to the later photo-only task.
    evidence = _collect_url_evidence_from_html(current_url, html, ocr_image=None)
    return OwnedProductURLCapture(
        normalized_url=redirect_chain[0],
        final_url=current_url,
        redirect_chain=tuple(redirect_chain),
        captured_at=captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        capture_version=capture_version,
        parser_version=parser_version,
        source_content_hash=hashlib.sha256(response.content).hexdigest(),
        title=evidence.title,
        description=evidence.description,
        image_urls=tuple(evidence.image_urls),
        specs=tuple(dict(item) for item in evidence.specs),
    )


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
    validate_public_url(url, resolve_host)
    html = fetch_html(url)
    return _collect_url_evidence_from_html(url, html, ocr_image=ocr_image)


def _collect_url_evidence_from_html(
    url: str,
    html: str,
    *,
    ocr_image: Callable[[str], str] | None,
) -> URLEvidence:
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
