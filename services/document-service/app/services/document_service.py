import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.exceptions import DocumentNotFound, InvalidDateRange
from app.models import Document
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
