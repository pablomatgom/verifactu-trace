import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import Amount, RequestModel
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
