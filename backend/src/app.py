import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from src.config import settings
from src.db.database import engine, Base, ensure_runtime_schema_compatibility
from src.api.projects import router as projects_router
from src.api.files import router as files_router
from src.api.facts import router as facts_router
from src.api.ai import router as ai_router
from src.api.pages import router as pages_router
from src.api.exports import router as exports_router
from src.api.publications import router as publications_router
from src.api.operations import router as operations_router
from src.api.brands import router as brands_router
from src.api.workspaces import router as workspaces_router
from src.api.agent_runs import router as agent_runs_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    try:
        Base.metadata.create_all(bind=engine)
        ensure_runtime_schema_compatibility()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to initialize PostgreSQL database during startup: {e}")
    yield
    # Shutdown / cleanup if needed
    pass


app = FastAPI(
    title="Sellform Core API",
    description="Backend API for Sellform Product Content Studio",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3100",
        "http://127.0.0.1:3100",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from src.api.figma_plugin import router as figma_plugin_router
from src.api.image_generation import router as image_generation_router
from src.api.marketplaces import router as marketplaces_router

# Include API Routers
app.include_router(projects_router, prefix="/api/v1")
app.include_router(files_router, prefix="/api/v1")
app.include_router(facts_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(pages_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")
app.include_router(publications_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(brands_router, prefix="/api/v1")
app.include_router(workspaces_router, prefix="/api/v1")
app.include_router(figma_plugin_router, prefix="/api/v1")
app.include_router(image_generation_router, prefix="/api/v1")
app.include_router(marketplaces_router, prefix="/api/v1")
app.include_router(agent_runs_router, prefix="/api")


# Mount Static Uploads Folder
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


@app.get("/")
def read_root():
    return {"status": "running", "service": "Sellform Core API"}
