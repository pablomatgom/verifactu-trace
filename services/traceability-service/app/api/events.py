from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.events import EventCreate, EventRead
from app.db import get_session
from app.services import event_service
from app.services.event_service import EventData

router = APIRouter(prefix="/api/v1/traceability/events", tags=["events"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Record an event",
    response_description="The event, with its sequence and the hashes that chain it.",
    responses={422: error_response("The request is not valid (code VALIDATION_ERROR).")},
)
def create_event(body: EventCreate, session: Annotated[Session, Depends(get_session)]) -> EventRead:
    """Record an event at the end of the chain of its document.

    The server assigns the id, the `sequence` (1 for the first event of the document, then
    correlative) and the hashes. Events of the same document are chained in the order they are
    recorded. This endpoint is internal: the events normally arrive from the Redis streams.
    """
    event = event_service.record_event(
        session,
        EventData(
            document_id=body.document_id,
            event_type=body.event_type,
            occurred_at=body.occurred_at or datetime.now(UTC),
            payload=body.payload,
        ),
    )
    # Build the response while the session is still open.
    return EventRead.model_validate(event, from_attributes=True)
