import os
from typing import Literal

from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"
    # Sellform runtime uses PostgreSQL by default.
    # SQLite was used only in early MVP sprints and should not be used for
    # normal local development or product verification.
    DATABASE_URL: str = "postgresql://sellform:sellformpassword@localhost:5544/sellform_dev"
    # PostgreSQL-only integration and browser E2E use an explicitly separate
    # local database.  These are intentionally never implicit fallbacks for
    # unit tests or ordinary runtime configuration.
    TEST_DATABASE_URL: str | None = None
    UNIT_TEST_DATABASE_URL: str | None = None
    E2E_DATABASE_URL: str | None = None
    SELLFORM_ALLOW_TEST_DATABASE: bool = False
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # Sprint 9 authentication. Development has a local session bootstrap so
    # local work remains possible before social OAuth apps are registered.
    SELLFORM_AUTH_MODE: str = "development"
    SELLFORM_AUTH_ALLOW_TEST_MOCK: bool = False
    SELLFORM_SESSION_SECRET: str = "change-this-development-session-secret"
    SELLFORM_SESSION_COOKIE_NAME: str = "sellform_session"
    SELLFORM_SESSION_CSRF_COOKIE_NAME: str = "sellform_csrf"
    SELLFORM_SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 14
    SELLFORM_AUTH_STATE_TTL_SECONDS: int = 600
    SELLFORM_PUBLIC_APP_URL: str = "http://localhost:3000"
    # OAuth providers must redirect to the API callback endpoint; the browser
    # application receives the final post-login redirect separately.
    SELLFORM_PUBLIC_API_URL: str = "http://localhost:8001"
    SELLFORM_SESSION_COOKIE_SECURE: bool = False
    SELLFORM_OAUTH_GOOGLE_CLIENT_ID: str | None = None
    SELLFORM_OAUTH_GOOGLE_CLIENT_SECRET: str | None = None
    SELLFORM_OAUTH_KAKAO_CLIENT_ID: str | None = None
    SELLFORM_OAUTH_KAKAO_CLIENT_SECRET: str | None = None
    SELLFORM_OAUTH_NAVER_CLIENT_ID: str | None = None
    SELLFORM_OAUTH_NAVER_CLIENT_SECRET: str | None = None
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
    # LG-0 keeps the existing AgentGraph path as the safe default. Later
    # LangGraph migration sprints can opt in per environment without changing
    # existing projects or their execution behavior.
    SELLFORM_GRAPH_RUNTIME: Literal["legacy", "langgraph"] = "legacy"
    # The workflow checkpoint store is intentionally separate from the
    # SQLAlchemy URL so it can be moved to a dedicated PostgreSQL database in
    # production. An empty value means "use DATABASE_URL".
    SELLFORM_LANGGRAPH_CHECKPOINT_DATABASE_URL: str | None = None
    SELLFORM_LANGGRAPH_CHECKPOINT_SETUP_ON_START: bool = True
    SELLFORM_TEXT_LLM_PRIMARY_PROVIDER: str = "openai"
    SELLFORM_TEXT_LLM_PRIMARY_MODEL: str = "gpt-5.4-nano"
    SELLFORM_TEXT_LLM_FALLBACK1_PROVIDER: str = "gemini"
    SELLFORM_TEXT_LLM_FALLBACK1_MODEL: str = "gemini-2.5-flash"
    SELLFORM_TEXT_LLM_FALLBACK2_PROVIDER: str = "claude"
    SELLFORM_TEXT_LLM_FALLBACK2_MODEL: str = "claude-3-5-sonnet-20241022"
    SELLFORM_TEXT_LLM_ENABLE_FALLBACKS: bool = True
    SELLFORM_IMAGE_PRIMARY_PROVIDER: str = "openai"


    # AI API keys
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None

    # Image Generation Configurations (Sprint 44.5 / 56)
    SELLFORM_IMAGE_PROVIDER: str = "openai"
    SELLFORM_IMAGE_MODEL: str = "gpt-image-1-mini"
    SELLFORM_IMAGE_PREVIEW_MODEL: str = "gpt-image-1-mini"
    SELLFORM_IMAGE_OUTPUT_FORMAT: str = "png"
    SELLFORM_IMAGE_GENERATION_MODE: str = "mock"
    SELLFORM_IMAGE_COST_APPROVAL_REQUIRED: bool = True
    SELLFORM_IMAGE_MAX_CANDIDATES_PER_SLOT: int = 3
    # LG-5R durable DB worker. The queue is persisted even when the in-process
    # poller is disabled; deployments may run ``image_generation_worker`` as a
    # separate process against the same database.
    SELLFORM_IMAGE_WORKER_ENABLED: bool = True
    SELLFORM_IMAGE_WORKER_POLL_SECONDS: float = 0.5
    SELLFORM_IMAGE_WORKER_LEASE_SECONDS: int = 60
    SELLFORM_IMAGE_WORKER_BATCH_SIZE: int = 4

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
    SELLFORM_URL_OCR_ENABLED: bool = False
    # OCR translation is only allowed to call a paid provider when explicitly
    # enabled.  Otherwise unresolved text remains reviewable and blocks the
    # Sprint 3 fact-extraction gate instead of being guessed.
    SELLFORM_OCR_AI_TRANSLATION_ENABLED: bool = False
    SELLFORM_ASSET_AI_VISION_ENABLED: bool = False

    # Optional Figma collaboration integration (Sprint 32)
    SELLFORM_FIGMA_MCP_ENABLED: bool = False
    SELLFORM_PUBLIC_ASSET_BASE_URL: str = "http://localhost:8001"

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
        # config.py lives in backend/src.  OAuth and local runtime values are
        # intentionally stored in backend/.env, not in the repository root.
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
