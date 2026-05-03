import logging

from fastapi import FastAPI

from core.config import settings
from routes import accounts_router, movies_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Online Cinema", description="Description of project")

api_version_prefix = "/api/v1"

app.include_router(
    accounts_router, prefix=f"{api_version_prefix}/accounts", tags=["accounts"]
)
app.include_router(
    movies_router, prefix=f"{api_version_prefix}/movies", tags=["movies"]
)


@app.on_event("startup")
async def startup_event():
    logger.info("Application is starting up...")
    logger.info(f"Using storage endpoint: {settings.S3_STORAGE_HOST}")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application is shutting down...")
