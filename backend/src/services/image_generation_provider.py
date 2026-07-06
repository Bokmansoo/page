from typing import List, Optional, Dict, Any, Protocol, Literal
from pydantic import BaseModel, Field, model_validator


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
    
    # Sprint 52 / 56 fields
    status: str = "success"
    assets: List[str] = Field(default_factory=list)



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
            
        # Draw a simple 512x512 dummy image using PIL
        from PIL import Image, ImageDraw
        import io
        img = Image.new("RGB", (512, 512), color="red")
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
            img = Image.new("RGB", (512, 512), color="red")
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
