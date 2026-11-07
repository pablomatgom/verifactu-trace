import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import RequestModel
from app.models import SubmissionStatus


class SubmissionCreate(RequestModel):
    """The invoice to send to the AEAT."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"invoice_id": "5d2e8a6c-1f40-4b9a-9c77-3e0a6b4d1f52"}},
    )

    invoice_id: uuid.UUID = Field(description="Id of the invoice to send.")


class SubmissionRead(BaseModel):
    """A submission to the AEAT and where it is."""

    id: uuid.UUID = Field(description="Id of the submission, assigned by the server.")
    invoice_id: uuid.UUID = Field(description="Id of the invoice that is sent.")
    invoice_number: str | None = Field(
        description="Number of the invoice, such as F-2026-000001, if it is known."
    )
    status: SubmissionStatus = Field(
        description=(
            "PENDING (waiting to be sent), SENT (an attempt is in progress), ACCEPTED or REJECTED "
            "(the AEAT answered, final), RETRYING (it failed and will be tried again at "
            "`next_attempt_at`) or FAILED (it failed and the attempts ran out, final)."
        )
    )
    attempts: int = Field(description="How many times it has been sent.")
    next_attempt_at: datetime | None = Field(
        description="When it will be tried next. Empty once the submission is final."
    )
    last_error: str | None = Field(
        description="Why the last attempt failed or was rejected, such as AEAT_UNAVAILABLE."
    )
    aeat_reference: str | None = Field(description="Reference the AEAT gave when it accepted it.")


class SubmissionList(BaseModel):
    """The submissions that meet the filter."""

    items: list[SubmissionRead] = Field(description="The submissions. Empty if there are none.")
