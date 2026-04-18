from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(title="Online Cinema")


@app.get("/")
def read_root():
    return {"message": "Hello World", "db_url": settings.DATABASE_URL}
