import datetime
import uuid
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON
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


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)

    owner = relationship("User", back_populates="workspaces")
    brands = relationship("Brand", back_populates="workspace")
    projects = relationship("ProductProject", back_populates="workspace")


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
    raw_input_url = Column(String(1000), nullable=True)
    raw_input_text = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    workspace = relationship("Workspace", back_populates="projects")
    brand = relationship("Brand", back_populates="projects")
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")
    job_statuses = relationship("JobStatus", back_populates="project", cascade="all, delete-orphan")


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
