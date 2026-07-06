import sys
import os
import tempfile
import uuid
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from src.app import app
from src.db.database import Base, get_db
from src.db.models import User, Workspace, Brand, ProductProject, Asset, ProductPage, PageSection, ProductFact, PageVersion, AuditLog, JobStatus, AiJobLog, ExportJob, PublishedPage, FigmaExportJob, ImageGenerationJobRecord
from src.config import settings

# Prevent real API calls during tests by clearing API keys.
# Individual tests that verify AI integration will monkeypatch these values.
settings.OPENAI_API_KEY = None
settings.GEMINI_API_KEY = None
settings.ANTHROPIC_API_KEY = None
settings.SELLFORM_FIGMA_PLUGIN_TICKET_SECRET = "test-only-figma-plugin-secret-32-chars"

# Setup a clean temporary SQLite database for testing.
#
# Windows development environments can fail with `disk I/O error` when SQLite
# creates rollback journal files in the workspace. Use the OS temp directory
# instead of the repository root so background-task sessions can still share the
# same database file without touching locked workspace journals.
TEST_DB_PATH = os.path.join(
    tempfile.gettempdir(),
    f"sellform_test_{os.getpid()}_{uuid.uuid4().hex}.db",
)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{TEST_DB_PATH}"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _configure_test_sqlite_connection(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=OFF")
    cursor.close()

TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session(monkeypatch):
    # Generate unique SQLite database file path for this test function.
    db_fd, db_path = tempfile.mkstemp(suffix=".db", prefix="sellform_test_")
    os.close(db_fd)
    
    db_url = f"sqlite:///{db_path}"
    fn_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    
    @event.listens_for(fn_engine, "connect")
    def _configure_test_sqlite_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=OFF")
        cursor.close()
        
    import src.db.database
    src.db.database.SessionLocal.configure(bind=fn_engine)
    monkeypatch.setattr(src.db.database, "engine", fn_engine)
    
    Base.metadata.create_all(bind=fn_engine)
    db = src.db.database.SessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=fn_engine)
        fn_engine.dispose()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except Exception:
                pass


@pytest.fixture(scope="function")
def testing_session_local(db_session):
    import src.db.database
    return src.db.database.SessionLocal


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
