import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Submission, SubmissionStatus


def create_if_absent(
    session: Session, invoice_id: uuid.UUID, invoice_number: str | None, now: datetime
) -> Submission | None:
    """Create the PENDING submission of an invoice, or return None if it already has one.

    INSERT ... ON CONFLICT DO NOTHING lets the database decide, so two replicas that receive the
    same invoice at the same time cannot both create it (and neither fails with an error).
    """
    statement = (
        insert(Submission)
        .values(
            id=uuid.uuid4(),
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            status=SubmissionStatus.PENDING,
            attempts=0,
            next_attempt_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_submissions_invoice_id")
        .returning(Submission.id)
    )
    new_id = session.execute(statement).scalar_one_or_none()
    return None if new_id is None else session.get(Submission, new_id)


def get(session: Session, submission_id: uuid.UUID) -> Submission | None:
    """The submission, read again from the database even if the session already has it."""
    return session.get(Submission, submission_id, populate_existing=True)


def claim_due(
    session: Session, now: datetime, stuck_before: datetime, limit: int
) -> list[Submission]:
    """Lock the submissions that are due to be sent, oldest first.

    A submission is due when it is PENDING or RETRYING and its date has come, or when it has been
    SENT for so long that the attempt must have been lost (the service died while sending it).

    SKIP LOCKED makes a replica ignore the rows another one has locked instead of waiting for
    them, so two replicas that poll at the same time take different submissions.
    """
    due = or_(
        and_(
            Submission.status.in_([SubmissionStatus.PENDING, SubmissionStatus.RETRYING]),
            Submission.next_attempt_at <= now,
        ),
        and_(Submission.status == SubmissionStatus.SENT, Submission.updated_at <= stuck_before),
    )
    query = (
        select(Submission)
        .where(due)
        .order_by(Submission.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(session.scalars(query))
