import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import Amount, RequestModel, Text
from app.models import DocumentStatus, DocumentType

# The docstrings and `description`s below are published in /docs: they are written for the
# client of the API, not for the developer.


class CustomerIn(RequestModel):
    """Customer the order is addressed to."""

    name: Text = Field(max_length=200, description="Name or business name of the customer.")
    tax_id: Text = Field(max_length=20, description="Tax identification number (NIF/CIF).")


class OrderLineIn(RequestModel):
    """One line of an order: a quantity of a product or service at a unit price."""

    description: Text = Field(max_length=300, description="What is being ordered.")
    quantity: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=3,
        description="Amount ordered, greater than zero. It accepts up to 3 decimals (2.5 kg).",
    )
    unit_price: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2,
        description="Price of one unit, excluding VAT, with up to 2 decimals.",
    )
    vat_rate: Decimal = Field(
        default=Decimal(21),
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
        description="VAT percentage applied to the line, from 0 to 100.",
    )


class OrderCreate(RequestModel):
    """Data needed to register an order.

    The id, the number, the date, the status and the amounts are assigned by the server, and
    sending any of them is an error.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "customer": {"name": "Acme S.L.", "tax_id": "B12345678"},
                "lines": [
                    {"description": "Widget", "quantity": 2, "unit_price": 10.5, "vat_rate": 21}
                ],
            }
        }
    )

    customer: CustomerIn = Field(description="Customer the order is addressed to.")
    lines: list[OrderLineIn] = Field(min_length=1, description="Lines of the order, at least one.")


class CustomerOut(BaseModel):
    """Customer of a registered order."""

    name: str = Field(description="Name or business name of the customer.")
    tax_id: str = Field(description="Tax identification number (NIF/CIF).")


class OrderLineOut(BaseModel):
    """One line of a registered order."""

    model_config = ConfigDict(from_attributes=True)

    position: int = Field(description="Position of the line in the order, starting at 1.")
    description: str = Field(description="What was ordered.")
    quantity: Amount = Field(description="Amount ordered.")
    unit_price: Amount = Field(description="Price of one unit, excluding VAT.")
    vat_rate: Amount = Field(description="VAT percentage applied to the line.")


class OrderRead(BaseModel):
    """A registered order with the amounts calculated by the server."""

    id: uuid.UUID = Field(description="Identifier of the order, assigned by the server.")
    type: DocumentType = Field(description="Kind of document. Always ORDER here.")
    number: str = Field(description="Unique number: series, year and counter, as P-2026-000001.")
    status: DocumentStatus = Field(description="Lifecycle state of the order.")
    issue_date: date = Field(description="Date the order was registered.")
    customer: CustomerOut = Field(description="Customer the order is addressed to.")
    lines: list[OrderLineOut] = Field(description="Lines of the order, in order.")
    total_net: Amount = Field(description="Sum of the lines, excluding VAT.")
    total_vat: Amount = Field(description="Sum of the VAT of every line.")
    total: Amount = Field(description="Net amount plus VAT.")
