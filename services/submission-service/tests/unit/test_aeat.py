import re
import uuid

import pytest

from app.aeat import AeatOutcome, SimulatedAeat, get_aeat

INVOICE_ID = uuid.UUID("5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52")


class Numbers:
    """A source of numbers that gives the ones it was given, one after another."""

    def __init__(self, *numbers: float):
        self._numbers = iter(numbers)

    def random(self) -> float:
        return next(self._numbers)


def test_accept_simulation_accepts_with_a_reference():
    response = SimulatedAeat("accept").send(INVOICE_ID)

    assert response.outcome == AeatOutcome.ACCEPTED
    assert re.fullmatch(r"SIM-[0-9A-F]{12}", response.detail)


def test_the_reference_depends_on_the_invoice():
    aeat = SimulatedAeat("accept")

    first = aeat.send(INVOICE_ID).detail
    again = aeat.send(INVOICE_ID).detail
    other = aeat.send(uuid.uuid4()).detail

    assert first == again
    assert first != other


def test_reject_simulation_rejects_with_an_error_code():
    response = SimulatedAeat("reject").send(INVOICE_ID)

    assert response.outcome == AeatOutcome.REJECTED
    assert response.detail == "AEAT_INVALID_RECORD"


def test_fail_simulation_is_always_unavailable():
    aeat = SimulatedAeat("fail")

    responses = [aeat.send(INVOICE_ID) for _ in range(5)]

    assert {response.outcome for response in responses} == {AeatOutcome.UNAVAILABLE}
    assert {response.detail for response in responses} == {"AEAT_UNAVAILABLE"}


def test_flaky_simulation_with_a_rate_of_one_always_fails():
    aeat = SimulatedAeat("flaky", failure_rate=1)

    assert aeat.send(INVOICE_ID).outcome == AeatOutcome.UNAVAILABLE


def test_flaky_simulation_with_a_rate_of_zero_never_fails():
    aeat = SimulatedAeat("flaky", failure_rate=0)

    assert aeat.send(INVOICE_ID).outcome == AeatOutcome.ACCEPTED


def test_flaky_simulation_mixes_failures_and_acceptances():
    # Below the rate the attempt fails, from the rate up it is accepted.
    aeat = SimulatedAeat("flaky", failure_rate=0.5, rng=Numbers(0.1, 0.5, 0.9))

    outcomes = [aeat.send(INVOICE_ID).outcome for _ in range(3)]

    assert outcomes == [AeatOutcome.UNAVAILABLE, AeatOutcome.ACCEPTED, AeatOutcome.ACCEPTED]


def test_an_unknown_simulation_is_refused():
    with pytest.raises(ValueError, match="unknown AEAT simulation"):
        SimulatedAeat("sometimes")


@pytest.mark.parametrize("rate", [-0.1, 1.1])
def test_a_failure_rate_outside_zero_and_one_is_refused(rate: float):
    with pytest.raises(ValueError, match="between 0 and 1"):
        SimulatedAeat("flaky", failure_rate=rate)


def test_the_application_builds_the_simulation_from_the_environment(monkeypatch):
    monkeypatch.setenv("AEAT_SIMULATION", "reject")
    get_aeat.cache_clear()
    try:
        response = get_aeat().send(INVOICE_ID)
    finally:
        get_aeat.cache_clear()

    assert response.outcome == AeatOutcome.REJECTED


def test_a_wrong_simulation_in_the_environment_fails_at_startup(monkeypatch):
    monkeypatch.setenv("AEAT_SIMULATION", "sometimes")
    get_aeat.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="unknown AEAT simulation"):
            get_aeat()
    finally:
        get_aeat.cache_clear()
