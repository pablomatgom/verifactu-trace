from datetime import timedelta

import pytest

from app.services.retry import MAX_DELAY, RetryPolicy


def test_the_wait_doubles_after_each_failed_attempt():
    policy = RetryPolicy(max_attempts=10, base_seconds=5)

    delays = [policy.delay(attempts) for attempts in (1, 2, 3, 4)]

    assert delays == [
        timedelta(seconds=5),
        timedelta(seconds=10),
        timedelta(seconds=20),
        timedelta(seconds=40),
    ]


def test_the_base_can_be_a_fraction_of_a_second():
    assert RetryPolicy(max_attempts=3, base_seconds=0.5).delay(2) == timedelta(seconds=1)


def test_a_zero_base_means_no_wait():
    assert RetryPolicy(max_attempts=3, base_seconds=0).delay(3) == timedelta(0)


@pytest.mark.parametrize("attempts", [12, 30, 200])
def test_the_wait_never_exceeds_the_maximum(attempts: int):
    assert RetryPolicy(max_attempts=500, base_seconds=5).delay(attempts) == MAX_DELAY
