"""Sending a FAILED or REJECTED submission again by hand.

The tests pass the time in as `now`, as the ones of the life of a submission do.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.aeat import AeatOutcome, AeatResponse
from app.exceptions import SubmissionNotFound, SubmissionNotRetryable
from app.models import Submission, SubmissionStatus
from app.services import submission_service
from app.services.retry import RetryPolicy

NOW = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
LATER = NOW + timedelta(hours=2)
POLICY = RetryPolicy(max_attempts=3, base_seconds=10)

ACCEPTED = AeatResponse(AeatOutcome.ACCEPTED, "SIM-ABC")
UNAVAILABLE = AeatResponse(AeatOutcome.UNAVAILABLE, "AEAT_UNAVAILABLE")


def save(session: Session, status: SubmissionStatus, **values) -> Submission:
    submission = Submission(invoice_id=uuid.uuid4(), status=status, **values)
    session.add(submission)
    session.flush()
    return submission


def failed(session: Session) -> Submission:
    return save(
        session, SubmissionStatus.FAILED, attempts=3, last_error="AEAT_UNAVAILABLE", updated_at=NOW
    )


@pytest.mark.parametrize("status", [SubmissionStatus.FAILED, SubmissionStatus.REJECTED])
def test_a_failed_or_rejected_submission_goes_back_to_pending_and_due(
    session: Session, status: SubmissionStatus
):
    submission = save(session, status, attempts=3, last_error="AEAT_INVALID_RECORD")

    result = submission_service.retry_submission(session, submission.id, LATER)

    assert result.status == SubmissionStatus.PENDING
    assert result.next_attempt_at == LATER
    assert result.updated_at == LATER


def test_the_attempts_start_again_and_the_last_error_is_kept(session: Session):
    submission = failed(session)

    result = submission_service.retry_submission(session, submission.id, LATER)

    assert result.attempts == 0
    assert result.last_error == "AEAT_UNAVAILABLE"


def test_the_retry_is_saved(session: Session):
    submission = failed(session)

    submission_service.retry_submission(session, submission.id, LATER)

    session.expire_all()
    assert session.get(Submission, submission.id).status == SubmissionStatus.PENDING


@pytest.mark.parametrize(
    "status",
    [
        SubmissionStatus.ACCEPTED,
        SubmissionStatus.PENDING,
        SubmissionStatus.SENT,
        SubmissionStatus.RETRYING,
    ],
)
def test_any_other_state_cannot_be_retried_and_is_left_as_it_is(
    session: Session, status: SubmissionStatus
):
    submission = save(session, status, attempts=2, last_error="X", aeat_reference="REF")

    with pytest.raises(SubmissionNotRetryable, match=str(status)):
        submission_service.retry_submission(session, submission.id, LATER)

    assert (submission.status, submission.attempts) == (status, 2)
    assert (submission.last_error, submission.aeat_reference) == ("X", "REF")


def test_a_submission_that_does_not_exist_is_not_found(session: Session):
    with pytest.raises(SubmissionNotFound):
        submission_service.retry_submission(session, uuid.uuid4(), LATER)


def test_a_retried_submission_is_sent_again_and_can_be_accepted(session: Session, scripted_aeat):
    submission = failed(session)
    aeat = scripted_aeat(ACCEPTED)
    submission_service.retry_submission(session, submission.id, LATER)

    claimed = submission_service.claim_due(session, LATER)
    assert submission.id in claimed
    result = submission_service.send(session, aeat, submission.id, POLICY, LATER)

    assert result is not None
    assert result.status == SubmissionStatus.ACCEPTED
    assert result.attempts == 1
    assert aeat.calls == [submission.invoice_id]


def test_a_retry_gets_a_whole_set_of_attempts(session: Session, scripted_aeat):
    # With the old count (3 of 3) the first failure would send it straight back to FAILED.
    submission = failed(session)
    aeat = scripted_aeat(UNAVAILABLE)
    submission_service.retry_submission(session, submission.id, LATER)

    now = LATER
    statuses = []
    for _ in range(POLICY.max_attempts):
        submission_service.claim_due(session, now)
        result = submission_service.send(session, aeat, submission.id, POLICY, now)
        assert result is not None
        statuses.append(result.status)
        now += timedelta(hours=1)

    assert statuses == [
        SubmissionStatus.RETRYING,
        SubmissionStatus.RETRYING,
        SubmissionStatus.FAILED,
    ]
    assert len(aeat.calls) == 3


def test_a_submission_that_is_not_due_yet_is_not_taken_before_the_retry(session: Session):
    submission = failed(session)

    assert submission.id not in submission_service.claim_due(session, LATER)
