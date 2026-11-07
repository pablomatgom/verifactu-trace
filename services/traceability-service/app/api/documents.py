import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.events import (
    ChainDocument,
    ChainVerificationRead,
    DocumentChainRead,
    EventHistory,
    EventRead,
)
from app.db import get_session
from app.documents_client import DocumentClient, get_document_client
from app.services import chain_service, event_service, verification

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


@router.get(
    "/{invoice_id}/chain",
    summary="Get the documentary chain of an invoice",
    response_description="The order, the delivery note and the invoice, in that order.",
    responses={
        404: error_response("There is no invoice with that id (code INVOICE_NOT_FOUND)."),
        422: error_response("The identifier is not a valid UUID (code VALIDATION_ERROR)."),
        502: error_response(
            "document-service returned documents that do not form a chain (code INCONSISTENT_CHAIN)."
        ),
        503: error_response(
            "document-service cannot be reached (code DOCUMENT_SERVICE_UNAVAILABLE)."
        ),
    },
)
def get_chain(
    invoice_id: uuid.UUID, client: Annotated[DocumentClient, Depends(get_document_client)]
) -> DocumentChainRead:
    """Get the documents an invoice comes from: its order, its delivery note and itself.

    They are listed in the order they were made. The chain is rebuilt from the references between
    the documents, starting at the invoice and following each one to the document it comes from,
    which document-service holds: if it is down, this endpoint answers 503. An id that is not an
    invoice, even if it is another kind of document, is a 404.
    """
    return DocumentChainRead(
        invoice_id=invoice_id,
        chain=[
            ChainDocument(
                type=document.type,
                id=document.id,
                number=document.number,
                issue_date=document.issue_date,
            )
            for document in chain_service.get_chain(client, invoice_id)
        ],
    )
