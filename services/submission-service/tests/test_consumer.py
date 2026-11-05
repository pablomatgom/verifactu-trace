"""The consumer against a real Redis stream and the real database.

Each test uses its own stream and consumer group (the name has a random part), so the tests do
not see each other's entries, and the submissions it registered are removed at the end.
"""

import time
import uuid
from collections.abc import Iterator

import pytest
from redis import Redis
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.consumer import InvoiceIssuedConsumer
from app.models import Submission, SubmissionStatus
from app.services import submission_service
from app.services.submission_service import SubmissionData


@pytest.fixture
def stream(redis_client: Redis) -> Iterator[str]:
    name = f"test.invoice.issued.{uuid.uuid4()}"
    yield name
    redis_client.delete(name)


@pytest.fixture
def invoices(engine: Engine) -> Iterator[list[uuid.UUID]]:
    """The invoices a test issues, so that their submissions are removed at the end."""
    issued: list[uuid.UUID] = []
    yield issued
    with Session(engine) as session:
        session.execute(delete(Submission).where(Submission.invoice_id.in_(issued)))
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


def submissions_of(engine: Engine, invoice_id: uuid.UUID) -> list[Submission]:
    with Session(engine) as session:
        return list(session.scalars(select(Submission).where(Submission.invoice_id == invoice_id)))


def pending(redis_client: Redis, stream: str) -> int:
    return redis_client.xpending(stream, f"group-{stream}")["pending"]


def test_an_issued_invoice_gets_a_pending_submission(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)

    handled = consumer(redis_client, engine, stream).poll()

    assert handled == 1
    [submission] = submissions_of(engine, invoice_id)
    assert submission.status == SubmissionStatus.PENDING
    assert submission.invoice_number == "F-2026-000001"
    assert submission.attempts == 0


def test_the_entry_is_acknowledged_once_it_is_registered(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    publish(redis_client, stream, invoices)

    consumer(redis_client, engine, stream).poll()

    assert pending(redis_client, stream) == 0


def test_entries_published_before_the_consumer_existed_are_registered(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    # The stream already has entries when the group is created for the first time.
    first = publish(redis_client, stream, invoices)
    second = publish(redis_client, stream, invoices)

    consumer(redis_client, engine, stream).poll()

    assert len(submissions_of(engine, first)) == 1
    assert len(submissions_of(engine, second)) == 1


def test_an_invoice_announced_twice_has_only_one_submission(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)
    redis_client.xadd(stream, {"invoice_id": str(invoice_id), "number": "F-2026-000001"})

    consumer(redis_client, engine, stream).poll()

    assert len(submissions_of(engine, invoice_id)) == 1
    assert pending(redis_client, stream) == 0  # the second entry was acknowledged too


def test_an_invoice_already_requested_by_hand_is_not_registered_again(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)
    with Session(engine) as session:
        submission_service.create_submission(session, SubmissionData(invoice_id=invoice_id))

    consumer(redis_client, engine, stream).poll()

    assert len(submissions_of(engine, invoice_id)) == 1
    assert pending(redis_client, stream) == 0


def test_an_entry_that_could_not_be_registered_stays_pending_and_is_retried(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)

    def database_down() -> Session:
        raise RuntimeError("database down")

    broken = InvoiceIssuedConsumer(
        redis_client,
        database_down,
        stream=stream,
        group=f"group-{stream}",
        block_milliseconds=50,
    )

    with pytest.raises(RuntimeError, match="database down"):
        broken.poll()
    assert pending(redis_client, stream) == 1
    assert submissions_of(engine, invoice_id) == []

    consumer(redis_client, engine, stream).poll()  # the database is back

    assert len(submissions_of(engine, invoice_id)) == 1
    assert pending(redis_client, stream) == 0


def test_an_invalid_entry_is_discarded_and_does_not_block_the_next_ones(
    redis_client: Redis,
    engine: Engine,
    stream: str,
    invoices: list[uuid.UUID],
    caplog: pytest.LogCaptureFixture,
):
    redis_client.xadd(stream, {"invoice_id": "not-a-uuid", "number": "F-1"})
    valid = publish(redis_client, stream, invoices)

    consumer(redis_client, engine, stream).poll()

    assert len(submissions_of(engine, valid)) == 1
    assert pending(redis_client, stream) == 0
    assert "Discarded an invalid entry" in caplog.text


def test_entries_left_pending_by_another_consumer_are_taken_over(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    invoice_id = publish(redis_client, stream, invoices)
    # A consumer reads the entry and dies without registering it (a container that was replaced).
    dead = consumer(redis_client, engine, stream, name="dead")
    dead.ensure_group()
    dead._read(">")
    assert submissions_of(engine, invoice_id) == []

    # Another replica takes over what has been pending for longer than the limit (0 here).
    alive = consumer(redis_client, engine, stream, name="alive", claim_after_milliseconds=0)
    alive.poll()

    assert len(submissions_of(engine, invoice_id)) == 1
    assert pending(redis_client, stream) == 0


def test_the_background_thread_registers_the_entries(
    redis_client: Redis, engine: Engine, stream: str, invoices: list[uuid.UUID]
):
    worker = consumer(redis_client, engine, stream)
    worker.start()
    try:
        invoice_id = publish(redis_client, stream, invoices)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not submissions_of(engine, invoice_id):
            time.sleep(0.05)
    finally:
        worker.stop()

    assert len(submissions_of(engine, invoice_id)) == 1
