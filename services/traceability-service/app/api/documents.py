import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.events import ChainVerificationRead, EventHistory, EventRead
from app.db import get_session
from app.services import event_service, verification

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


@router.get(
    "/{document_id}/verification",
    summary="Verify the chain of a document",
    response_description="Whether the chain of events is intact and, if not, where it breaks.",
    responses={
        404: error_response("The document has no events (code EVENTS_NOT_FOUND)."),
        422: error_response("The identifier is not a valid UUID (code VALIDATION_ERROR)."),
    },
)
def verify_chain(
    document_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> ChainVerificationRead:
    """Check that nobody has tampered with the events of a document.

    The hashes of the chain are recomputed in order, from the first event. If every event holds,
    `valid` is true. Otherwise `valid` is false and `first_invalid_sequence` is the `sequence` of
    the first event that fails: one whose data was changed, one that was replaced, or the one
    after an event that was deleted. Events after it are not reported, since they are no longer
    trustworthy.

    A chain that was truncated at its end, by deleting its last events, cannot be told from a
    shorter one: no later event vouches for them. A document that has no events gets a 404.
    """
    result = verification.verify_document(session, document_id)
    return ChainVerificationRead(
        document_id=result.document_id,
        valid=result.valid,
        events_checked=result.events_checked,
        first_invalid_sequence=result.first_invalid_sequence,
    )
