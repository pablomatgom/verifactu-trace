import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.aeat import AeatClient, AeatOutcome
from app.exceptions import SubmissionAlreadyExists
from app.models import Submission, SubmissionStatus
from app.repositories import submission_repository
from app.services.retry import RetryPolicy

# A submission that has been SENT this long without an answer is taken as lost (the service died
# while sending it) and is sent again.
STUCK_AFTER = timedelta(minutes=1)

# How many submissions a worker takes at a time.
BATCH_SIZE = 10


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
