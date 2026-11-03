from fastapi import FastAPI

from app.api import delivery_notes, health, orders
from app.api.errors import register_error_handlers
from app.api.health import SERVICE_NAME

app = FastAPI(title=SERVICE_NAME, version="0.1.0")

register_error_handlers(app)

app.include_router(health.router)
app.include_router(orders.router)
app.include_router(delivery_notes.router)
