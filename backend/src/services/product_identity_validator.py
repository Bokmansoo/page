import hashlib
import io
import json
from pathlib import Path
import re
from PIL import Image
from typing import Any, List, Mapping

from src.services.image_asset_inspector import (
    MAX_ASPECT_RATIO,
    MIN_ASPECT_RATIO,
    MIN_RECOMMENDED_EDGE,
)


class ProductIdentityValidationError(Exception):
    pass


LG12_FROZEN_IMAGE_EVIDENCE_SCHEMA_VERSION = "lg12-frozen-image-evidence-v1"
_LG12_IDENTITY_FIELDS = frozenset({
    "product_identity", "product_name", "model", "model_name", "sku",
    "variant", "product_variant", "color", "colour", "finish", "material",
    "material_grade", "component", "components", "component_count",
})


def _canonical_image_evidence_hash(value: Mapping[str, Any]) -> str:
    """Hash bounded frozen evidence without treating its self-hash as content."""

    body = dict(value)
    body.pop("evidence_hash", None)
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bounded_identity_metadata(value: Any) -> dict[str, str]:
    """Keep only explicit, small visual identity labels; never infer pixels."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key, raw in value.items():
        normalized = str(key or "").strip().lower()
        if normalized not in _LG12_IDENTITY_FIELDS or not isinstance(raw, str):
            continue
        text = raw.strip()
        if text and len(text) <= 160:
            result[normalized] = text
    return dict(sorted(result.items()))


def _bounded_lg9_validation_summary(value: Any) -> dict[str, Any]:
    """Freeze the structured LG-9 signals used by TASK-12.4, not raw output."""

    result = dict(value or {}) if isinstance(value, Mapping) else {}
    details = dict(result.get("details") or {})
    identity = dict(details.get("identity") or {})
    checks: list[dict[str, str]] = []
    raw_checks = identity.get("checks") or {}
    if isinstance(raw_checks, Mapping):
        raw_checks = [
            {"feature": key, **dict(item)} if isinstance(item, Mapping) else {"feature": key, "status": item}
            for key, item in raw_checks.items()
        ]
    if isinstance(raw_checks, list):
        for item in raw_checks:
            if not isinstance(item, Mapping):
                continue
            feature = str(item.get("feature") or "").strip().lower()
            status = str(item.get("status") or "").strip().lower()
            if feature and status and len(feature) <= 64 and len(status) <= 64:
                checks.append({"feature": feature, "status": status})
    checks.sort(key=lambda item: (item["feature"], item["status"]))
    crop = dict(details.get("crop") or {})
    return {
        "status": str(result.get("status") or "").strip().lower(),
        "identity_status": str(identity.get("status") or "").strip().lower(),
        "identity_checks": checks,
        "identity_metadata": _bounded_identity_metadata(
            identity.get("observed_identity") or identity.get("identity_metadata")
        ),
        "quality_warnings": sorted({str(item).upper() for item in list(result.get("warnings") or []) if isinstance(item, str)}),
        "risk_codes": sorted({str(item).lower() for item in list(result.get("risk_codes") or []) if isinstance(item, str)}),
        "safe_crop_status": str(crop.get("safe_crop_status") or "").strip().lower(),
    }


def build_frozen_image_quality_evidence(*, asset: Any, job: Any | None) -> dict[str, Any]:
    """Capture bounded image QA input exactly when an asset enters a frozen page.

    The evaluator can later consult a mutable Asset row only for its storage
    locator and to re-check the bytes.  Quality, crop, and identity semantics
    must come from this immutable manifest evidence snapshot.
    """

    inspection = inspect_frozen_image_file(
        file_path=str(getattr(asset, "file_path", "") or ""),
        declared_mime_type=str(getattr(asset, "mime_type", "") or ""),
    )
    asset_hash = str(getattr(asset, "content_hash", "") or "")
    if not asset_hash or inspection["content_hash"] != asset_hash:
        raise ProductIdentityValidationError("Frozen image asset content hash does not match its storage bytes.")
    validation = _bounded_lg9_validation_summary(getattr(job, "validation_result", {}) if job is not None else {})
    metadata = {
        "identity_status": str(getattr(asset, "identity_status", "") or "").strip().lower(),
        "product_identity_preserved": bool(getattr(asset, "product_identity_preserved", False)),
        "safe_crop_status": str(getattr(asset, "safe_crop_status", "") or "").strip().lower(),
        "quality_warnings": sorted({
            str(item).upper() for item in list(getattr(asset, "quality_warnings", None) or []) if isinstance(item, str)
        }),
        "identity_metadata": validation["identity_metadata"],
    }
    generation = None
    if job is not None:
        generation = {
            "record_id": str(getattr(job, "id", "") or ""),
            "job_id": str(getattr(job, "job_id", "") or ""),
            "output_asset_id": str(getattr(job, "output_asset_id", "") or ""),
            "validation_result_hash": _canonical_image_evidence_hash({"validation": validation}),
            "validation": validation,
        }
    body = {
        "schema_version": LG12_FROZEN_IMAGE_EVIDENCE_SCHEMA_VERSION,
        "asset": {"id": str(getattr(asset, "id", "") or ""), "version": 1, "hash": asset_hash},
        "file": {
            "content_hash": inspection["content_hash"], "width": int(inspection["width"]),
            "height": int(inspection["height"]), "format": str(inspection["image_format"]),
        },
        "metadata": metadata,
        "generation": generation,
    }
    return {**body, "evidence_hash": _canonical_image_evidence_hash(body)}


def inspect_frozen_image_file(*, file_path: str, declared_mime_type: str) -> dict[str, Any]:
    """Read only bounded integrity metadata for one frozen local image.

    This deliberately returns no image body or pixels.  The quality evaluator
    uses the same established image inspection limits as LG-9 and verifies the
    file once before deriving dimensions/format metadata.
    """

    mime_by_format = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }
    path = Path(str(file_path or ""))
    if not path.is_file():
        raise ProductIdentityValidationError("Frozen image file is missing.")
    byte_size = path.stat().st_size
    if byte_size <= 0:
        raise ProductIdentityValidationError("Frozen image file is empty.")
    if declared_mime_type not in mime_by_format.values():
        raise ProductIdentityValidationError("Frozen image MIME type is unsupported.")

    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    try:
        # Pillow documents that verify() must be immediately followed by a
        # reopen before metadata/pixels are accessed.  Loading after reopen
        # catches defects that are only visible while decoding the raster.
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            image_format = str(image.format or "")
            width, height = image.size
    except Exception as exc:  # Pillow raises format-specific decode errors.
        raise ProductIdentityValidationError("Frozen image bytes are corrupt or undecodable.") from exc

    if mime_by_format.get(image_format) != declared_mime_type:
        raise ProductIdentityValidationError("Frozen image MIME type does not match decoded format.")
    if width <= 0 or height <= 0:
        raise ProductIdentityValidationError("Frozen image dimensions are invalid.")

    warnings: list[str] = []
    if width < MIN_RECOMMENDED_EDGE or height < MIN_RECOMMENDED_EDGE:
        warnings.append("LOW_RESOLUTION")
    aspect_ratio = width / height
    if aspect_ratio < MIN_ASPECT_RATIO or aspect_ratio > MAX_ASPECT_RATIO:
        warnings.append("EXTREME_ASPECT_RATIO")
    return {
        "content_hash": digest.hexdigest(),
        "byte_size": byte_size,
        "image_format": image_format,
        "width": width,
        "height": height,
        "warnings": warnings,
    }


class ProductIdentityValidator:
    STRUCTURAL_IDENTITY_ELEMENTS = ("buttons", "ports", "components", "logo")

    @staticmethod
    def _positive_prompt_text(prompt: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", prompt.lower())
        negative_markers = (
            "do not",
            "don't",
            "without",
            "avoid",
            "exclude",
            "no text",
            "no logo",
            "overlaid",
        )
        return " ".join(
            sentence
            for sentence in sentences
            if not any(marker in sentence for marker in negative_markers)
        )

    @staticmethod
    def validate_image_quality(
        content_bytes: bytes,
        mime_type: str = "image/png",
        min_width: int = 512,
        min_height: int = 512
    ) -> Image.Image:
        format_mime_types = {
            "PNG": "image/png",
            "JPEG": "image/jpeg",
            "WEBP": "image/webp",
        }
        if mime_type not in format_mime_types.values():
            raise ProductIdentityValidationError(
                f"Unsupported output MIME type: {mime_type}"
            )

        # 1. Decodability
        try:
            img = Image.open(io.BytesIO(content_bytes))
            detected_mime_type = format_mime_types.get(img.format or "")
            if detected_mime_type != mime_type:
                raise ProductIdentityValidationError(
                    f"Output MIME type mismatch: declared {mime_type}, "
                    f"decoded {detected_mime_type or 'unknown'}"
                )
            img.verify()  # Verify integrity
            img = Image.open(io.BytesIO(content_bytes))  # Re-open after verify()
        except ProductIdentityValidationError:
            raise
        except Exception as e:
            raise ProductIdentityValidationError(f"Invalid image bytes: unable to decode. Details: {e}")

        # 2. Dimensions check
        width, height = img.size
        if width < min_width or height < min_height:
            raise ProductIdentityValidationError(
                f"Image dimensions too small: {width}x{height} (minimum required: {min_width}x{min_height})"
            )

        # 3. Non-empty pixel content check (check standard deviation of a grayscale thumbnail)
        gray_thumb = img.resize((8, 8)).convert("L")
        pixels = list(gray_thumb.getdata())
        mean = sum(pixels) / len(pixels)
        variance = sum((x - mean) ** 2 for x in pixels) / len(pixels)
        std_dev = variance ** 0.5
        if std_dev < 1.0:
            raise ProductIdentityValidationError("Image contains solid/empty color only.")

        return img

    @staticmethod
    def validate_identity_preservation(
        img: Image.Image,
        source_asset_paths: List[str],
        prompt: str,
        role: str
    ) -> List[str]:
        warnings = []
        prompt_lower = ProductIdentityValidator._positive_prompt_text(prompt)

        # 1. Text / logo / certificate exclusion validation
        # Reject outputs if prompt explicitly requests text/logos that should not be baked in
        text_keywords = ["text", "words", "letters", "writing", "logo", "badge", "certificate", "label", "stamp", "watermark", "pricing", "discount"]
        # Match complete instruction words.  Substring checks incorrectly treated
        # harmless visual phrases such as "lifestyle context" as a request for
        # rasterized "text" and blocked otherwise valid LG-8 scene prompts.
        requests_raster_content = any(
            re.search(rf"\b{re.escape(keyword)}\b", prompt_lower)
            for keyword in text_keywords
        )
        if requests_raster_content:
            # Only reject if it's a product role where text/logos shouldn't be generated
            if role in ["representative_product", "cutout_product", "lifestyle_scene", "detail_closeup", "cta_visual"]:
                raise ProductIdentityValidationError(
                    "Output rejected: Contains requested marketing text, certification marks, or logos not present in source evidence."
                )

        if not source_asset_paths:
            return warnings

        # Load first source image for reference comparison
        try:
            src_img = Image.open(source_asset_paths[0])
        except Exception:
            # If source image cannot be read, skip visual comparison
            return warnings

        # Convert both to RGB to ensure comparable channels
        img_rgb = img.convert("RGB")
        src_rgb = src_img.convert("RGB")

        # 2. Dominant color consistency check
        # Resize to 1x1 to get average color
        src_1x1 = src_rgb.resize((1, 1))
        img_1x1 = img_rgb.resize((1, 1))
        
        src_color = src_1x1.getpixel((0, 0))
        img_color = img_1x1.getpixel((0, 0))

        r_diff = src_color[0] - img_color[0]
        g_diff = src_color[1] - img_color[1]
        b_diff = src_color[2] - img_color[2]
        color_dist = (r_diff**2 + g_diff**2 + b_diff**2) ** 0.5

        if color_dist > 150.0:
            warnings.append(
                f"Severe color drift detected (distance: {color_dist:.1f}). The average color of the generated image differs significantly from the original product photo."
            )

        # 3. Visible silhouette / layout consistency check
        # Resize both to 16x16 grayscale for layout comparison
        src_gray = src_rgb.resize((16, 16)).convert("L")
        img_gray = img_rgb.resize((16, 16)).convert("L")
        
        mad = 0.0
        for y in range(16):
            for x in range(16):
                mad += abs(src_gray.getpixel((x, y)) - img_gray.getpixel((x, y)))
        mad /= 256.0

        if mad > 100.0:
            warnings.append(
                f"Silhouette/layout inconsistency detected (mean absolute difference: {mad:.1f}). The shape or structure differs from the original product photo."
            )
        elif mad < 2.0:
            # A generated commercial image that is effectively pixel-identical
            # to the supplier capture is not a redesign.  Keep it out of the
            # approval flow rather than relying on a prompt-only policy.
            raise ProductIdentityValidationError(
                "Output rejected: generated image is too similar to the supplier reference layout."
            )

        return warnings

    @staticmethod
    def _normalized_crop(image: Image.Image, box: object) -> Image.Image | None:
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            return None
        try:
            left, top, right, bottom = (float(value) for value in box)
        except (TypeError, ValueError):
            return None
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            return None
        width, height = image.size
        pixels = (
            int(round(left * width)),
            int(round(top * height)),
            int(round(right * width)),
            int(round(bottom * height)),
        )
        if pixels[0] >= pixels[2] or pixels[1] >= pixels[3]:
            return None
        return image.crop(pixels).convert("L").resize((16, 16))

    @staticmethod
    def _region_difference(source: Image.Image, output: Image.Image) -> float:
        source_pixels = list(source.getdata())
        output_pixels = list(output.getdata())
        return sum(abs(int(a) - int(b)) for a, b in zip(source_pixels, output_pixels)) / max(
            1, len(source_pixels)
        )

    @staticmethod
    def inspect_identity_preservation(
        img: Image.Image,
        source_asset_paths: List[str],
        prompt: str,
        role: str,
        identity_constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return an evidence-aware LG-9 identity report.

        The existing color/silhouette validator remains the baseline. Fine
        product features can only pass when the immutable scene prompt carries
        normalized reference/output regions for them. Missing or malformed
        evidence is reported as ``needs_review`` instead of being guessed as a
        pass. Region entries use ``reference_box`` and ``output_box`` values in
        normalized ``[left, top, right, bottom]`` coordinates.
        """

        warnings = ProductIdentityValidator.validate_identity_preservation(
            img=img,
            source_asset_paths=source_asset_paths,
            prompt=prompt,
            role=role,
        )
        checks: dict[str, dict[str, Any]] = {
            "color": {
                "status": "needs_review" if any("color drift" in item.lower() for item in warnings) else "passed"
            },
            "silhouette": {
                "status": "needs_review" if any("silhouette" in item.lower() for item in warnings) else "passed"
            },
        }
        constraints = identity_constraints or {}
        feature_regions = constraints.get("feature_regions") or {}
        sources: list[Image.Image | None] = []
        for source_path in source_asset_paths:
            try:
                with Image.open(source_path) as source_image:
                    sources.append(source_image.convert("RGB"))
            except (OSError, ValueError):
                sources.append(None)

        insufficient: list[str] = []
        for element in ProductIdentityValidator.STRUCTURAL_IDENTITY_ELEMENTS:
            regions = feature_regions.get(element) if isinstance(feature_regions, dict) else None
            if not isinstance(regions, list) or not regions:
                checks[element] = {
                    "status": "needs_review",
                    "reason": "structured_reference_unavailable",
                }
                insufficient.append(element)
                continue

            differences: list[float] = []
            invalid_region = False
            for region in regions:
                if not isinstance(region, dict):
                    invalid_region = True
                    break
                reference_index = region.get("reference_index", 0)
                if (
                    not isinstance(reference_index, int)
                    or isinstance(reference_index, bool)
                    or reference_index < 0
                    or reference_index >= len(sources)
                    or sources[reference_index] is None
                ):
                    invalid_region = True
                    break
                source = sources[reference_index]
                assert source is not None
                source_crop = ProductIdentityValidator._normalized_crop(source, region.get("reference_box"))
                output_crop = ProductIdentityValidator._normalized_crop(img, region.get("output_box"))
                if source_crop is None or output_crop is None:
                    invalid_region = True
                    break
                differences.append(ProductIdentityValidator._region_difference(source_crop, output_crop))
            if invalid_region or not differences:
                checks[element] = {
                    "status": "needs_review",
                    "reason": "structured_reference_invalid",
                }
                insufficient.append(element)
                continue
            max_difference = max(differences)
            checks[element] = {
                "status": "passed" if max_difference <= 45.0 else "needs_review",
                "reason": "region_match" if max_difference <= 45.0 else "region_mismatch",
                "max_mean_absolute_difference": round(max_difference, 2),
                "region_count": len(differences),
            }
            if max_difference > 45.0:
                warnings.append(
                    f"{element} preservation requires review (region difference: {max_difference:.1f})."
                )

        if insufficient:
            warnings.append(
                "Structured identity evidence is unavailable for: " + ", ".join(insufficient) + "."
            )
        status = "passed" if checks and all(item["status"] == "passed" for item in checks.values()) else "needs_review"
        return {"status": status, "checks": checks, "warnings": warnings}
