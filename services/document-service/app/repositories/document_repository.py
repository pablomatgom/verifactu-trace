import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentLine, DocumentType


def add(session: Session, document: Document) -> Document:
    """Stage a document (and its lines) and send it to the database without committing.

    flush() runs the INSERTs inside the current transaction, so constraint errors show up here
    and the generated values are available. Committing is up to the service.
    """
    session.add(document)
    session.flush()
    return document


def get_order_for_update(session: Session, order_id: uuid.UUID) -> Document | None:
    """Return the order with that id, locking its row until the end of the transaction.

    The lock makes two requests that deliver the same order wait for each other, so the second
    one sees what the first delivered. Without it both could pass the check and, together, deliver
    more than was ordered. Returns None if there is no document with that id, or it is not an order.
    """
    query = (
        select(Document)
        .where(Document.id == order_id, Document.type == DocumentType.ORDER)
        .with_for_update()
    )
    return session.scalar(query)


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
