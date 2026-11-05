import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus, DocumentType
from app.repositories import document_repository
from app.services import delivery_note_service, invoice_service, order_service
from app.services.delivery_note_service import DeliveredLineData, DeliveryNoteData
from app.services.order_service import OrderData
from app.services.pricing import LineData


class IgnoringPublisher:
    def publish(self, stream: str, fields: dict[str, str]) -> None:
        pass


def invoice_of(delivery_note: Document, number: str) -> Document:
    """An invoice built by hand, skipping the checks of the service."""
    return Document(
        type=DocumentType.INVOICE,
        series="T",
        number=number,
        status=DocumentStatus.ISSUED,
        issue_date=delivery_note.issue_date,
        customer_name="Acme S.L.",
        customer_tax_id="B12345678",
        total_net=0,
        total_vat=0,
        total=0,
        parent_id=delivery_note.id,
    )


def test_the_database_rejects_a_second_invoice_of_the_same_delivery_note(session: Session):
    from decimal import Decimal

    order = order_service.create_order(
        session,
        OrderData(
            "Acme S.L.", "B12345678", [LineData("Widget", Decimal(5), Decimal(1), Decimal(21))]
        ),
    )
    delivery_note = delivery_note_service.create_delivery_note(
        session, DeliveryNoteData(order.id, [DeliveredLineData(1, Decimal(5))])
    )
    invoice_service.create_invoice(
        session, IgnoringPublisher(), invoice_service.InvoiceData(delivery_note.id)
    )

    # The service would refuse this. Going around it shows the index is the last defence.
    second_invoice = invoice_of(delivery_note, "T-2026-000001")

    with pytest.raises(IntegrityError, match="uq_documents_one_invoice_per_delivery_note"):
        document_repository.add(session, second_invoice)


def test_many_delivery_notes_can_share_their_order(session: Session):
    from decimal import Decimal

    order = order_service.create_order(
        session,
        OrderData(
            "Acme S.L.", "B12345678", [LineData("Widget", Decimal(5), Decimal(1), Decimal(21))]
        ),
    )

    for quantity in (1, 2):
        delivery_note_service.create_delivery_note(
            session, DeliveryNoteData(order.id, [DeliveredLineData(1, Decimal(quantity))])
        )

    # The unique index only covers invoices, so this did not fail.
    assert session.query(Document).filter_by(parent_id=order.id).count() == 2
