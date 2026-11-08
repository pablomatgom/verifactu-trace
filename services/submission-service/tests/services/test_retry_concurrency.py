"""Two requests to retry the same submission at the same time.

It needs transactions that really commit, so it opens its own sessions on the engine and cleans
up afterwards.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, delete, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.exceptions import SubmissionNotRetryable
from app.models import Submission, SubmissionStatus
from app.repositories import submission_repository
from app.services import submission_service

NOW = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


@pytest.fixture
def failed_id(engine: Engine) -> Iterator[uuid.UUID]:
    """A FAILED submission that is really saved, and removed at the end."""
    with Session(engine) as session:
        submission = Submission(
            invoice_id=uuid.uuid4(), status=SubmissionStatus.FAILED, attempts=5, updated_at=NOW
        )
        session.add(submission)
        session.commit()
        submission_id = submission.id
    yield submission_id
    with Session(engine) as session:
        session.execute(delete(Submission).where(Submission.id == submission_id))
        session.commit()


def test_a_second_retry_after_the_first_is_refused(engine: Engine, failed_id: uuid.UUID):
    with Session(engine) as first:
        submission_service.retry_submission(first, failed_id, NOW)

    with Session(engine) as second, pytest.raises(SubmissionNotRetryable, match="PENDING"):
        submission_service.retry_submission(second, failed_id, NOW)


def test_a_submission_being_retried_is_locked_for_the_other_request(
    engine: Engine, failed_id: uuid.UUID
):
    first = Session(engine)
    second = Session(engine)
    try:
        # The first request has read the submission and not finished yet. The second must wait
        # for it, not read the old FAILED state: the timeout turns that wait into a quick
        # failure of the test instead of a test that hangs.
        assert submission_repository.get_for_update(first, failed_id) is not None
        second.execute(text("SET LOCAL lock_timeout = '1s'"))

        with pytest.raises(OperationalError, match="lock"):
            submission_repository.get_for_update(second, failed_id)
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
