import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import TraceEvent


def lock_chain(session: Session, document_id: uuid.UUID) -> None:
    """Take the lock of a document's chain until the end of the transaction.

    A new event needs the last one of its document, and for the first event there is no row to
    lock with SELECT ... FOR UPDATE. An advisory lock is a mutex identified by a number, so it
    also works when there is nothing to lock yet. hashtext() turns the text into that number;
    two documents with the same number would only wait for each other, nothing else.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"trace:{document_id}"}
    )


def get_last(session: Session, document_id: uuid.UUID) -> TraceEvent | None:
    """The last event of the document's chain, or None if it has no events yet."""
    query = (
        select(TraceEvent)
        .where(TraceEvent.document_id == document_id)
        .order_by(TraceEvent.sequence.desc())
        .limit(1)
    )
    return session.scalars(query).first()


def get_by_source_message(session: Session, source_message_id: str) -> TraceEvent | None:
    """The event recorded from a Redis stream entry, or None if that entry was not recorded."""
    query = select(TraceEvent).where(TraceEvent.source_message_id == source_message_id)
    return session.scalars(query).first()


def add(session: Session, event: TraceEvent) -> TraceEvent:
    """Add the event to the session and flush it, so it gets its defaults (created_at)."""
    session.add(event)
    session.flush()
    session.refresh(event)
    return event
