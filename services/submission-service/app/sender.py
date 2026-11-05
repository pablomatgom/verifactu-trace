"""The worker that sends the submissions to the AEAT and retries the ones that failed.

The database is its queue: a submission is due when it is PENDING or RETRYING and its
`next_attempt_at` has come. Keeping the retries there, and not in memory, means they survive a
restart of the service, and any replica can pick them up.
"""

import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.aeat import AeatClient
from app.services import submission_service
from app.services.retry import RetryPolicy

logger = logging.getLogger(__name__)

# How often to look for submissions that are due when there is nothing to do.
POLL_SECONDS = 1.0


class SubmissionSender:
    """Looks for the due submissions in a background thread and sends them."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        aeat: AeatClient,
        policy: RetryPolicy,
        poll_seconds: float = POLL_SECONDS,
    ):
        self._session_factory = session_factory
        self._aeat = aeat
        self._policy = policy
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> int:
        """Send the submissions that are due now. Returns how many it took."""
        with self._session_factory() as session:
            submission_ids = submission_service.claim_due(session)
        for submission_id in submission_ids:
            try:
                with self._session_factory() as session:
                    submission_service.send(session, self._aeat, submission_id, self._policy)
            except Exception:
                # One failure must not stop the rest of the batch. The submission stays SENT
                # and, as nobody answers for it, it is taken as lost and sent again later.
                logger.exception("Sending the submission %s failed", submission_id)
        return len(submission_ids)

    def start(self) -> None:
        """Start sending in a background thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="submission-sender")
        self._thread.daemon = True  # it must not keep the process alive when the app stops
        self._thread.start()

    def stop(self) -> None:
        """Stop the thread and wait for it to finish what it is doing."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_seconds + 5)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                taken = self.run_once()
            except Exception:
                # The database is down, or something else outside a single submission failed.
                logger.exception("Looking for due submissions failed, trying again")
                taken = 0
            if taken == 0:
                self._stop.wait(self._poll_seconds)
