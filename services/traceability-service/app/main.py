from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.api import documents, events, health
from app.api.errors import register_error_handlers
from app.api.health import SERVICE_NAME
from app.consumer import InvoiceIssuedConsumer, create_redis
from app.db import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Read the `invoice.issued` stream while the application is running.

    FastAPI runs this on start (up to the `yield`) and on stop (after it). The tests do not
    start the lifespan, so they do not need a Redis unless they ask for one on purpose.
    """
    consumer = InvoiceIssuedConsumer(create_redis(), lambda: Session(get_engine()))
    consumer.start()
    yield
    consumer.stop()


app = FastAPI(title=SERVICE_NAME, version="0.1.0", lifespan=lifespan)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(events.router)
app.include_router(documents.router)
