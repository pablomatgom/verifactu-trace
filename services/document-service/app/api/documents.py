import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.documents import DocumentLineOut, DocumentRead
from app.api.schemas.orders import CustomerOut
from app.db import get_session
from app.models import Document
from app.services import document_service

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def _to_read(document: Document) -> DocumentRead:
    return DocumentRead(
        id=document.id,
        type=document.type,
        number=document.number,
        status=document.status,
        issue_date=document.issue_date,
        parent_id=document.parent_id,
        customer=CustomerOut(name=document.customer_name, tax_id=document.customer_tax_id),
        lines=[
            DocumentLineOut(
                position=line.position,
                source_line=line.source_line.position if line.source_line else None,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
            )
            for line in document.lines
        ],
        total_net=document.total_net,
        total_vat=document.total_vat,
        total=document.total,
    )


@router.get(
    "/{document_id}",
    summary="Get a document",
    response_description="The document, with its lines and amounts.",
    responses={
        404: error_response("The document does not exist (code DOCUMENT_NOT_FOUND)."),
        422: error_response("The identifier is not a valid UUID (code VALIDATION_ERROR)."),
    },
)
def get_document(
    document_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> DocumentRead:
    """Get an order, a delivery note or an invoice by its identifier.

    The three kinds of document come in the same shape, and `type` says which one it is.
    `parent_id` points to the previous document of the chain, so a client can walk it from an
    invoice back to its order. A malformed identifier is a 422.
    """
    # Construct the response here while the session is still active to
    # avoid database errors when accessing lazy-loaded relationships later.
    return _to_read(document_service.get_document(session, document_id))
