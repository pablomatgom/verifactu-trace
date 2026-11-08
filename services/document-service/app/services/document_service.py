import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.exceptions import DocumentNotCancellable, DocumentNotFound, InvalidDateRange
from app.models import Document, DocumentStatus, DocumentType
from app.repositories import document_repository
from app.repositories.document_repository import DocumentFilters


@dataclass
class DocumentPage:
    """One page of a list of documents."""

    items: list[Document]
    page: int
    size: int
    # How many documents meet the filters in all, not only in this page.
    total: int


def get_document(session: Session, document_id: uuid.UUID) -> Document:
    """Return the order, delivery note or invoice with that id, or raise DocumentNotFound."""
    document = document_repository.get(session, document_id)
    if document is None:
        raise DocumentNotFound(f"document {document_id} does not exist")
    return document


def list_documents(
    session: Session, filters: DocumentFilters, page: int, size: int
) -> DocumentPage:
    """Return one page (the first is number 1) of the documents that meet the filters."""
    if (
        filters.date_from is not None
        and filters.date_to is not None
        and filters.date_from > filters.date_to
    ):
        raise InvalidDateRange(
            f"the start date {filters.date_from} is later than the end date {filters.date_to}"
        )
    items, total = document_repository.search(session, filters, (page - 1) * size, size)
    return DocumentPage(items=items, page=page, size=size, total=total)


def cancel_document(session: Session, document_id: uuid.UUID) -> Document:
    """Cancel an order or a delivery note that nothing has been built on.

    - An invoice cannot be cancelled, only rectified.
    - A document that is already cancelled cannot be cancelled again.
    - A delivery note that has been invoiced cannot be cancelled.
    - An order with delivery notes that are not cancelled cannot be cancelled: they would be left
      without an order. They are cancelled first.

    The row is locked, so a request that creates a delivery note of the order (or an invoice of the
    delivery note) at the same time either goes first, and the cancellation is refused, or goes
    after, and is refused because the document is cancelled. Raises DocumentNotFound if there is no
    document with that id.
    """
    document = document_repository.lock(session, document_id)
    if document is None:
        raise DocumentNotFound(f"document {document_id} does not exist")

    if document.type == DocumentType.INVOICE:
        raise DocumentNotCancellable(
            f"invoice {document.number} cannot be cancelled: an issued invoice can only be "
            "rectified"
        )
    if document.type == DocumentType.CORRECTIVE_INVOICE:
        raise DocumentNotCancellable(
            f"corrective invoice {document.number} cannot be cancelled: it is final, like any "
            "issued invoice"
        )
    if document.status == DocumentStatus.CANCELLED:
        raise DocumentNotCancellable(f"{document.number} is already cancelled")
    if document.type == DocumentType.DELIVERY_NOTE and document_repository.exists_child(
        session, document.id, DocumentType.INVOICE
    ):
        raise DocumentNotCancellable(f"delivery note {document.number} already has an invoice")
    if document.type == DocumentType.ORDER:
        live = document_repository.live_delivery_notes(session, document.id)
        if live:
            raise DocumentNotCancellable(
                f"order {document.number} has delivery notes that are not cancelled "
                f"({', '.join(live)}): cancel them first"
            )

    document.status = DocumentStatus.CANCELLED
    session.commit()
    # Read again with its lines, which the response shows, in the queries the GET uses.
    cancelled = document_repository.get(session, document_id)
    assert cancelled is not None
    return cancelled
