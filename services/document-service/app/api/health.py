import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session

SERVICE_NAME = "document-service"

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    """Report whether the service is running and can reach its database (200), or not (503)."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        # The response only says "database"; the log keeps the real cause for whoever debugs it.
        logger.warning("Database health check failed", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable", "service": SERVICE_NAME, "detail": "database"}
    return {"status": "ok", "service": SERVICE_NAME}
