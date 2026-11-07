import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.events import EventHistory, EventRead
from app.db import get_session
from app.services import event_service

router = APIRouter(prefix="/api/v1/traceability/documents", tags=["documents"])


@router.get(
    "/{document_id}/events",
    summary="Get the history of a document",
    response_description="The events of the document, ordered by sequence.",
    responses={
        404: error_response("The document has no events (code EVENTS_NOT_FOUND)."),
        422: error_response("The identifier is not a valid UUID (code VALIDATION_ERROR)."),
    },
)
def get_history(
    document_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> EventHistory:
    """Get every event recorded for a document, ordered by `sequence`.

    A document that has no events gets a 404: this service only knows a document through its
    events, so it cannot tell a document that does not exist from one that nothing has happened
    to yet.
    """
    events = event_service.get_history(session, document_id)
    # Build the response while the session is still open.
    return EventHistory(
        document_id=document_id,
        events=[EventRead.model_validate(event, from_attributes=True) for event in events],
    )
