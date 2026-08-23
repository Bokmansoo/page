import datetime
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    Float,
    Boolean,
    DDL,
    event,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from src.db.database import Base
from src.services.commerce_policy import initial_asset_usage_status


def generate_uuid():
    return str(uuid.uuid4())


def default_asset_usage_status(context):
    return initial_asset_usage_status(context.get_current_parameters().get("source_type"))


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    workspaces = relationship("Workspace", back_populates="owner")
    memberships = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")
    oauth_accounts = relationship("OAuthAccount", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)

    owner = relationship("User", back_populates="workspaces")
    brands = relationship("Brand", back_populates="workspace")
    projects = relationship("ProductProject", back_populates="workspace")
    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    invitations = relationship("WorkspaceInvitation", back_populates="workspace", cascade="all, delete-orphan")


class OAuthAccount(Base):
    """A stable provider identity. E-mail is intentionally not the key."""
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_account_id", name="uq_oauth_provider_account"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(30), nullable=False)
    provider_account_id = Column(String(255), nullable=False)
    provider_email = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    scopes_json = Column(JSON, nullable=False, default=list)
    linked_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="oauth_accounts")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    active_workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=True, index=True)
    token_hash = Column(String(128), nullable=False, unique=True, index=True)
    csrf_token_hash = Column(String(128), nullable=False)
    user_agent = Column(String(500), nullable=True)
    ip_address = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")
    active_workspace = relationship("Workspace", foreign_keys=[active_workspace_id])


class OAuthLoginAttempt(Base):
    __tablename__ = "oauth_login_attempts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    state_hash = Column(String(128), nullable=False, unique=True, index=True)
    provider = Column(String(30), nullable=False)
    intent = Column(String(20), nullable=False, default="login")
    nonce = Column(String(255), nullable=False)
    code_verifier = Column(String(255), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    redirect_path = Column(String(500), nullable=False, default="/workspace")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)


class Brand(Base):
    __tablename__ = "brands"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    name = Column(String(255), nullable=False)
    logo_url = Column(String(500), nullable=True)
    brand_colors = Column(JSON, nullable=True)  # e.g., {"primary": "#...", "secondary": "#..."}
    font_tone = Column(String(50), nullable=False, default="modern")
    default_disclaimer = Column(Text, nullable=True)

    workspace = relationship("Workspace", back_populates="brands")
    projects = relationship("ProductProject", back_populates="brand")


class ProductProject(Base):
    __tablename__ = "product_projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    brand_id = Column(String(36), ForeignKey("brands.id"), nullable=False)
    name = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="draft")  # draft, processing, checking, ready
    current_step = Column(String(50), nullable=False, default="raw_input")
    category = Column(String(100), nullable=True)  # Fashion, Beauty, Food, Living
    category_confirmed = Column(Boolean, nullable=False, default=False)
    category_confirmed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    category_confirmed_at = Column(DateTime, nullable=True)
    raw_input_url = Column(String(1000), nullable=True)
    raw_input_text = Column(Text, nullable=True)
    selected_style = Column(String(50), nullable=True)
    selected_background = Column(String(100), nullable=True)
    intake_snapshot = Column(JSON, nullable=True)  # normalized intake and reviewed understanding data
    style_candidates_snapshot = Column(JSON, nullable=True)  # list of style candidate dicts from last generation
    style_generation = Column(Integer, nullable=False, default=0)  # increments on each regeneration
    visual_package_jobs = Column(JSON, nullable=True)  # visual package planned/needs_generation image jobs
    planning_mode = Column(String(20), nullable=False, default="quality")
    planning_draft = Column(JSON, nullable=True)
    # LG-6 freezes the Brand Kit used when a project is created. Project
    # overrides are separate immutable BrandKitVersion records.
    brand_kit_version_id = Column(
        String(36),
        ForeignKey("brand_kit_versions.id", use_alter=True, name="fk_project_brand_kit_version"),
        nullable=True,
    )
    brand_kit_override_version_id = Column(
        String(36),
        ForeignKey("brand_kit_versions.id", use_alter=True, name="fk_project_brand_kit_override_version"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    workspace = relationship("Workspace", back_populates="projects")
    brand = relationship("Brand", back_populates="projects")
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")
    source_captures = relationship("SourceCapture", back_populates="project", cascade="all, delete-orphan")
    job_statuses = relationship("JobStatus", back_populates="project", cascade="all, delete-orphan")
    facts = relationship("ProductFact", back_populates="project", cascade="all, delete-orphan")
    job_logs = relationship("AiJobLog", back_populates="project", cascade="all, delete-orphan")
    pages = relationship("ProductPage", back_populates="project", cascade="all, delete-orphan")
    export_jobs = relationship("ExportJob", back_populates="project", cascade="all, delete-orphan")
    published_pages = relationship("PublishedPage", back_populates="project", cascade="all, delete-orphan")


class Asset(Base):
    __tablename__ = "assets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id"), nullable=False)
    source_type = Column(String(50), nullable=False)  # sourced, self_shot, ai_corrected
    # V2 policy status: supplier captures can be retained as references without
    # becoming eligible for the final seller-facing detail page.
    usage_status = Column(String(30), nullable=False, default=default_asset_usage_status)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    # Seller-confirmed position in the immutable Sprint 1 intake bundle.
    # Null means that the asset has not been selected for an intake bundle.
    intake_order = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    source_asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    cutout_status = Column(String(50), nullable=True)
    background_removed = Column(Boolean, default=False)
    product_identity_preserved = Column(Boolean, default=True)

    # Sprint 2: persistent product-visual classification contract.
    asset_role = Column(String(50), nullable=False, default="unknown")
    role_confidence = Column(Float, nullable=False, default=0.0)
    role_source = Column(String(20), nullable=False, default="auto")
    quality_status = Column(String(20), nullable=False, default="warning")
    identity_status = Column(String(20), nullable=False, default="needs_review")
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    image_format = Column(String(20), nullable=True)
    quality_warnings = Column(JSON, nullable=False, default=list)
    content_hash = Column(String(64), nullable=True)
    ocr_text = Column(Text, nullable=True)
    safe_crop_status = Column(String(30), nullable=False, default="needs_review")
    is_representative = Column(Boolean, nullable=False, default=False)
    representative_source = Column(String(20), nullable=False, default="auto")
    classification_version = Column(Integer, nullable=False, default=0)

    project = relationship("ProductProject", back_populates="assets")
    inspections = relationship(
        "AssetInspectionRecord", back_populates="asset", cascade="all, delete-orphan"
    )


