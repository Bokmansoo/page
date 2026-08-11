"""Provider boundary reserved for UX-2E.

UX-2E-0 never invokes this adapter.  Keeping the contract here prevents a
future browser component from calling an image or LLM provider directly.
"""

from __future__ import annotations

from typing import Protocol

from src.schemas.api_ready_generation import GenerationJobRequestSchema, GenerationJobResultSchema
from src.services.image_generation_provider import ImageGenerationRequest, ImageGenerationResult


class GenerationProviderAdapter(Protocol):
    def submit(self, request: GenerationJobRequestSchema) -> GenerationJobResultSchema:
        """Submit an approved scene request and return a provider job handle."""

    def get_status(self, provider_job_id: str, request_id: str) -> GenerationJobResultSchema:
        """Return provider-neutral status/result metadata for a job."""


class ImageGenerationProviderAdapter(Protocol):
    """Server-side image-provider boundary used by UX-2E-2."""

    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        """Generate one reviewed image without exposing provider credentials to the browser."""


class ProviderNotConnectedError(RuntimeError):
    pass


class UnconfiguredGenerationProvider:
    """Safe default: no outbound request and no synthetic generated result."""

    def submit(self, request: GenerationJobRequestSchema) -> GenerationJobResultSchema:
        raise ProviderNotConnectedError("AI generation provider is not connected. No request was sent.")

    def get_status(self, provider_job_id: str, request_id: str) -> GenerationJobResultSchema:
        return GenerationJobResultSchema(
            request_id=request_id,
            status="pending_provider",
            provider_job_id=provider_job_id,
            failure_category="not_connected",
            retryable=True,
            message="AI generation provider is not connected.",
        )


def get_image_generation_adapter(provider_name: str, model: str | None = None) -> ImageGenerationProviderAdapter:
    """Resolve an allow-listed provider behind the common server adapter."""
    normalized = (provider_name or "").strip().lower()
    if normalized != "openai":
        raise ProviderNotConnectedError(f"Unsupported image generation provider: {normalized or 'unset'}")
    from src.services.openai_image_provider import OpenAIImageProvider

    return OpenAIImageProvider(model=model)
