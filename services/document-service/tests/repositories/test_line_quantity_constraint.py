from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Document, DocumentLine, DocumentStatus, DocumentType
from app.repositories import document_repository


def document_with_quantity(quantity: Decimal, number: str) -> Document:
    """A document built by hand, skipping the checks of the API, with a single line."""
    return Document(
        type=DocumentType.CORRECTIVE_INVOICE,
        series="T",
        number=number,
        status=DocumentStatus.ISSUED,
        issue_date="2026-11-08",
        customer_name="Acme S.L.",
        customer_tax_id="B12345678",
        total_net=0,
        total_vat=0,
        total=0,
        lines=[
            DocumentLine(
                position=1,
                description="Widget",
                quantity=quantity,
                unit_price=Decimal(1),
                vat_rate=Decimal(21),
            )
        ],
    )


def test_the_database_accepts_a_negative_quantity_for_the_lines_of_a_corrective_invoice(
    session: Session,
):
    document = document_repository.add(
        session, document_with_quantity(Decimal(-2), "T-2026-900001")
    )

    assert document.lines[0].quantity == Decimal(-2)


def test_the_database_still_rejects_a_quantity_of_zero(session: Session):
    document = document_with_quantity(Decimal(0), "T-2026-900002")

    with pytest.raises(IntegrityError, match="ck_document_lines_quantity_not_zero"):
        document_repository.add(session, document)
