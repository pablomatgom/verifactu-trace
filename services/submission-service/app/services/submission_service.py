import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.aeat import AeatClient, AeatOutcome
from app.exceptions import SubmissionAlreadyExists, SubmissionNotFound, SubmissionNotRetryable
from app.models import Submission, SubmissionStatus
from app.repositories import submission_repository
from app.repositories.submission_repository import SubmissionFilters
from app.services.retry import RetryPolicy

# A submission that has been SENT this long without an answer is taken as lost (the service died
# while sending it) and is sent again.
STUCK_AFTER = timedelta(minutes=1)

# How many submissions a worker takes at a time.
BATCH_SIZE = 10

# The final states that a person can send again: the AEAT never answered (FAILED) or refused it
# (REJECTED, which is worth sending again once the cause has been corrected). An ACCEPTED one
# must not be sent twice, and the others are already on their way.
RETRYABLE_STATUSES = (SubmissionStatus.FAILED, SubmissionStatus.REJECTED)


@dataclass
class SubmissionPage:
    """One page of a list of submissions."""

    items: list[Submission]
    page: int
    size: int
    # How many submissions meet the filters in all, not only in this page.
    total: int


@dataclass
class SubmissionData:
    invoice_id: uuid.UUID
    # Known when the submission comes from the `invoice.issued` event.
    invoice_number: str | None = None


def create_submission(
    session: Session, data: SubmissionData, now: datetime | None = None
) -> Submission:
    """Register the invoice to be sent. A worker sends it afterwards.

    Raises SubmissionAlreadyExists if the invoice already has a submission.
    """
    now = now or datetime.now(UTC)
    submission = submission_repository.create_if_absent(
        session, data.invoice_id, data.invoice_number, now
    )
    if submission is None:
        raise SubmissionAlreadyExists(f"invoice {data.invoice_id} already has a submission")
    session.commit()
    return submission


def get_submission(session: Session, submission_id: uuid.UUID) -> Submission:
    """The submission, or SubmissionNotFound if there is none with that id."""
    submission = submission_repository.get(session, submission_id)
    if submission is None:
        raise SubmissionNotFound(f"submission {submission_id} does not exist")
    return submission


def list_submissions(
    session: Session, filters: SubmissionFilters, page: int, size: int
) -> SubmissionPage:
    """One page (the first is number 1) of the submissions that meet the filters."""
    items, total = submission_repository.search(session, filters, (page - 1) * size, size)
    return SubmissionPage(items=items, page=page, size=size, total=total)


def retry_submission(
    session: Session, submission_id: uuid.UUID, now: datetime | None = None
) -> Submission:
    """Queue a FAILED or REJECTED submission to be sent again, with its attempts from zero.

    The worker sends it as it does with any PENDING one. The attempts start again so the retry
    gets a whole set of them: with the old count, a submission that ran out of attempts would go
    back to FAILED after a single try. `last_error` stays until the next attempt answers, so
    the reason it was stopped is not lost.

    Raises SubmissionNotFound if there is none with that id, and SubmissionNotRetryable if it is
    not FAILED or REJECTED.
    """
    now = now or datetime.now(UTC)
    submission = submission_repository.get_for_update(session, submission_id)
    if submission is None:
        raise SubmissionNotFound(f"submission {submission_id} does not exist")
    if submission.status not in RETRYABLE_STATUSES:
        raise SubmissionNotRetryable(
            f"submission {submission_id} is {submission.status}: only a FAILED or REJECTED "
            "submission can be retried"
        )
    submission.status = SubmissionStatus.PENDING
    submission.attempts = 0
    submission.next_attempt_at = now
    submission.updated_at = now
    session.commit()
    return submission


def claim_due(
    session: Session, now: datetime | None = None, limit: int = BATCH_SIZE
) -> list[uuid.UUID]:
    """Take the submissions that are due, mark them SENT and count the attempt.

    Marking them and committing before calling the AEAT is what keeps another replica from
    sending the same ones: once they are SENT they are no longer due.
    """
    now = now or datetime.now(UTC)
    submissions = submission_repository.claim_due(session, now, now - STUCK_AFTER, limit)
    for submission in submissions:
        submission.status = SubmissionStatus.SENT
        submission.attempts += 1
        submission.updated_at = now
    ids = [submission.id for submission in submissions]
    session.commit()
    return ids


def send(
    session: Session,
    aeat: AeatClient,
    submission_id: uuid.UUID,
    policy: RetryPolicy,
    now: datetime | None = None,
) -> Submission | None:
    """Send a submission that was claimed and apply what the AEAT answers.

    Returns None if there is no such submission. If it is no longer SENT (another replica took
    over a submission it thought lost), it is returned as it is.
    """
    submission = submission_repository.get(session, submission_id)
    if submission is None or submission.status != SubmissionStatus.SENT:
        return submission
    invoice_id = submission.invoice_id
    # End the transaction before calling out, so the connection is not held while the AEAT
    # takes its time to answer.
    session.commit()

    response = aeat.send(invoice_id)

    now = now or datetime.now(UTC)
    submission = submission_repository.get(session, submission_id)
    if submission is None or submission.status != SubmissionStatus.SENT:
        return submission
    submission.updated_at = now
    if response.outcome == AeatOutcome.ACCEPTED:
        submission.status = SubmissionStatus.ACCEPTED
        submission.aeat_reference = response.detail
        submission.last_error = None
        submission.next_attempt_at = None
    elif response.outcome == AeatOutcome.REJECTED:
        # The AEAT refused it: sending it again would get the same answer.
        submission.status = SubmissionStatus.REJECTED
        submission.last_error = response.detail
        submission.next_attempt_at = None
    else:
        submission.last_error = response.detail
        if submission.attempts >= policy.max_attempts:
            submission.status = SubmissionStatus.FAILED
            submission.next_attempt_at = None
        else:
            submission.status = SubmissionStatus.RETRYING
            submission.next_attempt_at = now + policy.delay(submission.attempts)
    session.commit()
    return submission
