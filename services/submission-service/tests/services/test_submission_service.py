"""The life of a submission: created, claimed, sent, accepted, rejected, retried or failed.

The tests pass the time in as `now`, so a wait of 40 seconds does not make a test slow.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.aeat import AeatOutcome, AeatResponse
from app.exceptions import SubmissionAlreadyExists
from app.models import Submission, SubmissionStatus
from app.services import submission_service
from app.services.retry import RetryPolicy
from app.services.submission_service import STUCK_AFTER, SubmissionData

NOW = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
POLICY = RetryPolicy(max_attempts=3, base_seconds=10)

ACCEPTED = AeatResponse(AeatOutcome.ACCEPTED, "SIM-ABC")
REJECTED = AeatResponse(AeatOutcome.REJECTED, "AEAT_INVALID_RECORD")
UNAVAILABLE = AeatResponse(AeatOutcome.UNAVAILABLE, "AEAT_UNAVAILABLE")


def create(session: Session, now: datetime = NOW) -> Submission:
    data = SubmissionData(invoice_id=uuid.uuid4(), invoice_number="F-2026-000001")
    return submission_service.create_submission(session, data, now)


def attempt(session: Session, aeat, submission: Submission, now: datetime) -> Submission:
    """Claim the submission (it must be due) and send it, as the worker does."""
    claimed = submission_service.claim_due(session, now)
    assert submission.id in claimed
    result = submission_service.send(session, aeat, submission.id, POLICY, now)
    assert result is not None
    return result


def test_a_new_submission_is_pending_and_due_now(session: Session):
    submission = create(session)

    assert submission.status == SubmissionStatus.PENDING
    assert submission.attempts == 0
    assert submission.next_attempt_at == NOW
    assert submission.last_error is None


def test_an_invoice_has_only_one_submission(session: Session):
    data = SubmissionData(invoice_id=uuid.uuid4())
    submission_service.create_submission(session, data, NOW)

    with pytest.raises(SubmissionAlreadyExists, match=str(data.invoice_id)):
        submission_service.create_submission(session, data, NOW)


def test_claiming_marks_the_submission_as_sent_and_counts_the_attempt(session: Session):
    submission = create(session)

    claimed = submission_service.claim_due(session, NOW)

    assert submission.id in claimed
    assert submission.status == SubmissionStatus.SENT
    assert submission.attempts == 1


def test_a_claimed_submission_is_not_claimed_again(session: Session):
    submission = create(session)
    submission_service.claim_due(session, NOW)

    assert submission.id not in submission_service.claim_due(session, NOW)


def test_a_submission_that_is_not_due_yet_is_not_claimed(session: Session):
    submission = create(session, now=NOW + timedelta(seconds=30))

    assert submission.id not in submission_service.claim_due(session, NOW)
    assert submission.status == SubmissionStatus.PENDING


def test_an_accepted_response_ends_in_accepted(session: Session, scripted_aeat):
    submission = create(session)

    result = attempt(session, scripted_aeat(ACCEPTED), submission, NOW)

    assert result.status == SubmissionStatus.ACCEPTED
    assert result.attempts == 1
    assert result.aeat_reference == "SIM-ABC"
    assert result.last_error is None
    assert result.next_attempt_at is None


def test_the_aeat_is_asked_to_send_the_invoice_of_the_submission(session: Session, scripted_aeat):
    submission = create(session)
    aeat = scripted_aeat(ACCEPTED)

    attempt(session, aeat, submission, NOW)

    assert aeat.calls == [submission.invoice_id]


def test_a_rejected_response_ends_in_rejected_without_retrying(session: Session, scripted_aeat):
    submission = create(session)

    result = attempt(session, scripted_aeat(REJECTED), submission, NOW)

    assert result.status == SubmissionStatus.REJECTED
    assert result.attempts == 1
    assert result.last_error == "AEAT_INVALID_RECORD"
    assert result.next_attempt_at is None
    # It is final: it is never due again.
    assert submission.id not in submission_service.claim_due(session, NOW + timedelta(days=1))


def test_a_transient_failure_goes_to_retrying_with_a_wait(session: Session, scripted_aeat):
    submission = create(session)

    result = attempt(session, scripted_aeat(UNAVAILABLE), submission, NOW)

    assert result.status == SubmissionStatus.RETRYING
    assert result.attempts == 1
    assert result.last_error == "AEAT_UNAVAILABLE"
    assert result.next_attempt_at == NOW + timedelta(seconds=10)


def test_the_wait_between_retries_grows(session: Session, scripted_aeat):
    submission = create(session)
    aeat = scripted_aeat(UNAVAILABLE)

    first = attempt(session, aeat, submission, NOW)
    first_wait = first.next_attempt_at - NOW
    at = first.next_attempt_at
    second = attempt(session, aeat, submission, at)
    second_wait = second.next_attempt_at - at

    assert (first_wait, second_wait) == (timedelta(seconds=10), timedelta(seconds=20))


def test_a_retry_is_not_made_before_its_time(session: Session, scripted_aeat):
    submission = create(session)
    attempt(session, scripted_aeat(UNAVAILABLE), submission, NOW)

    too_early = NOW + timedelta(seconds=9)
    on_time = NOW + timedelta(seconds=10)

    assert submission.id not in submission_service.claim_due(session, too_early)
    assert submission.id in submission_service.claim_due(session, on_time)


def test_the_attempts_run_out_and_the_submission_fails(session: Session, scripted_aeat):
    submission = create(session)
    aeat = scripted_aeat(UNAVAILABLE)
    at = NOW

    for _ in range(POLICY.max_attempts):
        result = attempt(session, aeat, submission, at)
        at = result.next_attempt_at or at

    assert result.status == SubmissionStatus.FAILED
    assert result.attempts == POLICY.max_attempts
    assert result.last_error == "AEAT_UNAVAILABLE"
    assert result.next_attempt_at is None
    # It is final: it is not tried again however long it waits.
    assert submission.id not in submission_service.claim_due(session, at + timedelta(days=1))


def test_a_submission_that_fails_and_then_succeeds_is_accepted(session: Session, scripted_aeat):
    submission = create(session)
    aeat = scripted_aeat(UNAVAILABLE, UNAVAILABLE, ACCEPTED)
    at = NOW

    for _ in range(3):
        result = attempt(session, aeat, submission, at)
        at = result.next_attempt_at or at

    assert result.status == SubmissionStatus.ACCEPTED
    assert result.attempts == 3
    assert result.last_error is None  # the earlier failures no longer apply
    assert len(aeat.calls) == 3


def test_an_attempt_that_was_lost_is_sent_again(session: Session, scripted_aeat):
    # The service died after claiming the submission and before saving the answer, so it stays
    # SENT. After a while it is taken as lost and claimed again.
    submission = create(session)
    submission_service.claim_due(session, NOW)
    assert submission.status == SubmissionStatus.SENT

    assert submission.id not in submission_service.claim_due(session, NOW + STUCK_AFTER / 2)
    assert submission.id in submission_service.claim_due(session, NOW + STUCK_AFTER)

    assert submission.attempts == 2  # the lost attempt counts


def test_sending_a_submission_that_is_not_sent_does_nothing(session: Session, scripted_aeat):
    submission = create(session)  # PENDING: nobody claimed it
    aeat = scripted_aeat(ACCEPTED)

    result = submission_service.send(session, aeat, submission.id, POLICY, NOW)

    assert result is not None
    assert result.status == SubmissionStatus.PENDING
    assert aeat.calls == []


def test_sending_a_submission_that_does_not_exist_returns_none(session: Session, scripted_aeat):
    aeat = scripted_aeat(ACCEPTED)

    assert submission_service.send(session, aeat, uuid.uuid4(), POLICY, NOW) is None
    assert aeat.calls == []


def test_the_oldest_due_submission_goes_first(session: Session):
    newer = create(session, now=NOW)
    older = create(session, now=NOW - timedelta(minutes=5))

    claimed = submission_service.claim_due(session, NOW, limit=1)

    assert claimed == [older.id]
    assert newer.status == SubmissionStatus.PENDING
