import base64
import os
import hashlib
import json
import re
import shutil
import zipfile
import uuid
import datetime
from io import BytesIO
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlencode
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy.orm import Session
from src.db.models import Asset, ExportArtifact
from src.services.commerce_policy import REFERENCE_SOURCE_TYPES, is_asset_final_output_eligible
from src.services.page_asset_policy import get_page_eligible_assets
from src.services.channel_export_service import get_channel_preset, image_sha256, supported_channel_keys
from src.services.page_visual_contract import LG11CanvasSafetyError, ensure_lg11_canvas_safe, validate_lg11_canvas_safety
from src.services.prompt_intelligence_service import canonical_hash


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_LG10_DETAIL_PAGE_VERSION_SCHEMA = "lg10-detail-page-version-v1"
_LG10_COPYABLE_HTML_ARTIFACT = "lg10_copyable_html"
_LG10_STANDALONE_PACKAGE_ARTIFACT = "lg10_standalone_package"
LG12_FROZEN_EXPORT_PARITY_EVIDENCE_SCHEMA_VERSION = "lg12-frozen-export-parity-evidence-v1"
LG12_CHANNEL_TRANSFORM_VERSION = "channel-export-bundle-v1"
LG12_STANDALONE_TRANSFORM_VERSION = "lg10-standalone-export-v1"
_LG11_CHANNEL_ARTIFACT_TYPES = frozenset({"channel_long", "channel_package"})
_LG11_EXPORT_FORMATS = frozenset({"png", "jpg", "jpeg", "html", "zip"})


class FrozenExportSnapshotError(ValueError):
    """The immutable LG-10 version cannot safely be converted to a package."""


def parse_lg11_export_artifact_token(artifact_token: str) -> dict[str, str] | None:
    """Parse one channel-bound frozen artifact without guessing its channel.

    The same parser is consumed by download admission and LG-12 parity checks.
    In particular, the last token is always a format, never a fallback channel.
    """

    parts = str(artifact_token or "").split(":")
    if len(parts) == 3 and parts[0] in _LG11_CHANNEL_ARTIFACT_TYPES:
        artifact_type, channel, output_format = parts
        if channel in supported_channel_keys() and output_format in _LG11_EXPORT_FORMATS:
            return {"artifact_type": artifact_type, "channel": channel, "format": output_format}
        return None
    if len(parts) == 2 and parts[1] in supported_channel_keys():
        if parts[0] == _LG10_COPYABLE_HTML_ARTIFACT:
            return {"artifact_type": parts[0], "channel": parts[1], "format": "html"}
        if parts[0] == _LG10_STANDALONE_PACKAGE_ARTIFACT:
            return {"artifact_type": parts[0], "channel": parts[1], "format": "zip"}
    return None


def _lg12_hash_reference(*, identifier: str, version: str | int, digest: str, artifact_type: str) -> dict[str, Any]:
    if not identifier or not digest or not _SHA256_HEX.fullmatch(str(digest)):
        raise FrozenExportSnapshotError("Frozen export parity evidence requires an exact ID/version/hash reference.")
    return {"id": str(identifier), "version": version, "hash": str(digest), "type": artifact_type}


def _lg12_frozen_preview_parity_evidence(version, *, channel: str) -> dict[str, Any]:
    """Derive bounded preview identity only from an immutable DetailPageVersion."""

    if channel not in supported_channel_keys():
        raise FrozenExportSnapshotError("Frozen preview parity requires an explicit supported channel.")
    # Export creation enforces LG-11 safety.  Read-only QA must instead be
    # able to return the frozen violation as structured evidence.
    snapshot, rendering, manifest = _frozen_lg10_export_inputs(
        version, channel=channel, enforce_channel_safety=False,
    )
    snapshot_body = dict(snapshot)
    snapshot_hash = str(snapshot_body.pop("snapshot_hash", "") or "")
    if not snapshot_hash or canonical_hash(snapshot_body) != snapshot_hash:
        raise FrozenExportSnapshotError("Frozen DetailPageVersion hash is invalid for parity evidence.")
    rendering_body = dict(rendering)
    render_hash = str(rendering_body.pop("render_hash", "") or "")
    if not render_hash or canonical_hash(rendering_body) != render_hash:
        raise FrozenExportSnapshotError("Frozen renderer hash is invalid for parity evidence.")
    manifest_body = dict(manifest)
    manifest_hash = str(manifest_body.pop("manifest_hash", "") or "")
    if not manifest_hash or canonical_hash(manifest_body) != manifest_hash:
        raise FrozenExportSnapshotError("Frozen approved asset manifest hash is invalid for parity evidence.")
    canonical = dict(dict(snapshot.get("lg10") or {}).get("canonical_page_assembly_input") or {})
    rendered_sections = [dict(item) for item in list(rendering.get("sections") or []) if isinstance(item, Mapping)]
    if not rendered_sections:
        raise FrozenExportSnapshotError("Frozen preview parity requires rendered section identities.")
    sections = [
        {
            "section_id": str(section.get("section_id") or ""),
            "sort_order": int(section.get("sort_order")),
            "visible": bool(dict(section.get("canvas") or {}).get("is_visible", True)),
            "height_px": int(dict(section.get("canvas") or {}).get("height_px") or 0),
        }
        for section in rendered_sections
    ]
    if not all(item["section_id"] for item in sections) or len({item["section_id"] for item in sections}) != len(sections):
        raise FrozenExportSnapshotError("Frozen preview contains invalid section identities.")
    copy_fields: list[dict[str, str]] = []
    element_refs: list[dict[str, str]] = []
    preview_height = 0
    for section in rendered_sections:
        canvas = dict(section.get("canvas") or {})
        if bool(canvas.get("is_visible", True)):
            preview_height += max(0, int(canvas.get("height_px") or 0))
        section_id = str(section.get("section_id") or "")
        for element in list(section.get("canvas_elements") or []):
            if not isinstance(element, Mapping) or bool(element.get("deleted", False)):
                continue
            element_id = str(element.get("element_id") or "")
            if not element_id:
                raise FrozenExportSnapshotError("Frozen preview contains an element without a stable identity.")
            # Geometry, lock/group and visibility semantics are pinned by a
            # hash only: QA reports never embed editable canvas payloads.
            element_refs.append({
                "section_id": section_id,
                "element_id": element_id,
                "element_hash": canonical_hash(dict(element)),
            })
        for field in list(section.get("text_layer") or []):
            if not isinstance(field, Mapping):
                continue
            field_id = str(field.get("field") or "")
            if field_id:
                copy_fields.append({"field": field_id, "text_hash": canonical_hash(str(field.get("text") or ""))})
    asset_refs = [
        {"asset_id": str(item.get("asset_id") or ""), "asset_content_hash": str(item.get("asset_content_hash") or "")}
        for item in list(manifest.get("assets") or []) if isinstance(item, Mapping)
    ]
    if any(not item["asset_id"] or not _SHA256_HEX.fullmatch(item["asset_content_hash"]) for item in asset_refs):
        raise FrozenExportSnapshotError("Frozen preview asset manifest contains invalid asset references.")
    if len(element_refs) > 256 or len({(item["section_id"], item["element_id"]) for item in element_refs}) != len(element_refs):
        raise FrozenExportSnapshotError("Frozen preview contains invalid element identities.")
    evidence = dict(rendering.get("lg12_layout_evidence") or {})
    evidence_hash = str(evidence.get("evidence_hash") or "")
    if evidence_hash:
        evidence_body = dict(evidence); evidence_body.pop("evidence_hash", None)
        if not _SHA256_HEX.fullmatch(evidence_hash) or canonical_hash(evidence_body) != evidence_hash:
            raise FrozenExportSnapshotError("Frozen layout evidence hash is invalid for parity evidence.")
    page_plan = dict((canonical.get("planning_refs") or {}).get("page_plan") or {})
    brand_ref = dict(canonical.get("brand_kit_ref") or {})
    return {
        "page_ref": _lg12_hash_reference(identifier=str(version.id), version=str(snapshot.get("schema_version") or ""), digest=snapshot_hash, artifact_type="DetailPageVersion"),
        "preview_ref": _lg12_hash_reference(identifier=f"canonical-preview:{version.id}", version=str(rendering.get("renderer_version") or "lg10"), digest=render_hash, artifact_type="frozen_preview"),
        "renderer_ref": _lg12_hash_reference(identifier=f"canonical-renderer:{version.id}", version=str(rendering.get("renderer_version") or "lg10"), digest=render_hash, artifact_type="frozen_renderer"),
        "channel": channel,
        "manifest_hash": manifest_hash,
        "sections": sections,
        "element_refs": sorted(element_refs, key=lambda item: (item["section_id"], item["element_id"], item["element_hash"])),
        "preview_dimensions": {
            "width": int((validate_lg11_canvas_safety(version_snapshot=snapshot, channel=channel).get("viewport") or {}).get("width") or 0),
            "height": preview_height,
        },
        "asset_refs": sorted(asset_refs, key=lambda item: (item["asset_id"], item["asset_content_hash"])),
        "copy_refs": sorted(copy_fields, key=lambda item: (item["field"], item["text_hash"])),
        "layout_evidence_hash": evidence_hash or None,
        "page_plan_ref": {
            "type": "PagePlanVersion",
            "id": str(page_plan.get("id") or page_plan.get("artifact_id") or ""),
            "version": page_plan.get("version") or page_plan.get("artifact_version"),
            "hash": str(page_plan.get("hash") or page_plan.get("artifact_hash") or ""),
        },
        "brand_kit_ref": {
            "type": "BrandKitVersion",
            "id": str(brand_ref.get("brand_kit_version_id") or ""),
            "version": str((rendering.get("brand_tokens") or {}).get("brand_kit_version") or ""),
            "hash": str(brand_ref.get("brand_kit_hash") or ""),
        },
        "canvas_safety": validate_lg11_canvas_safety(version_snapshot=snapshot, channel=channel),
    }


