import io
import re
from PIL import Image
from typing import List, Optional


class ProductIdentityValidationError(Exception):
    pass


class ProductIdentityValidator:
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
        if any(kw in prompt_lower for kw in text_keywords):
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

        return warnings
