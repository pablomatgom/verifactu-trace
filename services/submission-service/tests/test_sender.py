"""The worker that sends the submissions, against the real database.

The tests use a wait of 0 between retries (`RetryPolicy(base_seconds=0)`), so a retry is due at
once and no test has to sleep. The waits that grow are tested in tests/services/ with a fixed
clock.
"""

import time
import uuid
from collections.abc import Iterator

import pytest
from redis import Redis
from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app.aeat import AeatOutcome, AeatResponse
from app.consumer import InvoiceIssuedConsumer
from app.models import Submission, SubmissionStatus
from app.sender import SubmissionSender
from app.services import submission_service
from app.services.retry import RetryPolicy
from app.services.submission_service import SubmissionData

POLICY = RetryPolicy(max_attempts=3, base_seconds=0)

ACCEPTED = AeatResponse(AeatOutcome.ACCEPTED, "SIM-ABC")
REJECTED = AeatResponse(AeatOutcome.REJECTED, "AEAT_INVALID_RECORD")
UNAVAILABLE = AeatResponse(AeatOutcome.UNAVAILABLE, "AEAT_UNAVAILABLE")


@pytest.fixture
def invoices(engine: Engine) -> Iterator[list[uuid.UUID]]:
    """The invoices a test submits, so that their submissions are removed at the end."""
    submitted: list[uuid.UUID] = []
    yield submitted
    with Session(engine) as session:
        session.execute(delete(Submission).where(Submission.invoice_id.in_(submitted)))
        session.commit()


def submit(engine: Engine, invoices: list[uuid.UUID]) -> uuid.UUID:
    """Register a pending submission, as the consumer or the endpoint do."""
    invoice_id = uuid.uuid4()
    invoices.append(invoice_id)
    with Session(engine) as session:
        submission_service.create_submission(session, SubmissionData(invoice_id=invoice_id))
    return invoice_id


def current(engine: Engine, invoice_id: uuid.UUID) -> Submission:
    with Session(engine) as session:
        return session.query(Submission).filter_by(invoice_id=invoice_id).one()


def sender(engine: Engine, aeat) -> SubmissionSender:
    return SubmissionSender(lambda: Session(engine), aeat, POLICY, poll_seconds=0.05)


def test_a_pending_submission_is_sent_and_accepted(engine: Engine, invoices, scripted_aeat):
    invoice_id = submit(engine, invoices)
    aeat = scripted_aeat(ACCEPTED)

    sender(engine, aeat).run_once()

    submission = current(engine, invoice_id)
    assert submission.status == SubmissionStatus.ACCEPTED
    assert submission.aeat_reference == "SIM-ABC"
    assert invoice_id in aeat.calls


def test_a_rejected_submission_is_not_retried(engine: Engine, invoices, scripted_aeat):
    invoice_id = submit(engine, invoices)
    aeat = scripted_aeat(REJECTED)
    worker = sender(engine, aeat)

    worker.run_once()
    worker.run_once()

    assert current(engine, invoice_id).status == SubmissionStatus.REJECTED
    assert aeat.calls.count(invoice_id) == 1


def test_a_failed_submission_is_retried_until_it_is_accepted(
    engine: Engine, invoices, scripted_aeat
):
    invoice_id = submit(engine, invoices)
    aeat = scripted_aeat(UNAVAILABLE, UNAVAILABLE, ACCEPTED)
    worker = sender(engine, aeat)

    worker.run_once()
    assert current(engine, invoice_id).status == SubmissionStatus.RETRYING
    worker.run_once()
    assert current(engine, invoice_id).status == SubmissionStatus.RETRYING
    worker.run_once()

    submission = current(engine, invoice_id)
    assert submission.status == SubmissionStatus.ACCEPTED
    assert submission.attempts == 3


def test_a_submission_that_always_fails_ends_in_failed(engine: Engine, invoices, scripted_aeat):
    invoice_id = submit(engine, invoices)
    aeat = scripted_aeat(UNAVAILABLE)
    worker = sender(engine, aeat)

    for _ in range(POLICY.max_attempts + 2):  # more rounds than attempts: it must stop by itself
        worker.run_once()

    submission = current(engine, invoice_id)
    assert submission.status == SubmissionStatus.FAILED
    assert submission.attempts == POLICY.max_attempts
    assert submission.last_error == "AEAT_UNAVAILABLE"
    assert aeat.calls.count(invoice_id) == POLICY.max_attempts


def test_an_unexpected_error_in_one_submission_does_not_stop_the_others(
    engine: Engine, invoices, caplog: pytest.LogCaptureFixture
):
    class FailsForTheFirst:
        def __init__(self, bad: uuid.UUID):
            self.bad = bad

        def send(self, invoice_id: uuid.UUID, invoice_number: str | None) -> AeatResponse:
            if invoice_id == self.bad:
                raise ConnectionError("the AEAT client broke")
            return ACCEPTED

    bad = submit(engine, invoices)
    good = submit(engine, invoices)

    sender(engine, FailsForTheFirst(bad)).run_once()

    assert current(engine, good).status == SubmissionStatus.ACCEPTED
    # The broken one stays SENT: it will be taken as lost and sent again later.
    assert current(engine, bad).status == SubmissionStatus.SENT
    assert "Sending the submission" in caplog.text


def test_the_background_thread_sends_and_retries(engine: Engine, invoices, scripted_aeat):
    invoice_id = submit(engine, invoices)
    worker = sender(engine, scripted_aeat(UNAVAILABLE, ACCEPTED))
    worker.start()
    try:
        deadline = time.monotonic() + 5
        while (
            time.monotonic() < deadline
            and current(engine, invoice_id).status != SubmissionStatus.ACCEPTED
        ):
            time.sleep(0.05)
    finally:
        worker.stop()

    submission = current(engine, invoice_id)
    assert submission.status == SubmissionStatus.ACCEPTED
    assert submission.attempts == 2


def test_an_invoice_issued_event_ends_in_an_accepted_submission(
    engine: Engine, redis_client: Redis, invoices, scripted_aeat
):
    """The whole flow: the event arrives, a submission is registered, and it is sent."""
    stream = f"test.invoice.issued.{uuid.uuid4()}"
    invoice_id = uuid.uuid4()
    invoices.append(invoice_id)
    redis_client.xadd(stream, {"invoice_id": str(invoice_id), "number": "F-2026-000007"})
    try:
        InvoiceIssuedConsumer(
            redis_client,
            lambda: Session(engine),
            stream=stream,
            group=f"group-{stream}",
            block_milliseconds=50,
        ).poll()
        assert current(engine, invoice_id).status == SubmissionStatus.PENDING

        sender(engine, scripted_aeat(ACCEPTED)).run_once()

        submission = current(engine, invoice_id)
        assert submission.status == SubmissionStatus.ACCEPTED
        assert submission.invoice_number == "F-2026-000007"
    finally:
        redis_client.delete(stream)
