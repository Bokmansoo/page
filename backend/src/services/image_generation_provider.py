from typing import List, Optional, Dict, Any, Protocol, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class ImageGenerationRequest(BaseModel):
    job_id: str
    role: str
    prompt: str
    negative_prompt: str = ""
    source_asset_paths: List[str] = Field(default_factory=list)
    preserve_product_identity: bool = True
    size: str = "1024x1024"
    quality: Literal["low", "medium", "high", "auto"] = "medium"
    transparent_background: bool = False
    
    # Sprint 52 / 56 fields
    slot_id: str = ""
    reference_asset_ids: List[str] = Field(default_factory=list)
    requires_cost_approval: bool = False
    cost_approved: bool = True
    product_identity_required: bool = True

    @model_validator(mode="after")
    def validate_request(self) -> "ImageGenerationRequest":
        # Keep backward compatibility with existing preserve_product_identity validator
        # but don't reject if reference_asset_ids are present but source_asset_paths are empty
        if self.preserve_product_identity and not self.source_asset_paths and not self.reference_asset_ids:
            raise ValueError("source_asset_paths must not be empty when preserve_product_identity is True")
        return self


class ImageGenerationResult(BaseModel):
    content: bytes
    mime_type: str = "image/png"
    provider: str
    model: str
    revised_prompt: Optional[str] = None
    usage_metadata: Dict[str, Any] = Field(default_factory=dict)
    # A provider may return the small set of explicitly observed product
    # identity labels that its generation/review contract produced.  This is
    # evidence only: callers still compare it with frozen Truth and seller
    # confirmation during QA; it never promotes a commercial fact.
    observed_identity: Dict[str, str] = Field(default_factory=dict)
    
    # Sprint 52 / 56 fields
    status: str = "success"
    assets: List[str] = Field(default_factory=list)

    @field_validator("observed_identity")
    @classmethod
    def _bounded_observed_identity(cls, value: Dict[str, str]) -> Dict[str, str]:
        allowed = {
            "product_identity", "product_name", "model", "model_name", "sku",
            "variant", "product_variant", "color", "colour", "finish", "material",
            "material_grade", "component", "components", "component_count",
        }
        if len(value) > len(allowed):
            raise ValueError("observed_identity contains too many fields")
        normalized: Dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key or "").strip().lower()
            text = str(raw_value or "").strip()
            if key not in allowed or not text or len(text) > 160:
                raise ValueError("observed_identity contains an invalid field")
            normalized[key] = text
        return dict(sorted(normalized.items()))



class ImageGenerationProvider(Protocol):
    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        ...


class MockImageGenerationProvider:
    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if request.requires_cost_approval and not request.cost_approved:
            return ImageGenerationResult(
                content=b"",
                mime_type="image/png",
                provider="mock",
                model="mock-model",
                status="blocked_cost_approval"
            )
            
        # Draw a deterministic image at the requested bounded canvas.
        from PIL import Image, ImageDraw
        import io
        try:
            width, height = (int(part) for part in request.size.lower().split("x", 1))
            if width <= 0 or height <= 0 or width > 4096 or height > 4096:
                raise ValueError
        except (TypeError, ValueError):
            width, height = 512, 512
        img = Image.new("RGB", (width, height), color="red")
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 100, 100], fill="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        
        return ImageGenerationResult(
            content=buf.getvalue(),
            mime_type="image/png",
            provider="mock",
            model="mock-model",
            status="success"
        )


class ImageGenerationProviderRouter:
    def __init__(self, mode: str = "mock", primary_provider: str = "openai"):
        self.mode = mode
        self.primary_provider = primary_provider

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        from src.config import settings

        model = settings.SELLFORM_IMAGE_MODEL

        if self.mode == "real" and not request.cost_approved:
            return ImageGenerationResult(
                content=b"",
                mime_type="image/png",
                provider=self.primary_provider,
                model=model,
                status="blocked_cost_approval",
                assets=[]
            )

        if self.mode == "mock":
            # Return dummy mock placeholder image
            from PIL import Image, ImageDraw
            import io
            try:
                width, height = (int(part) for part in request.size.lower().split("x", 1))
                if width <= 0 or height <= 0 or width > 4096 or height > 4096:
                    raise ValueError
            except (TypeError, ValueError):
                width, height = 512, 512
            img = Image.new("RGB", (width, height), color="red")
            draw = ImageDraw.Draw(img)
            draw.rectangle([10, 10, 100, 100], fill="blue")
            buf = io.BytesIO()
            img.save(buf, format="PNG")

            return ImageGenerationResult(
                content=buf.getvalue(),
                mime_type="image/png",
                provider="mock",
                model="mock-model",
                status="success",
                assets=["mock-asset-id"]
            )

        # Real Mode: fallback mock or OpenAIImageProvider invocation
        # Since E2E/Contract testing may use "real" mode with mock config,
        # we can delegate to Mock or real depending on API key availability
        # to ensure it behaves safely.
        try:
            from src.services.openai_image_provider import OpenAIImageProvider
            provider = OpenAIImageProvider(model=model)
            return provider.generate(request)
        except Exception as exc:
            return ImageGenerationResult(
                content=b"",
                mime_type="image/png",
                provider=self.primary_provider,
                model=model,
                status="provider_error",
                assets=[],
                usage_metadata={"error": str(exc)[:300]},
            )
