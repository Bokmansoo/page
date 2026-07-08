import base64
import logging
from contextlib import ExitStack
from typing import Optional
from openai import OpenAI, BadRequestError, AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError, APIError
from src.config import settings
from src.services.image_generation_provider import ImageGenerationRequest, ImageGenerationResult

logger = logging.getLogger(__name__)


def _compact_error_message(error: Exception, limit: int = 500) -> str:
    return " ".join(str(error).split())[:limit]


class OpenAIImageProvider:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.SELLFORM_IMAGE_MODEL
        if not self.api_key:
            raise RuntimeError("AUTHENTICATION_FAILED")
        self.client = OpenAI(api_key=self.api_key)

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if request.requires_cost_approval and not request.cost_approved:
            return ImageGenerationResult(
                content=b"",
                mime_type="image/png",
                provider="openai",
                model=self.model,
                status="blocked_cost_approval"
            )

        adjusted_prompt = request.prompt.strip()
        if request.negative_prompt.strip():
            adjusted_prompt = (
                f"{adjusted_prompt}\n\nAvoid these visual elements: "
                f"{request.negative_prompt.strip()}"
            )
        background = "transparent" if request.transparent_background else "opaque"
        output_format = settings.SELLFORM_IMAGE_OUTPUT_FORMAT

        if (
            request.preserve_product_identity
            and request.reference_asset_ids
            and not request.source_asset_paths
        ):
            raise RuntimeError("REFERENCE_ASSET_PATHS_REQUIRED")

        try:
            if request.preserve_product_identity and request.source_asset_paths:
                with ExitStack() as stack:
                    image_files = [
                        stack.enter_context(open(path, "rb"))
                        for path in request.source_asset_paths
                    ]
                    edit_kwargs = dict(
                        model=self.model,
                        image=image_files,
                        prompt=adjusted_prompt,
                        size=request.size,
                        quality=request.quality,
                        background=background,
                        output_format=output_format,
                    )
                    if self.model != "gpt-image-1-mini":
                        edit_kwargs["input_fidelity"] = "high"
                    response = self.client.images.edit(**edit_kwargs)
            else:
                response = self.client.images.generate(
                    model=self.model,
                    prompt=adjusted_prompt,
                    size=request.size,
                    quality=request.quality,
                    background=background,
                    output_format=output_format,
                )

            b64_json = response.data[0].b64_json
            if not b64_json:
                raise ValueError("No b64_json content received from OpenAI Image API")
            
            content_bytes = base64.b64decode(b64_json)
            revised_prompt = getattr(response.data[0], "revised_prompt", None)
            usage = getattr(response, "usage", None)
            if isinstance(usage, dict):
                usage_metadata = usage
            elif hasattr(usage, "model_dump"):
                dumped_usage = usage.model_dump()
                usage_metadata = dumped_usage if isinstance(dumped_usage, dict) else {}
            else:
                usage_metadata = {}
            mime_type = {
                "jpeg": "image/jpeg",
                "webp": "image/webp",
            }.get(output_format, "image/png")

            return ImageGenerationResult(
                content=content_bytes,
                mime_type=mime_type,
                provider="openai",
                model=self.model,
                revised_prompt=revised_prompt,
                usage_metadata=usage_metadata,
            )

        except BadRequestError as e:
            # Often moderation block or invalid format/size
            detail = _compact_error_message(e)
            err_msg = detail.lower()
            if (
                "billing_hard_limit_reached" in err_msg
                or "billing_limit_user_error" in err_msg
                or "billing hard limit" in err_msg
            ):
                error_code = "BILLING_HARD_LIMIT_REACHED"
            elif "safety" in err_msg or "policy" in err_msg or "moderation" in err_msg:
                error_code = "MODERATION_REJECTED"
            else:
                error_code = "INVALID_REQUEST"
            logger.error(f"OpenAI BadRequestError: {e}")
            raise RuntimeError(f"{error_code}: {detail}") from e

        except AuthenticationError as e:
            logger.error(f"OpenAI AuthenticationError: {e}")
            raise RuntimeError("AUTHENTICATION_FAILED") from e

        except RateLimitError as e:
            logger.error(f"OpenAI RateLimitError: {e}")
            raise RuntimeError("RATE_LIMIT_EXCEEDED") from e

        except (APITimeoutError, APIConnectionError) as e:
            logger.error(f"OpenAI Timeout/Connection error: {e}")
            raise RuntimeError("TIMEOUT") from e

        except APIError as e:
            logger.error(f"OpenAI General APIError: {e}")
            raise RuntimeError("PROVIDER_ERROR") from e

        except Exception as e:
            logger.error(f"Unexpected error in OpenAIImageProvider: {e}")
            raise RuntimeError("PROVIDER_ERROR") from e
