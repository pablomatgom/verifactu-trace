import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.api.schemas.common import Amount
from app.api.schemas.orders import CustomerOut
from app.models import DocumentStatus, DocumentType

# The docstrings and `description`s below are published in /docs: they are written for the
# client of the API, not for the developer.


class DocumentLineOut(BaseModel):
    """One line of a document, whatever its type."""

    position: int = Field(description="Position of the line in the document, starting at 1.")
    source_line: int | None = Field(
        description=(
            "Position of the line of the previous document that this one comes from: the order "
            "line for a delivery note line, the delivery note line for an invoice line. "
            "Null in an order."
        )
    )
    description: str = Field(description="What is ordered, delivered or billed.")
    quantity: Amount = Field(description="Amount ordered, delivered or billed.")
    unit_price: Amount = Field(description="Price of one unit, excluding VAT.")
    vat_rate: Amount = Field(description="VAT percentage applied to the line.")


class DocumentSummary(BaseModel):
    """A document as it appears in a list: its header and amounts, without the lines."""

    id: uuid.UUID = Field(description="Identifier of the document.")
    type: DocumentType = Field(description="Kind of document: ORDER, DELIVERY_NOTE or INVOICE.")
    number: str = Field(description="Unique number: series, year and counter, as P-2026-000001.")
    status: DocumentStatus = Field(description="Lifecycle state of the document.")
    issue_date: date = Field(description="Date the document was registered or issued.")
    parent_id: uuid.UUID | None = Field(
        description="Identifier of the previous document of the chain. Null in an order."
    )
    customer: CustomerOut = Field(description="Customer of the document.")
    total_net: Amount = Field(description="Sum of the lines, excluding VAT.")
    total_vat: Amount = Field(description="Sum of the VAT of every line.")
    total: Amount = Field(description="Net amount plus VAT.")


class DocumentPageRead(BaseModel):
    """One page of documents, with what is needed to ask for the next one."""

    items: list[DocumentSummary] = Field(
        description="The documents of this page, the newest first. Empty if the page is past the end."
    )
    page: int = Field(description="Number of this page, starting at 1.")
    size: int = Field(description="Maximum number of documents per page.")
    total: int = Field(description="Number of documents that meet the filters, in all the pages.")


class DocumentRead(BaseModel):
    """An order, a delivery note or an invoice, in the same shape for the three."""

    id: uuid.UUID = Field(description="Identifier of the document.")
    type: DocumentType = Field(description="Kind of document: ORDER, DELIVERY_NOTE or INVOICE.")
    number: str = Field(
        description="Unique number: series, year and counter, as P-2026-000001, A-... or F-..."
    )
    status: DocumentStatus = Field(description="Lifecycle state of the document.")
    issue_date: date = Field(description="Date the document was registered or issued.")
    parent_id: uuid.UUID | None = Field(
        description=(
            "Identifier of the previous document of the chain: the order of a delivery note, "
            "the delivery note of an invoice. Null in an order."
        )
    )
    customer: CustomerOut = Field(description="Customer of the document.")
    lines: list[DocumentLineOut] = Field(description="Lines of the document, in order.")
    total_net: Amount = Field(description="Sum of the lines, excluding VAT.")
    total_vat: Amount = Field(description="Sum of the VAT of every line.")
    total: Amount = Field(description="Net amount plus VAT.")
