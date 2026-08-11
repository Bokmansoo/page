"""Channel preset and deterministic long-image splitting for Sprint 7 exports.

The page renderer always creates one canonical master image.  Channel output is
derived from that image only: no text, asset or section order is regenerated
for an individual marketplace.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from PIL import Image


@dataclass(frozen=True)
class ChannelPreset:
    key: str
    label: str
    version: str
    width: int
    max_segment_height: int
    default_format: str
    jpeg_quality: int
    background: str
    filename_prefix: str


_DEFAULT_PRESETS = {
    "coupang": ChannelPreset(
        key="coupang", label="쿠팡", version="2026-08-03", width=860,
        max_segment_height=10000, default_format="jpg", jpeg_quality=92,
        background="#ffffff", filename_prefix="coupang-detail",
    ),
    "smartstore": ChannelPreset(
        key="smartstore", label="네이버 스마트스토어", version="2026-08-03", width=860,
        max_segment_height=10000, default_format="png", jpeg_quality=92,
        background="#ffffff", filename_prefix="smartstore-detail",
    ),
}


def channel_presets() -> dict[str, ChannelPreset]:
    """Load replaceable preset values without changing rendering code.

    SELLFORM_CHANNEL_EXPORT_PRESETS_JSON can contain an object keyed by channel.
    Unknown/invalid overrides are deliberately ignored to retain a safe export.
    """
    raw = os.getenv("SELLFORM_CHANNEL_EXPORT_PRESETS_JSON")
    if not raw:
        return _DEFAULT_PRESETS
    try:
        values = json.loads(raw)
        result = dict(_DEFAULT_PRESETS)
        for key, item in values.items():
            if key not in result or not isinstance(item, dict):
                continue
            base = asdict(result[key])
            base.update({name: value for name, value in item.items() if name in base})
            result[key] = ChannelPreset(**base)
        return result
    except (TypeError, ValueError, json.JSONDecodeError):
        return _DEFAULT_PRESETS


def get_channel_preset(key: str) -> ChannelPreset:
    preset = channel_presets().get(key)
    if not preset:
        raise ValueError("preset_name must be coupang or smartstore")
    return preset


def serialize_channel_presets() -> list[dict]:
    return [asdict(preset) for preset in channel_presets().values()]


def image_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_split_heights(total_height: int, section_heights: Iterable[int], max_height: int) -> list[tuple[int, int]]:
    """Return contiguous, non-overlapping ranges, preferring section boundaries."""
    if total_height <= 0 or max_height <= 0:
        raise ValueError("total_height and max_height must be positive")
    boundaries = {0, total_height}
    cursor = 0
    for height in section_heights:
        cursor = min(total_height, cursor + max(0, int(height)))
        boundaries.add(cursor)
    sorted_boundaries = sorted(boundaries)
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < total_height:
        limit = min(total_height, start + max_height)
        candidates = [point for point in sorted_boundaries if start < point <= limit]
        end = max(candidates) if candidates else limit
        ranges.append((start, end))
        start = end
    return ranges


def _save(image: Image.Image, path: str, output_format: str, quality: int) -> None:
    if output_format == "jpg":
        if image.mode == "RGBA":
            flattened = Image.new("RGB", image.size, "white")
            flattened.paste(image, mask=image.getchannel("A"))
            image = flattened
        image.convert("RGB").save(path, "JPEG", quality=quality, optimize=True)
    else:
        image.save(path, "PNG", optimize=True)


def create_channel_export_bundle(
    *, master_path: str, output_dir: str, project_slug: str, preset_key: str,
    output_format: str, section_heights: Iterable[int] = (), section_images_zip: str | None = None,
    generation_plan: dict[str, Any] | None = None,
) -> dict:
    """Resize one master, split it safely, and package long+parts deterministically."""
    preset = get_channel_preset(preset_key)
    normalized_format = "jpg" if output_format.lower() in {"jpg", "jpeg"} else "png"
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    prefix = f"{project_slug}-{preset.filename_prefix}-{preset.version}"
    with Image.open(master_path) as source:
        source = source.convert("RGBA")
        # Marketplace JPG exports must not turn transparent areas black.
        flattened = Image.new("RGBA", source.size, preset.background)
        flattened.alpha_composite(source)
        source = flattened.convert("RGB")
        if source.width != preset.width:
            target_height = round(source.height * preset.width / source.width)
            master = source.resize((preset.width, target_height), Image.Resampling.LANCZOS)
            scale = target_height / source.height
            scaled_heights = [round(int(height) * scale) for height in section_heights]
        else:
            master = source.copy()
            scaled_heights = [int(height) for height in section_heights]

    long_path = os.path.join(output_dir, f"{prefix}-long.{normalized_format}")
    _save(master, long_path, normalized_format, preset.jpeg_quality)
    ranges = safe_split_heights(master.height, scaled_heights, preset.max_segment_height)
    part_paths: list[str] = []
    for index, (top, bottom) in enumerate(ranges, start=1):
        part_path = os.path.join(output_dir, f"{prefix}-{index:03d}.{normalized_format}")
        _save(master.crop((0, top, master.width, bottom)), part_path, normalized_format, preset.jpeg_quality)
        part_paths.append(part_path)
    master.close()

    zip_path = os.path.join(output_dir, f"{prefix}-package.zip")
    manifest = {
        "preset": asdict(preset), "format": normalized_format,
        "master": os.path.basename(long_path),
        "master_sha256": image_sha256(long_path),
        "parts": [
            {"filename": os.path.basename(path), "top": start, "bottom": end}
            for path, (start, end) in zip(part_paths, ranges)
        ],
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(long_path, arcname=os.path.basename(long_path))
        for path in part_paths:
            archive.write(path, arcname=os.path.basename(path))
        if section_images_zip and os.path.isfile(section_images_zip):
            archive.write(section_images_zip, arcname="sections-by-page.zip")
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        # The JPG itself is deliberately only the rendered page.  Keep the
        # exact provider-free plan in its delivery ZIP so reviewers can tell
        # which scenes are safe-photo/HTML fallbacks and which await AI.
        if generation_plan:
            archive.writestr(
                "generation-plan.json",
                json.dumps(generation_plan, ensure_ascii=False, indent=2, default=str),
            )
    return {
        "preset": asdict(preset), "long_image": long_path, "package_zip": zip_path,
        "parts": part_paths, "manifest": manifest,
    }
