import asyncio
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
from src.api.graph_runs import router as graph_runs_router
from src.api.auth_routes import router as auth_router
from src.api.prompt_intelligence import router as prompt_intelligence_router
from src.api.brand_kits import router as brand_kits_router
from src.api.creative_briefs import router as creative_briefs_router
from src.api.quality_promotion import router as quality_promotion_router
from src.api.social_kit import router as social_kit_router
from src.api.video import router as video_router



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    try:
        Base.metadata.create_all(bind=engine)
        ensure_runtime_schema_compatibility()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Failed to initialize PostgreSQL database during startup: {e}")
    worker_stop: asyncio.Event | None = None
    worker_task: asyncio.Task | None = None
    if settings.SELLFORM_IMAGE_WORKER_ENABLED:
        from src.db.database import SessionLocal
        from src.services.image_generation_worker import image_worker_poller, recover_expired_image_work

        recovery_db = SessionLocal()
        try:
            recover_expired_image_work(recovery_db)
        finally:
            recovery_db.close()
        worker_stop = asyncio.Event()
        worker_task = asyncio.create_task(image_worker_poller(worker_stop), name="sellform-durable-image-worker")
    try:
        yield
    finally:
        if worker_stop is not None:
            worker_stop.set()
        if worker_task is not None:
            await worker_task


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
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
    ],
    # The local unpacked extension has a different chrome-extension:// origin.
    # It is still limited by its activeTab permission and an explicit short-lived
    # connection token; no broad host permission is granted to the extension.
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from src.api.figma_plugin import router as figma_plugin_router
from src.api.image_generation import router as image_generation_router
from src.api.storyboard_image_jobs import router as storyboard_image_jobs_router
from src.api.marketplaces import router as marketplaces_router
from src.api.browser_extension import router as browser_extension_router

# Include API Routers
app.include_router(auth_router, prefix="/api/v1")
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
app.include_router(storyboard_image_jobs_router, prefix="/api/v1")
app.include_router(marketplaces_router, prefix="/api/v1")
app.include_router(browser_extension_router, prefix="/api/v1")
app.include_router(agent_runs_router, prefix="/api")
app.include_router(graph_runs_router, prefix="/api/v1")
app.include_router(prompt_intelligence_router, prefix="/api/v1")
app.include_router(brand_kits_router, prefix="/api/v1")
app.include_router(creative_briefs_router, prefix="/api/v1")
app.include_router(quality_promotion_router, prefix="/api/v1")
app.include_router(social_kit_router, prefix="/api/v1")
app.include_router(video_router, prefix="/api/v1")


# Mount Static Uploads Folder
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


@app.get("/")
def read_root():
    return {"status": "running", "service": "Sellform Core API"}
