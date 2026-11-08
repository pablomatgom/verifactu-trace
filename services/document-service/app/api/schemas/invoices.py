import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.schemas.common import Amount, RequestModel, Text
from app.api.schemas.orders import CustomerOut
from app.models import DocumentStatus, DocumentType

# The docstrings and `description`s below are published in /docs: they are written for the
# client of the API, not for the developer.


class InvoiceCreate(RequestModel):
    """Data needed to issue an invoice.

    Only the delivery note is sent. The invoice bills what that delivery note delivered, with the
    customer and prices of the order, and the id, the number, the date, the status and the amounts
    are assigned by the server. Sending any of them is an error.
    """

    model_config = ConfigDict(
        json_schema_extra={"example": {"delivery_note_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"}}
    )

    delivery_note_id: uuid.UUID = Field(
        description="Identifier of the delivery note that is invoiced. It can only be invoiced once."
    )


class InvoiceLineOut(BaseModel):
    """One line of an issued invoice."""

    position: int = Field(description="Position of the line in the invoice, starting at 1.")
    delivery_note_line: int = Field(
        description="Position of the delivery note line that this line bills."
    )
    description: str = Field(description="What is billed, as written in the order.")
    quantity: Amount = Field(description="Amount billed.")
    unit_price: Amount = Field(description="Price of one unit, excluding VAT.")
    vat_rate: Amount = Field(description="VAT percentage applied to the line.")


class InvoiceRead(BaseModel):
    """An issued invoice with the amounts calculated by the server."""

    id: uuid.UUID = Field(description="Identifier of the invoice, assigned by the server.")
    type: DocumentType = Field(description="Kind of document. Always INVOICE here.")
    number: str = Field(description="Unique number: series, year and counter, as F-2026-000001.")
    status: DocumentStatus = Field(description="Lifecycle state of the invoice.")
    issue_date: date = Field(description="Date the invoice was issued.")
    delivery_note_id: uuid.UUID = Field(
        description="Identifier of the delivery note that this invoice bills."
    )
    order_id: uuid.UUID = Field(description="Identifier of the order the delivery note comes from.")
    customer: CustomerOut = Field(description="Customer of the order.")
    lines: list[InvoiceLineOut] = Field(description="Lines of the invoice, in order.")
    total_net: Amount = Field(description="Sum of the lines, excluding VAT (the taxable base).")
    total_vat: Amount = Field(description="Sum of the VAT of every line.")
    total: Amount = Field(description="Net amount plus VAT.")


class CorrectionLineIn(RequestModel):
    """How much of one line of the invoice is taken back."""

    invoice_line: int = Field(
        ge=1, description="Position of the invoice line that is corrected, starting at 1."
    )
    quantity: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=3,
        description=(
            "Amount taken back, greater than zero. The corrective invoice shows it as negative. "
            "It accepts up to 3 decimals."
        ),
    )


class CorrectionCreate(RequestModel):
    """Data needed to issue a corrective invoice.

    It says why the invoice is rectified and, optionally, which lines and how much of them. The
    customer, the descriptions, the prices and the VAT are those of the invoice, and the id, the
    number, the date, the status and the amounts are assigned by the server. Sending any of them
    is an error.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reason": "Two units were returned damaged",
                "lines": [{"invoice_line": 1, "quantity": 2}],
            }
        }
    )

    reason: Text = Field(max_length=300, description="Why the invoice is rectified.")
    lines: list[CorrectionLineIn] | None = Field(
        default=None,
        min_length=1,
        description=(
            "What is taken back of each invoice line, at least one. A line may be left out. "
            "If omitted, everything that has not been corrected yet is."
        ),
    )

    @model_validator(mode="after")
    def invoice_lines_are_not_repeated(self) -> "CorrectionCreate":
        if self.lines is not None:
            positions = [line.invoice_line for line in self.lines]
            if len(positions) != len(set(positions)):
                raise ValueError("an invoice line can only appear once")
        return self


class CorrectionLineOut(BaseModel):
    """One line of a corrective invoice."""

    position: int = Field(description="Position of the line in the corrective invoice, from 1.")
    invoice_line: int = Field(description="Position of the invoice line that this line corrects.")
    description: str = Field(description="What is corrected, as written in the invoice.")
    quantity: Amount = Field(description="Amount taken back, as a negative number.")
    unit_price: Amount = Field(description="Price of one unit, excluding VAT, as in the invoice.")
    vat_rate: Amount = Field(description="VAT percentage applied to the line, as in the invoice.")


class CorrectionRead(BaseModel):
    """An issued corrective invoice, with the amounts calculated by the server."""

    id: uuid.UUID = Field(
        description="Identifier of the corrective invoice, assigned by the server."
    )
    type: DocumentType = Field(description="Kind of document. Always CORRECTIVE_INVOICE here.")
    number: str = Field(description="Unique number: series, year and counter, as R-2026-000001.")
    status: DocumentStatus = Field(description="Lifecycle state of the corrective invoice.")
    issue_date: date = Field(description="Date the corrective invoice was issued.")
    corrects_invoice_id: uuid.UUID = Field(
        description="Identifier of the invoice that it rectifies."
    )
    reason: str = Field(description="Why the invoice is rectified.")
    customer: CustomerOut = Field(description="Customer of the invoice.")
    lines: list[CorrectionLineOut] = Field(description="Lines of the corrective invoice, in order.")
    total_net: Amount = Field(description="Sum of the lines, excluding VAT. Negative.")
    total_vat: Amount = Field(description="Sum of the VAT of every line. Negative.")
    total: Amount = Field(description="Net amount plus VAT. Negative: it reduces what is owed.")
