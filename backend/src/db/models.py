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
    Boolean
)
from sqlalchemy.orm import relationship
from src.db.database import Base


def generate_uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)

    workspaces = relationship("Workspace", back_populates="owner")
    memberships = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")


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
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    workspace = relationship("Workspace", back_populates="projects")
    brand = relationship("Brand", back_populates="projects")
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")
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
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    mime_type = Column(String(100), nullable=False)
    file_size = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    source_asset_id = Column(String(36), ForeignKey("assets.id"), nullable=True)
    cutout_status = Column(String(50), nullable=True)
    background_removed = Column(Boolean, default=False)
    product_identity_preserved = Column(Boolean, default=True)

    project = relationship("ProductProject", back_populates="assets")


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
    verification_status = Column(String(50), nullable=False, default="unknown")  # unknown, confirmed, needs_revision
    extraction_source = Column(String(50), nullable=True)  # manual_text, url, image, metadata
    provider = Column(String(50), nullable=True)
    model_name = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=True)
    needs_review = Column(Boolean, nullable=False, default=True)
    risk_flags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("ProductProject", back_populates="facts")
    source_asset = relationship("Asset")
    histories = relationship("FactHistory", back_populates="fact", cascade="all, delete-orphan")


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

    fact = relationship("ProductFact", back_populates="histories")
    user = relationship("User")
    previous_source_asset = relationship("Asset")


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
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    project = relationship("ProductProject")
    output_asset = relationship("Asset")


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

