import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.exceptions import EventsNotFound
from app.models import TraceEvent
from app.repositories import event_repository
from app.services.hashing import GENESIS_HASH, canonical_content, compute_hash


@dataclass
class EventData:
    document_id: uuid.UUID
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    # Id of the Redis stream entry the event comes from, if it comes from one.
    source_message_id: str | None = None


def get_history(session: Session, document_id: uuid.UUID) -> list[TraceEvent]:
    """The events of a document in the order of its chain, or EventsNotFound if it has none."""
    events = event_repository.list_by_document(session, document_id)
    if not events:
        raise EventsNotFound(f"document {document_id} has no events")
    return events


def record_event(session: Session, data: EventData) -> TraceEvent:
    """Add an event to the end of its document's chain and save it."""
    # Locking the chain makes "read the last event" and "add the next one" a single step for
    # events of the same document that arrive at the same time: they are chained one after the
    # other, in the order they got the lock.
    event_repository.lock_chain(session, data.document_id)

    if data.source_message_id is not None:
        already_recorded = event_repository.get_by_source_message(session, data.source_message_id)
        if already_recorded is not None:
            # The stream delivered the same entry again, so it must not be chained twice.
            return already_recorded

    last = event_repository.get_last(session, data.document_id)
    sequence = 1 if last is None else last.sequence + 1
    previous_hash = GENESIS_HASH if last is None else last.hash

    content = canonical_content(
        data.document_id, sequence, data.event_type, data.occurred_at, data.payload
    )
    event = TraceEvent(
        document_id=data.document_id,
        sequence=sequence,
        event_type=data.event_type,
        occurred_at=data.occurred_at,
        payload=data.payload,
        previous_hash=previous_hash,
        hash=compute_hash(content, previous_hash),
        source_message_id=data.source_message_id,
    )
    event_repository.add(session, event)
    session.commit()
    return event
