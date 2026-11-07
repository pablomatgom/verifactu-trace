import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import TraceEvent
from app.services import event_service
from app.services.hashing import GENESIS_HASH, canonical_content, compute_hash


@dataclass(frozen=True)
class ChainVerification:
    document_id: uuid.UUID
    valid: bool
    # How many events the chain of the document has, which is how many the verification covers.
    events_checked: int
    # The first event that does not hold, or None if the chain is intact.
    first_invalid_sequence: int | None


def first_invalid_sequence(events: Sequence[TraceEvent]) -> int | None:
    """Recompute the chain in order and return the `sequence` of the first event that fails.

    `events` are the events of one document, ordered by sequence. An event fails if:

    - its `sequence` is not the one that follows the previous event (the first must be 1), which
      is what an event that was deleted from the middle leaves behind;
    - its `previous_hash` is not the stored `hash` of the previous event (or the initial hash,
      for the first), which is what an event that was replaced leaves behind; or
    - its `hash` is not the one recomputed from its own content and its `previous_hash`, which is
      what an event whose data was changed leaves behind.

    Each event is compared with its neighbour's stored hash, not with a recomputed one, so a
    tampered event is reported on its own position and not on the ones after it.
    """
    expected_sequence = 1
    expected_previous_hash = GENESIS_HASH
    for event in events:
        content = canonical_content(
            event.document_id,
            event.sequence,
            event.event_type,
            event.occurred_at,
            event.payload,
        )
        if (
            event.sequence != expected_sequence
            or event.previous_hash != expected_previous_hash
            or event.hash != compute_hash(content, event.previous_hash)
        ):
            return event.sequence
        expected_sequence += 1
        expected_previous_hash = event.hash
    return None


def verify_document(session: Session, document_id: uuid.UUID) -> ChainVerification:
    """Check the integrity of the chain of a document, or raise EventsNotFound if it has none."""
    events = event_service.get_history(session, document_id)
    failing = first_invalid_sequence(events)
    return ChainVerification(
        document_id=document_id,
        valid=failing is None,
        events_checked=len(events),
        first_invalid_sequence=failing,
    )
