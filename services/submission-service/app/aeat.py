"""The AEAT, as far as this service is concerned: something that answers an invoice.

The real AEAT is out of the scope of the project, so `SimulatedAeat` stands in for it. The rest of
the service depends on `AeatClient`, so a client of the real service could replace it without
changing anything else.
"""

import secrets
import uuid
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Protocol

from app.config import aeat_failure_rate, aeat_simulation


class AeatOutcome(StrEnum):
    """What the AEAT answered."""

    ACCEPTED = "ACCEPTED"
    # The AEAT read the invoice and refused it. Sending it again would not change the answer.
    REJECTED = "REJECTED"
    # The AEAT could not answer (it is down, it timed out). Sending it again may work.
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class AeatResponse:
    outcome: AeatOutcome
    # The reference of the record when accepted, or an error code such as AEAT_UNAVAILABLE.
    detail: str


class RandomSource(Protocol):
    """Something that gives numbers between 0 and 1 (what `flaky` needs to decide)."""

    def random(self) -> float: ...


class AeatClient(Protocol):
    """Something that can send an invoice to the AEAT."""

    def send(self, invoice_id: uuid.UUID) -> AeatResponse:
        """Send the invoice and return the answer. It does not raise for a refusal or an outage."""
        ...


# How the simulation answers, chosen with AEAT_SIMULATION:
#   accept  every attempt is accepted (the default)
#   reject  every attempt is rejected
#   fail    every attempt finds the AEAT unavailable, so the submission ends up FAILED
#   flaky   each attempt finds the AEAT unavailable with probability AEAT_FAILURE_RATE,
#           and is accepted otherwise: it shows the retries working
SIMULATIONS = ("accept", "reject", "fail", "flaky")


class SimulatedAeat:
    """Answers as the AEAT could, according to the chosen simulation."""

    def __init__(
        self,
        simulation: str = "accept",
        failure_rate: float = 0.5,
        rng: RandomSource | None = None,
    ):
        if simulation not in SIMULATIONS:
            raise ValueError(
                f"unknown AEAT simulation {simulation!r}, expected one of {SIMULATIONS}"
            )
        if not 0 <= failure_rate <= 1:
            raise ValueError(f"the failure rate must be between 0 and 1, not {failure_rate}")
        self._simulation = simulation
        self._failure_rate = failure_rate
        self._rng = rng or secrets.SystemRandom()

    def send(self, invoice_id: uuid.UUID) -> AeatResponse:
        if self._simulation == "reject":
            return AeatResponse(AeatOutcome.REJECTED, "AEAT_INVALID_RECORD")
        if self._simulation == "fail" or (
            self._simulation == "flaky" and self._rng.random() < self._failure_rate
        ):
            return AeatResponse(AeatOutcome.UNAVAILABLE, "AEAT_UNAVAILABLE")
        return AeatResponse(AeatOutcome.ACCEPTED, f"SIM-{invoice_id.hex[:12].upper()}")


@lru_cache
def get_aeat() -> AeatClient:
    """The AEAT client of the application, built from the environment on first use."""
    try:
        return SimulatedAeat(aeat_simulation(), aeat_failure_rate())
    except ValueError as error:
        raise RuntimeError(str(error)) from None
