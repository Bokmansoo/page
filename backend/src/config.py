import os
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Sellform runtime uses PostgreSQL by default.
    # SQLite was used only in early MVP sprints and should not be used for
    # normal local development or product verification.
    DATABASE_URL: str = "postgresql://sellform:sellformpassword@localhost:5434/sellform_dev"
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10
    SELLFORM_RAG_DEBUG_ENABLED: bool = Field(
        default=False,
        validation_alias=AliasChoices("SELLFORM_RAG_DEBUG_ENABLED", "FACTORY_RAG_DEBUG_ENABLED"),
    )
    SELLFORM_RAG_RUNTIME_MOCK: bool = Field(
        default=False,
        validation_alias=AliasChoices("SELLFORM_RAG_RUNTIME_MOCK", "FACTORY_RAG_RUNTIME_MOCK"),
    )

    # Generation & Agent Configuration (Sprint 48)
    SELLFORM_GENERATION_MODE: str = "mock"
    SELLFORM_TEXT_LLM_PRIMARY_PROVIDER: str = "openai"
    SELLFORM_TEXT_LLM_FALLBACK1_PROVIDER: str = "gemini"
    SELLFORM_TEXT_LLM_FALLBACK2_PROVIDER: str = "claude"
    SELLFORM_IMAGE_PRIMARY_PROVIDER: str = "openai"


    # AI API keys
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    # Image Generation Configurations (Sprint 44.5)
    SELLFORM_IMAGE_PROVIDER: str = "openai"
    SELLFORM_IMAGE_MODEL: str = "gpt-image-1.5"
    SELLFORM_IMAGE_PREVIEW_MODEL: str = "gpt-image-1-mini"
    SELLFORM_IMAGE_OUTPUT_FORMAT: str = "png"

    # AI Fact Extraction Configurations (Sprint 16)
    OPENAI_FACT_MODEL: str = "gpt-4o-mini"
    AI_FACT_EXTRACTION_TIMEOUT_SECONDS: int = 30
    AI_FACT_EXTRACTION_MAX_FACTS: int = 20

    # LLM Router Configurations (Sprint 18+)
    #
    # Public Sellform configuration uses SELLFORM_* names.
    # FACTORY_* names remain accepted only as backward-compatible aliases for
    # older Sprint-era local environments.
    SELLFORM_LLM_DEFAULT_PROVIDER: str = Field(
        default="openai",
        validation_alias=AliasChoices("SELLFORM_LLM_DEFAULT_PROVIDER", "FACTORY_LLM_DEFAULT_PROVIDER"),
    )
    SELLFORM_LLM_DEFAULT_MODEL: str = Field(
        default="gpt-5.4-nano",
        validation_alias=AliasChoices("SELLFORM_LLM_DEFAULT_MODEL", "FACTORY_LLM_DEFAULT_MODEL"),
    )
    SELLFORM_LLM_FALLBACK1_PROVIDER: str = Field(
        default="google",
        validation_alias=AliasChoices("SELLFORM_LLM_FALLBACK1_PROVIDER", "FACTORY_LLM_FALLBACK1_PROVIDER"),
    )
    SELLFORM_LLM_FALLBACK1_MODEL: str = Field(
        default="gemini-2.5-flash",
        validation_alias=AliasChoices("SELLFORM_LLM_FALLBACK1_MODEL", "FACTORY_LLM_FALLBACK1_MODEL"),
    )
    SELLFORM_LLM_FALLBACK2_PROVIDER: str = Field(
        default="deterministic",
        validation_alias=AliasChoices("SELLFORM_LLM_FALLBACK2_PROVIDER", "FACTORY_LLM_FALLBACK2_PROVIDER"),
    )
    SELLFORM_LLM_FALLBACK2_MODEL: str = Field(
        default="local-rule-based",
        validation_alias=AliasChoices("SELLFORM_LLM_FALLBACK2_MODEL", "FACTORY_LLM_FALLBACK2_MODEL"),
    )
    SELLFORM_LLM_ENABLE_FALLBACKS: bool = Field(
        default=True,
        validation_alias=AliasChoices("SELLFORM_LLM_ENABLE_FALLBACKS", "FACTORY_LLM_ENABLE_FALLBACKS"),
    )

    @property
    def FACTORY_RAG_DEBUG_ENABLED(self) -> bool:
        """Backward-compatible alias for older Sprint-era code."""
        return self.SELLFORM_RAG_DEBUG_ENABLED

    @property
    def FACTORY_RAG_RUNTIME_MOCK(self) -> bool:
        """Backward-compatible alias for older Sprint-era code."""
        return self.SELLFORM_RAG_RUNTIME_MOCK

    @property
    def effective_openai_model(self) -> str:
        """Prefer the Sellform LLM router model, fallback to legacy OPENAI_FACT_MODEL."""
        val = self.SELLFORM_LLM_DEFAULT_MODEL
        if not val or not val.strip():
            return self.OPENAI_FACT_MODEL
        return val.strip()

    # Web Browsing Settings (Sprint 23)
    SELLFORM_WEB_BROWSING_ENABLED: bool = True
    SELLFORM_WEB_BROWSING_PROVIDER: str = "openai"
    SELLFORM_WEB_BROWSING_MODEL: str = "gpt-5.4-nano"
    SELLFORM_WEB_BROWSING_TIMEOUT_SECONDS: int = 30
    SELLFORM_WEB_BROWSING_MAX_CHARS: int = 12000

    # Optional Figma collaboration integration (Sprint 32)
    SELLFORM_FIGMA_MCP_ENABLED: bool = False
    SELLFORM_PUBLIC_ASSET_BASE_URL: str = "http://localhost:8000"

    # Figma Bridge Configurations (Sprint 33)
    SELLFORM_FIGMA_BRIDGE_URL: str = "http://127.0.0.1:3417"
    SELLFORM_FIGMA_BRIDGE_TOKEN: str = ""
    SELLFORM_FIGMA_BRIDGE_TIMEOUT_SECONDS: int = 120

    # Figma Plugin Configurations (Sprint 34)
    SELLFORM_FIGMA_PLUGIN_TICKET_SECRET: str = ""
    SELLFORM_FIGMA_PLUGIN_TICKET_TTL_SECONDS: int = 600
    SELLFORM_FIGMA_PLUGIN_SESSION_TTL_SECONDS: int = 600
    SELLFORM_FIGMA_PLUGIN_PACKAGE_MAX_BYTES: int = 20971520

    # Allow loading from environment file (.env or similar)
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
