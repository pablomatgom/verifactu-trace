import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import TraceEvent
from app.repositories import event_repository
from app.services.event_service import EventData, record_event
from app.services.hashing import GENESIS_HASH, canonical_content, compute_hash

OCCURRED_AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def data(document_id: uuid.UUID, event_type: str = "INVOICE_ISSUED", **changes) -> EventData:
    values = {
        "document_id": document_id,
        "event_type": event_type,
        "occurred_at": OCCURRED_AT,
        "payload": {"number": "F-2026-000001"},
    }
    return EventData(**{**values, **changes})


def test_the_first_event_of_a_document_starts_the_chain(session: Session):
    event = record_event(session, data(uuid.uuid4()))

    assert event.sequence == 1
    assert event.previous_hash == GENESIS_HASH
    assert len(event.hash) == 64


def test_the_next_event_is_chained_to_the_previous_one(session: Session):
    document_id = uuid.uuid4()

    first = record_event(session, data(document_id, "A"))
    second = record_event(session, data(document_id, "B"))
    third = record_event(session, data(document_id, "C"))

    assert [first.sequence, second.sequence, third.sequence] == [1, 2, 3]
    assert second.previous_hash == first.hash
    assert third.previous_hash == second.hash
    assert len({first.hash, second.hash, third.hash}) == 3


def test_each_document_has_its_own_chain(session: Session):
    record_event(session, data(uuid.uuid4()))
    record_event(session, data(uuid.uuid4()))

    other = record_event(session, data(uuid.uuid4()))

    assert other.sequence == 1
    assert other.previous_hash == GENESIS_HASH


def test_the_stored_hash_can_be_recomputed_from_the_stored_event(session: Session):
    document_id = uuid.uuid4()
    record_event(session, data(document_id, "A"))
    record_event(session, data(document_id, "B", payload={"total": "1.50", "n": 2}))
    session.expire_all()  # forget what is in memory, so the values come back from the database

    stored = event_repository.get_last(session, document_id)

    assert stored is not None
    content = canonical_content(
        stored.document_id, stored.sequence, stored.event_type, stored.occurred_at, stored.payload
    )
    assert stored.hash == compute_hash(content, stored.previous_hash)


def test_the_event_gets_its_id_and_the_date_it_was_recorded(session: Session):
    event = record_event(session, data(uuid.uuid4()))

    assert isinstance(event.id, uuid.UUID)
    assert event.created_at is not None


def test_the_same_stream_entry_is_recorded_only_once(session: Session):
    document_id = uuid.uuid4()
    entry = data(document_id, source_message_id=f"test-{uuid.uuid4()}")

    first = record_event(session, entry)
    again = record_event(session, entry)

    assert again.id == first.id
    assert session.query(TraceEvent).filter_by(document_id=document_id).count() == 1


def test_two_entries_of_the_same_document_are_chained_in_the_order_they_arrive(session: Session):
    document_id = uuid.uuid4()
    marker = uuid.uuid4()

    first = record_event(session, data(document_id, source_message_id=f"{marker}-1"))
    second = record_event(session, data(document_id, source_message_id=f"{marker}-2"))

    assert (first.sequence, second.sequence) == (1, 2)
    assert second.previous_hash == first.hash