def frozen_preview_parity_evidence(version, *, channel: str) -> dict[str, Any]:
    """Public read-only frozen preview identity used by TASK-12.7."""

    return _lg12_frozen_preview_parity_evidence(version, channel=channel)


def _lg12_parity_evidence_path(file_path: str) -> Path:
    return Path(f"{file_path}.lg12-parity.json")


def write_lg12_frozen_export_parity_evidence(*, version, artifact: ExportArtifact, channel: str) -> dict[str, Any]:
    """Freeze bounded lineage beside a produced export file.

    This is deliberately called only after the output file and immutable
    ExportArtifact row exist.  It never serializes HTML, images, ZIP members,
    or mutable preview state.
    """

    parsed = parse_lg11_export_artifact_token(artifact.artifact_type)
    if parsed is None or parsed["channel"] != channel:
        raise FrozenExportSnapshotError("Export artifact channel identity is missing or mismatched.")
    if not artifact.id or not artifact.file_path or not os.path.isfile(artifact.file_path):
        raise FrozenExportSnapshotError("Frozen export artifact file is unavailable for parity evidence.")
    # A produced artifact is still admitted only after the production LG-11
    # safety check; the non-enforcing read above is QA-only.
    _frozen_lg10_export_inputs(version, channel=channel)
    preview = _lg12_frozen_preview_parity_evidence(version, channel=channel)
    preset = get_channel_preset(channel)
    file_hash = image_sha256(artifact.file_path)
    transform = (
        LG12_CHANNEL_TRANSFORM_VERSION
        if parsed["artifact_type"] in _LG11_CHANNEL_ARTIFACT_TYPES
        else LG12_STANDALONE_TRANSFORM_VERSION
    )
    body = {
        "schema_version": LG12_FROZEN_EXPORT_PARITY_EVIDENCE_SCHEMA_VERSION,
        "artifact_ref": _lg12_hash_reference(identifier=str(artifact.id), version=1, digest=file_hash, artifact_type="ExportArtifact"),
        "artifact_type": parsed["artifact_type"], "channel": channel, "format": parsed["format"],
        "file_sha256": file_hash,
        "page_ref": preview["page_ref"], "preview_ref": preview["preview_ref"], "renderer_ref": preview["renderer_ref"],
        "manifest_hash": preview["manifest_hash"], "sections": preview["sections"], "element_refs": preview["element_refs"],
        "preview_dimensions": preview["preview_dimensions"], "asset_refs": preview["asset_refs"],
        "copy_refs": preview["copy_refs"], "layout_evidence_hash": preview["layout_evidence_hash"],
        "page_plan_ref": preview["page_plan_ref"], "brand_kit_ref": preview["brand_kit_ref"],
        "preset": {"key": preset.key, "version": preset.version, "width": preset.width, "max_segment_height": preset.max_segment_height, "default_format": preset.default_format},
        "transform_version": transform,
    }
    evidence = {**body, "evidence_hash": canonical_hash(body)}
    _lg12_parity_evidence_path(artifact.file_path).write_text(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8",
    )
    return evidence


def load_lg12_frozen_export_parity_evidence(*, artifact: ExportArtifact) -> dict[str, Any] | None:
    """Read and integrity-check an already frozen bounded export sidecar."""

    path = _lg12_parity_evidence_path(artifact.file_path)
    if not path.is_file():
        return None
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FrozenExportSnapshotError("Frozen export parity evidence cannot be read.") from exc
    if not isinstance(evidence, dict):
        raise FrozenExportSnapshotError("Frozen export parity evidence is malformed.")
    evidence_hash = str(evidence.pop("evidence_hash", "") or "")
    if not _SHA256_HEX.fullmatch(evidence_hash) or canonical_hash(evidence) != evidence_hash:
        raise FrozenExportSnapshotError("Frozen export parity evidence hash is invalid.")
    evidence["evidence_hash"] = evidence_hash
    return evidence


