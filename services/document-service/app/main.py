from fastapi import FastAPI

from app.api import health
from app.api.health import SERVICE_NAME

app = FastAPI(title=SERVICE_NAME, version="0.1.0")

app.include_router(health.router)
