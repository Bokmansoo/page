import io
import re
from PIL import Image
from typing import Any, List


class ProductIdentityValidationError(Exception):
    pass


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