class AssetInspectionRecord(Base):
    """An immutable, versioned result of one Sprint 2 asset analysis run.

    Asset columns keep the latest lightweight classification used by existing
    flows.  This table preserves the analysis evidence and lets a seller retry
    OCR/classification without modifying the source file or losing history.
    """

    __tablename__ = "asset_inspections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id = Column(String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_version = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="pending")  # pending, completed, failed
    analyzer_version = Column(String(100), nullable=False, default="local-asset-understanding-v1")
    asset_role = Column(String(50), nullable=True)
    rights_status = Column(String(30), nullable=True)
    final_output_eligible = Column(Boolean, nullable=False, default=False)
    duplicate_asset_ids = Column(JSON, nullable=False, default=list)
    warnings = Column(JSON, nullable=False, default=list)
    ocr_blocks = Column(JSON, nullable=False, default=list)
    translation_blocks = Column(JSON, nullable=False, default=list)
    numeric_evidence = Column(JSON, nullable=False, default=list)
    analysis_metadata = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    asset = relationship("Asset", back_populates="inspections")


class SourceCapture(Base):
    """One attempted product/reference URL collection in an intake bundle."""

    __tablename__ = "source_captures"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    url = Column(String(1000), nullable=False)
    platform = Column(String(100), nullable=False, default="unknown")
    source_role = Column(String(30), nullable=False, default="product")
    collection_status = Column(String(30), nullable=False, default="pending")
    failure_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    collected_image_count = Column(Integer, nullable=False, default=0)
    collected_spec_count = Column(Integer, nullable=False, default=0)
    # Structured provenance for browser-assisted captures.  This deliberately
    # contains only the seller-approved capture scope and never browser
    # credentials, cookies, or a complete page dump.
    capture_metadata = Column(JSON, nullable=False, default=dict)
    attempted_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    project = relationship("ProductProject", back_populates="source_captures")


class BrowserExtensionConnection(Base):
    """A short-lived, workspace-scoped connection issued to the local extension.

    The browser extension never receives a Sellform user session, cookies, or a
    general API key.  It exchanges a single-use code for this limited token.
    """

    __tablename__ = "browser_extension_connections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    code_hash = Column(String(64), nullable=False, unique=True, index=True)
    code_expires_at = Column(DateTime, nullable=False)
    code_used_at = Column(DateTime, nullable=True)
    token_hash = Column(String(64), nullable=True, unique=True, index=True)
    token_expires_at = Column(DateTime, nullable=True)
    token_revoked_at = Column(DateTime, nullable=True)
    token_rotated_at = Column(DateTime, nullable=True)
    extension_name = Column(String(100), nullable=True)
    extension_version = Column(String(50), nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class BrowserExtensionCapture(Base):
    """Audit record for an explicitly selected browser product capture.

    Only metadata and selected visible content are stored.  Cookies, auth
    headers and a full background page dump are intentionally not modelled.
    """

    __tablename__ = "browser_extension_captures"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    connection_id = Column(String(36), ForeignKey("browser_extension_connections.id", ondelete="SET NULL"), nullable=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="SET NULL"), nullable=True, index=True)
    source_capture_id = Column(String(36), ForeignKey("source_captures.id", ondelete="SET NULL"), nullable=True)
    url = Column(String(1000), nullable=False)
    domain = Column(String(255), nullable=False)
    page_title = Column(String(1000), nullable=True)
    language = Column(String(20), nullable=True)
    site_adapter = Column(String(100), nullable=False, default="generic-visible-selection-v1")
    extension_version = Column(String(50), nullable=True)
    selected_text = Column(Text, nullable=True)
    selected_html = Column(Text, nullable=True)
    selected_images = Column(JSON, nullable=False, default=list)
    # Asset ids/content hashes are stored alongside the original URL as
    # provenance.  The captured bytes, not a hotlinked supplier URL, are what
    # remains available to the project after a source URL expires.
    selected_asset_ids = Column(JSON, nullable=False, default=list)
    selection_scope = Column(JSON, nullable=False, default=dict)
    document_order = Column(JSON, nullable=False, default=list)
    sensitive_findings = Column(JSON, nullable=False, default=list)
    transfer_status = Column(String(30), nullable=False, default="previewed")
    captured_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class CommerceStoryBaselineRecord(Base):
    """Workspace-owned registration for one fixed Coupang-style regression pack."""

    __tablename__ = "commerce_story_baseline_records"
    __table_args__ = (
        UniqueConstraint("workspace_id", "baseline_key", name="uq_commerce_baseline_workspace_key"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    baseline_key = Column(String(50), nullable=False)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    reference_capture_asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    baseline_export_asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    evaluation_json = Column(JSON, nullable=False, default=dict)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    workspace = relationship("Workspace")
    project = relationship("ProductProject")
    reference_capture_asset = relationship("Asset", foreign_keys=[reference_capture_asset_id])
    baseline_export_asset = relationship("Asset", foreign_keys=[baseline_export_asset_id])
    user = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)  # project_created, file_uploaded, etc.
    entity_type = Column(String(100), nullable=False)  # project, asset, brand, etc.
    entity_id = Column(String(36), nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class JobStatus(Base):
    __tablename__ = "job_statuses"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id"), nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending, running, completed, failed
    error_message = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("ProductProject", back_populates="job_statuses")


class ProductFact(Base):
    __tablename__ = "product_facts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id"), nullable=False)
    fact_text = Column(Text, nullable=False)
    source_text = Column(Text, nullable=True)
    source_asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    # V2: extracted, source_confirmed, seller_confirmed, needs_review,
    # conflicted or rejected.  Legacy string values remain readable during
    # local-project migration.
    verification_status = Column(String(50), nullable=False, default="extracted")
    extraction_source = Column(String(50), nullable=True)  # manual_text, url, image, metadata
    provider = Column(String(50), nullable=True)
    model_name = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, nullable=False, default=True)
    risk_flags = Column(JSON, nullable=True)
    # Sprint 3 evidence-board fields.  `fact_text` remains the backwards-
    # compatible display sentence; these fields preserve the actual fact.
    field_key = Column(String(100), nullable=True, index=True)
    fact_category = Column(String(50), nullable=True)
    original_text = Column(Text, nullable=True)
    translated_text = Column(Text, nullable=True)
    normalized_value = Column(String(255), nullable=True)
    normalized_unit = Column(String(50), nullable=True)
    scope = Column(String(30), nullable=True, default="product")
    model_option = Column(String(255), nullable=True)
    extractor_version = Column(String(50), nullable=True)
    conflict_group_key = Column(String(255), nullable=True, index=True)
    seller_confirmed_at = Column(DateTime, nullable=True)
    seller_confirmed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("ProductProject", back_populates="facts")
    source_asset = relationship("Asset")
    histories = relationship("FactHistory", back_populates="fact", cascade="all, delete-orphan")
    evidences = relationship("FactEvidence", back_populates="fact", cascade="all, delete-orphan")


