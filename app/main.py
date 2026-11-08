from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.models.database import init_db, SessionLocal
from app.api.routes import router as api_router
from app.services.search_service import search_service
from app.core.logging import logger


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Initializing database tables...")
    init_db()
    db = SessionLocal()
    try:
        # The vector index lives in memory, so rebuild it from stored page text on boot
        indexed = search_service.rebuild_index(db)
        logger.info(f"Database initialized. Search index rebuilt with {indexed} documents.")
    finally:
        db.close()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Enterprise-grade AI-Powered Document Intelligence System for multi-format financial document extraction, validation, and cross-document reconciliation.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
