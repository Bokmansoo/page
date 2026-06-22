from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.db.database import engine, Base
from src.api.projects import router as projects_router
from src.api.files import router as files_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown / cleanup if needed
    pass


app = FastAPI(
    title="Sellform Core API",
    description="Backend API for Sellform Product Content Studio",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(projects_router, prefix="/api/v1")
app.include_router(files_router, prefix="/api/v1")


@app.get("/")
def read_root():
    return {"status": "running", "service": "Sellform Core API"}
