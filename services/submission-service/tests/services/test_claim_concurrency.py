"""A worker that looks for due submissions skips the ones another worker has locked.

It needs transactions that really commit, so it opens its own sessions on the engine and cleans
up afterwards.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, text
from sqlalchemy.orm import Session

from app.models import Submission
from app.repositories import submission_repository
from app.services import submission_service
from app.services.submission_service import SubmissionData

NOW = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)


def test_a_submission_locked_by_one_worker_is_skipped_by_the_other(engine: Engine):
    with Session(engine) as session:
        submission = submission_service.create_submission(
            session, SubmissionData(invoice_id=uuid.uuid4()), NOW
        )
        submission_id = submission.id

    first = Session(engine)
    second = Session(engine)
    try:
        # The first worker has locked it and has not finished yet: the second must not wait for
        # it (that would stop every replica behind the slowest) and must not take it either.
        taken_by_first = submission_repository.claim_due(first, NOW, NOW, limit=100)
        # Without SKIP LOCKED the second worker would wait for the lock; the timeout makes that
        # a quick failure of the test instead of a test that hangs.
        second.execute(text("SET LOCAL lock_timeout = '2s'"))
        taken_by_second = submission_repository.claim_due(second, NOW, NOW, limit=100)

        assert submission_id in [submission.id for submission in taken_by_first]
        assert submission_id not in [submission.id for submission in taken_by_second]
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()
        with Session(engine) as session:
            session.execute(delete(Submission).where(Submission.id == submission_id))
            session.commit()
