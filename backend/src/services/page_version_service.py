import uuid
import datetime
from sqlalchemy.orm import Session
from src.db.models import DetailPageVersion

# Fallback for tests not passing db
_in_memory_versions = {}

class InMemoryDetailPageVersion:
    def __init__(self, project_id, name, sections, style_key):
        self.id = str(uuid.uuid4())
        self.project_id = project_id
        self.name = name
        self.style_key = style_key
        self.sections_json = sections
        self.is_final = False
        self.created_at = datetime.datetime.utcnow()

    @property
    def sections(self):
        return self.sections_json


def create_page_version(project_id: str, name: str, sections: list[dict], style_key: str, db: Session = None):
    if db is not None:
        # Clear existing version first if needed or just add new
        version = DetailPageVersion(
            project_id=project_id,
            name=name,
            style_key=style_key,
            sections_json=sections,
            is_final=False
        )
        db.add(version)
        db.commit()
        db.refresh(version)
        return version
    else:
        version = InMemoryDetailPageVersion(project_id, name, sections, style_key)
        _in_memory_versions[version.id] = version
        return version


def restore_page_version(version_id: str, db: Session = None):
    if db is not None:
        version = db.query(DetailPageVersion).filter(DetailPageVersion.id == version_id).first()
        return version
    else:
        return _in_memory_versions.get(version_id)


def mark_final_version(version_id: str, db: Session = None):
    if db is not None:
        version = db.query(DetailPageVersion).filter(DetailPageVersion.id == version_id).first()
        if version:
            db.query(DetailPageVersion).filter(
                DetailPageVersion.project_id == version.project_id,
                DetailPageVersion.id != version_id
            ).update({"is_final": False})
            version.is_final = True
            db.commit()
            db.refresh(version)
        return version
    else:
        version = _in_memory_versions.get(version_id)
        if version:
            for v in _in_memory_versions.values():
                if v.project_id == version.project_id:
                    v.is_final = False
            version.is_final = True
        return version


def list_page_versions(project_id: str, db: Session = None):
    if db is not None:
        return db.query(DetailPageVersion).filter(DetailPageVersion.project_id == project_id).all()
    else:
        return [v for v in _in_memory_versions.values() if v.project_id == project_id]
