import uuid
from datetime import UTC, datetime

import pytest

from app.models import TraceEvent
from app.services.hashing import GENESIS_HASH, canonical_content, compute_hash
from app.services.verification import first_invalid_sequence

DOCUMENT_ID = uuid.UUID("5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52")
OCCURRED_AT = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def make_event(sequence: int, previous_hash: str, **changes) -> TraceEvent:
    """An event whose hash is the right one for its content, built as the service builds it."""
    values = {
        "document_id": DOCUMENT_ID,
        "sequence": sequence,
        "event_type": f"EVENT_{sequence}",
        "occurred_at": OCCURRED_AT,
        "payload": {"number": f"F-2026-00000{sequence}", "total": "380.82"},
    }
    values.update(changes)
    content = canonical_content(
        values["document_id"],
        values["sequence"],
        values["event_type"],
        values["occurred_at"],
        values["payload"],
    )
    return TraceEvent(
        **values, previous_hash=previous_hash, hash=compute_hash(content, previous_hash)
    )


def make_chain(length: int) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    previous_hash = GENESIS_HASH
    for sequence in range(1, length + 1):
        event = make_event(sequence, previous_hash)
        events.append(event)
        previous_hash = event.hash
    return events


def test_an_intact_chain_is_valid():
    assert first_invalid_sequence(make_chain(5)) is None


def test_a_chain_of_one_event_is_valid():
    assert first_invalid_sequence(make_chain(1)) is None


def test_a_chain_without_events_has_nothing_invalid():
    assert first_invalid_sequence([]) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"payload": {"number": "F-2026-000002", "total": "1.00"}},
        {"event_type": "SOMETHING_ELSE"},
        {"occurred_at": datetime(2026, 10, 14, 9, 31, tzinfo=UTC)},
    ],
    ids=["payload", "event_type", "occurred_at"],
)
def test_changing_the_data_of_an_event_is_reported_on_that_event(changes: dict):
    events = make_chain(5)
    for field, value in changes.items():
        setattr(events[2], field, value)

    # The data changed but the stored hash did not, so the hash no longer matches the content.
    assert first_invalid_sequence(events) == 3


def test_changing_the_stored_hash_of_an_event_is_reported_on_that_event():
    events = make_chain(5)
    events[2].hash = "f" * 64

    assert first_invalid_sequence(events) == 3


def test_changing_the_previous_hash_of_an_event_is_reported_on_that_event():
    events = make_chain(5)
    events[2].previous_hash = "a" * 64

    assert first_invalid_sequence(events) == 3


def test_a_first_event_that_does_not_start_from_the_initial_hash_is_invalid():
    events = make_chain(3)
    events[0].previous_hash = "a" * 64

    assert first_invalid_sequence(events) == 1


def test_a_deleted_event_is_reported_on_the_one_after_it():
    events = make_chain(5)
    del events[1]  # sequence 2 is gone: 1, 3, 4, 5

    assert first_invalid_sequence(events) == 3


def test_a_deleted_first_event_is_reported_on_the_new_first():
    events = make_chain(3)
    del events[0]  # 2, 3

    assert first_invalid_sequence(events) == 2


def test_a_deleted_event_is_detected_even_if_the_next_one_is_rechained():
    events = make_chain(4)
    # Event 2 is deleted and event 3 is rewritten to follow event 1, with a hash that matches its
    # content and its new previous hash. Every link holds, and only the gap in the sequence
    # (1, 3, 4) shows that something is missing.
    events[2] = make_event(3, events[0].hash, payload=events[2].payload)
    del events[1]

    assert first_invalid_sequence(events[:2]) == 3


def test_only_the_first_invalid_event_is_reported():
    events = make_chain(6)
    events[1].payload = {"changed": True}
    events[4].payload = {"changed": True}

    assert first_invalid_sequence(events) == 2


def test_an_event_that_is_replaced_with_a_consistent_hash_breaks_the_next_one():
    events = make_chain(4)
    # Whoever replaces event 2 also recomputes its hash, so the event itself looks fine...
    events[1] = make_event(2, events[0].hash, payload={"number": "F-FAKE", "total": "0.00"})

    # ...but event 3 was chained to the hash of the original one.
    assert first_invalid_sequence(events) == 3


def test_replacing_the_last_event_with_a_consistent_hash_cannot_be_detected():
    # This is the limit of a hash chain: no later event vouches for the last one. Detecting it
    # needs the last hash to be kept somewhere else (see docs/arquitectura.md). The test states
    # the limit so it cannot be forgotten.
    events = make_chain(3)
    events[2] = make_event(3, events[1].hash, payload={"number": "F-FAKE", "total": "0.00"})

    assert first_invalid_sequence(events) is None


def test_removing_the_last_events_cannot_be_detected():
    events = make_chain(5)

    assert first_invalid_sequence(events[:3]) is None
