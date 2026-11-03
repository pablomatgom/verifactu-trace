import logging
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.events import INVOICE_ISSUED, EventPublisher, EventPublishError
from app.exceptions import DeliveryNoteAlreadyInvoiced, ReferenceNotFound
from app.models import Document, DocumentLine, DocumentStatus, DocumentType
from app.repositories import counter_repository, document_repository
from app.services.numbering import SERIES, format_number
from app.services.pricing import LineData, calculate_totals

logger = logging.getLogger(__name__)


@dataclass
class InvoiceData:
    delivery_note_id: uuid.UUID


def create_invoice(session: Session, publisher: EventPublisher, data: InvoiceData) -> Document:
    """Issue the invoice of a delivery note: check it, number it, save it and announce it."""
    # Locking the delivery note makes the check and the insert one step for concurrent requests.
    delivery_note = document_repository.get_for_update(
        session, data.delivery_note_id, DocumentType.DELIVERY_NOTE
    )
    if delivery_note is None:
        raise ReferenceNotFound(f"delivery note {data.delivery_note_id} does not exist")
    if document_repository.exists_child(session, delivery_note.id, DocumentType.INVOICE):
        raise DeliveryNoteAlreadyInvoiced(
            f"delivery note {delivery_note.number} already has an invoice"
        )

    today = date.today()
    series = SERIES[DocumentType.INVOICE]
    number = counter_repository.next_number(session, series, today.year)

    # The invoice bills what the delivery note delivered, at the prices of the order.
    net, vat, total = calculate_totals(
        [
            LineData(line.description, line.quantity, line.unit_price, line.vat_rate)
            for line in delivery_note.lines
        ]
    )
    invoice = Document(
        type=DocumentType.INVOICE,
        series=series,
        number=format_number(series, today.year, number),
        status=DocumentStatus.ISSUED,
        issue_date=today,
        customer_name=delivery_note.customer_name,
        customer_tax_id=delivery_note.customer_tax_id,
        total_net=net,
        total_vat=vat,
        total=total,
        parent_id=delivery_note.id,
        lines=[
            DocumentLine(
                position=line.position,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_rate=line.vat_rate,
                source_line_id=line.id,
            )
            for line in delivery_note.lines
        ],
    )
    document_repository.add(session, invoice)
    session.commit()

    _announce(publisher, invoice, order_id=delivery_note.parent_id)
    return invoice


def _announce(publisher: EventPublisher, invoice: Document, order_id: uuid.UUID | None) -> None:
    """Publish `invoice.issued`, once the invoice is committed.

    If the event cannot be published the invoice stays issued: a failure of the services that
    react to it must not stop invoices from being issued. It is logged so it can be noticed.
    """
    fields = {
        "invoice_id": str(invoice.id),
        "number": invoice.number,
        "delivery_note_id": str(invoice.parent_id),
        "order_id": str(order_id),
        "total": str(invoice.total),
        "issued_at": invoice.created_at.isoformat(),
    }
    try:
        publisher.publish(INVOICE_ISSUED, fields)
    except EventPublishError:
        logger.exception("Event %s of invoice %s was not published", INVOICE_ISSUED, invoice.number)