def _frozen_lg10_brand_assets(rendering: dict[str, Any]) -> list[dict[str, str]]:
    """Return the Brand Kit image identities actually placed by the frozen renderer."""

    asset_layer = dict((rendering.get("brand_tokens") or {}).get("asset_layer") or {})
    renderer_html = str(rendering.get("html") or "")
    assets: list[dict[str, str]] = []
    for role in ("logo", "watermark"):
        placement = "header" if role == "logo" else "watermark"
        identity = asset_layer.get(role)
        if identity is None:
            continue
        if (
            not isinstance(identity, dict)
            or not str(identity.get("asset_id") or "")
            or not _SHA256_HEX.fullmatch(str(identity.get("asset_content_hash") or ""))
        ):
            raise FrozenExportSnapshotError("Frozen Brand Kit asset identity is invalid.")
        if not re.search(
            rf'<(?:header|aside)\b(?=[^>]*data-brand-placement="{placement}")'
            rf'(?=[^>]*data-asset-id="{re.escape(str(identity["asset_id"]))}")'
            rf'(?=[^>]*data-asset-content-hash="{identity["asset_content_hash"]}")[^>]*>',
            renderer_html,
        ):
            raise FrozenExportSnapshotError("Frozen Brand Kit asset is not placed by the canonical renderer.")
        assets.append({
            "role": role,
            "asset_id": str(identity["asset_id"]),
            "asset_content_hash": str(identity["asset_content_hash"]),
        })
    return assets


def _is_lg10_brand_asset_eligible(asset: Asset) -> bool:
    """Brand marks are seller-rights assets, never supplier/reference imagery."""

    return (
        (asset.usage_status or "").lower() in {"seller_owned", "rights_confirmed"}
        and (asset.source_type or "").lower() not in {*REFERENCE_SOURCE_TYPES, "supplier"}
        and bool(asset.mime_type and asset.mime_type.startswith("image/"))
    )


class _CopyableHtmlSanitizer(HTMLParser):
    """Allow only static detail-page markup and mapped frozen images."""

    _allowed_tags = {
        "main", "header", "aside", "section", "figure", "img", "div", "h2",
        "p", "table", "tbody", "tr", "th", "td",
    }
    _void_tags = {"img"}
    _allowed_attrs = {
        "class", "data-section-id", "data-layout-token", "data-static-fallback",
        "data-asset-id", "data-asset-content-hash", "src", "alt",
    }
    _dropped_content_tags = {"script", "style", "iframe", "object", "embed", "link", "meta"}

    def __init__(self, asset_paths: dict[str, str] | None = None):
        super().__init__(convert_charrefs=False)
        self.asset_paths = asset_paths or {}
        self.parts: list[str] = []
        self.warnings: list[str] = []
        self._dropped_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._dropped_content_tags:
            self._dropped_depth += 1
            self.warnings.append(f"Removed unsupported {tag} markup from copyable HTML.")
            return
        if self._dropped_depth:
            return
        if tag not in self._allowed_tags:
            self.warnings.append(f"Removed unsupported {tag} markup from copyable HTML.")
            return

        clean_attrs: list[tuple[str, str]] = []
        attrs_by_name: dict[str, str] = {}
        for name, value in attrs:
            name = name.lower()
            value = value or ""
            if name.startswith("on") or name == "style" or name not in self._allowed_attrs:
                self.warnings.append(f"Removed unsafe {name} attribute from copyable HTML.")
                continue
            if name == "src" and not value.startswith("assets/"):
                self.warnings.append("Removed a non-bundled image URL from copyable HTML.")
                continue
            attrs_by_name[name] = value
            clean_attrs.append((name, value))

        rendered_attrs = "".join(
            f' {name}="{escape(value, quote=True)}"' for name, value in clean_attrs
        )
        self.parts.append(f"<{tag}{rendered_attrs}>")
        asset_id = attrs_by_name.get("data-asset-id")
        if tag in {"figure", "header", "aside"} and asset_id:
            relative_path = self.asset_paths.get(asset_id)
            if relative_path:
                self.parts.append(
                    f'<img src="{escape(relative_path, quote=True)}" alt="승인 이미지">'
                )
            else:
                self.warnings.append(
                    f"Excluded non-manifest asset {asset_id} from the standalone package."
                )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._void_tags:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._dropped_content_tags and self._dropped_depth:
            self._dropped_depth -= 1
            return
        if self._dropped_depth or tag not in self._allowed_tags or tag in self._void_tags:
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._dropped_depth:
            self.parts.append(escape(data))

    def handle_entityref(self, name: str) -> None:
        if not self._dropped_depth:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if not self._dropped_depth:
            self.parts.append(f"&#{name};")


