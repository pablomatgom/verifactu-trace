import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.common import Amount, RequestModel
from app.api.schemas.orders import CustomerOut
from app.models import DocumentStatus, DocumentType

# The docstrings and `description`s below are published in /docs: they are written for the
# client of the API, not for the developer.


class DeliveryNoteLineIn(RequestModel):
    """What is delivered of one line of the order."""

    order_line: int = Field(
        ge=1, description="Position of the order line that is delivered, starting at 1."
    )
    quantity: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=3,
        description="Amount delivered, greater than zero. It accepts up to 3 decimals.",
    )


class DeliveryNoteCreate(RequestModel):
    """Data needed to register a delivery note.

    The customer, the descriptions, the prices and the VAT are those of the order, and the id,
    the number, the date, the status and the amounts are assigned by the server. Sending any of
    them is an error.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "order_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                "lines": [{"order_line": 1, "quantity": 2}],
            }
        }
    )

    order_id: uuid.UUID = Field(description="Identifier of the order that is delivered.")
    lines: list[DeliveryNoteLineIn] = Field(
        min_length=1,
        description="What is delivered of each order line, at least one. A line may be left out.",
    )

    @model_validator(mode="after")
    def order_lines_are_not_repeated(self) -> "DeliveryNoteCreate":
        positions = [line.order_line for line in self.lines]
        if len(positions) != len(set(positions)):
            raise ValueError("an order line can only appear once")
        return self


class DeliveryNoteLineOut(BaseModel):
    """One line of a registered delivery note."""

    position: int = Field(description="Position of the line in the delivery note, starting at 1.")
    order_line: int = Field(description="Position of the order line that this line delivers.")
    description: str = Field(description="What was delivered, as written in the order.")
    quantity: Amount = Field(description="Amount delivered.")
    unit_price: Amount = Field(description="Price of one unit, excluding VAT, as in the order.")
    vat_rate: Amount = Field(description="VAT percentage applied to the line, as in the order.")


class DeliveryNoteRead(BaseModel):
    """A registered delivery note with the amounts calculated by the server."""

    id: uuid.UUID = Field(description="Identifier of the delivery note, assigned by the server.")
    type: DocumentType = Field(description="Kind of document. Always DELIVERY_NOTE here.")
    number: str = Field(description="Unique number: series, year and counter, as A-2026-000001.")
    status: DocumentStatus = Field(description="Lifecycle state of the delivery note.")
    issue_date: date = Field(description="Date the delivery note was registered.")
    order_id: uuid.UUID = Field(description="Identifier of the order that this note delivers.")
    customer: CustomerOut = Field(description="Customer of the order.")
    lines: list[DeliveryNoteLineOut] = Field(description="Lines of the delivery note, in order.")
    total_net: Amount = Field(description="Sum of the lines, excluding VAT.")
    total_vat: Amount = Field(description="Sum of the VAT of every line.")
    total: Amount = Field(description="Net amount plus VAT.")
