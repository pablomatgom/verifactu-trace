from dataclasses import dataclass
from datetime import timedelta

# The wait never grows past this, however many attempts are allowed.
MAX_DELAY = timedelta(hours=1)
# 2 ** 40 seconds is far beyond MAX_DELAY, so doubling more than this changes nothing.
MAX_DOUBLINGS = 40


@dataclass(frozen=True)
class RetryPolicy:
    """How many times a submission is tried and how long to wait between the attempts."""

    max_attempts: int
    base_seconds: float

    def delay(self, attempts: int) -> timedelta:
        """Wait before the next attempt, after `attempts` failed ones: it doubles every time.

        With a base of 5 seconds the waits are 5, 10, 20, 40... seconds. Waiting longer each
        time gives an AEAT that is struggling room to recover instead of hammering it.
        """
        # The exponent is capped so that 2 ** (attempts - 1) cannot grow without limit: with
        # enough attempts it would overflow, and the cap on the wait makes the rest irrelevant.
        seconds = self.base_seconds * 2 ** min(attempts - 1, MAX_DOUBLINGS)
        return timedelta(seconds=min(seconds, MAX_DELAY.total_seconds()))
