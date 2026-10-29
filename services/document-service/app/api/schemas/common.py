from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints


class RequestModel(BaseModel):
    """Base of every request body: an unknown field is an error, not something to ignore.

    Without this, a client that sends a field the server computes itself (such as `total`)
    would get a 201 and believe its value was used.
    """

    model_config = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    """Detail of an error."""

    code: str = Field(description="Machine-readable code, such as VALIDATION_ERROR.")
    message: str = Field(description="Explanation for a person. It names each failing field.")


class ErrorResponse(BaseModel):
    """The common error body of the API contract: {"error": {"code": ..., "message": ...}}."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "lines.0.quantity: Input should be greater than 0",
                }
            }
        }
    )

    error: ErrorBody = Field(description="What went wrong.")


# Pass it to an endpoint as `responses=VALIDATION_ERROR_RESPONSE` so that /docs documents the
# 422 with our body. Without it FastAPI documents its own default ({"detail": [...]}).
VALIDATION_ERROR_RESPONSE = {
    422: {
        "model": ErrorResponse,
        "description": "The request body is not valid: the message names each failing field.",
    }
}

# Amounts travel as JSON numbers, not strings (Pydantic writes a Decimal as a string by default).
Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]

# Text without surrounding spaces, and never empty.
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
