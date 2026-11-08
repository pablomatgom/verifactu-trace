import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.api.schemas.common import Amount
from app.api.schemas.orders import CustomerOut
from app.models import DocumentStatus, DocumentType

# The docstrings and `description`s below are published in /docs: they are written for the
# client of the API, not for the developer.

ID_DESCRIPTION = "Identifier of the document."
TYPE_DESCRIPTION = "Kind of document: ORDER, DELIVERY_NOTE or INVOICE."


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

    id: uuid.UUID = Field(description=ID_DESCRIPTION)
    type: DocumentType = Field(description=TYPE_DESCRIPTION)
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

    id: uuid.UUID = Field(description=ID_DESCRIPTION)
    type: DocumentType = Field(description=TYPE_DESCRIPTION)
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


class LineRefRead(BaseModel):
    """One side of a difference: a line of a document and the value it has."""

    document_type: DocumentType = Field(description=TYPE_DESCRIPTION)
    number: str = Field(description="Number of the document.")
    line: int | None = Field(
        description="Position of the line in the document. Null if the document has no such line."
    )
    value: Amount = Field(
        description="The value of the field in that line. Zero if there is no line."
    )


class DiscrepancyRead(BaseModel):
    """A value that is not the same in a line and in the line that comes from it."""

    field: str = Field(description="What differs: `quantity`, `unit_price` or `vat_rate`.")
    description: str = Field(description="What the line is, as written in the document.")
    source: LineRefRead = Field(description="The line of the earlier document.")
    target: LineRefRead = Field(description="The line of the later document that comes from it.")


class ComparedDocument(BaseModel):
    """A document that took part in the comparison."""

    type: DocumentType = Field(description=TYPE_DESCRIPTION)
    id: uuid.UUID = Field(description=ID_DESCRIPTION)
    number: str = Field(description="Number of the document.")


class DiscrepancyReport(BaseModel):
    """The differences found between the documents of a chain."""

    document_id: uuid.UUID = Field(description="Identifier of the document that was asked about.")
    compared: list[ComparedDocument] = Field(
        description="The documents of its chain that were compared, the order first."
    )
    discrepancies: list[DiscrepancyRead] = Field(
        description="The lines that do not match. Empty if the chain is coherent."
    )
