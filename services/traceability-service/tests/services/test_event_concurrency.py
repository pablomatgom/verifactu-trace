"""Events of the same document recorded at the same time are still chained one after the other.

It needs transactions that really commit, so it opens its own sessions on the engine and cleans
up afterwards.
"""

import itertools
import threading
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.models import TraceEvent
from app.repositories import event_repository
from app.services.event_service import EventData, record_event
from app.services.hashing import GENESIS_HASH

THREADS = 6


def test_concurrent_events_of_a_document_get_consecutive_sequences(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
):
    document_id = uuid.uuid4()

    # Without the lock, every request would read the same "last event" and try to save the same
    # sequence. To force that overlap, each request waits just after reading until the others
    # have read too. With the lock the others cannot even read until the first one has finished,
    # so the wait times out instead.
    all_read = threading.Barrier(THREADS)
    get_last = event_repository.get_last

    def get_last_once_all_have_read(*args, **kwargs):
        last = get_last(*args, **kwargs)
        try:
            all_read.wait(timeout=0.3)
        except threading.BrokenBarrierError:
            pass  # the others are waiting for the lock: they cannot arrive
        return last

    monkeypatch.setattr(event_repository, "get_last", get_last_once_all_have_read)

    errors: list[Exception] = []

    def record(n: int) -> None:
        try:
            with Session(engine) as session:
                record_event(
                    session,
                    EventData(document_id, "TEST", datetime.now(UTC), {"n": n}),
                )
        except Exception as error:  # noqa: BLE001  (any failure of a thread must reach the test)
            errors.append(error)

    threads = [threading.Thread(target=record, args=(n,)) for n in range(THREADS)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert errors == []
        with Session(engine) as session:
            events = session.scalars(
                select(TraceEvent)
                .where(TraceEvent.document_id == document_id)
                .order_by(TraceEvent.sequence)
            ).all()
        assert [event.sequence for event in events] == list(range(1, THREADS + 1))
        # Each event points to the hash of the one before it: the chain has no forks.
        assert events[0].previous_hash == GENESIS_HASH
        for previous, event in itertools.pairwise(events):
            assert event.previous_hash == previous.hash
    finally:
        with Session(engine) as session:
            session.execute(delete(TraceEvent).where(TraceEvent.document_id == document_id))
            session.commit()
