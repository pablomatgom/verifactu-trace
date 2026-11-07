import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Document, DocumentLine, DocumentStatus, DocumentType


def add(session: Session, document: Document) -> Document:
    """Stage a document (and its lines) and send it to the database without committing.

    flush() runs the INSERTs inside the current transaction, so constraint errors show up here
    and the generated values are available. Committing is up to the service.
    """
    session.add(document)
    session.flush()
    return document


@dataclass
class DocumentFilters:
    """What the list of documents is narrowed by. A filter left as None does not narrow."""

    type: DocumentType | None = None
    # Text that is the tax id of the customer, or part of the name.
    customer: str | None = None
    series: str | None = None
    status: DocumentStatus | None = None
    # Both ends are included.
    date_from: date | None = None
    date_to: date | None = None


def search(
    session: Session, filters: DocumentFilters, offset: int, limit: int
) -> tuple[list[Document], int]:
    """Return one page of the documents that meet the filters, and how many meet them in all.

    The newest come first. The number breaks the ties, so the order is the same on every call and
    a document cannot show up in two pages (or in none) while the client turns the pages.
    The lines are not loaded: a list does not show them.
    """
    conditions = []
    if filters.type is not None:
        conditions.append(Document.type == filters.type)
    if filters.series is not None:
        conditions.append(Document.series == filters.series)
    if filters.status is not None:
        conditions.append(Document.status == filters.status)
    if filters.date_from is not None:
        conditions.append(Document.issue_date >= filters.date_from)
    if filters.date_to is not None:
        conditions.append(Document.issue_date <= filters.date_to)
    if filters.customer is not None:
        # autoescape makes a % or _ typed by the client match itself instead of acting as a
        # wildcard of LIKE.
        conditions.append(
            or_(
                Document.customer_tax_id == filters.customer,
                Document.customer_name.icontains(filters.customer, autoescape=True),
            )
        )

    total = session.scalar(select(func.count()).select_from(Document).where(*conditions))
    query = (
        select(Document)
        .where(*conditions)
        .order_by(Document.issue_date.desc(), Document.number.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(query)), total or 0


def get(session: Session, document_id: uuid.UUID) -> Document | None:
    """Return the document with that id, whatever its type, with its lines and their sources.

    The lines are loaded here, in one query each, so that building the response does not trigger
    one more query per line.
    """
    query = (
        select(Document)
        .where(Document.id == document_id)
        .options(selectinload(Document.lines).joinedload(DocumentLine.source_line))
    )
    return session.scalar(query)


def get_for_update(
    session: Session, document_id: uuid.UUID, document_type: DocumentType
) -> Document | None:
    """Return the document with that id and type, locking its row until the end of the transaction.

    The lock makes two requests that work on the same document wait for each other, so the second
    one sees what the first did. Without it both could pass a check (such as "is there still
    something to deliver?") and break the rule together. Returns None if there is no document
    with that id, or it is not of that type.
    """
    query = (
        select(Document)
        .where(Document.id == document_id, Document.type == document_type)
        .with_for_update()
    )
    return session.scalar(query)


def exists_child(session: Session, parent_id: uuid.UUID, document_type: DocumentType) -> bool:
    """Say whether a document of that type already points to the given parent."""
    query = select(
        select(Document.id)
        .where(Document.parent_id == parent_id, Document.type == document_type)
        .exists()
    )
    return bool(session.scalar(query))


def delivered_quantities(session: Session, order_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    """Return how much has been delivered of each order line, keyed by the order line id.

    Lines that have not been delivered at all are not in the result.
    """
    query = (
        select(DocumentLine.source_line_id, func.sum(DocumentLine.quantity))
        .join(Document, DocumentLine.document_id == Document.id)
        .where(Document.parent_id == order_id, Document.type == DocumentType.DELIVERY_NOTE)
        .group_by(DocumentLine.source_line_id)
    )
    # Each row is (order line id, quantity), which dict() takes as a key and its value.
    return dict(session.execute(query).all())
