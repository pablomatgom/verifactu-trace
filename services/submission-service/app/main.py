from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.aeat import get_aeat
from app.api import health, submissions
from app.api.errors import register_error_handlers
from app.api.health import SERVICE_NAME
from app.config import max_attempts, retry_base_seconds
from app.consumer import InvoiceIssuedConsumer, create_redis
from app.db import get_engine
from app.sender import SubmissionSender
from app.services.retry import RetryPolicy


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the two background workers while the application is running.

    The consumer registers a submission for each invoice that is issued, and the sender sends the
    submissions that are due and retries the failed ones. FastAPI runs this on start (up to the
    `yield`) and on stop (after it). The tests do not start the lifespan, so they need neither
    Redis nor the workers unless they ask for them on purpose.
    """
    consumer = InvoiceIssuedConsumer(create_redis(), lambda: Session(get_engine()))
    sender = SubmissionSender(
        lambda: Session(get_engine()),
        get_aeat(),
        RetryPolicy(max_attempts(), retry_base_seconds()),
    )
    consumer.start()
    sender.start()
    yield
    sender.stop()
    consumer.stop()


app = FastAPI(title=SERVICE_NAME, version="0.1.0", lifespan=lifespan)

register_error_handlers(app)

app.include_router(health.router)
app.include_router(submissions.router)
