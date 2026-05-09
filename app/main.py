import logging

from fastapi import FastAPI

from app.core.config import settings
from app.routes import (
    accounts_router,
    movies_user_router,
    movies_admin_router,
    carts_router,
    orders_router,
    payments_router,
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

app = FastAPI(title="Online Cinema", description="Description of project")

api_version_prefix = "/api/v1"

app.include_router(
    accounts_router, prefix=f"{api_version_prefix}/accounts", tags=["accounts"]
)
app.include_router(
    movies_user_router, prefix=f"{api_version_prefix}/movies", tags=["movies_user"]
)
app.include_router(
    movies_admin_router,
    prefix=f"{api_version_prefix}/admin/movies",
    tags=["movies_admin"],
)
app.include_router(
    carts_router,
    prefix=f"{api_version_prefix}/cart",
    tags=["carts"],
)
app.include_router(
    orders_router,
    prefix=f"{api_version_prefix}/order",
    tags=["orders"],
)
app.include_router(
    payments_router,
    prefix=f"{api_version_prefix}/payment",
    tags=["payments"],
)


@app.on_event("startup")
async def startup_event():
    logger.info("Application is starting up...")
    logger.info(f"Using storage endpoint: {settings.S3_STORAGE_HOST}")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application is shutting down...")