def sanitize_copyable_html(
    html: str,
    *,
    asset_paths: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Return static markup without executable content or remote asset URLs."""
    sanitizer = _CopyableHtmlSanitizer(asset_paths=asset_paths)
    sanitizer.feed(html)
    sanitizer.close()
    return "".join(sanitizer.parts), sanitizer.warnings


def _sanitize_copyable_css(css: str) -> tuple[str, list[str]]:
    """Keep the deterministic renderer stylesheet local and non-executable."""
    warnings: list[str] = []
    safe_rules: list[str] = []
    for rule in str(css or "").split("}"):
        if not rule.strip():
            continue
        candidate = f"{rule}}}"
        if re.search(r"@import|url\s*\(|expression\s*\(|behavior\s*:", candidate, re.I):
            warnings.append("Removed unsafe stylesheet rule from standalone export.")
            continue
        safe_rules.append(candidate)
    return "".join(safe_rules), warnings


def _static_fallback_html(
    sections: list[dict[str, Any]],
    asset_paths: dict[str, str],
) -> str:
    """Render a fixed safe section when a channel cannot use a component."""
    fragments: list[str] = []
    for section in sections:
        section_id = escape(str(section.get("section_id") or "section"), quote=True)
        text_layer = list(section.get("text_layer") or [])
        title = escape(str((text_layer[0] if text_layer else {}).get("text") or ""))
        body = "".join(
            f"<p>{escape(str(item.get('text') or ''))}</p>"
            for item in text_layer[1:]
            if isinstance(item, dict)
        )
        images = "".join(
            f'<figure class="sf-asset-layer"><img src="{escape(asset_paths[asset_id], quote=True)}" alt="승인 이미지"></figure>'
            for asset in (section.get("asset_layer") or [])
            if isinstance(asset, dict)
            for asset_id in [str(asset.get("asset_id") or "")]
            if asset_id in asset_paths
        )
        fragments.append(
            f'<section class="sf-section sf-component-information_only" data-section-id="{section_id}" '
            f'data-static-fallback="unsupported_channel_component">{images}'
            f'<div class="sf-text-layer"><h2>{title}</h2>{body}</div></section>'
        )
    return '<main class="sf-page">' + "".join(fragments) + "</main>"


def _copyable_html_from_frozen_renderer(
    rendering: dict[str, Any],
    asset_paths: dict[str, str],
) -> tuple[str, list[str]]:
    sections = [dict(item) for item in (rendering.get("sections") or []) if isinstance(item, dict)]
    supported = all(
        section.get("component_id") in {"media_with_copy", "information_only"}
        and section.get("layout_token") in {"image_text", "spec_table"}
        for section in sections
    )
    if not supported:
        fallback_html = _static_fallback_html(sections, asset_paths)
        clean_html, warnings = sanitize_copyable_html(fallback_html, asset_paths=asset_paths)
        return clean_html, [
            "Unsupported channel component was replaced with the fixed static fallback.",
            *warnings,
        ]
    return sanitize_copyable_html(str(rendering.get("html") or ""), asset_paths=asset_paths)


def build_lg10_copyable_html(
    *,
    db: Session,
    project_id: str,
    version,
    channel: str | None = "smartstore",
) -> dict[str, Any]:
    """Build paste-ready HTML from one frozen LG-10 version.

    Unlike the standalone ZIP, this artifact has no local file dependency:
    approved asset bytes are embedded only after their frozen SHA-256 identity
    has been rechecked.  It intentionally never resolves mutable page state or
    creates a public asset URL.
    """

    _, rendering, manifest = _frozen_lg10_export_inputs(version, channel=channel)
    entries = [dict(item) for item in manifest.get("assets") or [] if isinstance(item, dict)]
    brand_assets = _frozen_lg10_brand_assets(rendering)
    asset_ids = [str(item.get("asset_id") or "") for item in entries]
    brand_asset_ids = [str(item.get("asset_id") or "") for item in brand_assets]
    if not all(asset_ids) or len(set(asset_ids)) != len(asset_ids) or not all(brand_asset_ids):
        raise FrozenExportSnapshotError("Approved manifest contains invalid asset identities.")

    assets = {
        asset.id: asset
        for asset in db.query(Asset).filter(
            Asset.project_id == project_id,
            Asset.id.in_([*asset_ids, *brand_asset_ids]),
        ).all()
    }
    embedded_sources: dict[str, str] = {}
    for entry in entries:
        asset_id = str(entry.get("asset_id") or "")
        expected_hash = str(entry.get("asset_content_hash") or "")
        asset = assets.get(asset_id)
        if (
            asset is None
            or not is_asset_final_output_eligible(asset)
            or not _SHA256_HEX.fullmatch(expected_hash)
            or asset.content_hash != expected_hash
            or not asset.mime_type.startswith("image/")
            or not asset.file_path
            or not os.path.isfile(asset.file_path)
            or image_sha256(asset.file_path) != expected_hash
        ):
            raise FrozenExportSnapshotError("Approved asset bytes no longer match the frozen DetailPageVersion.")
        encoded = base64.b64encode(Path(asset.file_path).read_bytes()).decode("ascii")
        embedded_sources[asset.id] = f"data:{asset.mime_type};base64,{encoded}"

    for entry in brand_assets:
        asset_id = entry["asset_id"]
        expected_hash = entry["asset_content_hash"]
        asset = assets.get(asset_id)
        if (
            asset is None
            or not _is_lg10_brand_asset_eligible(asset)
            or asset.content_hash != expected_hash
            or not asset.file_path
            or not os.path.isfile(asset.file_path)
            or image_sha256(asset.file_path) != expected_hash
        ):
            raise FrozenExportSnapshotError("Brand Kit asset bytes no longer match the frozen DetailPageVersion.")
        encoded = base64.b64encode(Path(asset.file_path).read_bytes()).decode("ascii")
        embedded_sources[asset.id] = f"data:{asset.mime_type};base64,{encoded}"

    fragment, warnings = _copyable_html_from_frozen_renderer(rendering, embedded_sources)
    css, css_warnings = _sanitize_copyable_css(str(rendering.get("css") or ""))
    warnings.extend(css_warnings)
    if not fragment.strip() or not css.strip():
        raise FrozenExportSnapshotError("Frozen renderer output cannot produce copyable HTML.")
    copyable_html = (
        f'<div data-sellform-detail-page-version-id="{escape(str(version.id), quote=True)}">'
        f'<style data-sellform-copyable-html="true">{css}</style>{fragment}</div>'
    )
    return {
        "detail_page_version_id": version.id,
        "html": copyable_html,
        "warnings": sorted(set(warnings)),
        "approved_asset_manifest": manifest,
    }


def _safe_asset_extension(asset) -> str:
    extension = Path(asset.filename).suffix.lower()
    allowed = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    if extension not in allowed:
        raise FrozenExportSnapshotError("Approved asset has an unsupported standalone image format.")
    return extension


def _frozen_lg10_export_inputs(
    version,
    *,
    channel: str | None = "smartstore",
    enforce_channel_safety: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    snapshot = version.sections_json if isinstance(version.sections_json, dict) else {}
    if snapshot.get("schema_version") != _LG10_DETAIL_PAGE_VERSION_SCHEMA:
        raise FrozenExportSnapshotError("Standalone exports require an LG-10 frozen DetailPageVersion.")
    if isinstance(snapshot.get("lg11"), dict):
        if channel not in {"smartstore", "coupang"}:
            raise FrozenExportSnapshotError("LG-11 frozen exports require an explicit channel identity.")
        if enforce_channel_safety:
            try:
                # Direct service callers receive the same frozen Canvas gate as
                # the HTTP preview/export APIs; this never consults a mutable
                # draft.
                ensure_lg11_canvas_safe(version_snapshot=snapshot, channel=channel)
            except LG11CanvasSafetyError as exc:
                raise FrozenExportSnapshotError(str(exc)) from exc
    lg10 = snapshot.get("lg10") if isinstance(snapshot.get("lg10"), dict) else {}
    canonical_input = lg10.get("canonical_page_assembly_input")
    rendering = lg10.get("canonical_rendering")
    approved_manifest = canonical_input.get("approved_asset_manifest") if isinstance(canonical_input, dict) else None
    page_manifest = (
        canonical_input.get("page_asset_manifest") or approved_manifest
        if isinstance(canonical_input, dict)
        else None
    )
    image_contract = (
        canonical_input.get("image_generation_contract")
        if isinstance(canonical_input, dict)
        else None
    )
    if isinstance(image_contract, dict):
        required_scene_count = int(image_contract.get("required_scene_count") or 0)
        completion_basis = str(image_contract.get("completion_basis") or "")
    elif isinstance(approved_manifest, dict):
        required_scene_count = len(approved_manifest.get("assets") or [])
        completion_basis = "approved_required_scenes"
    else:
        required_scene_count = -1
        completion_basis = ""
    if not isinstance(rendering, dict) or not isinstance(page_manifest, dict):
        raise FrozenExportSnapshotError("Frozen DetailPageVersion is missing the LG-10 rendering or page asset manifest.")
    if required_scene_count > 0:
        if (
            completion_basis != "approved_required_scenes"
            or not isinstance(approved_manifest, dict)
            or page_manifest != approved_manifest
        ):
            raise FrozenExportSnapshotError("Standalone exports require approved final assets.")
    elif (
        required_scene_count != 0
        or completion_basis != "no_required_image_scenes"
        or approved_manifest is not None
    ):
        raise FrozenExportSnapshotError("Standalone export cannot bypass an incomplete required image manifest.")
    entries = list(page_manifest.get("assets") or [])
    manifest_without_hash = dict(page_manifest)
    manifest_hash = str(manifest_without_hash.pop("manifest_hash", "") or "")
    expected_manifest_hash = hashlib.sha256(
        json.dumps(manifest_without_hash, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not _SHA256_HEX.fullmatch(manifest_hash) or manifest_hash != expected_manifest_hash:
        raise FrozenExportSnapshotError("Standalone exports require an untampered page asset manifest.")
    if required_scene_count > 0 and not entries:
        raise FrozenExportSnapshotError("Standalone exports require approved final assets.")
    return snapshot, rendering, page_manifest


def build_lg10_standalone_export_bundle(
    *,
    db: Session,
    project_id: str,
    version,
    output_dir: str | None = None,
    channel: str | None = "smartstore",
) -> dict[str, Any]:
    """Build a local-only HTML/CSS/image package from one frozen LG-10 version.

    This deliberately consumes only frozen asset identities. It never resolves
    preview URLs or mutable page state; Brand Kit images are included only when
    the frozen renderer actually placed them.
    """
    _, rendering, manifest = _frozen_lg10_export_inputs(version, channel=channel)
    entries = [dict(item) for item in manifest.get("assets") or [] if isinstance(item, dict)]
    brand_assets = _frozen_lg10_brand_assets(rendering)
    asset_ids = [str(item.get("asset_id") or "") for item in entries]
    brand_asset_ids = [str(item.get("asset_id") or "") for item in brand_assets]
    if not all(asset_ids) or len(set(asset_ids)) != len(asset_ids) or not all(brand_asset_ids):
        raise FrozenExportSnapshotError("Approved manifest contains invalid asset identities.")

    assets = {
        asset.id: asset
        for asset in db.query(Asset).filter(
            Asset.project_id == project_id,
            Asset.id.in_([*asset_ids, *brand_asset_ids]),
        ).all()
    }
    output_root = Path(output_dir or os.path.join(os.getcwd(), "uploads", "exports"))
    package_root = output_root / f"lg10-{project_id}-{version.id}-standalone"
    asset_root = package_root / "assets"
    asset_root.mkdir(parents=True, exist_ok=True)

    asset_paths: dict[str, str] = {}
    bundled_assets: list[dict[str, str]] = []
    for entry in entries:
        asset_id = str(entry.get("asset_id") or "")
        expected_hash = str(entry.get("asset_content_hash") or "")
        asset = assets.get(asset_id)
        if (
            asset is None
            or not is_asset_final_output_eligible(asset)
            or not _SHA256_HEX.fullmatch(expected_hash)
            or asset.content_hash != expected_hash
            or not asset.file_path
            or not os.path.isfile(asset.file_path)
            or image_sha256(asset.file_path) != expected_hash
        ):
            raise FrozenExportSnapshotError("Approved asset bytes no longer match the frozen DetailPageVersion.")
        relative_path = f"assets/{asset.id}{_safe_asset_extension(asset)}"
        shutil.copyfile(asset.file_path, package_root / relative_path)
        asset_paths[asset.id] = relative_path
        bundled_assets.append({
            "asset_id": asset.id,
            "asset_content_hash": expected_hash,
            "path": relative_path,
        })

    for entry in brand_assets:
        asset_id = entry["asset_id"]
        expected_hash = entry["asset_content_hash"]
        asset = assets.get(asset_id)
        if (
            asset is None
            or not _is_lg10_brand_asset_eligible(asset)
            or asset.content_hash != expected_hash
            or not asset.file_path
            or not os.path.isfile(asset.file_path)
            or image_sha256(asset.file_path) != expected_hash
        ):
            raise FrozenExportSnapshotError("Brand Kit asset bytes no longer match the frozen DetailPageVersion.")
        if asset_id in asset_paths:
            continue
        relative_path = f"assets/{asset.id}{_safe_asset_extension(asset)}"
        shutil.copyfile(asset.file_path, package_root / relative_path)
        asset_paths[asset.id] = relative_path
        bundled_assets.append({
            "asset_id": asset.id,
            "asset_content_hash": expected_hash,
            "path": relative_path,
        })

    copyable_html, warnings = _copyable_html_from_frozen_renderer(rendering, asset_paths)
    css, css_warnings = _sanitize_copyable_css(str(rendering.get("css") or ""))
    warnings.extend(css_warnings)
    if not copyable_html.strip() or not css.strip():
        raise FrozenExportSnapshotError("Frozen renderer output cannot produce a standalone export.")

    manifest_payload = {
        "schema_version": "lg10-standalone-export-v1",
        "detail_page_version_id": version.id,
        "approved_asset_manifest": manifest,
        "brand_assets": brand_assets,
        "bundled_assets": bundled_assets,
    }
    font_manifest = {
        "schema_version": "lg10-font-manifest-v1",
        "detail_page_version_id": version.id,
        "typography": dict((rendering.get("brand_tokens") or {}).get("typography") or {}),
        "bundled_fonts": [],
        "note": "No remote font files are loaded by the standalone package.",
    }
    index_html = (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<link rel=\"stylesheet\" href=\"styles.css\"></head><body>"
        f"{copyable_html}</body></html>"
    )
    html_path = package_root / "copyable.html"
    css_path = package_root / "styles.css"
    index_path = package_root / "index.html"
    manifest_path = package_root / "approved-asset-manifest.json"
    font_manifest_path = package_root / "font-manifest.json"
    html_path.write_text(copyable_html, encoding="utf-8")
    css_path.write_text(css, encoding="utf-8")
    index_path.write_text(index_html, encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    font_manifest_path.write_text(json.dumps(font_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (package_root / "README.txt").write_text(
        "Open index.html locally. All images and CSS are bundled with relative paths; no API call is required.\n",
        encoding="utf-8",
    )

    zip_path = output_root / f"lg10-{project_id}-{version.id}-standalone.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_root).as_posix())
    return {
        "html_path": str(html_path),
        "zip_path": str(zip_path),
        "warnings": sorted(set(warnings)),
        "detail_page_version_id": version.id,
        "approved_asset_manifest": manifest,
    }


def build_export_render_path(project_id: str) -> str:
    """Build the export render URL path for a given project.

    The default path is outside /workspace/ to avoid capturing the app chrome
    (header, sidebar, etc.) in screenshots. Override via SELLFORM_EXPORT_RENDER_PATH.
    """
    render_path_template = os.getenv(
        "SELLFORM_EXPORT_RENDER_PATH",
        "/export-render/projects/{project_id}",
    )
    return render_path_template.format(project_id=project_id)


class ExportRenderNotReadyError(RuntimeError):
    """Raised when the render page reports asset loading failure."""


PLAYWRIGHT_CHROMIUM_INSTALL_COMMAND = "uv run playwright install chromium"


class PlaywrightChromiumUnavailableError(RuntimeError):
    """Raised when the Playwright package exists but Chromium is not installed."""

    def __init__(self) -> None:
        super().__init__(
            "JPG/PNG 내보내기에 필요한 Chromium이 설치되지 않았습니다. "
            "백엔드 폴더에서 다음 명령을 실행한 뒤 다시 시도해 주세요: "
            f"{PLAYWRIGHT_CHROMIUM_INSTALL_COMMAND}"
        )


def ensure_playwright_chromium_available(playwright) -> None:
    """Fail before export work starts when Playwright's Chromium is missing.

    BrowserType.executable_path is available on real Playwright instances. Test
    doubles that intentionally omit it remain supported and are validated by
    their launch implementation instead.
    """
    executable_path = getattr(playwright.chromium, "executable_path", None)
    if executable_path and not os.path.isfile(executable_path):
        raise PlaywrightChromiumUnavailableError()


def _is_missing_playwright_browser_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "executable doesn't exist" in message
        or "playwright install" in message
        or "browser executable" in message and "not found" in message
    )


def capture_next_render_export(
    *,
    project_id: str,
    version_id: str,
    channel: str | None = None,
    output_format: Literal["png", "jpg", "jpeg"] = "png",
    output_dir: str | None = None,
    render_base_url: str | None = None,
    auth_headers: dict[str, str] | None = None,
    playwright=None,
) -> dict[str, str]:
    """Capture the canonical Next.js render route as one image and section ZIP."""
    normalized_format = output_format.lower()
    if normalized_format == "jpeg":
        normalized_format = "jpg"
    if normalized_format not in {"png", "jpg"}:
        raise ValueError("output_format must be png, jpg, or jpeg")

    output_dir = os.path.abspath(
        output_dir or os.path.join(os.getcwd(), "uploads", "exports")
    )
    os.makedirs(output_dir, exist_ok=True)
    render_base_url = (
        render_base_url
        or os.getenv("SELLFORM_EXPORT_RENDER_BASE_URL")
        or "http://127.0.0.1:3000"
    ).rstrip("/")
    auth_headers = auth_headers or {}
    query = urlencode(
        {
            "version_id": version_id,
            **({"channel": channel} if channel else {}),
            "user_id": auth_headers.get("X-Mock-User-Id", ""),
            "workspace_id": auth_headers.get("X-Mock-Workspace-Id", ""),
        }
    )
    render_url = f"{render_base_url}{build_export_render_path(project_id)}?{query}"
    image_path = os.path.join(
        output_dir,
        f"{project_id}_{version_id}_long.{normalized_format}",
    )
    zip_path = os.path.join(output_dir, f"{project_id}_{version_id}_sections.zip")
    section_paths: list[tuple[str, str]] = []
    section_heights: list[int] = []
    browser = None
    owns_playwright = playwright is None
    playwright_manager = None
    owned_playwright = None

    try:
        if owns_playwright:
            from playwright.sync_api import sync_playwright

            playwright_manager = sync_playwright()
            playwright = playwright_manager.start()
            owned_playwright = playwright

        ensure_playwright_chromium_available(playwright)
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            if _is_missing_playwright_browser_error(exc):
                raise PlaywrightChromiumUnavailableError() from exc
            raise
        page = browser.new_page(
            viewport={"width": 900, "height": 1200},
            extra_http_headers=auth_headers,
        )
        page.goto(render_url, wait_until="networkidle", timeout=30000)
        page.wait_for_function(
            "() => ['true', 'error'].includes(document.documentElement.dataset.exportReady)",
            timeout=30000,
        )
        ready = page.locator("html").get_attribute("data-export-ready")
        if ready == "error":
            errors = page.locator("html").get_attribute("data-export-errors") or "[]"
            raise ExportRenderNotReadyError(
                f"required visual assets failed: {errors}"
            )

        screenshot_type = "jpeg" if normalized_format == "jpg" else "png"
        screenshot_options = {
            "path": image_path,
            "type": screenshot_type,
        }
        if screenshot_type == "jpeg":
            screenshot_options["quality"] = 92
        page.locator("[data-detail-page-document='true']").screenshot(
            **screenshot_options
        )

        sections = page.locator("[data-detail-page-section='true']")
        for index in range(sections.count()):
            filename = f"{index + 1:02d}-section.{normalized_format}"
            section_path = os.path.join(
                output_dir,
                f"temp_{project_id}_{version_id}_{filename}",
            )
            section_options = {
                "path": section_path,
                "type": screenshot_type,
            }
            if screenshot_type == "jpeg":
                section_options["quality"] = 92
            sections.nth(index).screenshot(**section_options)
            section_paths.append((filename, section_path))
            with Image.open(section_path) as section_image:
                section_heights.append(section_image.height)

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, section_path in section_paths:
                archive.write(section_path, arcname=filename)

        return {
            "long_vertical_image": image_path,
            "section_images_zip": zip_path,
            # Pixel boundaries are used by the channel splitter to avoid
            # cutting a section in half. They are not user supplied data.
            "section_heights": section_heights,
        }
    except Exception:
        for path in [image_path, zip_path, *(path for _, path in section_paths)]:
            if os.path.exists(path):
                os.remove(path)
        raise
    finally:
        for _, section_path in section_paths:
            if os.path.exists(section_path):
                os.remove(section_path)
        if browser is not None:
            browser.close()
        if owned_playwright is not None:
            owned_playwright.stop()


def load_export_font(size: int, bold: bool = False):
    """Load a Korean-capable font for exported detail-page images.

    Pillow's default bitmap font cannot render Korean text, so exported PNGs
    become unreadable on Windows/local runs. Prefer explicit env override, then
    common Korean fonts on Windows and Linux, and only fall back to Pillow's
    default font as a last resort.
    """
    env_font_path = os.getenv("SELLFORM_EXPORT_BOLD_FONT_PATH" if bold else "SELLFORM_EXPORT_FONT_PATH")
    candidates = [
        env_font_path,
        r"C:\Windows\Fonts\NotoSansKR-VF.ttf",
        r"C:\Windows\Fonts\malgunbd.ttf" if bold else r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\NGULIM.TTF",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for font_path in candidates:
        if not font_path or not os.path.exists(font_path):
            continue
        try:
            return ImageFont.truetype(font_path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_width(text: str, font) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    wrapped_lines: list[str] = []
    for raw_line in str(text or "").splitlines() or [""]:
        words = raw_line.split(" ")
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if _text_width(candidate, font) <= max_width:
                current = candidate
                continue
            if current:
                wrapped_lines.append(current)
                current = word
                continue
            # Very long unspaced strings, e.g. model codes/URLs.
            fragment = ""
            for char in word:
                candidate_fragment = f"{fragment}{char}"
                if _text_width(candidate_fragment, font) <= max_width:
                    fragment = candidate_fragment
                else:
                    if fragment:
                        wrapped_lines.append(fragment)
                    fragment = char
            current = fragment
        if current:
            wrapped_lines.append(current)
    return wrapped_lines

def build_export_manifest(project_id: str, version_id: str, sections: list[dict]) -> dict:
    sections = normalize_sections_snapshot(sections)
    return {
        "project_id": project_id,
        "version_id": version_id,
        "outputs": ["long_vertical_image", "section_images_zip"],
        "sections": [
            {
                "index": index + 1,
                "key": section.get("key"),
                "title": section.get("title"),
                "filename": f"{index + 1:02d}-{section.get('key', 'section')}.png",
            }
            for index, section in enumerate(sections)
        ],
    }

def normalize_sections_snapshot(sections_snapshot) -> list[dict]:
    if isinstance(sections_snapshot, dict):
        return sections_snapshot.get("sections", [])
    return sections_snapshot or []


def _draw_gradient_vertical(draw, width: int, height: int, start_color: str, end_color: str):
    r1, g1, b1 = int(start_color[1:3], 16), int(start_color[3:5], 16), int(start_color[5:7], 16)
    r2, g2, b2 = int(end_color[1:3], 16), int(end_color[3:5], 16), int(end_color[5:7], 16)
    for y in range(height):
        ratio = y / max(1, height)
        r = int(r1 + (r2 - r1) * ratio)
        g = int(g1 + (g2 - g1) * ratio)
        b = int(b1 + (b2 - b1) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))


def _draw_hero_section(draw, section, width, height, palette, title_font, body_font, label_font):
    accent = (37, 99, 235)
    text = (15, 23, 42)
    muted = (71, 85, 105)
    draw.rounded_rectangle([(48, 48), (width - 48, height - 48)], radius=36, fill=(255, 255, 255))
    draw.text((76, 82), section["eyebrow"], fill=muted, font=label_font)
    draw.text((76, 132), section["headline"], fill=accent, font=title_font)
    y = 196
    for line in _wrap_text(section["subcopy"], body_font, width - 152):
        draw.text((76, y), line, fill=text, font=body_font)
        y += 38
    draw.ellipse([(width - 260, height - 260), (width - 80, height - 80)], fill=palette[1])
    draw.arc([(width - 230, height - 230), (width - 110, height - 110)], start=20, end=320, fill=accent, width=10)


def _draw_image_text_section(img, draw, section, width, height, palette, title_font, body_font, label_font):
    accent = (37, 99, 235)
    text = (15, 23, 42)
    muted = (71, 85, 105)
    draw.rounded_rectangle([(44, 30), (width - 44, height - 30)], radius=24, fill=(255, 255, 255))
    
    visual_slot = section.get("visual_slot", {})
    image_drawn = False
    
    if visual_slot.get("kind") == "product_image" and visual_slot.get("file_path"):
        raw_path = visual_slot["file_path"]
        candidate_paths = [
            raw_path,
            os.path.join(os.getcwd(), "uploads", raw_path),
            os.path.join(os.getcwd(), raw_path),
            os.path.abspath(os.path.join(os.getcwd(), "..", "uploads", raw_path)),
            os.path.abspath(os.path.join(os.getcwd(), "backend", "uploads", raw_path))
        ]
        actual_path = None
        for p_path in candidate_paths:
            if os.path.exists(p_path):
                actual_path = p_path
                break
                
        if actual_path:
            try:
                box_width = width - 72 - 72
                box_height = 250 - 64
                with open(actual_path, "rb") as image_file:
                    image_bytes = image_file.read()
                with Image.open(BytesIO(image_bytes)) as prod_img:
                    prod_img_rgb = prod_img.convert("RGB")
                    prod_img_rgb.load()

                fitted_img = ImageOps.fit(prod_img_rgb, (box_width, box_height))
                try:
                    mask = Image.new("L", (box_width, box_height), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.rounded_rectangle([(0, 0), (box_width, box_height)], radius=20, fill=255)
                    
                    img.paste(fitted_img, (72, 64), mask=mask)
                    image_drawn = True
                finally:
                    fitted_img.close()
                    prod_img_rgb.close()
            except Exception:
                pass
                
    if not image_drawn:
        draw.rounded_rectangle([(72, 64), (width - 72, 250)], radius=20, fill=palette[1])
        draw.text((92, 92), visual_slot.get("fallback_label", "상품 이미지"), fill=muted, font=body_font)

    draw.text((72, 292), section["headline"], fill=accent, font=title_font)
    y = 350
    for line in _wrap_text(section["subcopy"], body_font, width - 144):
        draw.text((72, y), line, fill=text, font=body_font)
        y += 38


def _draw_commerce_cut(img, draw, sec, width, height, palette, title_font, body_font, label_font):
    accent = (37, 99, 235)
    text = (15, 23, 42)
    muted = (71, 85, 105)
    
    # 1. Background round box
    draw.rounded_rectangle([(30, 30), (width - 30, height - 30)], radius=32, fill=(255, 255, 255))
    
    visual_slot = sec.get("visual_slot", {})
    image_drawn = False
    
    # Image area allocation: 764x420 (approx 49.7% of total 860x750 area)
    box_width = width - 96
    box_height = 420
    img_x = 48
    img_y = 64
    
    if visual_slot.get("kind") == "product_image" and visual_slot.get("file_path"):
        raw_path = visual_slot["file_path"]
        candidate_paths = [
            raw_path,
            os.path.join(os.getcwd(), "uploads", raw_path),
            os.path.join(os.getcwd(), raw_path),
            os.path.abspath(os.path.join(os.getcwd(), "..", "uploads", raw_path)),
            os.path.abspath(os.path.join(os.getcwd(), "backend", "uploads", raw_path))
        ]
        actual_path = None
        for p_path in candidate_paths:
            if os.path.exists(p_path):
                actual_path = p_path
                break
                
        if actual_path:
            try:
                with open(actual_path, "rb") as image_file:
                    from io import BytesIO
                    image_bytes = image_file.read()
                with Image.open(BytesIO(image_bytes)) as prod_img:
                    prod_img_rgb = prod_img.convert("RGB")
                    prod_img_rgb.load()
                    
                fitted_img = ImageOps.fit(prod_img_rgb, (box_width, box_height))
                try:
                    mask = Image.new("L", (box_width, box_height), 0)
                    mask_draw = ImageDraw.Draw(mask)
                    mask_draw.rounded_rectangle([(0, 0), (box_width, box_height)], radius=24, fill=255)
                    
                    img.paste(fitted_img, (img_x, img_y), mask=mask)
                    image_drawn = True
                finally:
                    fitted_img.close()
                    prod_img_rgb.close()
            except Exception:
                pass
                
    if not image_drawn:
        draw.rounded_rectangle([(img_x, img_y), (img_x + box_width, img_y + box_height)], radius=24, fill=palette[1])
        role_label = visual_slot.get("role", "lifestyle_scene")
        draw.text((img_x + 36, img_y + 36), f"⚠️ [{role_label}] 촬영 컷 배치가 필요합니다", fill=muted, font=body_font)
        draw.text((img_x + 36, img_y + 76), "상황이나 라이프스타일 묘사 컷 업로드를 권장합니다.", fill=muted, font=label_font)

    headline = sec.get("headline", "")
    subcopy = sec.get("subcopy", "")
    supporting_text = sec.get("supporting_text")
    
    text_y = 510
    draw.text((48, text_y), headline, fill=accent, font=title_font)
    text_y += 54
    
    for line in _wrap_text(subcopy, body_font, width - 96):
        draw.text((48, text_y), line, fill=text, font=body_font)
        text_y += 34
        
    if supporting_text:
        text_y += 8
        for line in _wrap_text(supporting_text, label_font, width - 96):
            draw.text((48, text_y), line, fill=muted, font=label_font)
            text_y += 24


def _draw_spec_table_section(draw, section, width, height, title_font, body_font, label_font):
    text = (15, 23, 42)
    muted = (71, 85, 105)
    border = (226, 232, 240)
    draw.rounded_rectangle([(44, 30), (width - 44, height - 30)], radius=24, fill=(255, 255, 255))
    draw.text((72, 72), "구매 전 확인 정보", fill=text, font=title_font)
    y = 140
    for row in section.get("spec_rows", []):
        draw.line([(72, y), (width - 72, y)], fill=border, width=1)
        draw.text((72, y + 24), row["label"], fill=muted, font=label_font)
        draw.text((240, y + 24), row["value"], fill=text, font=body_font)
        y += 76


def run_export(
    project_id: str,
    version_id: str,
    sections: list[dict],
    db: Session = None,
    use_commerce_cut: bool = False,
    output_format: Literal["png", "jpg", "jpeg"] = "png",
) -> dict:
    from src.db.models import ProductProject
    from src.services.visual_page_renderer import build_visual_sections

    normalized_format = output_format.lower()
    if normalized_format == "jpeg":
        normalized_format = "jpg"
    if normalized_format not in {"png", "jpg"}:
        raise ValueError("output_format must be png, jpg, or jpeg")

    image_extension = normalized_format
    pillow_format = "PNG" if normalized_format == "png" else "JPEG"

    def save_export_image(image: Image.Image, path: str) -> None:
        if pillow_format == "JPEG":
            image.convert("RGB").save(path, format=pillow_format, quality=92, optimize=True)
        else:
            image.save(path, format=pillow_format, optimize=True)

    original_snapshot = sections
    sections = normalize_sections_snapshot(sections)
    export_dir = os.path.abspath(os.path.join(os.getcwd(), "uploads", "exports"))
    os.makedirs(export_dir, exist_ok=True)
    
    selected_bg = None
    selected_style = None
    project = None
    if db is not None:
        project = db.query(ProductProject).filter(ProductProject.id == project_id).first()
        if project and project.selected_background:
            selected_bg = project.selected_background
        if project and project.selected_style:
            selected_style = project.selected_style
    else:
        if isinstance(original_snapshot, dict):
            vb = original_snapshot.get("visual_background", {})
            if isinstance(vb, dict):
                selected_bg = vb.get("selected_background")
            selected_style = original_snapshot.get("style_key")

    BACKGROUND_PALETTES = {
        "cooling-blue": ["#EAF4FF", "#DDEBFF", "#FFFFFF"],
        "minimal-white": ["#F8F9FA", "#E9ECEF", "#FFFFFF"],
        "lifestyle-summer": ["#FFF9F2", "#FFEEDD", "#FFFFFF"]
    }
    
    palette = BACKGROUND_PALETTES.get(selected_bg) if selected_bg else BACKGROUND_PALETTES["cooling-blue"]
    
    image_assets = []
    if db is not None:
        assets = get_page_eligible_assets(db, project_id)
        image_assets = [
            {
                "id": a.id,
                "filename": a.filename,
                "file_path": a.file_path,
                "mime_type": a.mime_type,
                "source_type": a.source_type
            }
            for a in assets
        ]
    else:
        if isinstance(original_snapshot, dict):
            image_assets = original_snapshot.get("assets_snapshot", [])

    visual_sections = build_visual_sections(
        product_name=getattr(project, "title", "상품") if db is not None and project else "상품",
        category=getattr(project, "category", "Living") if db is not None and project else "Living",
        sections=sections,
        selected_background=selected_bg,
        image_assets=image_assets,
        use_commerce_cut=use_commerce_cut,
        selected_style=selected_style,
    )
    
    width = 860
    
    def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
        return (int(hex_str[1:3], 16), int(hex_str[3:5], 16), int(hex_str[5:7], 16))
        
    bg_color = hex_to_rgb(palette[0])
    
    label_font = load_export_font(16)
    title_font = load_export_font(34, bold=True)
    body_font = load_export_font(24)
    
    temp_files = []
    
    try:
        for idx, sec in enumerate(visual_sections):
            layout = sec["layout"]
            
            if use_commerce_cut:
                if layout in {"spec_visual", "spec_table"}:
                    section_height = max(350, 160 + len(sec.get("spec_rows", [])) * 76)
                else:
                    section_height = 750
            else:
                if layout == "hero":
                    title_lines = _wrap_text(sec["headline"], title_font, width - 152)
                    subcopy_lines = _wrap_text(sec["subcopy"], body_font, width - 152)
                    section_height = max(500, 260 + len(title_lines) * 46 + len(subcopy_lines) * 38)
                elif layout == "spec_table":
                    section_height = max(350, 160 + len(sec.get("spec_rows", [])) * 76)
                else:
                    title_lines = _wrap_text(sec["headline"], title_font, width - 144)
                    subcopy_lines = _wrap_text(sec["subcopy"], body_font, width - 144)
                    section_height = max(550, 380 + len(title_lines) * 46 + len(subcopy_lines) * 38)
                
            img = Image.new("RGB", (width, section_height), bg_color)
            draw = ImageDraw.Draw(img)
            
            if use_commerce_cut:
                if layout in {"spec_visual", "spec_table"}:
                    _draw_spec_table_section(draw, sec, width, section_height, title_font, body_font, label_font)
                else:
                    _draw_gradient_vertical(draw, width, section_height, palette[0], palette[1])
                    _draw_commerce_cut(img, draw, sec, width, section_height, palette, title_font, body_font, label_font)
            else:
                if layout == "hero":
                    _draw_gradient_vertical(draw, width, section_height, palette[0], palette[1])
                    _draw_hero_section(draw, sec, width, section_height, palette, title_font, body_font, label_font)
                elif layout == "spec_table":
                    _draw_spec_table_section(draw, sec, width, section_height, title_font, body_font, label_font)
                else:
                    _draw_image_text_section(img, draw, sec, width, section_height, palette, title_font, body_font, label_font)
            
            filename = f"{idx + 1:02d}-{sec['key']}.{image_extension}"
            file_path = os.path.join(export_dir, f"temp_{project_id}_{version_id}_{filename}")
            save_export_image(img, file_path)
            temp_files.append((filename, file_path, img))
            
        total_height = sum(img.height for _, _, img in temp_files)
        long_img = Image.new("RGB", (width, total_height), bg_color)
        
        current_y = 0
        for _, _, img in temp_files:
            long_img.paste(img, (0, current_y))
            current_y += img.height
            
        long_image_path = os.path.join(
            export_dir,
            f"{project_id}_{version_id}_long.{image_extension}",
        )
        save_export_image(long_img, long_image_path)
        long_img.close()
        
        zip_path = os.path.join(export_dir, f"{project_id}_{version_id}_sections.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for filename, file_path, _ in temp_files:
                zipf.write(file_path, arcname=filename)
                
        for _, file_path, img in temp_files:
            try:
                img.close()
                os.remove(file_path)
            except Exception:
                pass
                
        if db is not None:
            artifact_long = ExportArtifact(
                project_id=project_id,
                version_id=version_id,
                artifact_type="long_vertical_image",
                file_path=long_image_path
            )
            artifact_zip = ExportArtifact(
                project_id=project_id,
                version_id=version_id,
                artifact_type="section_images_zip",
                file_path=zip_path
            )
            db.add(artifact_long)
            db.add(artifact_zip)
            db.commit()
            
        return {
            "long_vertical_image": long_image_path,
            "section_images_zip": zip_path
        }
    except Exception as e:
        for _, file_path, img in temp_files:
            try:
                img.close()
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception:
                pass
        raise e
