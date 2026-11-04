"""The consumer against a real Redis stream and the real database.

Each test uses its own stream and consumer group (the name has a random part), so the tests do
not see each other's entries, and the events it recorded are removed at the end.
"""

import time
import uuid
from collections.abc import Iterator

import pytest
from redis import Redis
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.consumer import INVOICE_ISSUED_EVENT, InvoiceIssuedConsumer, to_event
from app.models import TraceEvent
from app.services.event_service import record_event


@pytest.fixture
def stream(redis_client: Redis) -> Iterator[str]:
    name = f"test.invoice.issued.{uuid.uuid4()}"
    yield name
    redis_client.delete(name)


@pytest.fixture
def invoices(engine: Engine) -> Iterator[list[uuid.UUID]]:
    """The invoices a test issues, so that their events are removed at the end."""
    issued: list[uuid.UUID] = []
    yield issued
    with Session(engine) as session:
        session.execute(delete(TraceEvent).where(TraceEvent.document_id.in_(issued)))
        session.commit()


def publish(redis_client: Redis, stream: str, invoices: list[uuid.UUID], **changes) -> uuid.UUID:
    """Publish an entry like document-service does, and return the id of its invoice."""
    invoice_id = uuid.uuid4()
    invoices.append(invoice_id)
    fields = {
        "invoice_id": str(invoice_id),
        "number": "F-2026-000001",
        "delivery_note_id": str(uuid.uuid4()),
        "order_id": str(uuid.uuid4()),
        "total": "380.82",
        "issued_at": "2026-10-14T09:30:00+00:00",
        **changes,
    }
    redis_client.xadd(stream, fields)
    return invoice_id


def consumer(redis_client: Redis, engine: Engine, stream: str, **options) -> InvoiceIssuedConsumer:
    return InvoiceIssuedConsumer(
        redis_client,
        lambda: Session(engine),
        stream=stream,
        group=f"group-{stream}",
        block_milliseconds=50,
        **options,
    )


def events_of(engine: Engine, document_id: uuid.UUID) -> list[TraceEvent]:
    with Session(engine) as session:
        query = select(TraceEvent).where(TraceEvent.document_id == document_id)
        return list(session.scalars(query.order_by(TraceEvent.sequence)))


def pending(redis_client: Redis, stream: str) -> int:
    return redis_client.xpending(stream, f"group-{stream}")["pending"]


def test_an_issued_invoice_is_recorded_as_the_first_event_of_its_chain(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)

    handled = consumer(redis_client, engine, stream).poll()

    assert handled == 1
    [event] = events_of(engine, invoice_id)
    assert event.event_type == INVOICE_ISSUED_EVENT
    assert event.sequence == 1
    assert event.payload["number"] == "F-2026-000001"
    assert event.payload["total"] == "380.82"
    assert event.source_message_id is not None


def test_the_entry_is_acknowledged_once_it_is_recorded(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    publish(redis_client, stream, invoices)

    consumer(redis_client, engine, stream).poll()

    assert pending(redis_client, stream) == 0


def test_entries_published_before_the_consumer_existed_are_recorded(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    # The stream already has entries when the group is created for the first time.
    first = publish(redis_client, stream, invoices)
    second = publish(redis_client, stream, invoices)

    consumer(redis_client, engine, stream).poll()

    assert len(events_of(engine, first)) == 1
    assert len(events_of(engine, second)) == 1


def test_an_entry_of_a_document_that_already_has_events_is_chained_to_them(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)
    # The same invoice announced again (a different entry of the stream).
    redis_client.xadd(
        stream,
        {
            "invoice_id": str(invoice_id),
            "number": "F-2026-000001",
            "delivery_note_id": str(uuid.uuid4()),
            "order_id": str(uuid.uuid4()),
            "total": "380.82",
            "issued_at": "2026-10-14T09:31:00+00:00",
        },
    )

    worker = consumer(redis_client, engine, stream)
    worker.poll()

    first, second = events_of(engine, invoice_id)
    assert (first.sequence, second.sequence) == (1, 2)
    assert second.previous_hash == first.hash


def test_an_entry_that_is_delivered_again_is_not_recorded_twice(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)
    worker = consumer(redis_client, engine, stream)
    worker.ensure_group()
    # Simulate a crash right after committing and before acknowledging: read it, record it, and
    # do not acknowledge it.
    [(message_id, fields)] = worker._read(">")
    with Session(engine) as session:
        record_event(session, to_event(message_id, fields))
    assert pending(redis_client, stream) == 1

    worker.poll()  # the entry is pending, so it is delivered again

    assert len(events_of(engine, invoice_id)) == 1
    assert pending(redis_client, stream) == 0


def test_an_entry_that_could_not_be_recorded_stays_pending_and_is_retried(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)
    broken = InvoiceIssuedConsumer(
        redis_client,
        lambda: (_ for _ in ()).throw(RuntimeError("database down")),  # type: ignore[arg-type,return-value]
        stream=stream,
        group=f"group-{stream}",
        block_milliseconds=50,
    )

    with pytest.raises(RuntimeError, match="database down"):
        broken.poll()
    assert pending(redis_client, stream) == 1
    assert events_of(engine, invoice_id) == []

    consumer(redis_client, engine, stream).poll()  # the database is back

    assert len(events_of(engine, invoice_id)) == 1
    assert pending(redis_client, stream) == 0


def test_an_invalid_entry_is_discarded_and_does_not_block_the_next_ones(
    redis_client: Redis,
    engine: Engine,
    stream: str,
    invoices: list[uuid.UUID],
    caplog: pytest.LogCaptureFixture,
):
    redis_client.xadd(stream, {"invoice_id": "not-a-uuid"})
    valid = publish(redis_client, stream, invoices)

    consumer(redis_client, engine, stream).poll()

    assert len(events_of(engine, valid)) == 1
    assert pending(redis_client, stream) == 0
    assert "Discarded an invalid entry" in caplog.text


def test_entries_left_pending_by_another_consumer_are_taken_over(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)
    # A consumer reads the entry and dies without recording it (a container that was replaced).
    dead = consumer(redis_client, engine, stream, name="dead")
    dead.ensure_group()
    dead._read(">")
    assert events_of(engine, invoice_id) == []

    # Another replica takes over what has been pending for longer than the limit (0 here).
    alive = consumer(redis_client, engine, stream, name="alive", claim_after_milliseconds=0)
    alive.poll()

    assert len(events_of(engine, invoice_id)) == 1
    assert pending(redis_client, stream) == 0


def test_the_background_thread_records_the_entries(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    worker = consumer(redis_client, engine, stream)
    worker.start()
    try:
        invoice_id = publish(redis_client, stream, invoices)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not events_of(engine, invoice_id):
            time.sleep(0.05)
    finally:
        worker.stop()

    assert len(events_of(engine, invoice_id)) == 1