class FactHistory(Base):
    __tablename__ = "fact_histories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    fact_id = Column(String(36), ForeignKey("product_facts.id", ondelete="CASCADE"), nullable=False)
    previous_fact_text = Column(Text, nullable=False)
    previous_source_text = Column(Text, nullable=True)
    previous_source_asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    previous_verification_status = Column(String(50), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)
    event_type = Column(String(50), nullable=False, default="updated")
    previous_payload = Column(JSON, nullable=True)
    note = Column(Text, nullable=True)

    fact = relationship("ProductFact", back_populates="histories")
    user = relationship("User")
    previous_source_asset = relationship("Asset")


class FactEvidence(Base):
    """Immutable source reference for a normalized product fact."""
    __tablename__ = "fact_evidences"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    fact_id = Column(String(36), ForeignKey("product_facts.id", ondelete="CASCADE"), nullable=False)
    source_type = Column(String(30), nullable=False)  # seller_input, url, asset_ocr
    source_url = Column(String(1000), nullable=True)
    source_asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    ocr_block_index = Column(Integer, nullable=True)
    bbox = Column(JSON, nullable=True)
    original_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    extractor_version = Column(String(50), nullable=True)
    # Tie OCR evidence to the immutable inspection run that produced it.  The
    # asset itself can be re-inspected, so block index alone is not sufficient
    # audit context.
    inspection_id = Column(String(36), nullable=True, index=True)
    ocr_language = Column(String(20), nullable=True)
    ocr_provider = Column(String(50), nullable=True)
    ocr_model = Column(String(100), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    fact = relationship("ProductFact", back_populates="evidences")
    source_asset = relationship("Asset")


class PromptPack(Base):
    """Workspace-scoped logical category or channel prompt pack."""

    __tablename__ = "prompt_packs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "pack_type", "pack_key", "locale", name="uq_prompt_pack_scope"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    pack_type = Column(String(20), nullable=False)  # category, channel
    pack_key = Column(String(100), nullable=False)
    locale = Column(String(20), nullable=False, default="ko-KR")
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class PromptPackVersion(Base):
    """Immutable prompt pack body with an explicit reviewed lifecycle."""

    __tablename__ = "prompt_pack_versions"
    __table_args__ = (
        UniqueConstraint("pack_id", "version", name="uq_prompt_pack_version"),
        Index(
            "ix_prompt_pack_one_active",
            "pack_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    pack_id = Column(String(36), ForeignKey("prompt_packs.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False, default="draft_generated", index=True)
    content_json = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    evaluation_score = Column(Float, nullable=True)
    evaluation_dataset_version = Column(String(100), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    validated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    approved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    activated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    validated_at = Column(DateTime, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    deprecated_at = Column(DateTime, nullable=True)


class CategoryEvaluationReport(Base):
    __tablename__ = "category_evaluation_reports"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    dataset_version = Column(String(100), nullable=False)
    classifier_version = Column(String(100), nullable=False)
    input_hash = Column(String(64), nullable=False)
    output_hash = Column(String(64), nullable=False)
    accuracy = Column(Float, nullable=False)
    safe_fallback_rate = Column(Float, nullable=False, default=0.0)
    report_json = Column(JSON, nullable=False, default=dict)
    creator_run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class BrandKit(Base):
    __tablename__ = "brand_kits"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_brand_kit_workspace_name"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class BrandKitVersion(Base):
    __tablename__ = "brand_kit_versions"
    __table_args__ = (
        UniqueConstraint("brand_kit_id", "version", name="uq_brand_kit_version"),
        Index(
            "ix_brand_kit_one_workspace_active",
            "workspace_id",
            unique=True,
            postgresql_where=text("status = 'active' AND scope = 'workspace'"),
            sqlite_where=text("status = 'active' AND scope = 'workspace'"),
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    brand_kit_id = Column(String(36), ForeignKey("brand_kits.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="draft", index=True)
    scope = Column(String(20), nullable=False, default="workspace")  # workspace, project
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=True, index=True)
    logo_asset_ids = Column(JSON, nullable=False, default=list)
    font_asset_ids = Column(JSON, nullable=False, default=list)
    color_tokens = Column(JSON, nullable=False, default=dict)
    typography = Column(JSON, nullable=False, default=dict)
    tone_of_voice = Column(JSON, nullable=False, default=dict)
    forbidden_terms = Column(JSON, nullable=False, default=list)
    cta_rules = Column(JSON, nullable=False, default=dict)
    image_style = Column(JSON, nullable=False, default=dict)
    layout_rules = Column(JSON, nullable=False, default=dict)
    background_rules = Column(JSON, nullable=False, default=dict)
    watermark_policy = Column(JSON, nullable=False, default=dict)
    constraints = Column(JSON, nullable=False, default=dict)
    asset_rights = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    activated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    activated_at = Column(DateTime, nullable=True)
    deprecated_at = Column(DateTime, nullable=True)


class CompiledPromptArtifact(Base):
    __tablename__ = "compiled_prompt_artifacts"
    __table_args__ = (UniqueConstraint("run_id", name="uq_compiled_prompt_run"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    category_pack_version_id = Column(String(36), ForeignKey("prompt_pack_versions.id"), nullable=False)
    channel_pack_version_id = Column(String(36), ForeignKey("prompt_pack_versions.id"), nullable=False)
    brand_kit_version_id = Column(String(36), ForeignKey("brand_kit_versions.id"), nullable=True)
    category_pack_hash = Column(String(64), nullable=False)
    channel_pack_hash = Column(String(64), nullable=False)
    brand_kit_hash = Column(String(64), nullable=True)
    compiler_version = Column(String(100), nullable=False)
    input_hash = Column(String(64), nullable=False)
    output_hash = Column(String(64), nullable=False)
    compiled_json = Column(JSON, nullable=False, default=dict)
    creator_run_id = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ScenePromptVersion(Base):
    """Immutable, provider-neutral visual prompt compiled for one scene.

    Typography and final Korean copy are intentionally absent from the visual
    prompt.  They remain renderer-owned so image providers cannot rasterize or
    corrupt sales copy.
    """

    __tablename__ = "scene_prompt_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "scene_id", "version", name="uq_scene_prompt_project_scene_version"),
        Index("ix_scene_prompt_project_scene_status", "project_id", "scene_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    section_id = Column(String(100), nullable=False, index=True)
    scene_id = Column(String(100), nullable=False, index=True)
    scene_type = Column(String(80), nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="active", index=True)
    objective = Column(Text, nullable=False)
    approved_fact_ids = Column(JSON, nullable=False, default=list)
    reference_asset_ids = Column(JSON, nullable=False, default=list)
    reference_hash = Column(String(64), nullable=False, index=True)
    identity_constraints = Column(JSON, nullable=False, default=dict)
    composition = Column(JSON, nullable=False, default=dict)
    camera = Column(JSON, nullable=False, default=dict)
    lighting = Column(JSON, nullable=False, default=dict)
    background = Column(JSON, nullable=False, default=dict)
    palette = Column(JSON, nullable=False, default=dict)
    material = Column(JSON, nullable=False, default=dict)
    negative_constraints = Column(JSON, nullable=False, default=list)
    text_policy = Column(JSON, nullable=False, default=dict)
    rights_snapshot = Column(JSON, nullable=False, default=list)
    instruction_priority = Column(JSON, nullable=False, default=list)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    size = Column(String(50), nullable=False)
    quality = Column(String(30), nullable=False, default="standard")
    expected_cost = Column(Float, nullable=False, default=0.0)
    prompt_version = Column(String(100), nullable=False)
    prompt_hash = Column(String(64), nullable=False, index=True)
    input_hash = Column(String(64), nullable=False, index=True)
    brand_kit_version_id = Column(String(36), ForeignKey("brand_kit_versions.id", ondelete="SET NULL"), nullable=True)
    brand_kit_visual_hash = Column(String(64), nullable=True, index=True)
    canonical_prompt = Column(JSON, nullable=False, default=dict)
    seller_adjustment = Column(Text, nullable=True)
    supersedes_version_id = Column(String(36), ForeignKey("scene_prompt_versions.id", ondelete="SET NULL"), nullable=True)
    stale_reason = Column(String(100), nullable=True)
    stale_impact = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    stale_at = Column(DateTime, nullable=True)


class ReviewInputVersion(Base):
    """Immutable seller-provided review corpus; never a product-fact source."""

    __tablename__ = "review_input_versions"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_review_input_project_version"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    input_format = Column(String(20), nullable=False)  # paste, txt, csv, xlsx
    source_label = Column(String(255), nullable=True)
    source_asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True, index=True)
    source_metadata = Column(JSON, nullable=False, default=dict)
    consent_status = Column(String(30), nullable=False, default="unconfirmed")
    rights_status = Column(String(30), nullable=False, default="unverified")
    content_text = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    collected_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ReviewInsightVersion(Base):
    __tablename__ = "review_insight_versions"
    __table_args__ = (UniqueConstraint("review_input_version_id", "analyzer_version", name="uq_review_insight_analysis"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    review_input_version_id = Column(String(36), ForeignKey("review_input_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    analyzer_version = Column(String(100), nullable=False, default="lg7-review-v1")
    insights_json = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    fact_promotion_status = Column(String(30), nullable=False, default="blocked")
    usage_status = Column(String(30), nullable=False, default="available")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ReferenceInputVersion(Base):
    __tablename__ = "reference_input_versions"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_reference_input_project_version"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    input_kind = Column(String(20), nullable=False)  # url, image, pdf, text
    source_url = Column(Text, nullable=True)
    asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    content_text = Column(Text, nullable=True)
    source_metadata = Column(JSON, nullable=False, default=dict)
    rights_status = Column(String(30), nullable=False, default="unverified")
    usage_scope = Column(String(30), nullable=False, default="analysis_only")
    content_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    collected_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ReferenceInsightVersion(Base):
    __tablename__ = "reference_insight_versions"
    __table_args__ = (UniqueConstraint("reference_input_version_id", "analyzer_version", name="uq_reference_insight_analysis"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    reference_input_version_id = Column(String(36), ForeignKey("reference_input_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    analyzer_version = Column(String(100), nullable=False, default="lg7-reference-v1")
    abstract_signals_json = Column(JSON, nullable=False, default=dict)
    content_hash = Column(String(64), nullable=False, index=True)
    usage_status = Column(String(30), nullable=False, default="available")
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class SellerCreativeDirectionVersion(Base):
    __tablename__ = "seller_creative_direction_versions"
    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_creative_direction_project_version"),)

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    desired_mood = Column(JSON, nullable=False, default=list)
    target_audience = Column(Text, nullable=True)
    emphasis = Column(JSON, nullable=False, default=list)
    forbidden_scenes = Column(JSON, nullable=False, default=list)
    content_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ProductSourceSnapshotVersion(Base):
    """Immutable, captured product-source identity for LG-12I intake."""

    __tablename__ = "product_source_snapshot_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_product_source_snapshot_project_version"),
        UniqueConstraint("project_id", "canonical_hash", name="uq_product_source_snapshot_project_hash"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(80), nullable=False)
    input_mode = Column(String(40), nullable=False)
    parent_version_id = Column(String(36), ForeignKey("product_source_snapshot_versions.id", ondelete="RESTRICT"), nullable=True)
    parent_version = Column(Integer, nullable=True)
    parent_version_hash = Column(String(64), nullable=True)
    source_refs_json = Column(JSON, nullable=False, default=list)
    provenance_json = Column(JSON, nullable=False, default=dict)
    rights_json = Column(JSON, nullable=False, default=dict)
    source_fidelity_json = Column(JSON, nullable=False, default=dict)
    canonical_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ProductTruthVersion(Base):
    """Immutable normalized truth/provenance version derived from a source snapshot."""

    __tablename__ = "product_truth_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_product_truth_project_version"),
        UniqueConstraint("project_id", "canonical_hash", name="uq_product_truth_project_hash"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(80), nullable=False)
    source_snapshot_version_id = Column(String(36), ForeignKey("product_source_snapshot_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_snapshot_version = Column(Integer, nullable=False)
    source_snapshot_hash = Column(String(64), nullable=False)
    parent_version_id = Column(String(36), ForeignKey("product_truth_versions.id", ondelete="RESTRICT"), nullable=True)
    parent_version = Column(Integer, nullable=True)
    parent_version_hash = Column(String(64), nullable=True)
    fact_refs_json = Column(JSON, nullable=False, default=list)
    evidence_refs_json = Column(JSON, nullable=False, default=list)
    unknown_refs_json = Column(JSON, nullable=False, default=list)
    conflict_refs_json = Column(JSON, nullable=False, default=list)
    prohibited_inference_refs_json = Column(JSON, nullable=False, default=list)
    # Bounded normalized candidates/provenance only.  It intentionally never
    # stores source bodies, OCR documents, or image bytes.
    normalization_json = Column(JSON, nullable=False, default=dict)
    canonical_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class SellerConfirmationVersion(Base):
    """Immutable seller confirmation and rights decision over a truth version."""

    __tablename__ = "seller_confirmation_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_seller_confirmation_project_version"),
        UniqueConstraint("project_id", "canonical_hash", name="uq_seller_confirmation_project_hash"),
        # A single intake run may persist each immutable confirmation cycle
        # only once.  The service additionally locks the project/run scope so
        # the unique constraint is a durable race backstop, not the sole
        # lineage policy.
        UniqueConstraint(
            "creator_run_id", "truth_version_id", "confirmation_cycle",
            name="uq_seller_confirmation_run_truth_cycle",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(80), nullable=False)
    truth_version_id = Column(String(36), ForeignKey("product_truth_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    truth_version = Column(Integer, nullable=False)
    truth_version_hash = Column(String(64), nullable=False)
    parent_version_id = Column(String(36), ForeignKey("seller_confirmation_versions.id", ondelete="RESTRICT"), nullable=True)
    parent_version = Column(Integer, nullable=True)
    parent_version_hash = Column(String(64), nullable=True)
    answers_json = Column(JSON, nullable=False, default=list)
    # A confirmation cycle pins the deterministic clarification set that was
    # presented to the seller.  It stores only bounded question/answer
    # identities; source bodies stay in the source artifacts.
    confirmation_cycle = Column(Integer, nullable=False, default=1)
    clarification_refs_json = Column(JSON, nullable=False, default=list)
    unresolved_refs_json = Column(JSON, nullable=False, default=list)
    # The frozen seller-confirmation request and its submitted answer bundle
    # allow a lost public resume response to be replayed without reapplying a
    # later confirmation cycle.  They are immutable row content, not mutable
    # request-session state.
    resume_request_hash = Column(String(64), nullable=True, index=True)
    resume_answer_bundle_hash = Column(String(64), nullable=True)
    confirmed_fact_refs_json = Column(JSON, nullable=False, default=list)
    rejected_fact_refs_json = Column(JSON, nullable=False, default=list)
    unknown_fact_refs_json = Column(JSON, nullable=False, default=list)
    rights_confirmations_json = Column(JSON, nullable=False, default=list)
    canonical_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    confirmed_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class CommerceCreativeMasterVersion(Base):
    """Immutable reference index; it intentionally never copies large artifact bodies."""

    __tablename__ = "commerce_creative_master_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_commerce_creative_master_project_version"),
        UniqueConstraint("project_id", "canonical_hash", name="uq_commerce_creative_master_project_hash"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(80), nullable=False)
    parent_version_id = Column(String(36), ForeignKey("commerce_creative_master_versions.id", ondelete="RESTRICT"), nullable=True)
    parent_version = Column(Integer, nullable=True)
    parent_version_hash = Column(String(64), nullable=True)
    source_snapshot_version_id = Column(String(36), ForeignKey("product_source_snapshot_versions.id", ondelete="RESTRICT"), nullable=False)
    source_snapshot_version = Column(Integer, nullable=False)
    source_snapshot_hash = Column(String(64), nullable=False)
    truth_version_id = Column(String(36), ForeignKey("product_truth_versions.id", ondelete="RESTRICT"), nullable=False)
    truth_version = Column(Integer, nullable=False)
    truth_version_hash = Column(String(64), nullable=False)
    confirmation_version_id = Column(String(36), ForeignKey("seller_confirmation_versions.id", ondelete="RESTRICT"), nullable=False)
    confirmation_version = Column(Integer, nullable=False)
    confirmation_version_hash = Column(String(64), nullable=False)
    creative_brief_version_id = Column(String(36), ForeignKey("product_creative_brief_versions.id", ondelete="RESTRICT"), nullable=False)
    creative_brief_version = Column(Integer, nullable=False)
    creative_brief_hash = Column(String(64), nullable=False)
    brand_kit_version_id = Column(String(36), ForeignKey("brand_kit_versions.id", ondelete="RESTRICT"), nullable=False)
    brand_kit_version = Column(Integer, nullable=False)
    brand_kit_hash = Column(String(64), nullable=False)
    evidence_artifact_refs_json = Column(JSON, nullable=False, default=list)
    approved_fact_snapshot_ref_json = Column(JSON, nullable=False, default=dict)
    approved_asset_manifest_ref_json = Column(JSON, nullable=False, default=dict)
    copy_artifact_ref_json = Column(JSON, nullable=False, default=dict)
    page_plan_artifact_ref_json = Column(JSON, nullable=False, default=dict)
    target_channels = Column(JSON, nullable=False, default=list)
    downstream_output_refs_json = Column(JSON, nullable=False, default=list)
    canonical_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class QualityThresholdProfileVersion(Base):
    """Immutable, project-scoped threshold contract for frozen DetailPage QA."""

    __tablename__ = "quality_threshold_profile_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "canonical_hash", name="uq_quality_threshold_profile_project_hash"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(80), nullable=False)
    parent_profile_id = Column(String(36), ForeignKey("quality_threshold_profile_versions.id", ondelete="RESTRICT"), nullable=True)
    parent_profile_version = Column(Integer, nullable=True)
    parent_profile_hash = Column(String(64), nullable=True)
    applicable_artifact_type = Column(String(80), nullable=False)
    applicable_channels_json = Column(JSON, nullable=False, default=list)
    thresholds_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(40), nullable=False)
    effective_from = Column(String(80), nullable=False)
    canonical_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    def payload(self) -> dict:
        payload = {
            "profile_id": self.id, "profile_version": self.version, "schema_version": self.schema_version,
            "applicable_artifact_type": self.applicable_artifact_type,
            "applicable_channels": self.applicable_channels_json,
            **dict(self.thresholds_json or {}), "status": self.status, "effective_from": self.effective_from,
            "canonical_hash": self.canonical_hash,
        }
        if self.parent_profile_id:
            payload["parent_profile_ref"] = {
                "id": self.parent_profile_id, "version": self.parent_profile_version, "hash": self.parent_profile_hash,
            }
        return payload


class QualityAssessmentReportVersion(Base):
    """Immutable reference-only quality result over a frozen DetailPageVersion."""

    __tablename__ = "quality_assessment_report_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "canonical_hash", name="uq_quality_assessment_report_project_hash"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(80), nullable=False)
    evaluator_bundle_version = Column(String(100), nullable=False)
    target_detail_page_version_id = Column(String(36), ForeignKey("detail_page_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_artifact_version = Column(String(80), nullable=False)
    target_artifact_hash = Column(String(64), nullable=False)
    approved_asset_manifest_hash = Column(String(64), nullable=False)
    target_channels_json = Column(JSON, nullable=False, default=list)
    threshold_profile_id = Column(String(36), ForeignKey("quality_threshold_profile_versions.id", ondelete="RESTRICT"), nullable=False)
    threshold_profile_version = Column(Integer, nullable=False)
    threshold_profile_hash = Column(String(64), nullable=False)
    report_json = Column(JSON, nullable=False, default=dict)
    canonical_hash = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class QualityPromotionVersion(Base):
    """Immutable final-promotion authority for one LG-12 frozen page.

    The Quality Bar remains a deterministic projection of the immutable QA
    report.  This row pins that projection at the precise point a seller is
    allowed to use final/export surfaces, so a later child page cannot inherit
    an old PASS by accident.
    """

    __tablename__ = "quality_promotion_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "canonical_hash", name="uq_quality_promotion_project_hash"),
        UniqueConstraint(
            "project_id", "detail_page_version_id", "quality_bar_hash",
            name="uq_quality_promotion_page_bar",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    schema_version = Column(String(80), nullable=False)
    detail_page_version_id = Column(String(36), ForeignKey("detail_page_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    detail_page_schema_version = Column(String(80), nullable=False)
    detail_page_hash = Column(String(64), nullable=False)
    quality_report_id = Column(String(36), ForeignKey("quality_assessment_report_versions.id", ondelete="RESTRICT"), nullable=False)
    quality_report_version = Column(Integer, nullable=False)
    quality_report_hash = Column(String(64), nullable=False)
    quality_bar_result_id = Column(String(160), nullable=False)
    quality_bar_hash = Column(String(64), nullable=False)
    master_ref_json = Column(JSON, nullable=False, default=dict)
    page_plan_ref_json = Column(JSON, nullable=False, default=dict)
    brand_kit_ref_json = Column(JSON, nullable=False, default=dict)
    target_channels_json = Column(JSON, nullable=False, default=list)
    canonical_hash = Column(String(64), nullable=False, index=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class ProductCreativeBriefVersion(Base):
    """Immutable compiler result consumed by every downstream planning node."""

    __tablename__ = "product_creative_brief_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_product_creative_brief_version"),
        UniqueConstraint("run_id", "input_hash", name="uq_product_creative_brief_run_input"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    previous_version_id = Column(String(36), ForeignKey("product_creative_brief_versions.id"), nullable=True)
    fact_snapshot_id = Column(String(36), ForeignKey("fact_snapshots.id"), nullable=True)
    fact_snapshot_hash = Column(String(64), nullable=True)
    compiled_prompt_artifact_id = Column(String(36), ForeignKey("compiled_prompt_artifacts.id"), nullable=True)
    category_pack_version_id = Column(String(36), ForeignKey("prompt_pack_versions.id"), nullable=True)
    channel_pack_version_id = Column(String(36), ForeignKey("prompt_pack_versions.id"), nullable=True)
    brand_kit_version_id = Column(String(36), ForeignKey("brand_kit_versions.id"), nullable=True)
    brand_kit_hash = Column(String(64), nullable=True)
    creative_direction_version_id = Column(String(36), ForeignKey("seller_creative_direction_versions.id"), nullable=True)
    review_insight_version_ids = Column(JSON, nullable=False, default=list)
    reference_insight_version_ids = Column(JSON, nullable=False, default=list)
    approved_fact_ids = Column(JSON, nullable=False, default=list)
    compiler_version = Column(String(100), nullable=False, default="lg7-creative-brief-v1")
    input_hash = Column(String(64), nullable=False, index=True)
    output_hash = Column(String(64), nullable=False, index=True)
    brief_json = Column(JSON, nullable=False, default=dict)
    # LG-12I uses the established Creative Brief artifact, but pins the intake
    # lineage that compiled it.  The legacy LG-7 columns above remain readable
    # for historical briefs; LG-12I rows are identified by this explicit,
    # one-way Source -> Truth -> Confirmation contract.
    source_snapshot_version_id = Column(String(36), ForeignKey("product_source_snapshot_versions.id", ondelete="RESTRICT"), nullable=True, index=True)
    source_snapshot_version = Column(Integer, nullable=True)
    source_snapshot_hash = Column(String(64), nullable=True)
    truth_version_id = Column(String(36), ForeignKey("product_truth_versions.id", ondelete="RESTRICT"), nullable=True, index=True)
    truth_version = Column(Integer, nullable=True)
    truth_version_hash = Column(String(64), nullable=True)
    confirmation_version_id = Column(String(36), ForeignKey("seller_confirmation_versions.id", ondelete="RESTRICT"), nullable=True, index=True)
    confirmation_version = Column(Integer, nullable=True)
    confirmation_version_hash = Column(String(64), nullable=True)
    target_channels = Column(JSON, nullable=False, default=list)
    review_reference_refs_json = Column(JSON, nullable=False, default=list)
    confirmed_fact_refs_json = Column(JSON, nullable=False, default=list)
    usable_asset_refs_json = Column(JSON, nullable=False, default=list)
    prohibited_claim_refs_json = Column(JSON, nullable=False, default=list)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


class WorkflowGateEvent(Base):
    __tablename__ = "workflow_gate_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    gate_stage = Column(String(80), nullable=False)
    interaction_mode = Column(String(20), nullable=False)
    decision = Column(String(30), nullable=False)
    decision_source = Column(String(20), nullable=False)  # seller, quick_auto
    rationale = Column(Text, nullable=False)
    impact_json = Column(JSON, nullable=False, default=dict)
    checkpoint_id = Column(String(128), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

class FactSnapshot(Base):
    """Reproducible approved-facts snapshot taken immediately before generation."""
    __tablename__ = "fact_snapshots"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    purpose = Column(String(50), nullable=False, default="generation")
    snapshot_hash = Column(String(64), nullable=False, index=True)
    facts_json = Column(JSON, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    project = relationship("ProductProject")
    user = relationship("User")


class AiJobLog(Base):
    __tablename__ = "ai_job_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    task_type = Column(String(100), nullable=False)  # e.g., fact_extraction, compliance_check
    provider = Column(String(50), nullable=False)  # e.g., openai, anthropic, google
    model_name = Column(String(100), nullable=False)
    prompt_version = Column(String(50), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    estimated_cost = Column(Float, nullable=True)
    status = Column(String(50), nullable=False, default="pending")  # success, failed
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    project = relationship("ProductProject", back_populates="job_logs")


class GenerationJobRecord(Base):
    """Provider-neutral durable job audit for OCR and grounded copy work."""
    __tablename__ = "generation_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(String(100), nullable=False, unique=True, index=True)
    request_id = Column(String(100), nullable=False, unique=True, index=True)
    task_type = Column(String(30), nullable=False)  # ocr_candidate, grounded_copy
    scene_id = Column(String(100), nullable=True)
    asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    provider = Column(String(50), nullable=False)
    model_name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="draft")
    failure_category = Column(String(50), nullable=True)
    retryable = Column(Boolean, nullable=False, default=False)
    input_snapshot = Column(JSON, nullable=False, default=dict)
    input_snapshot_hash = Column(String(64), nullable=False, index=True)
    output_json = Column(JSON, nullable=False, default=dict)
    estimated_cost = Column(Float, nullable=True)
    actual_cost = Column(Float, nullable=True)
    usage_metadata = Column(JSON, nullable=False, default=dict)
    attempt_count = Column(Integer, nullable=False, default=1)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    workspace = relationship("Workspace")
    project = relationship("ProductProject")
    asset = relationship("Asset")
    user = relationship("User")


class ProductPage(Base):
    __tablename__ = "product_pages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    theme_color = Column(String(50), nullable=False, default="#3B82F6")
    font_family = Column(String(50), nullable=False, default="sans-serif")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("ProductProject", back_populates="pages")
    sections = relationship("PageSection", back_populates="page", cascade="all, delete-orphan", order_by="PageSection.sort_order")
    versions = relationship("PageVersion", back_populates="page", cascade="all, delete-orphan")
    published_pages = relationship("PublishedPage", back_populates="page", cascade="all, delete-orphan")


class PageSection(Base):
    __tablename__ = "page_sections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    page_id = Column(String(36), ForeignKey("product_pages.id", ondelete="CASCADE"), nullable=False)
    section_type = Column(String(100), nullable=False)  # header, features, specifications, faq, etc.
    title = Column(String(255), nullable=True)
    body_copy = Column(Text, nullable=True)
    associated_fact_ids = Column(JSON, nullable=True)  # list of fact UUIDs
    image_asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    visual_kind = Column(String(30), nullable=True)
    visual_payload = Column(JSON, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_visible = Column(Boolean, nullable=False, default=True)
    facts_stale = Column(Boolean, nullable=False, default=False)

    page = relationship("ProductPage", back_populates="sections")
    image_asset = relationship("Asset")

    @property
    def role(self):
        role_map = {
            "problem": "문제 제기",
            "hero": "메인 소구점 강조",
            "benefit_a": "소구점 A",
            "benefit_b": "소구점 B",
            "hero_reemphasize": "소구점 A 재강조",
            "benefits_summary": "소구점 B~D 정리",
            "overall_summary": "전체 요약",
            "product_info": "상품 정보",
            "target_customer": "타깃 고객",
            "features": "소구점 정리",
            "caution": "주의사항",
            "cta": "최종 CTA",
            "lifestyle_scene": "사용 장면",
            "comparison": "비교 포인트",
            "specifications": "구성품/스펙",
            "pre_purchase": "구매 전 확인사항",
            "product_information": "상품 정보",
        }
        return role_map.get(self.section_type, self.section_type)

    @property
    def headline(self):
        return self.title

    @property
    def body(self):
        return self.body_copy

    @property
    def evidence_fact_ids(self):
        return self.associated_fact_ids or []

    @property
    def visual_strategy(self):
        if self.visual_payload:
            return self.visual_payload.get("strategy")
        return None

    @property
    def editable(self):
        return True


class PageVersion(Base):
    __tablename__ = "page_versions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    page_id = Column(String(36), ForeignKey("product_pages.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False)
    page_data = Column(JSON, nullable=False)  # full schema backup
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    page = relationship("ProductPage", back_populates="versions")
    user = relationship("User")


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    preset_name = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="pending")  # pending, running, completed, failed
    error_message = Column(Text, nullable=True)
    zip_asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    output_images = Column(JSON, nullable=True)  # list of image URLs/paths
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    project = relationship("ProductProject", back_populates="export_jobs")
    zip_asset = relationship("Asset", foreign_keys=[zip_asset_id])
    user = relationship("User")


class FigmaExportJob(Base):
    __tablename__ = "figma_export_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    target_file_url = Column(Text, nullable=False)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(50), nullable=False, default="queued")  # queued, authenticating, rendering, completed, failed
    result_file_url = Column(Text, nullable=True)
    result_node_url = Column(Text, nullable=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    auth_url = Column(Text, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("ProductProject")
    workspace = relationship("Workspace")


class PublishedPage(Base):
    __tablename__ = "published_pages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id"), nullable=False)
    page_id = Column(String(36), ForeignKey("product_pages.id"), nullable=False)
    slug = Column(String(100), unique=True, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    external_store_url = Column(String(1000), nullable=True)
    config = Column(JSON, nullable=True)  # JSON config details
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("ProductProject", back_populates="published_pages")
    page = relationship("ProductPage", back_populates="published_pages")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(50), nullable=False, default="member")  # owner, admin, member, viewer
    joined_at = Column(DateTime, default=datetime.datetime.utcnow)

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="memberships")


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    email = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="member")
    status = Column(String(50), nullable=False, default="pending")  # pending, accepted, declined
    invited_by = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    workspace = relationship("Workspace", back_populates="invitations")
    inviter = relationship("User")


class DetailPageVersion(Base):
    __tablename__ = "detail_page_versions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    style_key = Column(String(50), nullable=False)
    sections_json = Column(JSON, nullable=False)
    is_final = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    project = relationship("ProductProject")

    @property
    def sections(self):
        if isinstance(self.sections_json, dict):
            return self.sections_json.get("sections", [])
        return self.sections_json



class ExportArtifact(Base):
    __tablename__ = "export_artifacts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    version_id = Column(String(36), ForeignKey("detail_page_versions.id", ondelete="CASCADE"), nullable=False)
    artifact_type = Column(String(50), nullable=False)  # long_vertical_image, section_images_zip
    file_path = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    project = relationship("ProductProject")
    version = relationship("DetailPageVersion")


class FigmaPluginExportTicket(Base):
    __tablename__ = "figma_plugin_export_tickets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    code_hash = Column(String(64), unique=True, nullable=False, index=True)
    payload_json = Column(JSON, nullable=False)
    asset_map_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="issued")
    expires_at = Column(DateTime, nullable=False)
    redeemed_at = Column(DateTime, nullable=True)
    session_token_hash = Column(String(64), nullable=True)
    session_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    project = relationship("ProductProject")
    workspace = relationship("Workspace")


class ImageGenerationJobRecord(Base):
    __tablename__ = "image_generation_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(String(100), nullable=False, unique=True)
    section_id = Column(String(100), nullable=False)
    role = Column(String(50), nullable=False)
    source_asset_ids = Column(JSON, nullable=True)  # List of asset IDs
    prompt = Column(Text, nullable=False)
    negative_prompt = Column(Text, nullable=True)
    preserve_product_identity = Column(Boolean, default=True)
    output_size = Column(String(50), default="1024x1024")
    cost_tier = Column(String(50), default="standard")
    status = Column(String(50), default="planned")  # planned, awaiting_cost_approval, generating, needs_review, approved, rejected, failed
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    output_asset_id = Column(String(36), ForeignKey("assets.id", ondelete="SET NULL"), nullable=True)
    error_code = Column(String(100), nullable=True)
    warnings = Column(JSON, nullable=True)  # List of warning strings
    # Sprint 5 audit trail.  These fields keep a reproducible generation
    # contract without treating an AI image as final before seller approval.
    input_snapshot = Column(JSON, nullable=False, default=dict)
    validation_result = Column(JSON, nullable=False, default=dict)
    estimated_cost = Column(Float, nullable=True)
    actual_cost = Column(Float, nullable=True)
    usage_metadata = Column(JSON, nullable=False, default=dict)
    seed = Column(String(100), nullable=True)
    # LG-5R: the durable provider contract. ``attempt_count`` above remains
    # the provider adapter retry counter; ``generation_attempt`` identifies a
    # seller-requested scene regeneration and therefore participates in the
    # external-call idempotency key.
    scene_id = Column(String(100), nullable=True, index=True)
    prompt_version = Column(String(100), nullable=True)
    prompt_hash = Column(String(64), nullable=True, index=True)
    reference_hash = Column(String(64), nullable=True, index=True)
    planning_hash = Column(String(64), nullable=True, index=True)
    input_hash = Column(String(64), nullable=True, index=True)
    generation_attempt = Column(Integer, nullable=False, default=1)
    idempotency_key = Column(String(64), nullable=True, unique=True, index=True)
    required_for_completion = Column(Boolean, nullable=False, default=True)
    supersedes_job_id = Column(String(100), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    scene_prompt_version_id = Column(
        String(36), ForeignKey("scene_prompt_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("ProductProject")
    output_asset = relationship("Asset")
    scene_prompt_version = relationship("ScenePromptVersion")
    outbox_record = relationship(
        "ImageGenerationOutboxRecord", back_populates="image_job", uselist=False, cascade="all, delete-orphan"
    )


class ImageGenerationCostApprovalRecord(Base):
    """Immutable cost-plan snapshot approved before any provider dispatch."""

    __tablename__ = "image_generation_cost_approvals"
    __table_args__ = (
        UniqueConstraint("run_id", "cost_plan_hash", name="uq_image_cost_run_plan"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id = Column(String(36), nullable=False, index=True)
    planning_hash = Column(String(64), nullable=False, index=True)
    cost_plan_hash = Column(String(64), nullable=False, index=True)
    provider = Column(String(50), nullable=False)
    model = Column(String(100), nullable=False)
    scene_count = Column(Integer, nullable=False)
    scene_costs = Column(JSON, nullable=False, default=list)
    total_estimated_cost = Column(Float, nullable=False, default=0.0)
    currency = Column(String(20), nullable=False, default="credit")
    status = Column(String(20), nullable=False, default="pending")
    approved_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    deferred_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    run = relationship("AgentRun", foreign_keys=[run_id])


class ImageGenerationOutboxRecord(Base):
    """DB-backed provider delivery with a recoverable lease and dead letter."""

    __tablename__ = "image_generation_outbox"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id = Column(String(36), nullable=False, index=True)
    image_job_id = Column(String(36), ForeignKey("image_generation_jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    job_id = Column(String(100), nullable=False, index=True)
    idempotency_key = Column(String(64), nullable=False, unique=True, index=True)
    provider_mode = Column(String(20), nullable=False, default="mock")
    status = Column(String(30), nullable=False, default="queued", index=True)
    lease_owner = Column(String(100), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True, index=True)
    available_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
    delivery_attempts = Column(Integer, nullable=False, default=0)
    max_delivery_attempts = Column(Integer, nullable=False, default=3)
    provider_dispatch_count = Column(Integer, nullable=False, default=0)
    completion_resume_count = Column(Integer, nullable=False, default=0)
    last_error_code = Column(String(100), nullable=True)
    last_error_message = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    dead_lettered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    image_job = relationship("ImageGenerationJobRecord", back_populates="outbox_record")
    run = relationship("AgentRun", foreign_keys=[run_id])


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String(36), ForeignKey("product_projects.id", ondelete="CASCADE"), nullable=False)
    mode = Column(String(20), nullable=False, default="mock")
    status = Column(String(50), nullable=False, default="created")
    current_stage = Column(String(80), nullable=False, default="intake")
    input_snapshot = Column(JSON, nullable=False, default=dict)
    outputs_json = Column(JSON, nullable=False, default=dict)
    cost_approval_status = Column(String(50), nullable=False, default="not_required")
    estimated_cost = Column(Float, nullable=True)
    actual_cost = Column(Float, nullable=True)
    provider_trace = Column(JSON, nullable=False, default=list)
    error_log = Column(JSON, nullable=False, default=list)
    # LG-1: one durable LangGraph thread per AgentRun. The thread ID is
    # deliberately identical to ``id`` and is persisted for auditing and
    # restart/recovery checks.
    graph_thread_id = Column(String(36), nullable=True, unique=True, index=True)
    graph_checkpoint_id = Column(String(128), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    project = relationship("ProductProject")
    workspace = relationship("Workspace")
    user = relationship("User")
    steps = relationship("AgentRunStep", back_populates="run", cascade="all, delete-orphan")


class AgentRunStep(Base):
    __tablename__ = "agent_run_steps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(80), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    input_json = Column(JSON, nullable=False, default=dict)
    output_json = Column(JSON, nullable=False, default=dict)
    provider = Column(String(50), nullable=True)
    model = Column(String(100), nullable=True)
    prompt_version = Column(String(100), nullable=True)
    token_usage = Column(JSON, nullable=True)
    estimated_cost = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    run = relationship("AgentRun", back_populates="steps")


_LG12I_IMMUTABLE_VERSION_MODELS = (
    ProductSourceSnapshotVersion,
    ProductTruthVersion,
    SellerConfirmationVersion,
    CommerceCreativeMasterVersion,
    ProductCreativeBriefVersion,
    QualityThresholdProfileVersion,
    QualityAssessmentReportVersion,
    QualityPromotionVersion,
)


def _reject_lg12i_version_mutation(_mapper, _connection, _target) -> None:
    raise ValueError("LG-12I intake and Commerce Creative Master versions are immutable.")


for _lg12i_model in _LG12I_IMMUTABLE_VERSION_MODELS:
    event.listen(_lg12i_model, "before_update", _reject_lg12i_version_mutation)
    event.listen(_lg12i_model, "before_delete", _reject_lg12i_version_mutation)

    # PostgreSQL is protected by the checked-in migration trigger. The SQLite
    # mirror keeps local/test databases equally immutable and lets Core/SQL
    # paths exercise the same durable contract instead of relying on mapper
    # events alone.
    for _operation in ("UPDATE", "DELETE"):
        event.listen(
            _lg12i_model.__table__,
            "after_create",
            DDL(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{_lg12i_model.__tablename__}_{_operation.lower()}_immutable
                BEFORE {_operation} ON {_lg12i_model.__tablename__}
                BEGIN
                    SELECT RAISE(ABORT, 'LG12I_IMMUTABLE_VERSION: {_lg12i_model.__tablename__} is immutable');
                END
                """
            ).execute_if(dialect="sqlite"),
        )

