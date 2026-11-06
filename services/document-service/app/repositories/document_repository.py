import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import Document, DocumentLine, DocumentType


def add(session: Session, document: Document) -> Document:
    """Stage a document (and its lines) and send it to the database without committing.

    flush() runs the INSERTs inside the current transaction, so constraint errors show up here
    and the generated values are available. Committing is up to the service.
    """
    session.add(document)
    session.flush()
    return document


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
