from fastapi import FastAPI
from app.core.config import settings

from app.routes import accounts_router

app = FastAPI(title="Online Cinema",
    description="Description of project")

api_version_prefix = "/api/v1"

app.include_router(accounts_router, prefix=f"{api_version_prefix}/accounts", tags=["accounts"])

@app.get("/")
def read_root():
    return {"message": "Hello World", "db_url": settings.DATABASE_URL}
