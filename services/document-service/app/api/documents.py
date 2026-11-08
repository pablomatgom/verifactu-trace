import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.schemas.common import error_response
from app.api.schemas.documents import (
    DocumentLineOut,
    DocumentPageRead,
    DocumentRead,
    DocumentSummary,
)
from app.api.schemas.orders import CustomerOut
from app.db import get_session
from app.models import Document, DocumentStatus, DocumentType
from app.repositories.document_repository import DocumentFilters
from app.services import document_service

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

MAX_PAGE_SIZE = 100


def _to_summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        type=document.type,
        number=document.number,
        status=document.status,
        issue_date=document.issue_date,
        parent_id=document.parent_id,
        customer=CustomerOut(name=document.customer_name, tax_id=document.customer_tax_id),
        total_net=document.total_net,
        total_vat=document.total_vat,
        total=document.total,
    )


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
    "",
    summary="List documents",
    response_description="One page of documents, the newest first.",
    responses={
        422: error_response(
            "A parameter is not valid (VALIDATION_ERROR), or the start date is later than the "
            "end date (INVALID_DATE_RANGE)."
        )
    },
)
def list_documents(
    session: Annotated[Session, Depends(get_session)],
    type: Annotated[
        DocumentType | None, Query(description="Only the documents of this kind.")
    ] = None,
    customer: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description=(
                "Only the documents of a customer: the text is their tax id, or part of their "
                "name (without distinguishing capitals)."
            ),
        ),
    ] = None,
    series: Annotated[
        str | None,
        Query(min_length=1, max_length=10, description="Only the documents of this series."),
    ] = None,
    status: Annotated[
        DocumentStatus | None, Query(description="Only the documents in this state.")
    ] = None,
    date_from: Annotated[
        date | None,
        Query(alias="from", description="Only the documents issued on this date or later."),
    ] = None,
    date_to: Annotated[
        date | None,
        Query(alias="to", description="Only the documents issued on this date or earlier."),
    ] = None,
    page: Annotated[int, Query(ge=1, description="Number of the page, starting at 1.")] = 1,
    size: Annotated[
        int, Query(ge=1, le=MAX_PAGE_SIZE, description="Documents per page, up to 100.")
    ] = 20,
) -> DocumentPageRead:
    """List orders, delivery notes and invoices, narrowed by the filters that are given.

    The filters add up: a document must meet all of them. The newest come first, and the page is
    asked for with `page` and `size`. The answer carries `total`, the number of documents that
    meet the filters in all the pages, so a client knows how many pages there are. A page past
    the end is empty.
    """
    result = document_service.list_documents(
        session,
        DocumentFilters(
            type=type,
            customer=customer,
            series=series,
            status=status,
            date_from=date_from,
            date_to=date_to,
        ),
        page,
        size,
    )
    return DocumentPageRead(
        items=[_to_summary(document) for document in result.items],
        page=result.page,
        size=result.size,
        total=result.total,
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


@router.post(
    "/{document_id}/cancel",
    summary="Cancel an order or a delivery note",
    response_description="The document, now CANCELLED.",
    responses={
        404: error_response("The document does not exist (code DOCUMENT_NOT_FOUND)."),
        409: error_response(
            "The document cannot be cancelled (code DOCUMENT_NOT_CANCELLABLE): it is an invoice, "
            "it is already cancelled, it is a delivery note with an invoice, or it is an order "
            "with delivery notes that are not cancelled."
        ),
        422: error_response("The identifier is not a valid UUID (code VALIDATION_ERROR)."),
    },
)
def cancel_document(
    document_id: uuid.UUID, session: Annotated[Session, Depends(get_session)]
) -> DocumentRead:
    """Cancel an order or a delivery note that has not been invoiced, to correct a mistake.

    The document is kept, with the status `CANCELLED`, and cannot be used again: no delivery note
    can be made from a cancelled order, and no invoice from a cancelled delivery note. Cancelling a
    delivery note frees the quantities it delivered, so they can be delivered again.

    It is refused with a 409 if the document is an invoice (an issued invoice is rectified, not
    cancelled), if it is already cancelled, if it is a delivery note that already has an invoice,
    or if it is an order that still has delivery notes: cancel those first, so none is left
    without its order.
    """
    return _to_read(document_service.cancel_document(session, document_id))
